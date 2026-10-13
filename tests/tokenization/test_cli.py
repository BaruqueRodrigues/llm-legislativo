"""
tests/tokenization/test_cli.py
Testes unitários para a CLI do Tokenizer (legislm.tokenization.cli).
"""

import tempfile
import unittest
from pathlib import Path

from legislm.tokenization.cli import main


class TestTokenizationCLI(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.fixtures_dir = "tests/fixtures/common"
        self.config_path = "configs/tokenizer/pilot.yaml"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_cli_train_and_build_pipeline(self):
        """Valida execução dos subcomandos train e build via CLI."""
        tok_out = self.tmp_path / "tok_out"
        tokens_out = self.tmp_path / "tokens_out"

        # 1. Executa subcomando train
        train_args = [
            "train",
            "--config", self.config_path,
            "--release-dir", self.fixtures_dir,
            "--output-dir", str(tok_out),
            "--vocab-size", "512",
            "--min-frequency", "1",
            "--seed", "42",
        ]
        ret_train = main(train_args)
        self.assertEqual(ret_train, 0, "CLI train deve retornar código 0")

        self.assertTrue((tok_out / "tokenizer.json").exists())
        self.assertTrue((tok_out / "tokenizer_manifest.json").exists())
        self.assertTrue((tok_out / "COMPLETE.json").exists())

        # 2. Executa subcomando build
        build_args = [
            "build",
            "--config", self.config_path,
            "--tokenizer-dir", str(tok_out),
            "--release-dir", self.fixtures_dir,
            "--output-dir", str(tokens_out),
            "--context-length", "32",
            "--splits", "train",
        ]
        ret_build = main(build_args)
        self.assertEqual(ret_build, 0, "CLI build deve retornar código 0")

        self.assertTrue((tokens_out / "token_index.parquet").exists())
        self.assertTrue((tokens_out / "token_dataset_manifest.json").exists())
        self.assertTrue((tokens_out / "COMPLETE.json").exists())
        self.assertTrue((tokens_out / "tokens" / "train" / "shard_00000.npy").exists())

        # 3. Executa subcomando inspect
        inspect_args = [
            "inspect",
            "--tokenizer-dir", str(tok_out),
            "--text", "Art. 1º Teste de inspeção pela linha de comando.",
        ]
        ret_inspect = main(inspect_args)
        self.assertEqual(ret_inspect, 0, "CLI inspect deve retornar código 0")


if __name__ == "__main__":
    unittest.main()
