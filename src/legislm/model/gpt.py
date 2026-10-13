"""
src/legislm/model/gpt.py
Modelo Transformer Decoder educacional explícito (GPT) para o LLM legislativo.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from legislm.model.block import TransformerBlock
from legislm.model.config import GPTConfig


class GPTModel(nn.Module):
    """Transformer Decoder educacional implementado do zero em PyTorch.

    Componentes explícitos:
    - Embeddings de tokens e de posições aprendidas.
    - Dropout em embeddings, atenção e MLP.
    - Pilha de blocos Transformer com Pre-LayerNorm e conexões residuais.
    - LayerNorm final.
    - Projeção de saída (lm_head) com tying configurável (tie_embeddings).
    - Validação de dimensões, causalidade e cálculo de perda por alvos válidos.
    """

    def __init__(self, config: GPTConfig) -> None:
        super().__init__()
        self.config = config

        # 1. Embeddings de tokens e de posições aprendidas
        self.tok_emb = nn.Embedding(config.vocab_size, config.d_model)
        self.pos_emb = nn.Embedding(config.context_length, config.d_model)
        self.drop_emb = nn.Dropout(config.dropout)

        # 2. Pilha de blocos Transformer Decoder
        self.blocks = nn.ModuleList([TransformerBlock(config) for _ in range(config.n_layers)])

        # 3. LayerNorm final antes da projeção de vocabulário
        self.ln_f = nn.LayerNorm(config.d_model, eps=config.layer_norm_eps)

        # 4. Projeção linear final para o vocabulário (lm_head)
        self.lm_head = nn.Linear(config.d_model, config.vocab_size, bias=False)

        # 5. Tying de embeddings configurável
        if config.tie_embeddings:
            self.lm_head.weight = self.tok_emb.weight

        # Inicialização explícita dos pesos
        self.apply(self._init_weights)

        # Escalonamento de pesos residuais estilo GPT-2 (1 / sqrt(2 * n_layers))
        for pn, p in self.named_parameters():
            if pn.endswith("out_proj.weight") or pn.endswith("fc2.weight"):
                torch.nn.init.normal_(p, mean=0.0, std=0.02 / math.sqrt(2 * config.n_layers))

    def _init_weights(self, module: nn.Module) -> None:
        """Inicialização padrão gaussiana centrada em 0 com desvio 0.02."""
        if isinstance(module, nn.Linear):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                torch.nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
        elif isinstance(module, nn.LayerNorm):
            torch.nn.init.zeros_(module.bias)
            torch.nn.init.ones_(module.weight)

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        targets: Optional[torch.Tensor] = None,
        loss_mask: Optional[torch.Tensor] = None,
    ) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        """Executa a passagem para frente do modelo.

        Args:
            input_ids: Tensor de índices de tokens [batch_size, seq_len] (int64).
            attention_mask: Opcional. Máscara de atenção [batch_size, seq_len] (bool ou int).
            targets: Opcional. Alvos de próxima predição [batch_size, seq_len] (int64).
                     Posições sem alvo (como PAD) devem ter o valor -100.
            loss_mask: Opcional. Máscara booleana [batch_size, seq_len] de posições válidas para perda.

        Returns:
            Se targets is None:
                logits [batch_size, seq_len, vocab_size]
            Se targets is not None:
                (logits, loss) onde loss é a soma da CrossEntropy nos alvos válidos / total de alvos válidos.
        """
        if input_ids.dim() != 2:
            raise ValueError(f"input_ids deve ter 2 dimensões [B, L], recebido formato: {list(input_ids.shape)}")

        B, L = input_ids.shape
        if L > self.config.context_length:
            raise ValueError(
                f"Comprimento da sequência ({L}) excede o context_length máximo ({self.config.context_length})"
            )

        # Validação de IDs de entrada dentro do vocabulário
        if (input_ids < 0).any() or (input_ids >= self.config.vocab_size).any():
            min_val = input_ids.min().item()
            max_val = input_ids.max().item()
            raise ValueError(
                f"input_ids contém índices fora do vocabulário [0, {self.config.vocab_size - 1}]. "
                f"Min={min_val}, Max={max_val}"
            )

        # Validação de máscaras
        if attention_mask is not None:
            if attention_mask.shape[:2] != (B, L):
                raise ValueError(
                    f"attention_mask deve ter formato inicial ({B}, {L}), recebido: {list(attention_mask.shape)}"
                )

        # 1. Soma dos embeddings de tokens e posições
        device = input_ids.device
        positions = torch.arange(0, L, dtype=torch.long, device=device)
        x = self.tok_emb(input_ids) + self.pos_emb(positions)
        x = self.drop_emb(x)

        # 2. Passagem pelos blocos Transformer Decoder
        for block in self.blocks:
            x = block(x, attention_mask=attention_mask)

        # 3. LayerNorm final
        x = self.ln_f(x)

        # 4. Projeção para logits do vocabulário [B, L, vocab_size]
        logits = self.lm_head(x)

        # 5. Cálculo de perda se targets forem fornecidos
        if targets is not None:
            if targets.shape != (B, L):
                raise ValueError(
                    f"targets deve ter formato ({B}, {L}), recebido: {list(targets.shape)}"
                )

            effective_targets = targets.clone()
            if loss_mask is not None:
                if loss_mask.shape != (B, L):
                    raise ValueError(
                        f"loss_mask deve ter formato ({B}, {L}), recebido: {list(loss_mask.shape)}"
                    )
                effective_targets[~loss_mask.to(torch.bool)] = -100

            # Contrato: soma CE em alvos válidos / quantidade de alvos válidos; PAD (-100) não participa
            valid_targets = (effective_targets != -100).sum()
            loss = F.cross_entropy(
                logits.view(-1, self.config.vocab_size),
                effective_targets.view(-1),
                ignore_index=-100,
                reduction="sum",
            )
            if valid_targets > 0:
                loss = loss / valid_targets
            else:
                loss = torch.tensor(0.0, device=device, requires_grad=True)

            return logits, loss

        return logits
