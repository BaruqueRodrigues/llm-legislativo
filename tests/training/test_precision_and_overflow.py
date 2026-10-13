"""
tests/training/test_precision_and_overflow.py
Testes de gerenciamento de precisão (FP32/BF16/FP16), GradScaler e tratamento de overflow.
"""

import unittest

import torch
import torch.nn as nn
from torch.optim import SGD

from legislm.training.precision import PrecisionManager, StepExecutionTracker


class TestPrecisionAndOverflow(unittest.TestCase):
    def test_precision_contexts(self):
        """Verifica a configuração dos contextos de precisão FP32, BF16 e FP16."""
        pm_fp32 = PrecisionManager(precision="fp32", device_type="cpu")
        self.assertFalse(pm_fp32.is_scaler_active)
        self.assertIsNone(pm_fp32.scaler)

        pm_bf16 = PrecisionManager(precision="bf16", device_type="cpu")
        self.assertFalse(pm_bf16.is_scaler_active)
        self.assertIsNone(pm_bf16.scaler)

        pm_fp16 = PrecisionManager(precision="fp16", device_type="cpu")
        self.assertTrue(pm_fp16.is_scaler_active)
        self.assertIsNotNone(pm_fp16.scaler)

    def test_step_execution_tracker_normal_vs_overflow(self):
        """Verifica que o StepExecutionTracker detecta com exatidão chamadas a optimizer.step."""
        model = nn.Linear(4, 2)
        opt = SGD(model.parameters(), lr=0.1)

        tracker = StepExecutionTracker(opt)
        self.assertFalse(tracker.was_stepped)

        # Sem chamar step
        with tracker:
            pass
        self.assertFalse(tracker.was_stepped)

        # Chamando step normalmente
        with tracker:
            opt.step()
        self.assertTrue(tracker.was_stepped)

    def test_scaler_overflow_handling(self):
        """Testa o comportamento do GradScaler diante de gradientes infinitos (overflow)."""
        pm = PrecisionManager(precision="fp16", device_type="cpu")
        self.assertIsNotNone(pm.scaler)

        model = nn.Linear(4, 2)
        opt = SGD(model.parameters(), lr=0.1)

        # Caso 1: Passo normal sem overflow
        x = torch.randn(2, 4)
        loss = model(x).sum()
        pm.scaler.scale(loss).backward()
        pm.unscale_if_needed(opt)

        stepped, scale_after = pm.step_and_update(opt, global_step=1)
        self.assertTrue(stepped)
        self.assertEqual(pm.total_overflows, 0)
        self.assertEqual(len(pm.scale_transitions), 1)
        self.assertFalse(pm.scale_transitions[0].overflow_detected)

        # Caso 2: Injeção de Inf nos gradientes para provocar overflow
        opt.zero_grad()
        loss2 = model(x).sum()
        pm.scaler.scale(loss2).backward()

        # Injeta Inf nos gradientes
        for p in model.parameters():
            if p.grad is not None:
                p.grad.data.fill_(float("inf"))

        pm.unscale_if_needed(opt)
        scale_before = pm.scaler.get_scale()
        stepped2, scale_after2 = pm.step_and_update(opt, global_step=2)

        # Valida que o passo foi descartado
        self.assertFalse(stepped2, "Optimizer.step não pode ter sido executado com gradientes Inf")
        self.assertLess(
            scale_after2, scale_before, "A escala do GradScaler deve diminuir após detecção de overflow"
        )
        self.assertEqual(pm.total_overflows, 1)
        self.assertEqual(len(pm.scale_transitions), 2)
        self.assertTrue(pm.scale_transitions[1].overflow_detected)


if __name__ == "__main__":
    unittest.main()
