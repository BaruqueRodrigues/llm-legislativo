"""
src/legislm/training/benchmark.py
Benchmark realista de treino (CPU/GPU) com medição de VRAM/RAM, throughput e persistência.
"""

from __future__ import annotations

import gc
import math
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from legislm.model.gpt import GPTModel
from legislm.model.params import count_parameters
from legislm.training.checkpoint import load_checkpoint, save_checkpoint
from legislm.training.config import TrainingConfig
from legislm.training.data import TokenDataset, create_synthetic_dataset
from legislm.training.engine import Trainer
from legislm.training.persistence import LocalPersistenceBackend


def sync_device(device: torch.device) -> None:
    """Sincroniza o dispositivo se for CUDA ou MPS."""
    if device.type == "cuda":
        torch.cuda.synchronize()
    elif device.type == "mps" and hasattr(torch, "mps") and hasattr(torch.mps, "synchronize"):
        torch.mps.synchronize()


def run_benchmark(
    config: TrainingConfig,
    warmup_updates: int = 5,
    timed_updates: int = 20,
    dataset: Optional[TokenDataset] = None,
) -> Dict[str, Any]:
    """Executa benchmark realista e rigoroso de treinamento."""
    config.validate()
    device = torch.device(config.device)

    # 1. Instanciação e auditoria de parâmetros
    gpt_cfg = config.model.to_gpt_config()
    model = GPTModel(gpt_cfg).to(device)
    param_report = count_parameters(model)

    # 2. Dataset representativo
    if dataset is None:
        dataset = create_synthetic_dataset(
            num_docs=40,
            vocab_size=config.model.vocab_size,
            context_length=config.model.context_length,
            seed=config.training.seed,
        )

    # 3. Backend local temporário para medição de salvamento
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_run_root = Path(tmp_dir) / "bench_run"
        persistence = LocalPersistenceBackend(checkpoints_to_keep=2)

        trainer = Trainer(
            config=config,
            model=model,
            train_dataset=dataset,
            persistence_backend=persistence,
            segment_id="benchmark_segment",
        )
        trainer.persistent_run_root = tmp_run_root
        trainer.local_staging_root = tmp_run_root / "staging"

        # 4. Rodada de Warmup para aquecimento de grafos, caches e AdamW
        warmup_losses: List[float] = []
        for _ in range(warmup_updates):
            loss, _, _, _ = trainer.train_step()
            if not math.isfinite(loss):
                raise FloatingPointError(f"Perda não-finita durante warmup: {loss}")
            warmup_losses.append(loss)

        # 5. Reset de estatísticas de memória antes do trecho cronometrado
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            mem_start_alloc = torch.cuda.memory_allocated()
            mem_start_res = torch.cuda.memory_reserved()
        else:
            mem_start_alloc = 0
            mem_start_res = 0

        # 6. Trecho cronometrado de atualizações
        sync_device(device)
        start_time = time.perf_counter()

        timed_losses: List[float] = []
        valid_targets_total = 0
        positions_total = 0

        for _ in range(timed_updates):
            loss, _, stepped, v_targets = trainer.train_step()
            if not math.isfinite(loss):
                raise FloatingPointError(f"Perda não-finita durante benchmark: {loss}")
            timed_losses.append(loss)
            valid_targets_total += v_targets
            positions_total += (
                config.training.grad_accum_steps
                * config.training.micro_batch_size
                * config.model.context_length
            )

        sync_device(device)
        end_time = time.perf_counter()
        elapsed_seconds = end_time - start_time

        # 7. Memória de pico
        if device.type == "cuda":
            peak_allocated = torch.cuda.max_memory_allocated()
            peak_reserved = torch.cuda.max_memory_reserved()
        else:
            peak_allocated = 0
            peak_reserved = 0

        # 8. Medição de tempo e tamanho de checkpoint
        ckpt_start = time.perf_counter()
        verified_manifest = trainer.save_and_publish_checkpoint("bench_ckpt")
        ckpt_time = time.perf_counter() - ckpt_start

        # Medição de recarga
        load_start = time.perf_counter()
        resolved_dir = persistence.resolve_checkpoint(tmp_run_root, "bench_ckpt")
        _ = load_checkpoint(resolved_dir)
        load_time = time.perf_counter() - load_start

        ckpt_size_bytes = verified_manifest["files"][0]["size_bytes"]

    # 9. Consolidação dos resultados
    valid_targets_per_sec = valid_targets_total / max(1e-6, elapsed_seconds)
    positions_per_sec = positions_total / max(1e-6, elapsed_seconds)
    latency_per_update_ms = (elapsed_seconds / max(1, timed_updates)) * 1000.0
    latency_per_step_ms = (
        elapsed_seconds / max(1, timed_updates * config.training.grad_accum_steps)
    ) * 1000.0

    report = {
        "model_architecture": {
            "vocab_size": config.model.vocab_size,
            "context_length": config.model.context_length,
            "d_model": config.model.d_model,
            "n_layers": config.model.n_layers,
            "n_heads": config.model.n_heads,
            "tie_embeddings": config.model.tie_embeddings,
        },
        "parameter_counts": {
            "total_unique": param_report.total_unique_params,
            "trainable_unique": param_report.trainable_unique_params,
            "tied_saved": param_report.tied_params_count,
            "untied_total": param_report.total_untied_params,
        },
        "execution_settings": {
            "device": str(device),
            "precision": config.training.precision,
            "micro_batch_size": config.training.micro_batch_size,
            "grad_accum_steps": config.training.grad_accum_steps,
            "effective_batch_size": config.training.micro_batch_size
            * config.training.grad_accum_steps,
        },
        "timing_and_throughput": {
            "warmup_updates": warmup_updates,
            "timed_updates": timed_updates,
            "elapsed_seconds": round(elapsed_seconds, 4),
            "valid_targets_per_second": round(valid_targets_per_sec, 2),
            "positions_per_second": round(positions_per_sec, 2),
            "latency_per_update_ms": round(latency_per_update_ms, 2),
            "latency_per_step_ms": round(latency_per_step_ms, 2),
            "initial_loss": timed_losses[0] if timed_losses else 0.0,
            "final_loss": timed_losses[-1] if timed_losses else 0.0,
            "all_losses_finite": all(math.isfinite(x) for x in timed_losses),
        },
        "memory_usage": {
            "peak_allocated_bytes": peak_allocated,
            "peak_allocated_mb": round(peak_allocated / (1024**2), 2),
            "peak_reserved_bytes": peak_reserved,
            "peak_reserved_mb": round(peak_reserved / (1024**2), 2),
        },
        "checkpoint_performance": {
            "save_and_publish_seconds": round(ckpt_time, 4),
            "load_seconds": round(load_time, 4),
            "checkpoint_size_bytes": ckpt_size_bytes,
            "checkpoint_size_mb": round(ckpt_size_bytes / (1024**2), 2),
        },
    }
    return report
