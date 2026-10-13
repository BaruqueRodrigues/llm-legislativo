"""
tests/evaluation/test_evaluator.py
Testes do avaliador rigoroso, prova de perda ponderada exata e separação de alvos.
"""

import math
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List

import torch
import torch.nn as nn
import torch.nn.functional as F

from legislm.evaluation.evaluator import EvaluationMetrics, StrictEvaluator


@dataclass
class SimpleBatch:
    input_ids: torch.Tensor
    targets: torch.Tensor
    attention_mask: torch.Tensor
    loss_mask: torch.Tensor
    metadata: List[Dict[str, Any]]

    @property
    def valid_targets_count(self) -> int:
        return int((self.targets != -100).sum().item())

    @property
    def total_positions(self) -> int:
        return int(self.input_ids.numel())


class ConstantLogitsModel(nn.Module):
    """Modelo simples com logits fixos para validação matemática exata."""

    def __init__(self, vocab_size: int = 10, context_length: int = 16):
        super().__init__()
        self.config = type("Config", (), {
            "vocab_size": vocab_size,
            "context_length": context_length,
        })()
        self.param = nn.Parameter(torch.zeros(1))  # Apenas para ter parâmetro

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor = None) -> torch.Tensor:
        B, L = input_ids.shape
        # Retorna tensor onde token 0 tem logit 1.0 e demais 0.0
        logits = torch.zeros((B, L, self.config.vocab_size), dtype=torch.float32)
        logits[:, :, 0] = 1.0
        return logits


