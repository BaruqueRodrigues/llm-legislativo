"""
src/legislm/training/precision.py
Gerenciamento de precisão (FP32, BF16, FP16), autocast, GradScaler e rastreamento de overflow.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
from torch.optim import Optimizer


@dataclass
class ScaleTransition:
    global_step: int
    scale_before: float
    scale_after: float
    overflow_detected: bool


class StepExecutionTracker:
    """Rastreador explícito de execução de optimizer.step para detecção infalível de overflow em AMP."""

    def __init__(self, optimizer: Optimizer) -> None:
        self.optimizer = optimizer
        self.was_stepped = False
        self._orig_step = optimizer.step

    def __enter__(self) -> "StepExecutionTracker":
        self.was_stepped = False

        def hooked_step(*args: Any, **kwargs: Any) -> Any:
            self.was_stepped = True
            return self._orig_step(*args, **kwargs)

        self.optimizer.step = hooked_step  # type: ignore[assignment]
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.optimizer.step = self._orig_step  # type: ignore[assignment]


class PrecisionManager:
    """Gerenciador de precisão numérica condicionado ao hardware.

    - Mantém pesos e estados de otimizador estritamente em FP32.
    - Suporta autocast em BF16 ou FP16.
    - Controla GradScaler em FP16, com unscale antes do clipping.
    - Registra transições de escala e descarta avanços de scheduler caso ocorra overflow.
    """

    def __init__(self, precision: str = "fp32", device_type: str = "cpu") -> None:
        self.precision = precision
        self.device_type = "cuda" if device_type.startswith("cuda") else "cpu"
        self.scaler: Optional[torch.amp.GradScaler] = None
        self.scale_transitions: List[ScaleTransition] = []
        self.total_overflows = 0

        if self.precision == "fp16":
            # FP16 exige GradScaler
            device_for_scaler = self.device_type if self.device_type == "cuda" else "cpu"
            self.scaler = torch.amp.GradScaler(device_for_scaler, enabled=True)
        elif self.precision == "bf16":
            # BF16 não requer GradScaler na maioria dos hardwares
            self.scaler = None
        elif self.precision == "fp32":
            self.scaler = None
        else:
            raise ValueError(f"Precisão não suportada: {self.precision}")

    @property
    def is_scaler_active(self) -> bool:
        return self.scaler is not None and self.scaler.is_enabled()

    def autocast_context(self) -> Any:
        """Retorna o context manager de autocast correspondente."""
        if self.precision == "bf16":
            return torch.autocast(device_type=self.device_type, dtype=torch.bfloat16)
        if self.precision == "fp16":
            return torch.autocast(device_type=self.device_type, dtype=torch.float16)
        return contextlib.nullcontext()

    def unscale_if_needed(self, optimizer: Optimizer) -> None:
        """Executa unscale dos gradientes antes da aplicação de gradient clipping."""
        if self.is_scaler_active and self.scaler is not None:
            self.scaler.unscale_(optimizer)

    def step_and_update(
        self,
        optimizer: Optimizer,
        global_step: int,
    ) -> Tuple[bool, float]:
        """Executa o passo do otimizador e atualiza o scaler.

        Returns:
            Tuple[bool, float]: (update_foi_aplicado, escala_atual)
        """
        if not self.is_scaler_active or self.scaler is None:
            optimizer.step()
            return True, 1.0

        scale_before = self.scaler.get_scale()
        tracker = StepExecutionTracker(optimizer)
        with tracker:
            self.scaler.step(optimizer)

        self.scaler.update()
        scale_after = self.scaler.get_scale()

        # O update foi aplicado se o hooked_step foi efetivamente invocado
        stepped = tracker.was_stepped
        overflow = not stepped or (scale_after < scale_before)

        if overflow:
            self.total_overflows += 1

        self.scale_transitions.append(
            ScaleTransition(
                global_step=global_step,
                scale_before=scale_before,
                scale_after=scale_after,
                overflow_detected=overflow,
            )
        )

        return stepped, scale_after

    def state_dict(self) -> Dict[str, Any]:
        return {
            "precision": self.precision,
            "device_type": self.device_type,
            "total_overflows": self.total_overflows,
            "scaler_state": self.scaler.state_dict() if self.scaler is not None else None,
        }

    def load_state_dict(self, state_dict: Dict[str, Any]) -> None:
        self.total_overflows = state_dict.get("total_overflows", 0)
        if self.scaler is not None and state_dict.get("scaler_state") is not None:
            self.scaler.load_state_dict(state_dict["scaler_state"])
