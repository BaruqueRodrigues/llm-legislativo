"""
src/legislm/model/config.py
Configuração tipada para o Transformer Decoder (GPT educacional) do LLM legislativo.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml


@dataclass
class GPTConfig:
    """Configuração para o modelo GPT educacional.

    Atributos:
        vocab_size: Tamanho do vocabulário (inclui tokens especiais).
        context_length: Comprimento máximo de contexto (L).
        d_model: Dimensão oculta de embedding (d).
        n_layers: Número de blocos Transformer decoder.
        n_heads: Número de cabeças de atenção.
        dropout: Taxa de dropout para atenção, MLP e embeddings.
        tie_embeddings: Se True, compartilha pesos entre tok_emb e lm_head.
        bias: Se True, projeções lineares incluem bias.
        layer_norm_eps: Epsilon para estabilidade numérica nas LayerNorms.
        pad_token_id: ID do token de padding (0 por contrato normativo).
        bos_token_id: ID do token de início de sequência (1 por contrato).
        eos_token_id: ID do token de fim de sequência (2 por contrato).
    """

    vocab_size: int = 8192
    context_length: int = 512
    d_model: int = 384
    n_layers: int = 6
    n_heads: int = 6
    dropout: float = 0.1
    tie_embeddings: bool = True
    bias: bool = True
    layer_norm_eps: float = 1e-5
    pad_token_id: int = 0
    bos_token_id: int = 1
    eos_token_id: int = 2

    def __post_init__(self) -> None:
        """Validação estrita de parâmetros arquiteturais."""
        if self.vocab_size <= 0:
            raise ValueError(f"vocab_size deve ser positivo, recebido: {self.vocab_size}")
        if self.context_length <= 0:
            raise ValueError(f"context_length deve ser positivo, recebido: {self.context_length}")
        if self.d_model <= 0:
            raise ValueError(f"d_model deve ser positivo, recebido: {self.d_model}")
        if self.n_layers <= 0:
            raise ValueError(f"n_layers deve ser positivo, recebido: {self.n_layers}")
        if self.n_heads <= 0:
            raise ValueError(f"n_heads deve ser positivo, recebido: {self.n_heads}")
        if self.d_model % self.n_heads != 0:
            raise ValueError(
                f"d_model ({self.d_model}) deve ser estritamente divisível por n_heads ({self.n_heads}). "
                f"d_model % n_heads = {self.d_model % self.n_heads}"
            )
        if not (0.0 <= self.dropout < 1.0):
            raise ValueError(f"dropout deve estar em [0.0, 1.0), recebido: {self.dropout}")
        if self.layer_norm_eps <= 0.0:
            raise ValueError(f"layer_norm_eps deve ser positivo, recebido: {self.layer_norm_eps}")
        if self.pad_token_id < 0 or self.pad_token_id >= self.vocab_size:
            raise ValueError(f"pad_token_id ({self.pad_token_id}) fora dos limites do vocabulário [0, {self.vocab_size})")
        if self.bos_token_id < 0 or self.bos_token_id >= self.vocab_size:
            raise ValueError(f"bos_token_id ({self.bos_token_id}) fora dos limites do vocabulário [0, {self.vocab_size})")
        if self.eos_token_id < 0 or self.eos_token_id >= self.vocab_size:
            raise ValueError(f"eos_token_id ({self.eos_token_id}) fora dos limites do vocabulário [0, {self.vocab_size})")

    @property
    def head_dim(self) -> int:
        """Dimensão de cada cabeça individual de atenção."""
        return self.d_model // self.n_heads

    def to_dict(self) -> Dict[str, Any]:
        """Converte a configuração para dicionário."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GPTConfig:
        """Instancia GPTConfig a partir de um dicionário, filtrando chaves não pertencentes."""
        valid_keys = {
            "vocab_size",
            "context_length",
            "d_model",
            "n_layers",
            "n_heads",
            "dropout",
            "tie_embeddings",
            "bias",
            "layer_norm_eps",
            "pad_token_id",
            "bos_token_id",
            "eos_token_id",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> GPTConfig:
        """Carrega configuração de arquivo YAML (como pilot.yaml ou similar)."""
        p = Path(path)
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # Se contiver chave aninhada 'model', extrai dela
        if isinstance(data, dict) and "model" in data and isinstance(data["model"], dict):
            model_data = data["model"]
            return cls.from_dict(model_data)
        return cls.from_dict(data)
