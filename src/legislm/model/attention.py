"""
src/legislm/model/attention.py
Implementação explícita de Causal Multi-Head Attention com escala, softmax e mascaramento seguro de PAD.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from legislm.model.config import GPTConfig


class CausalMultiHeadAttention(nn.Module):
    """Mecanismo de Atenção Multi-Head Causal com projeções Q/K/V explícitas.

    Atende rigorosamente aos contratos do projeto:
    1. Projeções lineares separadas e transparentes para Query, Key e Value.
    2. Escala explícita 1/sqrt(d_head).
    3. Máscara causal combinada com máscara de padding de chaves e queries.
    4. Tratamento anti-NaN para queries descartadas (onde todas as chaves seriam mascaradas).
    """

    def __init__(self, config: GPTConfig) -> None:
        super().__init__()
        self.d_model = config.d_model
        self.n_heads = config.n_heads
        self.head_dim = config.head_dim
        self.scale = 1.0 / math.sqrt(self.head_dim)

        # Projeções explícitas e separadas para fins educacionais e auditoria clara
        self.q_proj = nn.Linear(self.d_model, self.d_model, bias=config.bias)
        self.k_proj = nn.Linear(self.d_model, self.d_model, bias=config.bias)
        self.v_proj = nn.Linear(self.d_model, self.d_model, bias=config.bias)
        self.out_proj = nn.Linear(self.d_model, self.d_model, bias=config.bias)

        # Dropouts configuráveis
        self.attn_dropout = nn.Dropout(config.dropout)
        self.resid_dropout = nn.Dropout(config.dropout)

        # Buffer da máscara causal triangular inferior [context_length, context_length]
        # (j <= i: posição i só pode atender posições j <= i)
        causal_mask = torch.tril(torch.ones(config.context_length, config.context_length, dtype=torch.bool))
        self.register_buffer("causal_mask", causal_mask.view(1, 1, config.context_length, config.context_length))

    def forward(
        self,
        x: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        return_attn_weights: bool = False,
    ) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        """Executa a atenção multi-head causal.

        Args:
            x: Tensor de entrada [batch_size, seq_len, d_model].
            attention_mask: Opcional. Tensor booleano ou 0/1 indicando posições válidas:
                - Formato [batch_size, seq_len]: True/1 para tokens reais, False/0 para PAD.
                - Formato [batch_size, 1, seq_len, seq_len] ou compatível.
            return_attn_weights: Se True, retorna também os pesos de atenção calculados.

        Returns:
            Tensor de saída projetado [batch_size, seq_len, d_model] (ou tupla com pesos).
        """
        B, L, d = x.shape
        if d != self.d_model:
            raise ValueError(f"Dimensão oculta esperada {self.d_model}, recebida: {d}")

        # 1. Projeções lineares Q, K, V
        # Formato resultante: [B, L, d_model]
        q = self.q_proj(x)
        k = self.k_proj(x)
        v = self.v_proj(x)

        # 2. Reorganização em múltiplas cabeças
        # [B, L, d_model] -> [B, L, n_heads, head_dim] -> [B, n_heads, L, head_dim]
        q = q.view(B, L, self.n_heads, self.head_dim).transpose(1, 2)
        k = k.view(B, L, self.n_heads, self.head_dim).transpose(1, 2)
        v = v.view(B, L, self.n_heads, self.head_dim).transpose(1, 2)

        # 3. Pontuação de atenção escalonada (Scaled Dot-Product)
        # scores: [B, n_heads, L, L]
        scores = torch.matmul(q, k.transpose(-2, -1)) * self.scale

        # 4. Construção da máscara combinada (Causal + Padding)
        # Causal pura: [1, 1, L, L]
        causal = self.causal_mask[:, :, :L, :L]

        if attention_mask is not None:
            if attention_mask.dim() == 2:
                # attention_mask: [B, L]
                # Converte para booleano
                bool_mask = attention_mask.to(torch.bool)
                key_mask = bool_mask.unsqueeze(1).unsqueeze(2)    # [B, 1, 1, L]
                query_mask = bool_mask.unsqueeze(1).unsqueeze(3)  # [B, 1, L, 1]
                # Combina: j <= i E key é válida E query é válida
                mask = causal & key_mask & query_mask             # [B, 1, L, L]
            elif attention_mask.dim() == 3:
                mask = causal & attention_mask.unsqueeze(1).to(torch.bool)
            elif attention_mask.dim() == 4:
                mask = causal & attention_mask.to(torch.bool)
            else:
                raise ValueError(f"attention_mask com dimensão não suportada: {attention_mask.dim()}")
        else:
            mask = causal

        # 5. Mascaramento seguro contra NaN para queries descartadas (ex.: tokens PAD à direita)
        # Se uma linha inteira de queries for mascarada (sem nenhuma chave válida),
        # um softmax de [-inf, -inf, ...] resultaria em NaN.
        # Identificamos quais linhas possuem ao menos uma chave válida:
        row_has_valid = mask.any(dim=-1, keepdim=True)  # [B, 1, L, 1]
        # Para linhas sem nenhuma chave válida, permitimos um valor seguro no softmax
        safe_mask = mask | (~row_has_valid)

        # Aplica -inf nas posições não seguras
        masked_scores = scores.masked_fill(~safe_mask, float("-inf"))

        # 6. Softmax estável sobre a última dimensão
        attn_weights = F.softmax(masked_scores, dim=-1)

        # Zera explicitamente os pesos nas linhas de queries descartadas (sem chaves válidas originais)
        attn_weights = attn_weights.masked_fill(~row_has_valid, 0.0)

        # 7. Dropout sobre os pesos de atenção
        attn_weights = self.attn_dropout(attn_weights)

        # 8. Multiplicação pelos Valores (V)
        # [B, n_heads, L, L] @ [B, n_heads, L, head_dim] -> [B, n_heads, L, head_dim]
        context = torch.matmul(attn_weights, v)

        # 9. Concatenação das cabeças
        # [B, n_heads, L, head_dim] -> [B, L, n_heads, head_dim] -> [B, L, d_model]
        context = context.transpose(1, 2).contiguous().view(B, L, self.d_model)

        # 10. Projeção final de saída e dropout residual
        out = self.out_proj(context)
        out = self.resid_dropout(out)

        # Se attention_mask for fornecida em [B, L], zera saídas de queries descartadas
        if attention_mask is not None and attention_mask.dim() == 2:
            bool_mask = attention_mask.to(torch.bool)
            out = out.masked_fill(~bool_mask.unsqueeze(-1), 0.0)

        if return_attn_weights:
            return out, attn_weights
        return out
