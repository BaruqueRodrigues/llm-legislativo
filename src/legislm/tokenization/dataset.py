"""
src/legislm/tokenization/dataset.py
Geração de shards .npy, índice Parquet, janelas de contexto e Dataset/Collator PyTorch.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from torch.utils.data import Dataset

from legislm.tokenization.bpe import LegislativeBpeTokenizer
from legislm.tokenization.config import TokenizerConfig
from legislm.tokenization.reader import CuratedDocument


@dataclass
class WindowInfo:
    """Informações pré-calculadas de uma janela contextual de predição."""

    doc_idx: int
    corpus_item_id: str
    shard_path: Path
    shard_offset: int  # Offset absoluto no arquivo shard .npy
    n_pairs: int       # Quantidade de pares (input, target) válidos
    window_offset: int # Offset relativo ao início do documento (s)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenBatch:
    """Lote canônico tensorizado de treinamento em PyTorch."""

    input_ids: torch.Tensor       # [B, L] int64
    targets: torch.Tensor         # [B, L] int64 (-100 nas posições de PAD)
    attention_mask: torch.Tensor  # [B, L] bool (True para inputs válidos)
    loss_mask: torch.Tensor       # [B, L] float32 (1.0 para alvos válidos, 0.0 para PAD)
    item_ids: List[str]
    window_offsets: List[int]
    metadata: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def valid_targets_count(self) -> int:
        """Número de alvos válidos no lote (desconsiderando -100)."""
        return int((self.targets != -100).sum().item())

    @property
    def total_positions(self) -> int:
        """Total de posições processadas no lote (B * L), incluindo padding."""
        return int(self.input_ids.numel())

    def to(self, device: torch.device | str) -> "TokenBatch":
        """Transfere tensores para o dispositivo alvo (CPU, CUDA, MPS)."""
        return TokenBatch(
            input_ids=self.input_ids.to(device),
            targets=self.targets.to(device),
            attention_mask=self.attention_mask.to(device),
            loss_mask=self.loss_mask.to(device),
            item_ids=self.item_ids,
            window_offsets=self.window_offsets,
            metadata=self.metadata,
        )

    def to_training_batch(self) -> Any:
        """Converte para legislm.training.data.Batch se o módulo estiver disponível."""
        try:
            from legislm.training.data import Batch
            return Batch(
                input_ids=self.input_ids,
                targets=self.targets,
                attention_mask=self.attention_mask,
                loss_mask=self.loss_mask.bool(),
                item_ids=self.item_ids,
                window_offsets=self.window_offsets,
                metadata=self.metadata,
            )
        except ImportError:
            return self

    def __getitem__(self, key: str) -> Any:
        """Permite acesso no formato de dicionário batch['input_ids']."""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(f"Chave '{key}' não encontrada em TokenBatch")


def make_batch(samples: List[Dict[str, Any]]) -> TokenBatch:
    """Função collator canônica para DataLoader do PyTorch."""
    B = len(samples)
    if B == 0:
        raise ValueError("samples vazio em make_batch")

    input_ids = torch.stack([s["input_ids"] for s in samples], dim=0)
    targets = torch.stack([s["targets"] for s in samples], dim=0)
    attention_mask = torch.stack([s["attention_mask"] for s in samples], dim=0)
    loss_mask = torch.stack([s["loss_mask"] for s in samples], dim=0)

    item_ids = [s["corpus_item_id"] for s in samples]
    window_offsets = [s["window_offset"] for s in samples]
    metadata = [s.get("metadata", {}) for s in samples]

    return TokenBatch(
        input_ids=input_ids,
        targets=targets,
        attention_mask=attention_mask,
        loss_mask=loss_mask,
        item_ids=item_ids,
        window_offsets=window_offsets,
        metadata=metadata,
    )


class TokenDataset(Dataset):
    """Dataset PyTorch de janelas contextuais derivadas determinísticas.

    Suporta:
    1. Carregamento direto de shards .npy com mapeamento de memória (mmap_mode='r').
    2. Criação em memória para testes a partir de lista de documentos.
    3. Derivação de janelas conforme CONTRATOS_DADOS Seção 8:
       - Context length L
       - Sem duplicar alvos de predição
       - Padding à direita com PAD=0 e targets=-100
       - loss_mask float32 e attention_mask bool
    """

    def __init__(
        self,
        windows: List[WindowInfo],
        shard_cache: Optional[Dict[str, np.ndarray]] = None,
        context_length: int = 512,
        pad_token_id: int = 0,
    ) -> None:
        self.windows = windows
        self.shard_cache = shard_cache or {}
        self.context_length = context_length
        self.pad_token_id = pad_token_id

    def __len__(self) -> int:
        return len(self.windows)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        win = self.windows[idx]
        shard_p_str = str(win.shard_path)

        if shard_p_str not in self.shard_cache:
            self.shard_cache[shard_p_str] = np.load(win.shard_path, mmap_mode="r")

        shard_arr = self.shard_cache[shard_p_str]

        # Extrai n_pairs + 1 tokens: [input_tokens..., last_target_token]
        start = win.shard_offset
        end = start + win.n_pairs + 1
        seq_slice = shard_arr[start:end]

        input_tokens = seq_slice[: win.n_pairs]
        target_tokens = seq_slice[1 : win.n_pairs + 1]

        L = self.context_length
        input_ids = torch.full((L,), self.pad_token_id, dtype=torch.long)
        targets = torch.full((L,), -100, dtype=torch.long)
        attention_mask = torch.zeros((L,), dtype=torch.bool)
        loss_mask = torch.zeros((L,), dtype=torch.float32)

        input_ids[: win.n_pairs] = torch.from_numpy(input_tokens.astype(np.int64))
        targets[: win.n_pairs] = torch.from_numpy(target_tokens.astype(np.int64))
        attention_mask[: win.n_pairs] = True
        loss_mask[: win.n_pairs] = 1.0

        return {
            "input_ids": input_ids,
            "targets": targets,
            "attention_mask": attention_mask,
            "loss_mask": loss_mask,
            "corpus_item_id": win.corpus_item_id,
            "window_offset": win.window_offset,
            "metadata": win.metadata,
        }

    def get_window(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, str, int, Dict[str, Any]]:
        """Método de compatibilidade direta com Training engine."""
        item = self[idx]
        return (
            item["input_ids"],
            item["targets"],
            item["attention_mask"],
            item["loss_mask"],
            item["corpus_item_id"],
            item["window_offset"],
            item["metadata"],
        )

    def build_batch(self, indices: List[int]) -> TokenBatch:
        """Monta um TokenBatch a partir de uma lista de índices."""
        samples = [self[i] for i in indices]
        return make_batch(samples)

    @classmethod
    def from_dataset_dir(
        cls,
        dataset_dir: Union[str, Path],
        split: str = "train",
        context_length: Optional[int] = None,
        pad_token_id: int = 0,
    ) -> "TokenDataset":
        """Carrega TokenDataset a partir do diretório com token_index.parquet e shards."""
        d_dir = Path(dataset_dir)
        index_path = d_dir / "token_index.parquet"
        manifest_path = d_dir / "token_dataset_manifest.json"

        if not index_path.exists():
            raise FileNotFoundError(f"Índice de tokens não encontrado: {index_path}")

        # Se context_length não for fornecido, lê do manifesto
        if context_length is None and manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                man_data = json.load(f)
            context_length = man_data.get("context_length", 512)
        elif context_length is None:
            context_length = 512

        index_table = pq.read_table(index_path)

        # Filtra registros do split
        windows: List[WindowInfo] = []
        shard_cache: Dict[str, np.ndarray] = {}

        for i in range(index_table.num_rows):
            row_split = index_table["split"][i].as_py()
            if row_split != split:
                continue

            item_id = index_table["corpus_item_id"][i].as_py()
            rel_shard_path = index_table["shard_path"][i].as_py()
            doc_offset = index_table["offset"][i].as_py()
            doc_length = index_table["length"][i].as_py()

            shard_full_path = d_dir / rel_shard_path
            if not shard_full_path.exists():
                raise FileNotFoundError(f"Shard de tokens ausente: {shard_full_path}")

            # Deriva janelas de predição para o documento
            # Total de pares alvos = doc_length - 1
            if doc_length < 2:
                continue

            for s in range(0, doc_length - 1, context_length):
                n_pairs = min(context_length, doc_length - 1 - s)
                if n_pairs > 0:
                    win = WindowInfo(
                        doc_idx=i,
                        corpus_item_id=item_id,
                        shard_path=shard_full_path,
                        shard_offset=doc_offset + s,
                        n_pairs=n_pairs,
                        window_offset=s,
                        metadata={"split": split, "length": doc_length},
                    )
                    windows.append(win)

        return cls(
            windows=windows,
            shard_cache=shard_cache,
            context_length=context_length,
            pad_token_id=pad_token_id,
        )


def build_token_dataset(
    docs_by_split: Dict[str, Iterable[CuratedDocument]],
    tokenizer: LegislativeBpeTokenizer,
    config: TokenizerConfig,
    output_dir: Union[str, Path],
    tokenizer_file_sha256: str,
) -> Tuple[Path, Path, Path]:
    """Tokeniza documentos por split, salva shards .npy, índice Parquet e manifesto.

    Invariantes garantidas:
    - Sequências formadas por [BOS] + encode(text) + [EOS].
    - Arquivos .npy int32 little-endian, sem pickle.
    - Intervalos [offset, offset + length) disjuntos e contíguos por shard.
    - Janelas contextuais sem duplicação de alvos de predição.
    - Manifesto conforme token_dataset_manifest.schema.json e marcador COMPLETE.json.
    """
    out_dir = Path(output_dir)
    tokens_base_dir = out_dir / config.dataset.shards_dir
    tokens_base_dir.mkdir(parents=True, exist_ok=True)

    index_rows: Dict[str, List[Any]] = {
        "corpus_item_id": [],
        "split": [],
        "shard_path": [],
        "offset": [],
        "length": [],
        "text_sha256": [],
        "utf8_bytes": [],
    }

    manifest_files: List[Dict[str, Any]] = []
    counts_by_split: Dict[str, Dict[str, int]] = {}

    max_shard_tokens = config.dataset.max_shard_tokens
    L = config.dataset.context_length

    for split_name, docs in docs_by_split.items():
        if not docs:
            continue

        split_tokens_dir = tokens_base_dir / split_name
        split_tokens_dir.mkdir(parents=True, exist_ok=True)

        current_shard_idx = 0
        current_shard_tokens: List[int] = []
        current_shard_offset = 0

        total_items = 0
        total_body_tokens = 0
        total_all_tokens = 0
        total_valid_targets = 0
        total_bytes = 0
        total_windows = 0

        def flush_shard(tokens: List[int], shard_idx: int) -> Dict[str, Any]:
            shard_fname = f"shard_{shard_idx:05d}.npy"
            shard_path = split_tokens_dir / shard_fname
            arr = np.array(tokens, dtype="<i4")  # little-endian int32
            np.save(shard_path, arr)

            size_bytes = shard_path.stat().st_size
            sha256_hash = hashlib.sha256(shard_path.read_bytes()).hexdigest()
            rel_path = f"{config.dataset.shards_dir}/{split_name}/{shard_fname}"

            return {
                "path": rel_path,
                "split": split_name,
                "size_bytes": size_bytes,
                "sha256": sha256_hash,
            }

        for doc in docs:
            total_items += 1
            body_ids = tokenizer.encode(doc.text)
            seq_ids = [1] + body_ids + [2]  # [BOS] + text + [EOS]
            seq_len = len(seq_ids)

            # Se adicionar esta sequência ultrapassar o limite do shard e o shard já tem tokens, descarrega
            if len(current_shard_tokens) + seq_len > max_shard_tokens and len(current_shard_tokens) > 0:
                file_meta = flush_shard(current_shard_tokens, current_shard_idx)
                manifest_files.append(file_meta)
                current_shard_idx += 1
                current_shard_tokens = []
                current_shard_offset = 0

            doc_offset = current_shard_offset
            current_shard_tokens.extend(seq_ids)
            current_shard_offset += seq_len

            shard_fname = f"shard_{current_shard_idx:05d}.npy"
            rel_shard_path = f"{config.dataset.shards_dir}/{split_name}/{shard_fname}"

            index_rows["corpus_item_id"].append(doc.corpus_item_id)
            index_rows["split"].append(split_name)
            index_rows["shard_path"].append(rel_shard_path)
            index_rows["offset"].append(doc_offset)
            index_rows["length"].append(seq_len)
            index_rows["text_sha256"].append(doc.text_sha256)
            index_rows["utf8_bytes"].append(doc.utf8_bytes)

            # Atualização de métricas do split
            total_body_tokens += len(body_ids)
            total_all_tokens += seq_len
            total_valid_targets += seq_len - 1
            total_bytes += doc.utf8_bytes

            # Contagem de janelas contextuais derivadas
            for s in range(0, seq_len - 1, L):
                n_pairs = min(L, seq_len - 1 - s)
                if n_pairs > 0:
                    total_windows += 1

        # Descarrega o último shard pendente do split
        if current_shard_tokens:
            file_meta = flush_shard(current_shard_tokens, current_shard_idx)
            manifest_files.append(file_meta)

        counts_by_split[split_name] = {
            "items": total_items,
            "body_tokens": total_body_tokens,
            "total_tokens": total_all_tokens,
            "valid_targets": total_valid_targets,
            "bytes": total_bytes,
            "windows": total_windows,
        }

    # Salva token_index.parquet
    index_schema = pa.schema([
        pa.field("corpus_item_id", pa.string(), nullable=False),
        pa.field("split", pa.string(), nullable=False),
        pa.field("shard_path", pa.string(), nullable=False),
        pa.field("offset", pa.int64(), nullable=False),
        pa.field("length", pa.int64(), nullable=False),
        pa.field("text_sha256", pa.string(), nullable=False),
        pa.field("utf8_bytes", pa.int64(), nullable=False),
    ])

    index_table = pa.Table.from_pydict(index_rows, schema=index_schema)
    index_file = out_dir / "token_index.parquet"
    pq.write_table(index_table, index_file)

    index_size = index_file.stat().st_size
    index_sha = hashlib.sha256(index_file.read_bytes()).hexdigest()
    manifest_files.append({
        "path": "token_index.parquet",
        "split": "all",
        "size_bytes": index_size,
        "sha256": index_sha,
    })

    # Monta token_dataset_manifest.json em conformidade estrita com o esquema
    manifest_data: Dict[str, Any] = {
        "token_dataset_id": config.token_dataset_id,
        "corpus_version": config.corpus_version,
        "split_version": config.split_version,
        "tokenizer_id": config.tokenizer_id,
        "tokenizer_file_sha256": tokenizer_file_sha256,
        "sequence_policy_version": config.sequence_policy_version,
        "context_length": config.dataset.context_length,
        "special_tokens": config.special_tokens.to_dict(),
        "dtype": config.dataset.dtype,
        "endianness": config.dataset.endianness,
        "counts": counts_by_split,
        "files": manifest_files,
    }

    manifest_file = out_dir / "token_dataset_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    manifest_sha = hashlib.sha256(manifest_file.read_bytes()).hexdigest()

    # Salva COMPLETE.json
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    complete_data = {
        "manifest_file": "token_dataset_manifest.json",
        "manifest_sha256": manifest_sha,
        "published_at_utc": now_utc,
    }
    complete_file = out_dir / "COMPLETE.json"
    with open(complete_file, "w", encoding="utf-8") as f:
        json.dump(complete_data, f, indent=2, ensure_ascii=False)

    return index_file, manifest_file, complete_file
