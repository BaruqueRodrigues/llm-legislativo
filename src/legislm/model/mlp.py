"""
src/legislm/model/mlp.py
Camada Feed-Forward (MLP) com expansão 4d, ativação GELU e dropout configurável.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from legislm.model.config import GPTConfig


class FeedForward(nn.Module):
    """Rede Feed-Forward densa (MLP) com projeção intermediária de 4 * d_model.

    Arquitetura:
        Linear(d_model -> 4 * d_model) -> GELU -> Linear(4 * d_model -> d_model) -> Dropout
    """

    def __init__(self, config: GPTConfig) -> None:
        super().__init__()
        self.fc1 = nn.Linear(config.d_model, 4 * config.d_model, bias=config.bias)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(4 * config.d_model, config.d_model, bias=config.bias)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Aplica projeção expansiva, não-linearidade GELU e contração de volta para d_model."""
        h = self.fc1(x)
        h = self.act(h)
        h = self.fc2(h)
        return self.dropout(h)