class TestStrictEvaluator(unittest.TestCase):
    def setUp(self):
        self.vocab_size = 10
        self.model = ConstantLogitsModel(vocab_size=self.vocab_size, context_length=16)
        self.evaluator = StrictEvaluator(model=self.model, vocab_size=self.vocab_size)

    def test_mathematical_proof_weighted_vs_naive_average(self):
        """Prova formal e empírica de que a média ingênua de micro-batches heterogêneos falha,
        enquanto a perda ponderada rigorosa preserva a soma NLL exata sobre todos os alvos válidos."""
        # Criamos dois lotes com quantidades muito diferentes de padding:
        # Lote 1: Apenas 2 alvos válidos (muito padding)
        # Lote 2: 10 alvos válidos (pouco padding)
        B, L = 1, 12

        # Lote 1: alvos válidos são [3, 4], resto é -100
        inp1 = torch.zeros((B, L), dtype=torch.long)
        tgt1 = torch.full((B, L), -100, dtype=torch.long)
        tgt1[0, :2] = torch.tensor([3, 4], dtype=torch.long)
        batch1 = SimpleBatch(
            input_ids=inp1,
            targets=tgt1,
            attention_mask=(tgt1 != -100),
            loss_mask=(tgt1 != -100),
            metadata=[{"house": "camara", "normalized_kind": "PL", "year": "2024"}],
        )

        # Lote 2: alvos válidos são [0, 0, ..., 0] (10 alvos)
        inp2 = torch.zeros((B, L), dtype=torch.long)
        tgt2 = torch.full((B, L), -100, dtype=torch.long)
        tgt2[0, :10] = torch.zeros(10, dtype=torch.long)
        batch2 = SimpleBatch(
            input_ids=inp2,
            targets=tgt2,
            attention_mask=(tgt2 != -100),
            loss_mask=(tgt2 != -100),
            metadata=[{"house": "senado", "normalized_kind": "parecer", "year": "2023"}],
        )

        batches = [batch1, batch2]

        # 1. Avaliador rigoroso calcula a perda ponderada exata:
        eval_metrics = self.evaluator.evaluate_batches(batches, split_name="val")

        total_valid = 2 + 10
        self.assertEqual(eval_metrics.total_valid_targets, total_valid)

        # Cálculo manual não-reduzido
        logits1 = self.model(inp1)
        ce1 = F.cross_entropy(logits1.view(-1, self.vocab_size), tgt1.view(-1), ignore_index=-100, reduction="sum").item()

        logits2 = self.model(inp2)
        ce2 = F.cross_entropy(logits2.view(-1, self.vocab_size), tgt2.view(-1), ignore_index=-100, reduction="sum").item()

        expected_weighted_loss = (ce1 + ce2) / total_valid
        naive_average_loss = 0.5 * ((ce1 / 2) + (ce2 / 10))

        # Confirma que a perda calculada pelo StrictEvaluator é a ponderada exata
        self.assertAlmostEqual(eval_metrics.loss, expected_weighted_loss, places=6)

        # Prova que a média ingênua é diferente da média ponderada real
        self.assertNotAlmostEqual(
            expected_weighted_loss,
            naive_average_loss,
            places=3,
            msg="A média ingênua deveria divergir matematicamente da ponderação exata em lotes heterogêneos!",
        )

    def test_pad_invariance_and_exclusion(self):
        """Prova que posições preenchidas com PAD (-100) são estritamente excluídas."""
        B, L = 1, 8
        inp = torch.zeros((B, L), dtype=torch.long)

        # Caso A: 4 alvos válidos com 4 tokens de PAD
        tgt_pad = torch.full((B, L), -100, dtype=torch.long)
        tgt_pad[0, :4] = torch.tensor([1, 2, 3, 4], dtype=torch.long)
        batch_pad = SimpleBatch(
            input_ids=inp,
            targets=tgt_pad,
            attention_mask=(tgt_pad != -100),
            loss_mask=(tgt_pad != -100),
            metadata=[{"house": "camara"}],
        )

        # Caso B: 4 alvos válidos com 12 tokens de PAD (total L=16)
        inp_more_pad = torch.zeros((B, 16), dtype=torch.long)
        tgt_more_pad = torch.full((B, 16), -100, dtype=torch.long)
        tgt_more_pad[0, :4] = torch.tensor([1, 2, 3, 4], dtype=torch.long)
        batch_more_pad = SimpleBatch(
            input_ids=inp_more_pad,
            targets=tgt_more_pad,
            attention_mask=(tgt_more_pad != -100),
            loss_mask=(tgt_more_pad != -100),
            metadata=[{"house": "camara"}],
        )

        res_pad = self.evaluator.evaluate_batches([batch_pad])
        res_more_pad = self.evaluator.evaluate_batches([batch_more_pad])

        self.assertEqual(res_pad.total_valid_targets, 4)
        self.assertEqual(res_more_pad.total_valid_targets, 4)
        self.assertAlmostEqual(res_pad.loss, res_more_pad.loss, places=6)
        self.assertAlmostEqual(res_pad.perplexity, res_more_pad.perplexity, places=6)

    def test_separation_of_text_and_eos_loss(self):
        """Verifica a segregação de métricas de perda de texto puro vs perda incluindo EOS."""
        B, L = 1, 4
        inp = torch.zeros((B, L), dtype=torch.long)
        # Alvos: 3 tokens de texto (IDs 3, 4, 5) e 1 token de término EOS (ID 2)
        tgt = torch.tensor([[3, 4, 5, 2]], dtype=torch.long)
        batch = SimpleBatch(
            input_ids=inp,
            targets=tgt,
            attention_mask=torch.ones((B, L), dtype=torch.bool),
            loss_mask=torch.ones((B, L), dtype=torch.bool),
            metadata=[{"house": "senado"}],
        )

        metrics = self.evaluator.evaluate_batches([batch], eos_token_id=2 if hasattr(self.evaluator, "eos_token_id") else 2)

        self.assertEqual(metrics.total_valid_targets, 4)
        self.assertEqual(metrics.total_text_targets, 3)
        self.assertEqual(metrics.total_eos_targets, 1)
        self.assertIsNotNone(metrics.text_loss)
        self.assertIsNotNone(metrics.text_perplexity)

    def test_word_perplexity_calculation(self):
        """Verifica se a perplexidade por palavra é calculada corretamente com base nas contagens."""
        B, L = 1, 4
        inp = torch.zeros((B, L), dtype=torch.long)
        tgt = torch.tensor([[0, 0, 0, 0]], dtype=torch.long)
        batch = SimpleBatch(
            input_ids=inp,
            targets=tgt,
            attention_mask=torch.ones((B, L), dtype=torch.bool),
            loss_mask=torch.ones((B, L), dtype=torch.bool),
            metadata=[{"house": "camara"}],
        )

        # 4 alvos válidos, total de 2 palavras
        metrics = self.evaluator.evaluate_batches([batch], total_words_count=2)

        self.assertEqual(metrics.total_words, 2)
        self.assertIsNotNone(metrics.word_perplexity)
        expected_word_loss = (metrics.loss * 4) / 2
        self.assertAlmostEqual(metrics.word_perplexity, math.exp(expected_word_loss), places=5)

    def test_empty_dataset_handling(self):
        """Verifica tratamento elegante de dataset vazio."""
        metrics = self.evaluator.evaluate_dataset([], split_name="test")
        self.assertEqual(metrics.total_valid_targets, 0)
        self.assertEqual(metrics.loss, 0.0)
        self.assertEqual(metrics.perplexity, 0.0)
        self.assertEqual(metrics.extra_metadata.get("status"), "empty_dataset")


if __name__ == "__main__":
    unittest.main()
