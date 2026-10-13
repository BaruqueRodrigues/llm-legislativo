"""
tests/training/test_optimizer.py
Testes de segregação de decay no AdamW e comportamento do CosineAnnealingWarmupScheduler.
"""

import math
import unittest

import torch

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel
from legislm.training.config import TrainingHyperparameters
from legislm.training.optimizer import CosineAnnealingWarmupScheduler, configure_optimizer


class TestOptimizerAndScheduler(unittest.TestCase):
    def setUp(self):
        self.gpt_cfg = GPTConfig(
            vocab_size=128,
            context_length=32,
            d_model=64,
            n_layers=2,
            n_heads=2,
            dropout=0.1,
            tie_embeddings=True,
        )
        self.model = GPTModel(self.gpt_cfg)
        self.training_cfg = TrainingHyperparameters(
            learning_rate=1e-3,
            min_learning_rate=1e-4,
            warmup_steps=10,
            max_steps=100,
            weight_decay=0.01,
        )

    def test_parameter_group_segregation(self):
        """Verifica se parâmetros 2D recebem decay e parâmetros 1D (biases, normas) têm decay = 0.0."""
        optimizer = configure_optimizer(self.model, self.training_cfg)
        self.assertEqual(len(optimizer.param_groups), 2)

        decay_group = optimizer.param_groups[0]
        no_decay_group = optimizer.param_groups[1]

        self.assertEqual(decay_group["weight_decay"], 0.01)
        self.assertEqual(no_decay_group["weight_decay"], 0.0)

        # Verifica que nenhum tensor em no_decay_group é 2D matriz de projeção linear sem ser norma
        for p in no_decay_group["params"]:
            self.assertTrue(p.dim() < 2 or p.shape[0] == self.gpt_cfg.d_model)

        # Verifica que os pesos de projeção linear estão no decay_group
        decay_params_set = set(decay_group["params"])
        self.assertIn(self.model.blocks[0].attn.q_proj.weight, decay_params_set)
        self.assertIn(self.model.blocks[0].mlp.fc1.weight, decay_params_set)

        # Biases e LayerNorms devem estar no no_decay_group
        no_decay_params_set = set(no_decay_group["params"])
        if self.model.blocks[0].attn.q_proj.bias is not None:
            self.assertIn(self.model.blocks[0].attn.q_proj.bias, no_decay_params_set)
        self.assertIn(self.model.ln_f.weight, no_decay_params_set)
        self.assertIn(self.model.ln_f.bias, no_decay_params_set)

    def test_cosine_warmup_scheduler_trajectory(self):
        """Valida a trajetória matemática da taxa de aprendizado com warmup e decaimento cossenoidal."""
        optimizer = configure_optimizer(self.model, self.training_cfg)
        scheduler = CosineAnnealingWarmupScheduler(
            optimizer=optimizer,
            learning_rate=1e-3,
            min_learning_rate=1e-4,
            warmup_steps=10,
            max_steps=100,
        )

        # Passo 0 (início do warmup)
        lr_0 = scheduler.get_last_lr()[0]
        self.assertAlmostEqual(lr_0, 1e-4, places=6)

        # Avança até o final do warmup (passo 10)
        for _ in range(10):
            scheduler.step()
        lr_warmup = scheduler.get_last_lr()[0]
        self.assertAlmostEqual(lr_warmup, 1e-3, places=6)

        # Meio do decaimento (passo 55)
        for _ in range(45):
            scheduler.step()
        lr_mid = scheduler.get_last_lr()[0]
        # Esperado: min_lr + 0.5 * (1 + cos(pi * (55-10)/90)) * (lr - min_lr) = min_lr + 0.5 * (1 + cos(pi/2)) * (lr - min_lr)
        # cos(pi/2) = 0 => 1e-4 + 0.5 * 9e-4 = 5.5e-4
        self.assertAlmostEqual(lr_mid, 5.5e-4, places=5)

        # Final (passo 100)
        for _ in range(45):
            scheduler.step()
        lr_final = scheduler.get_last_lr()[0]
        self.assertAlmostEqual(lr_final, 1e-4, places=6)

        # Além de max_steps (passo 120), deve permanecer em min_learning_rate
        for _ in range(20):
            scheduler.step()
        lr_after = scheduler.get_last_lr()[0]
        self.assertAlmostEqual(lr_after, 1e-4, places=6)

    def test_scheduler_state_dict_restoration(self):
        """Testa que state_dict e load_state_dict restauram exatamente o passo e LR."""
        optimizer = configure_optimizer(self.model, self.training_cfg)
        scheduler = CosineAnnealingWarmupScheduler(
            optimizer=optimizer,
            learning_rate=1e-3,
            min_learning_rate=1e-4,
            warmup_steps=10,
            max_steps=100,
        )
        for _ in range(30):
            scheduler.step()
        state = scheduler.state_dict()
        lr_before = scheduler.get_last_lr()[0]

        new_optimizer = configure_optimizer(self.model, self.training_cfg)
        new_scheduler = CosineAnnealingWarmupScheduler(
            optimizer=new_optimizer,
            learning_rate=1e-3,
            min_learning_rate=1e-4,
            warmup_steps=10,
            max_steps=100,
        )
        new_scheduler.load_state_dict(state)
        lr_after = new_scheduler.get_last_lr()[0]

        self.assertEqual(lr_before, lr_after)
        self.assertEqual(new_scheduler.current_step, 30)


if __name__ == "__main__":
    unittest.main()
