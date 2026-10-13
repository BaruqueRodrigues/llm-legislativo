"""
tests/evaluation/test_metrics_byte_nll.py
Testes da métrica comparável universal byte_nll_v1, segmentação UTF-8 e preservação de code points.
"""

import math
import unittest
from typing import List

import torch
import torch.nn as nn

from legislm.evaluation.metrics import (
    ByteNllResult,
    compute_byte_nll_v1,
    count_words,
    split_text_into_utf8_segments,
)
from legislm.tokenization.bpe import LegislativeBpeTokenizer


class MockLinearLanguageModel(nn.Module):
    """Modelo mock simplificado para testes analíticos determinísticos de perda."""

    def __init__(self, vocab_size: int = 16, context_length: int = 32):
        super().__init__()
        self.config = type("Config", (), {
            "vocab_size": vocab_size,
            "context_length": context_length,
        })()
        # Matriz fixa determinística para logits previsíveis
        self.linear = nn.Linear(vocab_size, vocab_size, bias=False)
        nn.init.eye_(self.linear.weight)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor = None) -> torch.Tensor:
        B, L = input_ids.shape
        # Produz logits com pico suave determinístico
        eye_logits = torch.zeros((B, L, self.config.vocab_size), dtype=torch.float32)
        for b in range(B):
            for l in range(L):
                tok = input_ids[b, l].item()
                eye_logits[b, l, tok % self.config.vocab_size] = 2.0
        return eye_logits


