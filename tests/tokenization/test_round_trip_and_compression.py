"""
tests/tokenization/test_round_trip_and_compression.py
Testes de round-trip exato, medição de compressão e distribuição de comprimentos.
"""

import unittest

from legislm.tokenization.bpe import LegislativeBpeTokenizer, train_bpe_tokenizer
from legislm.tokenization.config import TokenizerConfig


class TestRoundTripAndCompression(unittest.TestCase):
    def setUp(self):
        self.config = TokenizerConfig.from_dict({
            "tokenizer_id": "bpe_byte_test_rt",
            "corpus_version": "corpus_v1",
            "split_version": "split_v1",
            "sequence_policy_version": "doc_window_v1",
            "model": {
                "type": "BPE",
                "byte_fallback": True,
                "vocab_size": 1024,
                "min_frequency": 1,
            },
            "special_tokens": {"PAD": 0, "BOS": 1, "EOS": 2},
            "tokenization": {
                "lowercase": False,
                "strip_accents": False,
                "add_prefix_space": False,
            },
            "dataset": {
                "context_length": 64,
                "dtype": "int32",
                "endianness": "little",
            },
        })

    def test_round_trip_portuguese_legal_constructs(self):
        """Valida round-trip exato (bytes originais == decode(encode(bytes))) em textos normativos."""
        test_cases = [
            "PROJETO DE LEI Nº 1.234, DE 2024\nDispõe sobre a instituição do regime especial.",
            "Art. 1º É vedada a fixação de remuneração em desacordo com o teto constitucional.",
            "§ 1º O disposto neste artigo aplica-se à administração pública direta e indireta.",
            "I - aos servidores públicos dos Poderes Executivo, Legislativo e Judiciário;",
            "II - aos membros do Ministério Público e da Defensoria Pública;",
            "a) mediante prévia dotação orçamentária suficiente para atender às projeções;",
            "b) sem prejuízo das disposições da Lei Complementar nº 101, de 4 de maio de 2000.",
            "JUSTIFICAÇÃO\nA presente proposição visa aperfeiçoar o arcabouço normativo.",
            "Tipografia e pontuação especial: «citação», “aspas duplas”, ‘aspas simples’, travessão — e hífen -.",
            "Símbolos monetários e percentuais: R$ 1.500.000,50 e 15,75% a.a.",
            "Quebras heterogêneas:\r\nLinha CRLF\nLinha LF\tcom tabulação e   espaços múltiplos.",
            "Caracteres de borda: § º ª © ® ™ §1º §2º Art.1º Art.2º",
        ]

        tok, _ = train_bpe_tokenizer(test_cases, self.config)

        for text in test_cases:
            # Teste string -> encode -> decode -> string
            encoded_ids = tok.encode(text)
            decoded_text = tok.decode(encoded_ids)
            self.assertEqual(
                decoded_text, text, f"Falha no round-trip textual para: {text}"
            )

            # Teste bytes -> encode -> decode_to_bytes -> bytes
            orig_bytes = text.encode("utf-8")
            decoded_bytes = tok.decode_to_bytes(encoded_ids)
            self.assertEqual(
                decoded_bytes, orig_bytes, f"Falha no round-trip de bytes para: {text}"
            )

            # Teste verify_round_trip auxiliar
            self.assertTrue(tok.verify_round_trip(text))

    def test_round_trip_with_control_like_text(self):
        """Valida que textos com literais <pad>, <bos>, <eos>, <unk> sofrem round-trip exato."""
        text = "Texto contendo <pad> e <bos> e <eos> e <unk> e [PAD] [BOS] [EOS]."
        tok, _ = train_bpe_tokenizer([text], self.config)

        ids = tok.encode(text)
        decoded = tok.decode(ids)
        self.assertEqual(decoded, text)

        # Nenhum token de controle presente nos IDs
        self.assertNotIn(0, ids)
        self.assertNotIn(1, ids)
        self.assertNotIn(2, ids)

    def test_compression_measurement(self):
        """Valida que subpalavras geram compressão (bytes por token > 1.0)."""
        corpus = [
            "O CONGRESSO NACIONAL decreta e eu sanciono a seguinte Lei: " * 5,
            "Art. 1º Fica instituído o regime extraordinário de tramitação. " * 5,
            "Parágrafo único. As disposições deste artigo aplicam-se imediatamente. " * 5,
        ]

        tok, metrics = train_bpe_tokenizer(corpus, self.config)

        # Com BPE treinado em texto repetido, cada token agrupa múltiplos bytes
        self.assertGreater(metrics.compression_bytes_per_token, 1.0)
        self.assertGreater(metrics.total_training_bytes, metrics.total_training_tokens)
        self.assertGreater(metrics.tokens_per_character, 0.0)

    def test_doc_length_statistics(self):
        """Valida cálculo de min, max, mean, p50, p95 de comprimentos documentais."""
        corpus = [
            "Documento curto.",
            "Documento de tamanho médio com algum conteúdo explicativo.",
            "Documento bastante longo com repetidas seções normativas " * 10,
        ]

        tok, metrics = train_bpe_tokenizer(corpus, self.config)

        self.assertEqual(metrics.total_training_docs, 3)
        self.assertGreater(metrics.max_doc_tokens, metrics.min_doc_tokens)
        self.assertGreaterEqual(metrics.p95_doc_tokens, metrics.p50_doc_tokens)
        self.assertGreaterEqual(metrics.p50_doc_tokens, metrics.min_doc_tokens)
        self.assertLessEqual(metrics.p95_doc_tokens, metrics.max_doc_tokens)


if __name__ == "__main__":
    unittest.main()
