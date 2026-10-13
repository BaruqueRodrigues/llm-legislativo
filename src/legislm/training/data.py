"""
src/legislm/training/data.py
Lotes, rastreador estratificado e sampler determinístico para o LLM legislativo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

import torch


@dataclass
class Batch:
    """Estrutura canônica de um lote de treino conforme CONTRATOS_DADOS.md."""

    input_ids: torch.Tensor  # [B, L] int64
    targets: torch.Tensor  # [B, L] int64 (-100 nas posições sem alvo)
    attention_mask: torch.Tensor  # [B, L] bool (True para inputs válidos)
    loss_mask: torch.Tensor  # [B, L] bool (True para alvos válidos)
    item_ids: List[str]
    window_offsets: List[int]
    metadata: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def valid_targets_count(self) -> int:
        """Número de alvos válidos no lote (desconsiderando posições de PAD / -100)."""
        return int((self.targets != -100).sum().item())

    @property
    def total_positions(self) -> int:
        """Total de posições processadas no lote (B * L), incluindo padding."""
        return int(self.input_ids.numel())

    def to(self, device: torch.device | str) -> "Batch":
        """Transfere tensores para o dispositivo alvo."""
        return Batch(
            input_ids=self.input_ids.to(device),
            targets=self.targets.to(device),
            attention_mask=self.attention_mask.to(device),
            loss_mask=self.loss_mask.to(device),
            item_ids=self.item_ids,
            window_offsets=self.window_offsets,
            metadata=self.metadata,
        )


@dataclass
class DocumentItem:
    """Item documental legislativo para treinamento."""

    corpus_item_id: str
    token_ids: List[int]
    metadata: Dict[str, Any] = field(default_factory=dict)


class StratifiedTracker:
    """Rastreador de consumo estratificado e cobertura histórica.

    Registra explicitamente o consumo por estrato (casa, tipo documental, ano, versão)
    e distingue rigorosamente o orçamento do smoke da cobertura histórica completa.
    """

    def __init__(self, total_eligible_items: int) -> None:
        self.total_eligible_items = total_eligible_items
        self.total_items_consumed = 0
        self.unique_items_seen: Set[str] = set()
        self.passes_completed = 0
        self.strata_counts: Dict[str, Dict[str, int]] = {
            "house": {},
            "document_type": {},
            "year": {},
            "version": {},
        }

    def register_item(self, item_id: str, meta: Dict[str, Any]) -> None:
        """Registra o processamento de um item e atualiza os contadores de estratos."""
        self.total_items_consumed += 1
        self.unique_items_seen.add(item_id)

        house = str(meta.get("house", "unknown"))
        self.strata_counts["house"][house] = self.strata_counts["house"].get(house, 0) + 1

        doc_type = str(meta.get("normalized_kind", meta.get("type_code", "unknown")))
        self.strata_counts["document_type"][doc_type] = self.strata_counts["document_type"].get(doc_type, 0) + 1

        year = str(meta.get("year", meta.get("content_date", "unknown"))[:4] if meta.get("content_date") else meta.get("year", "unknown"))
        self.strata_counts["year"][year] = self.strata_counts["year"].get(year, 0) + 1

        version = str(meta.get("version_id", "unknown"))
        self.strata_counts["version"][version] = self.strata_counts["version"].get(version, 0) + 1

    def is_full_coverage(self) -> bool:
        """Retorna True apenas se TODOS os itens elegíveis foram observados ao menos uma vez."""
        if self.total_eligible_items == 0:
            return True
        return len(self.unique_items_seen) >= self.total_eligible_items

    def coverage_ratio(self) -> float:
        """Taxa de cobertura do corpus elegível [0.0, 1.0]."""
        if self.total_eligible_items == 0:
            return 1.0
        return float(len(self.unique_items_seen)) / float(self.total_eligible_items)

    def summary(self) -> Dict[str, Any]:
        return {
            "total_eligible_items": self.total_eligible_items,
            "unique_items_seen": len(self.unique_items_seen),
            "coverage_percentage": round(self.coverage_ratio() * 100.0, 2),
            "is_full_coverage": self.is_full_coverage(),
            "total_items_consumed": self.total_items_consumed,
            "passes_completed": self.passes_completed,
            "strata_counts": self.strata_counts,
        }

    def state_dict(self) -> Dict[str, Any]:
        return {
            "total_eligible_items": self.total_eligible_items,
            "total_items_consumed": self.total_items_consumed,
            "unique_items_seen": list(self.unique_items_seen),
            "passes_completed": self.passes_completed,
            "strata_counts": self.strata_counts,
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        self.total_eligible_items = state_dict["total_eligible_items"]
        self.total_items_consumed = state_dict["total_items_consumed"]
        self.unique_items_seen = set(state_dict["unique_items_seen"])
        self.passes_completed = state_dict["passes_completed"]
        self.strata_counts = state_dict["strata_counts"]


class DeterministicSampler:
    """Sampler determinístico e reproduzível com estado preservável e retomável.

    Permuta todos os itens da partição de treino sem exclusão ou filtro.
    Garante restauração exata do cursor para que a retomada produza a sequência idêntica.
    """

    def __init__(self, num_items: int, seed: int = 42, epoch: int = 0, cursor: int = 0) -> None:
        self.num_items = num_items
        self.seed = seed
        self.epoch = epoch
        self.cursor = cursor
        self.permutation: List[int] = []
        self._generate_permutation()

    def _generate_permutation(self) -> None:
        if self.num_items <= 0:
            self.permutation = []
            return
        g = torch.Generator()
        g.manual_seed(self.seed + self.epoch)
        self.permutation = torch.randperm(self.num_items, generator=g).tolist()

    def next_index(self) -> Tuple[int, bool]:
        """Retorna (índice, novo_ciclo_iniciado)."""
        if self.num_items <= 0:
            raise StopIteration("Sampler vazio")

        idx = self.permutation[self.cursor]
        self.cursor += 1
        new_cycle = False

        if self.cursor >= self.num_items:
            self.epoch += 1
            self.cursor = 0
            self._generate_permutation()
            new_cycle = True

        return idx, new_cycle

    def state_dict(self) -> Dict[str, Any]:
        return {
            "num_items": self.num_items,
            "seed": self.seed,
            "epoch": self.epoch,
            "cursor": self.cursor,
            "permutation": list(self.permutation),
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        self.num_items = state_dict["num_items"]
        self.seed = state_dict["seed"]
        self.epoch = state_dict["epoch"]
        self.cursor = state_dict["cursor"]
        self.permutation = list(state_dict["permutation"])


class TokenDataset:
    """Dataset de sequências legislativas particionadas em janelas contextuais.

    Regra canônica de janelas (CONTRATOS_DADOS Seção 8):
    Para comprimento L, inícios s em range(0, len(ids)-1, L):
    - n_pairs = min(L, len(ids)-1-s)
    - input = ids[s : s+n_pairs]
    - target = ids[s+1 : s+n_pairs+1]
    - Padding à direita com PAD=0 no input e target=-100
    - attention_mask indica tokens de input válidos
    - loss_mask indica alvos válidos
    """

    def __init__(
        self,
        items: Sequence[DocumentItem],
        context_length: int = 512,
        pad_token_id: int = 0,
    ) -> None:
        self.items = list(items)
        self.context_length = context_length
        self.pad_token_id = pad_token_id

        # Pré-calcula janelas para cada item
        self.windows: List[Tuple[int, int, int]] = []  # (item_idx, start_pos, n_pairs)
        for item_idx, doc in enumerate(self.items):
            token_ids = doc.token_ids
            # Exige ao menos 2 tokens para formar ao menos 1 par (input, target)
            if len(token_ids) < 2:
                continue
            for s in range(0, len(token_ids) - 1, self.context_length):
                n_pairs = min(self.context_length, len(token_ids) - 1 - s)
                if n_pairs > 0:
                    self.windows.append((item_idx, s, n_pairs))

    def __len__(self) -> int:
        return len(self.windows)

    def get_window(self, index: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, str, int, Dict[str, Any]]:
        """Retorna tensores e metadados de uma única janela."""
        item_idx, start_pos, n_pairs = self.windows[index]
        doc = self.items[item_idx]
        tokens = doc.token_ids

        input_slice = tokens[start_pos : start_pos + n_pairs]
        target_slice = tokens[start_pos + 1 : start_pos + 1 + n_pairs]

        L = self.context_length
        pad_len = L - n_pairs

        # Montagem de tensores com padding à direita
        input_ids = torch.full((L,), self.pad_token_id, dtype=torch.long)
        targets = torch.full((L,), -100, dtype=torch.long)
        attention_mask = torch.zeros((L,), dtype=torch.bool)
        loss_mask = torch.zeros((L,), dtype=torch.bool)

        input_ids[:n_pairs] = torch.tensor(input_slice, dtype=torch.long)
        targets[:n_pairs] = torch.tensor(target_slice, dtype=torch.long)
        attention_mask[:n_pairs] = True
        loss_mask[:n_pairs] = True

        return input_ids, targets, attention_mask, loss_mask, doc.corpus_item_id, start_pos, doc.metadata

    def build_batch(self, indices: List[int]) -> Batch:
        """Agrupa uma lista de índices de janelas em um lote tensorizado."""
        B = len(indices)
        L = self.context_length

        input_ids_batch = torch.empty((B, L), dtype=torch.long)
        targets_batch = torch.empty((B, L), dtype=torch.long)
        attention_mask_batch = torch.empty((B, L), dtype=torch.bool)
        loss_mask_batch = torch.empty((B, L), dtype=torch.bool)

        item_ids: List[str] = []
        window_offsets: List[int] = []
        metadata: List[Dict[str, Any]] = []

        for b_idx, idx in enumerate(indices):
            inp, tgt, attn, loss_m, item_id, offset, meta = self.get_window(idx)
            input_ids_batch[b_idx] = inp
            targets_batch[b_idx] = tgt
            attention_mask_batch[b_idx] = attn
            loss_mask_batch[b_idx] = loss_m
            item_ids.append(item_id)
            window_offsets.append(offset)
            metadata.append(meta)

        return Batch(
            input_ids=input_ids_batch,
            targets=targets_batch,
            attention_mask=attention_mask_batch,
            loss_mask=loss_mask_batch,
            item_ids=item_ids,
            window_offsets=window_offsets,
            metadata=metadata,
        )


def create_synthetic_dataset(
    num_docs: int = 20,
    min_length: int = 50,
    max_length: int = 600,
    vocab_size: int = 8192,
    context_length: int = 512,
    seed: int = 42,
) -> TokenDataset:
    """Cria um dataset sintético diversificado com representantes de ambas as casas e múltiplos estratos."""
    g = torch.Generator()
    g.manual_seed(seed)

    houses = ["camara", "senado"]
    kinds = ["PL", "PLP", "PEC", "parecer", "emenda", "substitutivo", "diario"]
    years = [2019, 2020, 2021, 2022, 2023, 2024]

    docs: List[DocumentItem] = []
    for i in range(num_docs):
        house = houses[i % len(houses)]
        kind = kinds[i % len(kinds)]
        year = years[i % len(years)]
        doc_len = int(torch.randint(min_length, max_length, (1,), generator=g).item())

        # Tokens aleatórios válidos no intervalo [3, vocab_size-1] (0=PAD, 1=BOS, 2=EOS)
        tokens = [1] + torch.randint(3, vocab_size, (doc_len,), generator=g).tolist() + [2]

        item_id = f"{house}:doc:{kind}_{year}_{i:04d}"
        meta = {
            "house": house,
            "normalized_kind": kind,
            "year": year,
            "version_id": f"v1_{i}",
        }
        docs.append(DocumentItem(corpus_item_id=item_id, token_ids=tokens, metadata=meta))

    return TokenDataset(docs, context_length=context_length)
