"""
src/legislm/training/engine.py
Loop de treinamento, acumulação exata de gradientes, avaliação e controle de orçamento.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import Optimizer

from legislm.model.gpt import GPTModel
from legislm.paths import require_data_root, resolve_persistent_path
from legislm.training.checkpoint import load_checkpoint, restore_training_state, save_checkpoint
from legislm.training.config import TrainingConfig
from legislm.training.data import Batch, DeterministicSampler, StratifiedTracker, TokenDataset
from legislm.training.optimizer import CosineAnnealingWarmupScheduler, configure_optimizer
from legislm.training.persistence import PersistenceBackend, get_persistence_backend
from legislm.training.precision import PrecisionManager


class Trainer:
    """Treinador educacional determinístico e reproduzível para o LLM legislativo."""

    def __init__(
        self,
        config: TrainingConfig,
        model: Optional[GPTModel] = None,
        train_dataset: Optional[TokenDataset] = None,
        eval_dataset: Optional[TokenDataset] = None,
        persistence_backend: Optional[PersistenceBackend] = None,
        segment_id: Optional[str] = None,
        session_max_steps: Optional[int] = None,
    ) -> None:
        self.config = config
        self.config.validate()
        self.device = torch.device(self.config.device)
        self.session_max_steps = session_max_steps

        # 1. Modelo Transformer Decoder explícito
        if model is None:
            gpt_cfg = self.config.model.to_gpt_config()
            self.model = GPTModel(gpt_cfg).to(self.device)
        else:
            self.model = model.to(self.device)

        # 2. Otimizador AdamW com segregação de decay e Scheduler com Warmup
        self.optimizer = configure_optimizer(self.model, self.config.training)
        self.scheduler = CosineAnnealingWarmupScheduler(
            self.optimizer,
            learning_rate=self.config.training.learning_rate,
            min_learning_rate=self.config.training.min_learning_rate,
            warmup_steps=self.config.training.warmup_steps,
            max_steps=self.config.training.max_steps,
        )

        # 3. Gerenciador de precisão e hardware
        self.precision_mgr = PrecisionManager(
            precision=self.config.training.precision,
            device_type=self.config.device,
        )

        # 4. Dados e Sampler
        self.train_dataset = train_dataset
        self.eval_dataset = eval_dataset

        num_train_items = len(self.train_dataset) if self.train_dataset is not None else 0
        self.sampler = DeterministicSampler(
            num_items=num_train_items,
            seed=self.config.training.seed,
        )
        self.tracker = StratifiedTracker(total_eligible_items=num_train_items)

        # 5. Persistência
        if persistence_backend is None:
            self.persistence = get_persistence_backend(
                self.config.persistence.backend,
                checkpoints_to_keep=self.config.persistence.checkpoints_to_keep,
            )
        else:
            self.persistence = persistence_backend

        # 6. Identificadores de segmento e contadores de progresso
        self.segment_id = segment_id or f"seg_{int(time.time())}"
        self.global_step = 0
        self.tokens_seen = 0
        self.tokens_for_successful_updates = 0
        self.overflow_updates_count = 0
        self.total_positions_evaluated = 0
        self.event_sequence = 0
        self.best_val_loss: Optional[float] = None

        # Diretórios locais e persistentes
        configured_runs = Path(self.config.persistence.runs_dir)
        if configured_runs.is_absolute():
            self.persistent_run_root = resolve_persistent_path(configured_runs) / self.config.run_id
            data_root = require_data_root() if os.environ.get("DATA_ROOT") else configured_runs.parent
        else:
            data_root = require_data_root()
            self.persistent_run_root = resolve_persistent_path(configured_runs) / self.config.run_id
        self.local_staging_root = data_root / "staging" / "checkpoints" / self.config.run_id
        self.metrics_log_path = self.persistent_run_root / "metrics" / f"metrics_{self.segment_id}.jsonl"

    def _log_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Registra métrica/evento em log append-only JSONL."""
        self.event_sequence += 1
        event = {
            "event_id": f"{self.config.run_id}:{self.segment_id}:{self.event_sequence:06d}",
            "event_type": event_type,
            "run_id": self.config.run_id,
            "segment_id": self.segment_id,
            "global_step": self.global_step,
            "tokens_seen": self.tokens_seen,
            "tokens_for_successful_updates": self.tokens_for_successful_updates,
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            **payload,
        }
        self.metrics_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.metrics_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def train_step(self) -> Tuple[float, float, bool, int]:
        """Executa um passo completo de atualização com acumulação exata de gradientes.

        Contrato: Soma de Cross-Entropy dividida pelo total de alvos válidos de todo o update,
        inclusive entre micro-lotes de tamanhos e quantidades heterogêneas de padding.

        Returns:
            Tuple[float, float, bool, int]: (loss, grad_norm, stepped, valid_targets_total)
        """
        if self.train_dataset is None or len(self.train_dataset) == 0:
            raise ValueError("train_dataset não fornecido ou vazio")

        self.model.train()
        accum_steps = self.config.training.grad_accum_steps
        micro_size = self.config.training.micro_batch_size

        # 1. Coleta micro-lotes para o ciclo de acumulação
        micro_batches: List[Batch] = []
        for _ in range(accum_steps):
            batch_indices: List[int] = []
            for _ in range(micro_size):
                idx, new_cycle = self.sampler.next_index()
                if new_cycle:
                    self.tracker.passes_completed += 1
                batch_indices.append(idx)
            mb = self.train_dataset.build_batch(batch_indices)
            micro_batches.append(mb)

            # Registra consumo estratificado de cada item do lote
            for item_id, meta in zip(mb.item_ids, mb.metadata):
                self.tracker.register_item(item_id, meta)

        # 2. Contabiliza total de alvos válidos em todo o update
        total_valid_targets = sum(mb.valid_targets_count for mb in micro_batches)
        total_positions = sum(mb.total_positions for mb in micro_batches)

        # 3. Retropropagação com ponderação exata sobre total_valid_targets
        update_loss_accum = 0.0

        for mb in micro_batches:
            mb_dev = mb.to(self.device)
            valid_k = mb_dev.valid_targets_count
            if valid_k == 0:
                continue

            with self.precision_mgr.autocast_context():
                logits = self.model(mb_dev.input_ids, attention_mask=mb_dev.attention_mask)
                effective_targets = mb_dev.targets.clone()
                # TokenDataset emits the equivalent 0/1 mask as float32; the
                # shared training contract is boolean. Normalize at this
                # consumer boundary so both representations mask PAD identically.
                loss_mask = mb_dev.loss_mask.to(dtype=torch.bool)
                effective_targets[~loss_mask] = -100

                # Soma não-reduzida de CE nas posições válidas
                ce_sum = F.cross_entropy(
                    logits.view(-1, self.config.model.vocab_size),
                    effective_targets.view(-1),
                    ignore_index=-100,
                    reduction="sum",
                )

                # Escala dividindo pelo total de alvos válidos de TODO o update
                scaled_loss = ce_sum / max(1, total_valid_targets)

            # Backward executado fora do autocast
            if self.precision_mgr.is_scaler_active and self.precision_mgr.scaler is not None:
                self.precision_mgr.scaler.scale(scaled_loss).backward()
            else:
                scaled_loss.backward()

            update_loss_accum += scaled_loss.item()

        # 4. Unscale antes de clipping
        self.precision_mgr.unscale_if_needed(self.optimizer)
        grad_norm = float(
            torch.nn.utils.clip_grad_norm_(
                self.model.parameters(),
                max_norm=self.config.training.grad_clip_norm,
            ).item()
        )

        # 5. Passo do otimizador e detecção de overflow
        stepped, current_scale = self.precision_mgr.step_and_update(
            self.optimizer,
            global_step=self.global_step,
        )

        # 6. Atualização de contadores e scheduler
        if stepped:
            self.global_step += 1
            self.scheduler.step()
            self.tokens_for_successful_updates += total_valid_targets
        else:
            self.overflow_updates_count += 1
            # Em overflow, scheduler não avança e global_step não incrementa

        self.tokens_seen += total_valid_targets
        self.total_positions_evaluated += total_positions

        # 7. Zera gradientes imediatamente após tentativa concluída
        self.optimizer.zero_grad(set_to_none=True)

        # 8. Registro de métricas do passo
        current_lr = self.scheduler.get_last_lr()[0]
        self._log_event(
            "train_step",
            {
                "loss": update_loss_accum,
                "learning_rate": current_lr,
                "grad_norm": grad_norm,
                "stepped": stepped,
                "scale": current_scale,
                "valid_targets_in_update": total_valid_targets,
                "total_positions_in_update": total_positions,
            },
        )

        return update_loss_accum, grad_norm, stepped, total_valid_targets

    def evaluate(self) -> Dict[str, float]:
        """Avalia a perda e perplexidade sobre a partição de avaliação."""
        if self.eval_dataset is None or len(self.eval_dataset) == 0:
            return {}

        self.model.eval()
        total_eval_ce = 0.0
        total_eval_targets = 0

        with torch.no_grad():
            micro_size = self.config.training.micro_batch_size
            for start_idx in range(0, len(self.eval_dataset), micro_size):
                end_idx = min(len(self.eval_dataset), start_idx + micro_size)
                indices = list(range(start_idx, end_idx))
                mb = self.eval_dataset.build_batch(indices).to(self.device)

                with self.precision_mgr.autocast_context():
                    logits = self.model(mb.input_ids, attention_mask=mb.attention_mask)
                    effective_targets = mb.targets.clone()
                    # Keep evaluation's masking semantics identical to training
                    # when the tokenizer dataset supplies its 0/1 float mask.
                    loss_mask = mb.loss_mask.to(dtype=torch.bool)
                    effective_targets[~loss_mask] = -100
                    ce_sum = F.cross_entropy(
                        logits.view(-1, self.config.model.vocab_size),
                        effective_targets.view(-1),
                        ignore_index=-100,
                        reduction="sum",
                    )

                total_eval_ce += ce_sum.item()
                total_eval_targets += mb.valid_targets_count

        val_loss = total_eval_ce / max(1, total_eval_targets)
        perplexity = math.exp(min(val_loss, 100.0))

        if self.best_val_loss is None or val_loss < self.best_val_loss:
            self.best_val_loss = val_loss

        self.model.train()

        metrics = {
            "eval_loss": val_loss,
            "perplexity": perplexity,
            "eval_valid_targets": total_eval_targets,
        }
        self._log_event("evaluation", metrics)
        return metrics

    def should_stop(self, start_time: float) -> Tuple[bool, str]:
        """Verifica se algum critério de parada foi satisfeito."""
        # Critério 0: Teto de passos da sessão atual
        if self.session_max_steps is not None and self.global_step >= self.session_max_steps:
            return True, f"session_max_steps atingido ({self.global_step} >= {self.session_max_steps})"

        # Critério 1: Passos máximos de atualização do plano científico
        if self.global_step >= self.config.training.max_steps:
            return True, f"max_steps atingido ({self.global_step} >= {self.config.training.max_steps})"

        # Critério 2: Orçamento de tokens
        if self.config.training.max_tokens is not None:
            if self.config.training.budget_counter == "successful_update_tokens":
                if self.tokens_for_successful_updates >= self.config.training.max_tokens:
                    return (
                        True,
                        f"max_tokens de updates bem-sucedidos atingido "
                        f"({self.tokens_for_successful_updates} >= {self.config.training.max_tokens})",
                    )
            else:
                if self.tokens_seen >= self.config.training.max_tokens:
                    return (
                        True,
                        f"max_tokens consumidos atingido ({self.tokens_seen} >= {self.config.training.max_tokens})",
                    )

        # Critério 3: Tempo máximo em segundos
        if self.config.training.max_seconds is not None:
            elapsed = time.time() - start_time
            if elapsed >= self.config.training.max_seconds:
                return True, f"max_seconds atingido ({elapsed:.1f}s >= {self.config.training.max_seconds}s)"

        return False, ""

    def save_and_publish_checkpoint(self, checkpoint_id: Optional[str] = None) -> Dict[str, Any]:
        """Salva localmente e publica no repositório persistente após validação completa."""
        if checkpoint_id is None:
            checkpoint_id = f"step_{self.global_step:06d}"

        local_ckpt_dir = self.local_staging_root / checkpoint_id
        _, manifest = save_checkpoint(
            save_dir=local_ckpt_dir,
            config=self.config,
            model=self.model,
            optimizer=self.optimizer,
            scheduler=self.scheduler,
            precision_mgr=self.precision_mgr,
            sampler=self.sampler,
            tracker=self.tracker,
            global_step=self.global_step,
            tokens_seen=self.tokens_seen,
            tokens_for_successful_updates=self.tokens_for_successful_updates,
            overflow_updates_count=self.overflow_updates_count,
            total_positions_evaluated=self.total_positions_evaluated,
            segment_id=self.segment_id,
            event_sequence=self.event_sequence,
            checkpoint_id=checkpoint_id,
            best_val_loss=self.best_val_loss,
        )

        # Publica no backend persistente
        verified_manifest = self.persistence.publish_checkpoint(
            local_checkpoint_dir=local_ckpt_dir,
            persistent_run_root=self.persistent_run_root,
        )

        self._log_event(
            "checkpoint_saved",
            {"checkpoint_id": checkpoint_id, "manifest_sha256": manifest["files"][0]["sha256"]},
        )
        return verified_manifest

    def resume_from_checkpoint(self, selector: str = "latest") -> None:
        """Resolve e restaura o estado de treino a partir de um checkpoint persistente."""
        ckpt_dir = self.persistence.resolve_checkpoint(
            persistent_run_root=self.persistent_run_root,
            selector=selector,
        )
        _, sci_hash, _ = self.config.compute_hashes()
        ckpt_data = load_checkpoint(ckpt_dir, expected_scientific_hash=sci_hash)

        restore_training_state(
            ckpt_data=ckpt_data,
            model=self.model,
            optimizer=self.optimizer,
            scheduler=self.scheduler,
            precision_mgr=self.precision_mgr,
            sampler=self.sampler,
            tracker=self.tracker,
        )

        self.global_step = ckpt_data["global_step"]
        self.tokens_seen = ckpt_data["tokens_seen"]
        self.tokens_for_successful_updates = ckpt_data["tokens_for_successful_updates"]
        self.overflow_updates_count = ckpt_data["overflow_updates_count"]
        self.total_positions_evaluated = ckpt_data["total_positions_evaluated"]
        self.event_sequence = ckpt_data["event_sequence"]
        self.best_val_loss = ckpt_data.get("best_val_loss")

        self._log_event("checkpoint_resumed", {"checkpoint_id": ckpt_data["checkpoint_id"]})

    def run(self) -> Dict[str, Any]:
        """Executa o loop principal de treinamento com paradas seguras e checkpoints intermediários."""
        start_time = time.time()
        last_ckpt_time = start_time

        while True:
            # 1. Avaliação periódica
            if (
                self.config.training.evaluation_interval > 0
                and self.global_step > 0
                and self.global_step % self.config.training.evaluation_interval == 0
            ):
                self.evaluate()

            # 2. Checkpoint periódico por passos ou por tempo
            now = time.time()
            time_since_ckpt = now - last_ckpt_time
            should_save_by_steps = (
                self.config.training.checkpoint_interval_steps > 0
                and self.global_step > 0
                and self.global_step % self.config.training.checkpoint_interval_steps == 0
            )
            should_save_by_time = (
                self.config.training.checkpoint_interval_seconds > 0
                and time_since_ckpt >= self.config.training.checkpoint_interval_seconds
            )

            if should_save_by_steps or should_save_by_time:
                self.save_and_publish_checkpoint()
                last_ckpt_time = now

            # 3. Verifica condições de término
            stop, reason = self.should_stop(start_time)
            if stop:
                break

            # 4. Executa passo de treino
            self.train_step()

        # Salva checkpoint final se houver passos executados
        if self.global_step > 0:
            self.save_and_publish_checkpoint(checkpoint_id=f"step_{self.global_step:06d}_final")

        total_elapsed = time.time() - start_time
        summary = {
            "status": "completed",
            "stop_reason": reason,
            "global_step": self.global_step,
            "tokens_seen": self.tokens_seen,
            "tokens_for_successful_updates": self.tokens_for_successful_updates,
            "overflow_updates_count": self.overflow_updates_count,
            "total_positions_evaluated": self.total_positions_evaluated,
            "elapsed_seconds": total_elapsed,
            "best_val_loss": self.best_val_loss,
            "coverage_summary": self.tracker.summary(),
        }
        self._log_event("training_completed", summary)
        return summary
