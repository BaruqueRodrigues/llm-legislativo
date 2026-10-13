"""
src/legislm/model/block.py
Bloco Transformer Decoder com arquitetura Pre-LayerNorm e conexões residuais.
"""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn

from legislm.model.attention import CausalMultiHeadAttention
from legislm.model.config import GPTConfig
from legislm.model.mlp import FeedForward


class TransformerBlock(nn.Module):
    """Bloco Decoder do Transformer com Pre-LayerNorm.

    Fluxo de cálculo:
        x_norm = ln_1(x)
        x = x + attn(x_norm, attention_mask)
        x = x + mlp(ln_2(x))
    """

    def __init__(self, config: GPTConfig) -> None:
        super().__init__()
        self.ln_1 = nn.LayerNorm(config.d_model, eps=config.layer_norm_eps)
        self.attn = CausalMultiHeadAttention(config)
        self.ln_2 = nn.LayerNorm(config.d_model, eps=config.layer_norm_eps)
        self.mlp = FeedForward(config)

    def forward(
        self,
        x: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Executa um bloco decoder completo com Pre-LN e conexões residuais."""
        # Conexão residual na atenção (Pre-LN)
        x = x + self.attn(self.ln_1(x), attention_mask=attention_mask)
        # Conexão residual no MLP (Pre-LN)
        x = x + self.mlp(self.ln_2(x))
        return x
