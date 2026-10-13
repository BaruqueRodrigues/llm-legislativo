"""
tests/training/test_loss_and_accumulation.py
Prova matemática da equivalência de gradiente em acumulação heterogênea.
"""

import copy
import unittest

import torch
import torch.nn.functional as F

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel
from legislm.training.data import Batch


class TestLossAndAccumulation(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(1234)
        self.gpt_cfg = GPTConfig(
            vocab_size=64,
            context_length=16,
            d_model=32,
            n_layers=2,
            n_heads=2,
            dropout=0.0,  # Zero dropout para comparação determinística de gradientes
            tie_embeddings=True,
        )

    def test_gradient_exactness_heterogeneous_accumulation(self):
        """Prova formal de que acumular CE_k / N_total é matematicamente idêntico

        à avaliação conjunta do lote, mesmo quando os micro-lotes possuem quantidades
        completamente distintas de padding / alvos válidos (N1 != N2).
        """
        # Modelo base
        model_joint = GPTModel(self.gpt_cfg)
        model_accum = copy.deepcopy(model_joint)

        L = self.gpt_cfg.context_length

        # Micro-lote 1: Apenas 4 alvos válidos (muito padding)
        N1 = 4
        inp1 = torch.randint(3, self.gpt_cfg.vocab_size, (1, L))
        inp1[0, N1:] = 0  # PAD
        tgt1 = torch.randint(3, self.gpt_cfg.vocab_size, (1, L))
        tgt1[0, N1:] = -100
        attn1 = torch.zeros((1, L), dtype=torch.bool)
        attn1[0, :N1] = True
        loss_m1 = torch.zeros((1, L), dtype=torch.bool)
        loss_m1[0, :N1] = True

        mb1 = Batch(
            input_ids=inp1,
            targets=tgt1,
            attention_mask=attn1,
            loss_mask=loss_m1,
            item_ids=["doc_1"],
            window_offsets=[0],
        )

        # Micro-lote 2: 14 alvos válidos (pouco padding)
        N2 = 14
        inp2 = torch.randint(3, self.gpt_cfg.vocab_size, (1, L))
        inp2[0, N2:] = 0  # PAD
        tgt2 = torch.randint(3, self.gpt_cfg.vocab_size, (1, L))
        tgt2[0, N2:] = -100
        attn2 = torch.zeros((1, L), dtype=torch.bool)
        attn2[0, :N2] = True
        loss_m2 = torch.zeros((1, L), dtype=torch.bool)
        loss_m2[0, :N2] = True

        mb2 = Batch(
            input_ids=inp2,
            targets=tgt2,
            attention_mask=attn2,
            loss_mask=loss_m2,
            item_ids=["doc_2"],
            window_offsets=[0],
        )

        N_total = mb1.valid_targets_count + mb2.valid_targets_count
        self.assertEqual(N_total, N1 + N2)
        self.assertNotEqual(N1, N2, "Testando estritamente tamanhos heterogêneos N1 != N2")

        # 1. Avaliação Conjunta (Joint Batch)
        inp_joint = torch.cat([mb1.input_ids, mb2.input_ids], dim=0)  # [2, L]
        tgt_joint = torch.cat([mb1.targets, mb2.targets], dim=0)  # [2, L]
        attn_joint = torch.cat([mb1.attention_mask, mb2.attention_mask], dim=0)

        model_joint.zero_grad(set_to_none=True)
        logits_joint = model_joint(inp_joint, attention_mask=attn_joint)
        ce_joint_sum = F.cross_entropy(
            logits_joint.view(-1, self.gpt_cfg.vocab_size),
            tgt_joint.view(-1),
            ignore_index=-100,
            reduction="sum",
        )
        loss_joint = ce_joint_sum / N_total
        loss_joint.backward()

        # 2. Avaliação Acumulada pelo Contrato (Accumulated Microbatches)
        model_accum.zero_grad(set_to_none=True)

        # Microbatch 1
        logits1 = model_accum(mb1.input_ids, attention_mask=mb1.attention_mask)
        ce1_sum = F.cross_entropy(
            logits1.view(-1, self.gpt_cfg.vocab_size),
            mb1.targets.view(-1),
            ignore_index=-100,
            reduction="sum",
        )
        scaled_loss1 = ce1_sum / N_total
        scaled_loss1.backward()

        # Microbatch 2
        logits2 = model_accum(mb2.input_ids, attention_mask=mb2.attention_mask)
        ce2_sum = F.cross_entropy(
            logits2.view(-1, self.gpt_cfg.vocab_size),
            mb2.targets.view(-1),
            ignore_index=-100,
            reduction="sum",
        )
        scaled_loss2 = ce2_sum / N_total
        scaled_loss2.backward()

        accum_total_loss = (scaled_loss1 + scaled_loss2).item()
        self.assertAlmostEqual(loss_joint.item(), accum_total_loss, places=6)

        # 3. Compara gradiente parâmetro por parâmetro
        for (name_j, p_j), (name_a, p_a) in zip(
            model_joint.named_parameters(), model_accum.named_parameters()
        ):
            self.assertEqual(name_j, name_a)
            self.assertIsNotNone(p_j.grad, f"Gradiente ausente em {name_j}")
            self.assertIsNotNone(p_a.grad, f"Gradiente ausente em {name_a}")
            self.assertTrue(
                torch.allclose(p_j.grad, p_a.grad, atol=1e-6, rtol=1e-5),
                f"Divergência de gradiente em {name_j}: max diff = {(p_j.grad - p_a.grad).abs().max().item()}",
            )

        # 4. Prova de que a média ingênua dos microbatches NÃO produz o gradiente correto
        model_naive = copy.deepcopy(model_joint)
        model_naive.zero_grad(set_to_none=True)

        logits1_n = model_naive(mb1.input_ids, attention_mask=mb1.attention_mask)
        loss1_naive = (
            F.cross_entropy(
                logits1_n.view(-1, self.gpt_cfg.vocab_size),
                mb1.targets.view(-1),
                ignore_index=-100,
                reduction="sum",
            )
            / N1
        )
        (loss1_naive / 2.0).backward()

        logits2_n = model_naive(mb2.input_ids, attention_mask=mb2.attention_mask)
        loss2_naive = (
            F.cross_entropy(
                logits2_n.view(-1, self.gpt_cfg.vocab_size),
                mb2.targets.view(-1),
                ignore_index=-100,
                reduction="sum",
            )
            / N2
        )
        (loss2_naive / 2.0).backward()

        # O gradiente ingênuo difere do gradiente correto porque N1 != N2
        has_divergence = False
        for p_j, p_n in zip(model_joint.parameters(), model_naive.parameters()):
            if not torch.allclose(p_j.grad, p_n.grad, atol=1e-4):
                has_divergence = True
                break
        self.assertTrue(
            has_divergence,
            "A média ingênua (divisão por K) deveria divergir matematicamente da média ponderada por alvos válidos",
        )


if __name__ == "__main__":
    unittest.main()
