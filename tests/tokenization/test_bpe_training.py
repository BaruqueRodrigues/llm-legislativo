"""
tests/tokenization/test_bpe_training.py
Testes do treinamento ByteLevel BPE, tokens especiais e manifesto normativo.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from legislm.tokenization.bpe import (
    LegislativeBpeTokenizer,
    save_tokenizer_bundle,
    train_bpe_tokenizer,
)
from legislm.tokenization.config import TokenizerConfig


class TestBpeTraining(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.config = TokenizerConfig.from_dict({
            "tokenizer_id": "bpe_byte_test",
            "corpus_version": "corpus_v1",
            "split_version": "split_v1",
            "sequence_policy_version": "doc_window_v1",
            "model": {
                "type": "BPE",
                "byte_fallback": True,
                "vocab_size": 512,
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

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_special_tokens_reserved_ids(self):
        """Valida que PAD=0, BOS=1, EOS=2 no vocabulário e na API."""
        tok = LegislativeBpeTokenizer.create_empty()
        self.assertEqual(tok.token_to_id("<pad>"), 0)
        self.assertEqual(tok.token_to_id("<bos>"), 1)
        self.assertEqual(tok.token_to_id("<eos>"), 2)

        self.assertEqual(tok.id_to_token(0), "<pad>")
        self.assertEqual(tok.id_to_token(1), "<bos>")
        self.assertEqual(tok.id_to_token(2), "<eos>")

    def test_literal_special_strings_in_text_are_not_control_ids(self):
        """Invariante D11: Strings literais '<pad>', '<bos>', '<eos>' viram texto comum, nunca IDs 0, 1 ou 2."""
        corpus = [
            "PROJETO DE LEI\nArt. 1º Fica instituído o regime especial.",
            "Texto contendo <pad> literal e <bos> literal e <eos> literal no corpo documental.",
            "Outro documento com [PAD], [BOS], [EOS] como caracteres comuns.",
        ]

        tok, _ = train_bpe_tokenizer(corpus, self.config)

        test_text = "Art. 1º O parâmetro <pad> não aciona token de preenchimento, nem <bos> ou <eos>."
        enc_ids = tok.encode(test_text)

        # Prova formal: nenhum dos IDs retornados é 0, 1 ou 2
        self.assertNotIn(0, enc_ids, "ID 0 (PAD) não pode ser emitido a partir de texto!")
        self.assertNotIn(1, enc_ids, "ID 1 (BOS) não pode ser emitido a partir de texto!")
        self.assertNotIn(2, enc_ids, "ID 2 (EOS) não pode ser emitido a partir de texto!")

        # Todos os IDs de texto devem ser >= 3
        for token_id in enc_ids:
            self.assertGreaterEqual(token_id, 3)

        # Decodificação exata restaura o texto com as literais
        decoded = tok.decode(enc_ids)
        self.assertEqual(decoded, test_text)

    def test_sequence_construction_delimiters(self):
        """Valida que encode_sequence produz estritamente [BOS=1] + encode(text) + [EOS=2]."""
        tok = LegislativeBpeTokenizer.create_empty()
        text = "PROJETO DE LEI"
        seq = tok.encode_sequence(text)

        self.assertEqual(seq[0], 1, "Primeiro token deve ser BOS=1")
        self.assertEqual(seq[-1], 2, "Último token deve ser EOS=2")
        self.assertEqual(seq[1:-1], tok.encode(text))

    def test_effective_vocab_size_and_merges(self):
        """Valida crescimento do vocabulário através de merges de subpalavras."""
        corpus = [
            "PROJETO DE LEI COMPLEMENTAR " * 10,
            "Art. 1º Fica revogado o programa exemplo em sua integralidade. " * 5,
        ]
        tok, metrics = train_bpe_tokenizer(corpus, self.config)

        # Alfabeto base: 256 bytes + 3 especiais = 259
        self.assertGreater(metrics.vocab_size_effective, 259)
        self.assertLessEqual(metrics.vocab_size_effective, self.config.model.vocab_size)
        self.assertEqual(tok.get_vocab_size(), metrics.vocab_size_effective)

    def test_tokenizer_bundle_manifest_schema_compliance(self):
        """Valida que tokenizer_manifest.json obedece estritamente ao esquema JSON normativo."""
        corpus = ["Art. 1º Disposição geral do teste."]
        tok, metrics = train_bpe_tokenizer(corpus, self.config)

        tok_f, man_f, comp_f = save_tokenizer_bundle(
            tokenizer=tok,
            metrics=metrics,
            config=self.config,
            output_dir=self.tmp_path,
            training_item_ids_hash="a" * 64,
            training_text_hashes_hash="b" * 64,
            training_bytes=100,
            seed=42,
        )

        self.assertTrue(tok_f.exists())
        self.assertTrue(man_f.exists())
        self.assertTrue(comp_f.exists())

        # Valida contra schemas/manifests/tokenizer_manifest.schema.json
        schema_file = Path("schemas/manifests/tokenizer_manifest.schema.json")
        self.assertTrue(schema_file.exists())
        with open(schema_file, "r", encoding="utf-8") as f:
            schema_data = json.load(f)

        with open(man_f, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        required_keys = schema_data.get("required", [])
        for k in required_keys:
            self.assertIn(k, manifest_data, f"Campo obrigatório '{k}' ausente no manifesto")

        self.assertEqual(manifest_data["tokenizer_id"], self.config.tokenizer_id)
        self.assertEqual(manifest_data["special_tokens"], {"PAD": 0, "BOS": 1, "EOS": 2})
        self.assertEqual(manifest_data["vocab_size"], metrics.vocab_size_effective)
        self.assertEqual(manifest_data["alphabet_policy"], "byte_level_full_256")
        self.assertEqual(manifest_data["normalization_policy"], "none_preserving")

        # Valida COMPLETE.json
        with open(comp_f, "r", encoding="utf-8") as f:
            complete_data = json.load(f)
        self.assertEqual(complete_data["manifest_file"], "tokenizer_manifest.json")
        self.assertEqual(complete_data["manifest_sha256"], hashlib.sha256(man_f.read_bytes()).hexdigest())

    def test_save_and_reload_tokenizer(self):
        """Valida que o tokenizer salvo e recarregado mantém comportamento idêntico."""
        corpus = ["Texto com acentuação e quebras:\nArt. 1º § 2º inciso IV."]
        tok, _ = train_bpe_tokenizer(corpus, self.config)

        tok_file = self.tmp_path / "tokenizer.json"
        tok.save(tok_file)

        reloaded = LegislativeBpeTokenizer.load(tok_file)
        self.assertEqual(tok.get_vocab_size(), reloaded.get_vocab_size())

        test_sample = "Art. 1º § 2º inciso IV."
        self.assertEqual(tok.encode(test_sample), reloaded.encode(test_sample))
        self.assertEqual(tok.decode(tok.encode(test_sample)), reloaded.decode(reloaded.encode(test_sample)))


if __name__ == "__main__":
    unittest.main()
