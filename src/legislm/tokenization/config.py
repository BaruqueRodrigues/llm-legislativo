"""
src/legislm/tokenization/config.py
Configuração tipada e determinística do Tokenizer BPE Byte-Level.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass
class BPEModelConfig:
    type: str = "BPE"
    byte_fallback: bool = True
    vocab_size: int = 8192
    min_frequency: int = 2

    def validate(self) -> None:
        if self.type != "BPE":
            raise ValueError(f"Tipo de modelo deve ser 'BPE', recebido: {self.type}")
        if not self.byte_fallback:
            raise ValueError("byte_fallback deve ser True para cobertura total de bytes")
        if self.vocab_size < 259:
            # 256 bytes + 3 tokens especiais (PAD, BOS, EOS) = 259 mínimo
            raise ValueError(
                f"vocab_size deve ser no mínimo 259 (256 bytes + 3 especiais), recebido: {self.vocab_size}"
            )
        if self.min_frequency < 1:
            raise ValueError(f"min_frequency deve ser >= 1, recebido: {self.min_frequency}")


@dataclass
class SpecialTokensConfig:
    PAD: int = 0
    BOS: int = 1
    EOS: int = 2

    def validate(self) -> None:
        if self.PAD != 0 or self.BOS != 1 or self.EOS != 2:
            raise ValueError(
                f"Contrato normativo exige PAD=0, BOS=1, EOS=2. Recebido: PAD={self.PAD}, BOS={self.BOS}, EOS={self.EOS}"
            )

    def to_dict(self) -> Dict[str, int]:
        return {"PAD": self.PAD, "BOS": self.BOS, "EOS": self.EOS}


@dataclass
class TokenizationParamsConfig:
    lowercase: bool = False
    strip_accents: bool = False
    add_prefix_space: bool = False

    def validate(self) -> None:
        if self.lowercase or self.strip_accents:
            raise ValueError(
                "Normalização destrutiva (lowercase ou strip_accents) é proibida pelo contrato normativo D11"
            )


@dataclass
class DatasetConfig:
    context_length: int = 512
    dtype: str = "int32"
    endianness: str = "little"
    shards_dir: str = "tokens"
    max_shard_tokens: int = 50_000_000

    def validate(self) -> None:
        if self.context_length <= 0:
            raise ValueError(f"context_length deve ser > 0, recebido: {self.context_length}")
        if self.dtype != "int32":
            raise ValueError(f"dtype deve ser 'int32', recebido: {self.dtype}")
        if self.endianness != "little":
            raise ValueError(f"endianness deve ser 'little', recebido: {self.endianness}")


@dataclass
class TokenizerConfig:
    tokenizer_id: str = "bpe_byte_v1_8k"
    corpus_version: str = "corpus_v1"
    split_version: str = "split_v1"
    sequence_policy_version: str = "doc_window_v1"
    token_dataset_id: str = "tok_dataset_v1"
    model: BPEModelConfig = field(default_factory=BPEModelConfig)
    special_tokens: SpecialTokensConfig = field(default_factory=SpecialTokensConfig)
    tokenization: TokenizationParamsConfig = field(default_factory=TokenizationParamsConfig)
    dataset: DatasetConfig = field(default_factory=DatasetConfig)

    def validate(self) -> None:
        if not self.tokenizer_id:
            raise ValueError("tokenizer_id não pode ser vazio")
        if not self.corpus_version:
            raise ValueError("corpus_version não pode ser vazio")
        if not self.split_version:
            raise ValueError("split_version não pode ser vazio")
        if not self.sequence_policy_version:
            raise ValueError("sequence_policy_version não pode ser vazio")
        self.model.validate()
        self.special_tokens.validate()
        self.tokenization.validate()
        self.dataset.validate()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def compute_config_hash(self) -> str:
        """Calcula hash determinístico SHA-256 da configuração canônica."""
        canonical_json = json.dumps(self.to_dict(), sort_keys=True, indent=None)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenizerConfig":
        model_data = data.get("model", {})
        spec_data = data.get("special_tokens", {})
        tok_data = data.get("tokenization", {})
        ds_data = data.get("dataset", {})

        cfg = cls(
            tokenizer_id=data.get("tokenizer_id", "bpe_byte_v1_8k"),
            corpus_version=data.get("corpus_version", "corpus_v1"),
            split_version=data.get("split_version", "split_v1"),
            sequence_policy_version=data.get("sequence_policy_version", "doc_window_v1"),
            token_dataset_id=data.get("token_dataset_id", "tok_dataset_v1"),
            model=BPEModelConfig(
                type=model_data.get("type", "BPE"),
                byte_fallback=model_data.get("byte_fallback", True),
                vocab_size=model_data.get("vocab_size", 8192),
                min_frequency=model_data.get("min_frequency", 2),
            ),
            special_tokens=SpecialTokensConfig(
                PAD=spec_data.get("PAD", 0),
                BOS=spec_data.get("BOS", 1),
                EOS=spec_data.get("EOS", 2),
            ),
            tokenization=TokenizationParamsConfig(
                lowercase=tok_data.get("lowercase", False),
                strip_accents=tok_data.get("strip_accents", False),
                add_prefix_space=tok_data.get("add_prefix_space", False),
            ),
            dataset=DatasetConfig(
                context_length=ds_data.get("context_length", 512),
                dtype=ds_data.get("dtype", "int32"),
                endianness=ds_data.get("endianness", "little"),
                shards_dir=ds_data.get("shards_dir", "tokens"),
                max_shard_tokens=ds_data.get("max_shard_tokens", 50_000_000),
            ),
        )
        cfg.validate()
        return cfg

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TokenizerConfig":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)
