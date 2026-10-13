"""
src/legislm/training/optimizer.py
Configuração de AdamW com segregação de decay e scheduler Cosine com Warmup.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import torch
import torch.nn as nn
from torch.optim import AdamW

from legislm.training.config import TrainingHyperparameters


def configure_optimizer(
    model: nn.Module,
    training_cfg: TrainingHyperparameters,
) -> AdamW:
    """Configura o otimizador AdamW com segregação estrita de regularização.

    - Parâmetros 2D (pesos de projeção Linear e Embedding) recebem weight_decay.
    - Parâmetros 1D (biases e pesos/biases de LayerNorm) têm weight_decay = 0.0.
    """
    decay_params: List[nn.Parameter] = []
    no_decay_params: List[nn.Parameter] = []

    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        # Biases e LayerNorms (1D) nunca recebem decay
        if param.dim() < 2 or "ln" in name or "bias" in name:
            no_decay_params.append(param)
        else:
            decay_params.append(param)

    optim_groups = [
        {"params": decay_params, "weight_decay": training_cfg.weight_decay},
        {"params": no_decay_params, "weight_decay": 0.0},
    ]

    optimizer = AdamW(
        optim_groups,
        lr=training_cfg.learning_rate,
        betas=(0.9, 0.95),
        eps=1e-8,
    )
    return optimizer


class CosineAnnealingWarmupScheduler:
    """Scheduler com Warmup linear e decaimento cossenoidal explícito.

    - De step=0 até step=warmup_steps: crescimento linear de min_lr para learning_rate.
    - De step=warmup_steps até step=max_steps: decaimento cossenoidal de learning_rate para min_lr.
    - Além de max_steps: fixa o aprendizado em min_lr.
    - Não avança caso o passo seja cancelado por overflow de AMP.
    """

    def __init__(
        self,
        optimizer: torch.optim.Optimizer,
        learning_rate: float,
        min_learning_rate: float,
        warmup_steps: int,
        max_steps: int,
        last_step: int = -1,
    ) -> None:
        self.optimizer = optimizer
        self.learning_rate = learning_rate
        self.min_learning_rate = min_learning_rate
        self.warmup_steps = warmup_steps
        self.max_steps = max_steps
        self.current_step = last_step

        if self.current_step == -1:
            self.step()  # Inicializa para step 0

    def get_lr_for_step(self, step: int) -> float:
        """Calcula o valor da taxa de aprendizado para um dado passo."""
        if step < self.warmup_steps:
            if self.warmup_steps == 0:
                return self.learning_rate
            alpha = float(step) / float(max(1, self.warmup_steps))
            return self.min_learning_rate + alpha * (self.learning_rate - self.min_learning_rate)

        if step >= self.max_steps:
            return self.min_learning_rate

        progress = float(step - self.warmup_steps) / float(max(1, self.max_steps - self.warmup_steps))
        cosine_coeff = 0.5 * (1.0 + math.cos(math.pi * progress))
        return self.min_learning_rate + cosine_coeff * (self.learning_rate - self.min_learning_rate)

    def step(self) -> float:
        """Avança exatamente um passo no agendamento e atualiza o otimizador."""
        self.current_step += 1
        lr = self.get_lr_for_step(self.current_step)
        for param_group in self.optimizer.param_groups:
            param_group["lr"] = lr
        return lr

    def get_last_lr(self) -> List[float]:
        """Retorna as taxas de aprendizado atuais de cada grupo de parâmetros."""
        return [group["lr"] for group in self.optimizer.param_groups]

    def state_dict(self) -> Dict[str, Any]:
        return {
            "learning_rate": self.learning_rate,
            "min_learning_rate": self.min_learning_rate,
            "warmup_steps": self.warmup_steps,
            "max_steps": self.max_steps,
            "current_step": self.current_step,
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        self.learning_rate = state_dict["learning_rate"]
        self.min_learning_rate = state_dict["min_learning_rate"]
        self.warmup_steps = state_dict["warmup_steps"]
        self.max_steps = state_dict["max_steps"]
        self.current_step = state_dict["current_step"]
        # Atualiza a taxa de aprendizado correspondente ao passo restaurado
        lr = self.get_lr_for_step(self.current_step)
        for param_group in self.optimizer.param_groups:
            param_group["lr"] = lr
