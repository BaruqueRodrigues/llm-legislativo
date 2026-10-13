"""
tests/evaluation/test_generator.py
Testes da geração controlada, amostragem com temperatura, top-k e exportação de relatórios.
"""

import json
import tempfile
import unittest
from pathlib import Path

import torch
import torch.nn as nn

from legislm.evaluation.generator import ControlledGenerator, GenerationResult
from legislm.tokenization.bpe import LegislativeBpeTokenizer


class ToyEchoLanguageModel(nn.Module):
    """Modelo simples previsível para testes de geração."""

    def __init__(self, vocab_size: int = 64, context_length: int = 32):
        super().__init__()
        self.config = type("Config", (), {
            "vocab_size": vocab_size,
            "context_length": context_length,
        })()
        # Inicializa parâmetro fictício
        self.dummy = nn.Parameter(torch.zeros(1))

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor = None) -> torch.Tensor:
        B, L = input_ids.shape
        logits = torch.zeros((B, L, self.config.vocab_size), dtype=torch.float32)
        # Favorece o próximo índice como (último_token + 1) % vocab_size
        last_tokens = input_ids[:, -1]
        for b in range(B):
            next_fav = (last_tokens[b].item() + 1) % self.config.vocab_size
            logits[b, -1, next_fav] = 5.0
        return logits


class TestControlledGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.tokenizer = LegislativeBpeTokenizer.create_empty()
        self.model = ToyEchoLanguageModel(
            vocab_size=self.tokenizer.get_vocab_size(),
            context_length=64,
        )
        self.generator = ControlledGenerator(
            model=self.model,
            tokenizer=self.tokenizer,
            run_id="test_run",
            checkpoint_id="step_001",
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_greedy_generation_is_strictly_deterministic(self):
        """Geração com greedy=True deve produzir tokens e texto idênticos."""
        prompt = "PROJETO DE LEI"
        res1 = self.generator.generate_single(prompt, max_new_tokens=10, greedy=True)
        res2 = self.generator.generate_single(prompt, max_new_tokens=10, greedy=True)

        self.assertEqual(res1.generated_tokens, res2.generated_tokens)
        self.assertEqual(res1.generated_text, res2.generated_text)
        self.assertEqual(res1.prompt_text, prompt)
        self.assertTrue(res1.greedy)

    def test_stochastic_generation_reproducible_with_seed(self):
        """Geração com amostragem estocástica (temperatura e top_k) deve ser 100% idêntica com mesma semente."""
        prompt = "Altera a Lei nº"
        res1 = self.generator.generate_single(
            prompt,
            max_new_tokens=15,
            temperature=0.8,
            top_k=5,
            greedy=False,
            seed=12345,
        )
        res2 = self.generator.generate_single(
            prompt,
            max_new_tokens=15,
            temperature=0.8,
            top_k=5,
            greedy=False,
            seed=12345,
        )

        self.assertEqual(res1.generated_tokens, res2.generated_tokens)
        self.assertEqual(res1.generated_text, res2.generated_text)

    def test_early_stopping_on_eos(self):
        """Modelo que emite EOS (token 2) deve interromper imediatamente a geração."""
        class EosEmittingModel(nn.Module):
            def __init__(self, vocab_size):
                super().__init__()
                self.config = type("Config", (), {"vocab_size": vocab_size, "context_length": 32})()

            def forward(self, input_ids, attention_mask=None):
                B, L = input_ids.shape
                logits = torch.zeros((B, L, self.config.vocab_size))
                # Força o token EOS (ID 2) no 3º token gerado
                if L >= 3:
                    logits[:, -1, 2] = 10.0
                else:
                    logits[:, -1, 10] = 10.0
                return logits

        eos_model = EosEmittingModel(self.tokenizer.get_vocab_size())
        gen = ControlledGenerator(eos_model, self.tokenizer, eos_token_id=2)

        res = gen.generate_single("Artigo 1º", max_new_tokens=50, greedy=True)
        self.assertTrue(res.stopped_on_eos)
        self.assertLess(res.generated_token_count, 50)

    def test_generate_from_official_prompts_file(self):
        """Testa geração completa a partir de configs/evaluation/prompts.json."""
        prompts_file = Path("configs/evaluation/prompts.json")
        self.assertTrue(prompts_file.exists())

        results = self.generator.generate_from_prompts_file(
            prompts_path=prompts_file,
            max_new_tokens=8,
            greedy=True,
            seed=42,
        )

        # configs/evaluation/prompts.json possui 4 prompts oficiais
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertIsInstance(r, GenerationResult)
            self.assertTrue(len(r.prompt_text) > 0)
            self.assertGreaterEqual(r.generated_token_count, 0)
            self.assertEqual(r.run_id, "test_run")
            self.assertEqual(r.checkpoint_id, "step_001")

    def test_export_json_and_markdown(self):
        """Testa salvamento em JSON e Markdown formatado."""
        prompts_file = Path("configs/evaluation/prompts.json")
        results = self.generator.generate_from_prompts_file(
            prompts_path=prompts_file,
            max_new_tokens=5,
            greedy=True,
        )

        json_out = self.tmp_path / "generations.json"
        md_out = self.tmp_path / "generations.md"

        self.generator.save_results_json(results, json_out)
        self.generator.save_results_markdown(results, md_out)

        self.assertTrue(json_out.exists())
        self.assertTrue(md_out.exists())

        with open(json_out, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)
        self.assertIn("prompt_id", data[0])
        self.assertIn("full_text", data[0])

        md_content = md_out.read_text(encoding="utf-8")
        self.assertIn("# Registro Oficial de Gerações do LLM Legislativo", md_content)
        self.assertIn("Prompt:", md_content)


if __name__ == "__main__":
    unittest.main()
