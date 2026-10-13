"""
src/legislm/evaluation/evaluator.py
Avaliação rigorosa ponderada pelo total de alvos válidos, perplexidade e métricas estratificadas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from legislm.evaluation.metrics import count_words
from legislm.model.gpt import GPTModel
from legislm.tokenization.bpe import LegislativeBpeTokenizer
from legislm.tokenization.reader import CuratedDocument, CuratedReleaseReader


@dataclass
class EvaluationMetrics:
    """Métricas científicas consolidadas de uma partição de avaliação."""

    split: str
    loss: float  # Cross-entropy ponderada por alvo válido (nats/token)
    perplexity: float  # exp(loss)
    text_loss: Optional[float] = None  # Loss excluindo tokens de controle/EOS
    text_perplexity: Optional[float] = None
    word_perplexity: Optional[float] = None  # exp(total_ce / total_words)
    total_valid_targets: int = 0
    total_text_targets: int = 0
    total_eos_targets: int = 0
    total_positions: int = 0
    padding_ratio: float = 0.0
    total_words: int = 0
    total_documents: int = 0
    total_windows: int = 0
    strata_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "split": self.split,
            "loss": self.loss,
            "perplexity": self.perplexity,
            "text_loss": self.text_loss,
            "text_perplexity": self.text_perplexity,
            "word_perplexity": self.word_perplexity,
            "total_valid_targets": self.total_valid_targets,
            "total_text_targets": self.total_text_targets,
            "total_eos_targets": self.total_eos_targets,
            "total_positions": self.total_positions,
            "padding_ratio": self.padding_ratio,
            "total_words": self.total_words,
            "total_documents": self.total_documents,
            "total_windows": self.total_windows,
            "strata_metrics": self.strata_metrics,
            "extra_metadata": self.extra_metadata,
        }


class StrictEvaluator:
    """Avaliador rigoroso e determinístico para o LLM Legislativo.

    Invariantes matemáticas e contratuais (docs/CONTRATOS_DADOS.md e docs/VALIDACAO.md):
    1. Cross-Entropy estritamente ponderada: soma de perda em todos os alvos válidos / total de alvos válidos.
       Jamais calcula média aritmética simples de micro-batches heterogêneos.
    2. Dropout desativado (eval/no_grad).
    3. Separação explícita entre alvos de texto ordinário e token EOS (ID 2).
    4. Alvos de PAD (-100) estritamente excluídos do numerador e do denominador.
    5. Rastreamento estratificado por casa, tipo documental e ano.
    """

    def __init__(
        self,
        model: nn.Module,
        device: Optional[Union[torch.device, str]] = None,
        vocab_size: Optional[int] = None,
        eos_token_id: int = 2,
        pad_token_id: int = 0,
    ) -> None:
        self.model = model
        if device is not None:
            self.device = torch.device(device)
        else:
            try:
                self.device = next(model.parameters()).device
            except StopIteration:
                self.device = torch.device("cpu")

        self.vocab_size = vocab_size or getattr(model.config, "vocab_size", None)
        if self.vocab_size is None:
            raise ValueError("vocab_size não pôde ser determinado a partir do modelo")
        self.eos_token_id = eos_token_id
        self.pad_token_id = pad_token_id

    def evaluate_batches(
        self,
        batches: Sequence[Any],
        split_name: str = "validation",
        total_documents_count: int = 0,
        total_words_count: int = 0,
        eos_token_id: Optional[int] = None,
    ) -> EvaluationMetrics:
        """Avalia uma sequência de lotes com acumulação de perda estritamente ponderada."""
        effective_eos_id = self.eos_token_id if eos_token_id is None else eos_token_id
        model_was_training = self.model.training
        self.model.eval()

        total_ce_sum = 0.0
        total_valid_targets = 0

        total_text_ce_sum = 0.0
        total_text_targets = 0

        total_eos_ce_sum = 0.0
        total_eos_targets = 0

        total_positions = 0
        total_windows = len(batches)

        # Estratificação por estrato
        strata: Dict[str, Dict[str, Dict[str, float]]] = {
            "house": {},
            "document_type": {},
            "year": {},
        }

        with torch.no_grad():
            for batch in batches:
                # Normalização de atributos do lote
                input_ids = getattr(batch, "input_ids").to(self.device)
                targets = getattr(batch, "targets").to(self.device)
                attention_mask = getattr(batch, "attention_mask", None)
                if attention_mask is not None:
                    attention_mask = attention_mask.to(self.device)

                loss_mask = getattr(batch, "loss_mask", None)
                if loss_mask is not None:
                    loss_mask = loss_mask.to(self.device).bool()

                effective_targets = targets.clone()
                if loss_mask is not None:
                    effective_targets[~loss_mask] = -100
                if attention_mask is not None:
                    # A máscara falsa deve excluir o alvo correspondente mesmo
                    # quando o produtor do lote não marcou PAD como -100.
                    target_attention = attention_mask.bool()
                    if target_attention.shape != effective_targets.shape:
                        raise ValueError(
                            "attention_mask deve ter a mesma forma que targets para avaliação"
                        )
                    effective_targets[~target_attention] = -100

                B, L = input_ids.shape
                batch_positions = B * L
                total_positions += batch_positions

                # Alvos válidos no batch
                valid_mask = effective_targets != -100
                batch_valid_count = int(valid_mask.sum().item())
                if batch_valid_count == 0:
                    continue

                logits = self.model(input_ids, attention_mask=attention_mask)
                # Formato [B * L, vocab_size] e [B * L]
                flat_logits = logits.view(-1, self.vocab_size)
                flat_targets = effective_targets.view(-1)

                # 1. Perda somada não-reduzida total nas posições válidas
                ce_batch = F.cross_entropy(
                    flat_logits,
                    flat_targets,
                    ignore_index=-100,
                    reduction="sum",
                ).item()

                total_ce_sum += ce_batch
                total_valid_targets += batch_valid_count

                # 2. Separação de texto vs EOS
                is_eos_mask = (flat_targets == effective_eos_id) & (flat_targets != -100)
                is_text_mask = (flat_targets != effective_eos_id) & (flat_targets != -100)

                eos_count = int(is_eos_mask.sum().item())
                text_count = int(is_text_mask.sum().item())

                if text_count > 0:
                    text_targets = flat_targets.clone()
                    text_targets[~is_text_mask] = -100
                    ce_text_batch = F.cross_entropy(
                        flat_logits,
                        text_targets,
                        ignore_index=-100,
                        reduction="sum",
                    ).item()
                    total_text_ce_sum += ce_text_batch
                    total_text_targets += text_count

                if eos_count > 0:
                    eos_targets = flat_targets.clone()
                    eos_targets[~is_eos_mask] = -100
                    ce_eos_batch = F.cross_entropy(
                        flat_logits,
                        eos_targets,
                        ignore_index=-100,
                        reduction="sum",
                    ).item()
                    total_eos_ce_sum += ce_eos_batch
                    total_eos_targets += eos_count

                # 3. Rastreamento estratificado por item no lote
                metadata_list = getattr(batch, "metadata", []) or []
                if metadata_list and len(metadata_list) == B:
                    # Distribui métricas de perda por linha do lote
                    ce_per_item = F.cross_entropy(
                        flat_logits,
                        flat_targets,
                        ignore_index=-100,
                        reduction="none",
                    ).view(B, L)

                    for b_idx in range(B):
                        meta = metadata_list[b_idx] or {}
                        item_valid = int(valid_mask[b_idx].sum().item())
                        if item_valid == 0:
                            continue
                        item_loss_sum = float(ce_per_item[b_idx][valid_mask[b_idx]].sum().item())

                        house = str(meta.get("house", "unknown"))
                        doc_type = str(meta.get("normalized_kind", meta.get("document_type", "unknown")))
                        c_date = meta.get("content_date", None)
                        year = str(c_date)[:4] if c_date else str(meta.get("year", "unknown"))

                        for s_name, s_val in [("house", house), ("document_type", doc_type), ("year", year)]:
                            if s_val not in strata[s_name]:
                                strata[s_name][s_val] = {"loss_sum": 0.0, "valid_targets": 0}
                            strata[s_name][s_val]["loss_sum"] += item_loss_sum
                            strata[s_name][s_val]["valid_targets"] += item_valid

        if model_was_training:
            self.model.train()

        # Cálculo de médias estritamente ponderadas
        if total_valid_targets > 0:
            loss = total_ce_sum / total_valid_targets
            perplexity = math.exp(min(loss, 100.0))
        else:
            loss = 0.0
            perplexity = 0.0

        if total_text_targets > 0:
            text_loss = total_text_ce_sum / total_text_targets
            text_perplexity = math.exp(min(text_loss, 100.0))
        else:
            text_loss = None
            text_perplexity = None

        if total_words_count > 0 and total_valid_targets > 0:
            word_loss = total_ce_sum / total_words_count
            word_perplexity = math.exp(min(word_loss, 100.0))
        else:
            word_perplexity = None

        padding_ratio = 1.0 - (total_valid_targets / total_positions) if total_positions > 0 else 0.0

        # Compilação dos estratos
        compiled_strata: Dict[str, Dict[str, Any]] = {}
        for s_name, s_dict in strata.items():
            compiled_strata[s_name] = {}
            for k, v in s_dict.items():
                v_tgts = v["valid_targets"]
                v_loss = v["loss_sum"] / v_tgts if v_tgts > 0 else 0.0
                compiled_strata[s_name][k] = {
                    "valid_targets": v_tgts,
                    "loss": v_loss,
                    "perplexity": math.exp(min(v_loss, 100.0)) if v_tgts > 0 else 0.0,
                }

        return EvaluationMetrics(
            split=split_name,
            loss=loss,
            perplexity=perplexity,
            text_loss=text_loss,
            text_perplexity=text_perplexity,
            word_perplexity=word_perplexity,
            total_valid_targets=total_valid_targets,
            total_text_targets=total_text_targets,
            total_eos_targets=total_eos_targets,
            total_positions=total_positions,
            padding_ratio=padding_ratio,
            total_words=total_words_count,
            total_documents=total_documents_count,
            total_windows=total_windows,
            strata_metrics=compiled_strata,
        )

    def evaluate_dataset(
        self,
        dataset: Any,
        micro_batch_size: int = 4,
        split_name: str = "validation",
    ) -> EvaluationMetrics:
        """Avalia um TokenDataset instanciado."""
        if dataset is None or len(dataset) == 0:
            return EvaluationMetrics(
                split=split_name,
                loss=0.0,
                perplexity=0.0,
                extra_metadata={"status": "empty_dataset"},
            )

        batches = []
        num_windows = len(dataset)
        for start_idx in range(0, num_windows, micro_batch_size):
            end_idx = min(num_windows, start_idx + micro_batch_size)
            indices = list(range(start_idx, end_idx))
            batch = dataset.build_batch(indices)
            batches.append(batch)

        total_docs = getattr(dataset, "total_items", len(getattr(dataset, "items", [])))
        return self.evaluate_batches(
            batches,
            split_name=split_name,
            total_documents_count=total_docs,
        )

    def evaluate_from_documents(
        self,
        documents: Sequence[CuratedDocument],
        tokenizer: LegislativeBpeTokenizer,
        context_length: int = 512,
        micro_batch_size: int = 4,
        split_name: str = "validation",
    ) -> EvaluationMetrics:
        """Constrói janelas e avalia diretamente uma sequência de CuratedDocument."""
        from legislm.training.data import DocumentItem, TokenDataset

        if not documents:
            return EvaluationMetrics(
                split=split_name,
                loss=0.0,
                perplexity=0.0,
                extra_metadata={"status": "no_documents_in_split"},
            )

        total_words = sum(count_words(d.text) for d in documents)
        items: List[DocumentItem] = []
        for d in documents:
            body_ids = tokenizer.encode(d.text)
            token_ids = [1] + body_ids + [2]  # [BOS] + text + [EOS]
            items.append(
                DocumentItem(
                    corpus_item_id=d.corpus_item_id,
                    token_ids=token_ids,
                    metadata={
                        "house": d.house,
                        "normalized_kind": d.normalized_kind,
                        "year": str(d.content_date)[:4] if d.content_date else "unknown",
                        "content_date": d.content_date,
                    },
                )
            )

        dataset = TokenDataset(items=items, context_length=context_length, pad_token_id=self.pad_token_id)
        metrics = self.evaluate_dataset(dataset, micro_batch_size=micro_batch_size, split_name=split_name)
        metrics.total_documents = len(documents)
        metrics.total_words = total_words
        if total_words > 0 and metrics.total_valid_targets > 0:
            total_ce_sum = metrics.loss * metrics.total_valid_targets
            word_loss = total_ce_sum / total_words
            metrics.word_perplexity = math.exp(min(word_loss, 100.0))
        return metrics

    def evaluate_from_release(
        self,
        release_dir: Union[str, Path],
        tokenizer: LegislativeBpeTokenizer,
        split_name: str = "validation",
        context_length: int = 512,
        micro_batch_size: int = 4,
    ) -> EvaluationMetrics:
        """Carrega e avalia documentos de uma partição específica de release curada Parquet."""
        reader = CuratedReleaseReader(release_dir)
        try:
            docs, summary = reader.load_documents(split=split_name)
        except Exception as e:
            return EvaluationMetrics(
                split=split_name,
                loss=0.0,
                perplexity=0.0,
                extra_metadata={"error": str(e), "status": "load_failed"},
            )

        if not docs:
            return EvaluationMetrics(
                split=split_name,
                loss=0.0,
                perplexity=0.0,
                extra_metadata={"status": f"split_{split_name}_has_0_eligible_documents"},
            )

        return self.evaluate_from_documents(
            documents=docs,
            tokenizer=tokenizer,
            context_length=context_length,
            micro_batch_size=micro_batch_size,
            split_name=split_name,
        )
