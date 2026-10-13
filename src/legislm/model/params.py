"""
src/legislm/model/params.py
Contagem única e exata de parâmetros do Transformer Decoder, com detalhamento de tying, normas e biases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import torch
import torch.nn as nn


@dataclass
class ParameterReport:
    """Relatório detalhado de contagem de parâmetros."""

    total_unique_params: int
    trainable_unique_params: int
    tied_params_count: int
    total_untied_params: int
    tie_embeddings_active: bool
    breakdown: Dict[str, Any]

    def summary_markdown(self) -> str:
        """Gera resumo em formato markdown estruturado."""
        lines = [
            "### Contagem Exata de Parâmetros",
            "",
            f"- **Total de parâmetros únicos:** {self.total_unique_params:,}",
            f"- **Parâmetros treináveis únicos:** {self.trainable_unique_params:,}",
            f"- **Tying de embeddings ativo:** {self.tie_embeddings_active}",
            f"- **Parâmetros compartilhados (economizados):** {self.tied_params_count:,}",
            f"- **Total sem tying (se desvinculado):** {self.total_untied_params:,}",
            "",
            "#### Detalhamento por Componente:",
            "| Componente | Parâmetros |",
            "|---|---|",
        ]
        for name, count in self.breakdown.items():
            if isinstance(count, int):
                lines.append(f"| `{name}` | {count:,} |")
        return "\n".join(lines)


def count_parameters(model: nn.Module) -> ParameterReport:
    """Calcula com exatidão matemática a contagem única de parâmetros.

    Evita dupla contagem decorrente de weight tying e discrimina pesos de bias e normas.
    """
    unique_params = set()
    trainable_unique = 0
    total_unique = 0

    for p in model.parameters():
        if p not in unique_params:
            unique_params.add(p)
            numel = p.numel()
            total_unique += numel
            if p.requires_grad:
                trainable_unique += numel

    # Verifica se há tying entre tok_emb e lm_head
    tie_active = False
    tied_count = 0
    if hasattr(model, "tok_emb") and hasattr(model, "lm_head"):
        if model.tok_emb.weight is model.lm_head.weight:
            tie_active = True
            tied_count = model.tok_emb.weight.numel()

    # Contagem componente a componente
    breakdown: Dict[str, Any] = {}
    if hasattr(model, "tok_emb"):
        breakdown["tok_emb"] = model.tok_emb.weight.numel()
    if hasattr(model, "pos_emb"):
        breakdown["pos_emb"] = model.pos_emb.weight.numel()

    if hasattr(model, "blocks"):
        total_layers = 0
        for i, block in enumerate(model.blocks):
            layer_params = sum(p.numel() for p in block.parameters())
            total_layers += layer_params
            breakdown[f"block_{i}"] = layer_params
        breakdown["all_blocks_total"] = total_layers

    if hasattr(model, "ln_f"):
        breakdown["ln_f"] = sum(p.numel() for p in model.ln_f.parameters())

    if hasattr(model, "lm_head"):
        if tie_active:
            breakdown["lm_head (tied to tok_emb)"] = 0
        else:
            breakdown["lm_head (untied)"] = sum(p.numel() for p in model.lm_head.parameters())

    # Contagem de biases e normas
    total_biases = 0
    total_layer_norm_params = 0
    for name, p in model.named_parameters():
        if p not in unique_params:
            continue
        if name.endswith(".bias"):
            total_biases += p.numel()
        if "ln_" in name:
            total_layer_norm_params += p.numel()

    breakdown["biases_total"] = total_biases
    breakdown["layer_norms_total"] = total_layer_norm_params

    total_untied = total_unique + tied_count if tie_active else total_unique

    return ParameterReport(
        total_unique_params=total_unique,
        trainable_unique_params=trainable_unique,
        tied_params_count=tied_count,
        total_untied_params=total_untied,
        tie_embeddings_active=tie_active,
        breakdown=breakdown,
    )