class TestMetricsByteNll(unittest.TestCase):
    def test_count_words_standard(self):
        text = "PROJETO DE LEI Nº 1234/2023\n\nAltera o art. 1º da Lei Federal."
        # Palavras separadas por whitespace:
        # ['PROJETO', 'DE', 'LEI', 'Nº', '1234/2023', 'Altera', 'o', 'art.', '1º', 'da', 'Lei', 'Federal.'] -> 12
        self.assertEqual(count_words(text), 12)
        self.assertEqual(count_words(""), 0)
        self.assertEqual(count_words("   "), 0)

    def test_split_text_utf8_segments_integrity(self):
        # Texto com múltiplos caracteres multibyte em português e símbolos
        text = "O art. 1º estabelece a criação de comissões temáticas para avaliação e votação. 🏛️"
        raw_bytes = text.encode("utf-8")

        for k in [4, 5, 8, 13, 20, 50, len(raw_bytes), len(raw_bytes) + 10]:
            segments = split_text_into_utf8_segments(text, max_bytes=k)
            # 1. Junção exata sem perda ou ganho de bytes
            reconstructed = b"".join(segments)
            self.assertEqual(reconstructed, raw_bytes)

            # 2. Cada segmento é UTF-8 válido
            for s in segments:
                self.assertLessEqual(len(s), k)
                decoded = s.decode("utf-8")
                self.assertTrue(len(decoded) > 0)

    def test_split_text_utf8_multibyte_boundary_safety(self):
        # Força o corte a cair exatamente no meio de um caractere de 2 bytes (ex: 'ç', 'ã', 'º') ou 4 bytes (emoji)
        # 'A' (1 byte), 'ç' (2 bytes: 0xC3 0xA7), 'ã' (2 bytes: 0xC3 0xA3), 'o' (1 byte)
        # Bytes: [0x41, 0xC3, 0xA7, 0xC3, 0xA3, 0x6F] -> total 6 bytes
        text = "Ação"
        # Se max_bytes = 2, 'A' (1 byte) + primeiro byte de 'ç' (1 byte) daria 2 bytes,
        # mas como 'ç' é multibyte, o particionador deve recuar para 1 byte ('A')
        segments = split_text_into_utf8_segments(text, max_bytes=2)
        self.assertEqual(b"".join(segments), text.encode("utf-8"))
        for s in segments:
            self.assertLessEqual(len(s), 2)
            self.assertNotIn(UnicodeDecodeError, [s.decode("utf-8")])

    def test_split_text_invalid_max_bytes(self):
        with self.assertRaises(ValueError):
            split_text_into_utf8_segments("Texto", max_bytes=0)
        # Emoji com 4 bytes em max_bytes=2 deve falhar pois não cabe
        with self.assertRaises(ValueError):
            split_text_into_utf8_segments("🏛️", max_bytes=2)

    def test_byte_nll_v1_fails_on_context_overflow(self):
        # Context length do modelo é 8, segmento gera mais de 8 tokens
        tok = LegislativeBpeTokenizer.create_empty()
        model = MockLinearLanguageModel(vocab_size=tok.get_vocab_size(), context_length=8)

        # Simula tokenizer incompatível com o limite byte-level: mais de um
        # token por byte, portanto a verificação de contexto deve falhar.
        tok.encode = lambda text: [3, 4] * len(text)
        tok.verify_round_trip = lambda text: True
        long_text = "abcdefgh"
        docs = [{"corpus_item_id": "test:001", "text": long_text}]

        with self.assertRaises(ValueError) as ctx:
            compute_byte_nll_v1(model=model, tokenizer=tok, documents=docs, k_bytes=7)
        self.assertIn("excedendo context_length", str(ctx.exception))

    def test_byte_nll_v1_fails_on_unequal_round_trip(self):
        # Mock de tokenizer que falha no round-trip
        mock_tok = LegislativeBpeTokenizer.create_empty()
        mock_tok.verify_round_trip = lambda x: False

        model = MockLinearLanguageModel(vocab_size=mock_tok.get_vocab_size(), context_length=64)
        docs = [{"corpus_item_id": "test:002", "text": "Texto legal"}]

        with self.assertRaises(ValueError) as ctx:
            compute_byte_nll_v1(model=model, tokenizer=mock_tok, documents=docs, k_bytes=63)
        self.assertIn("falhou no round-trip exato", str(ctx.exception))

    def test_byte_nll_v1_exact_math_and_strata(self):
        tok = LegislativeBpeTokenizer.create_empty()
        vocab_size = tok.get_vocab_size()
        model = MockLinearLanguageModel(vocab_size=vocab_size, context_length=128)

        doc1 = {
            "corpus_item_id": "camara:pl:100",
            "text": "Artigo primeiro da lei.",
            "house": "camara",
            "normalized_kind": "PL",
            "content_date": "2024-03-01",
        }
        doc2 = {
            "corpus_item_id": "senado:emenda:200",
            "text": "Parecer da comissão.",
            "house": "senado",
            "normalized_kind": "parecer",
            "content_date": "2023-05-10",
        }

        result = compute_byte_nll_v1(
            model=model,
            tokenizer=tok,
            documents=[doc1, doc2],
            k_bytes=127,
        )

        self.assertIsInstance(result, ByteNllResult)
        self.assertEqual(result.protocol_version, "byte_nll_v1")
        self.assertEqual(result.total_documents, 2)
        self.assertGreater(result.total_bytes, 0)
        self.assertGreater(result.total_tokens, 0)
        self.assertGreater(result.nats_per_byte, 0.0)
        self.assertAlmostEqual(result.bits_per_byte, result.nats_per_byte / math.log(2), places=6)

        # Verificação da ponderação estrita
        self.assertAlmostEqual(result.nats_per_byte, result.total_nll / result.total_bytes, places=6)
        self.assertEqual(len(result.item_list_sha256), 64)
        self.assertEqual(len(result.text_hashes_sha256), 64)
        self.assertEqual(result.context_length, 128)

        # Verificação de estratos
        self.assertIn("camara", result.strata_metrics["house"])
        self.assertIn("senado", result.strata_metrics["house"])
        self.assertIn("PL", result.strata_metrics["document_type"])
        self.assertIn("parecer", result.strata_metrics["document_type"])
        self.assertIn("2024", result.strata_metrics["year"])
        self.assertIn("2023", result.strata_metrics["year"])

    def test_byte_nll_manual_sum_and_tokenizer_independent_segment_identity(self):
        text = "Ação 🏛️"
        doc = {"corpus_item_id": "fixture:item:1", "text": text}
        byte_tok = LegislativeBpeTokenizer.create_empty()
        byte_model = MockLinearLanguageModel(byte_tok.get_vocab_size(), context_length=64)
        byte_result = compute_byte_nll_v1(byte_model, byte_tok, [doc], k_bytes=32)

        # Oráculo manual: cada segmento reinicia com BOS e pontua cada token
        # textual uma vez; somente a soma natural é dividida pelos bytes UTF-8.
        manual_nll = 0.0
        manual_tokens = 0
        for segment in split_text_into_utf8_segments(text, 32):
            ids = byte_tok.encode(segment)
            logits = byte_model(torch.tensor([[1] + ids[:-1]], dtype=torch.long))
            targets = torch.tensor([ids], dtype=torch.long)
            manual_nll += torch.nn.functional.cross_entropy(
                logits.view(-1, byte_tok.get_vocab_size()), targets.view(-1), reduction="sum"
            ).item()
            manual_tokens += len(ids)
        self.assertAlmostEqual(byte_result.total_nll, manual_nll, places=6)
        self.assertEqual(byte_result.total_tokens, manual_tokens)
        self.assertEqual(byte_result.total_bytes, len(text.encode("utf-8")))

        # Um BPE treinado em dados diferentes muda a granularidade, mas não o
        # conjunto exato de documentos/bytes ou a segmentação física comum.
        trained_tok = LegislativeBpeTokenizer.load("data/artifacts/tokenizer/tokenizer.json")
        trained_model = MockLinearLanguageModel(trained_tok.get_vocab_size(), context_length=64)
        trained_result = compute_byte_nll_v1(trained_model, trained_tok, [doc], k_bytes=32)
        self.assertEqual(byte_result.item_list_sha256, trained_result.item_list_sha256)
        self.assertEqual(byte_result.text_hashes_sha256, trained_result.text_hashes_sha256)
        self.assertEqual(byte_result.total_bytes, trained_result.total_bytes)
        self.assertEqual(byte_result.total_segments, trained_result.total_segments)

    def test_byte_nll_rejects_k_above_context_protocol_limit(self):
        tok = LegislativeBpeTokenizer.create_empty()
        model = MockLinearLanguageModel(tok.get_vocab_size(), context_length=16)
        with self.assertRaisesRegex(ValueError, "context_length-1"):
            compute_byte_nll_v1(model, tok, [{"corpus_item_id": "x", "text": "ok"}], k_bytes=16)


if __name__ == "__main__":
    unittest.main()
