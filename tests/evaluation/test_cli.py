"""
tests/evaluation/test_cli.py
Testes da interface de linha de comando (CLI) de avaliação e geração.
"""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

import torch

from legislm.evaluation.cli import build_parser, main, resolve_checkpoint_dir
from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel


class TestEvaluationCLI(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.tokenizer_path = Path("data/artifacts/tokenizer/tokenizer.json")
        self.prompts_path = Path("configs/evaluation/prompts.json")

        # Cria checkpoint compatível com o vocabulário oficial (1080 tokens)
        self.checkpoint_dir = self.tmp_path / "checkpoints" / "test_run" / "step_000010_final"
        self._create_compatible_checkpoint(self.checkpoint_dir, vocab_size=1080)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _create_compatible_checkpoint(self, target_dir: Path, vocab_size: int = 1080) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        cfg = GPTConfig(
            vocab_size=vocab_size,
            context_length=64,
            d_model=64,
            n_layers=2,
            n_heads=2,
        )
        model = GPTModel(cfg)

        pt_path = target_dir / "checkpoint.pt"
        ckpt_data = {
            "schema_version": 1,
            "run_id": "test_cli_run",
            "checkpoint_id": "step_000010_final",
            "global_step": 10,
            "tokens_seen": 500,
            "tokens_for_successful_updates": 500,
            "budget_counter": "successful_update_tokens",
            "segment_id": "seg_test",
            "model_state": model.state_dict(),
            "config_dict": {
                "model": {
                    "vocab_size": vocab_size,
                    "context_length": 64,
                    "d_model": 64,
                    "n_layers": 2,
                    "n_heads": 2,
                }
            },
            "config_file_sha256": "0" * 64,
            "scientific_config_hash": "0" * 64,
            "execution_config_hash": "0" * 64,
        }
        torch.save(ckpt_data, pt_path)

        pt_size = pt_path.stat().st_size
        pt_sha256 = hashlib.sha256(pt_path.read_bytes()).hexdigest()

        manifest = {
            "run_id": "test_cli_run",
            "checkpoint_id": "step_000010_final",
            "schema_version": 1,
            "global_step": 10,
            "tokens_seen": 500,
            "tokens_for_successful_updates": 500,
            "budget_counter": "successful_update_tokens",
            "segment_id": "seg_test",
            "config_file_sha256": "0" * 64,
            "scientific_config_hash": "0" * 64,
            "execution_config_hash": "0" * 64,
            "files": [
                {
                    "path": "checkpoint.pt",
                    "size_bytes": pt_size,
                    "sha256": pt_sha256,
                }
            ],
        }
        with open(target_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def test_cli_parser_builds_correctly(self):
        parser = build_parser()
        self.assertIsNotNone(parser)
        # Testa help
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_cli_generate_command(self):
        """Testa subcomando generate com salvamento em arquivo JSON."""
        if not self.tokenizer_path.exists():
            self.skipTest("Artefato do tokenizer não disponível no ambiente")

        out_json = self.tmp_path / "cli_gen_out.json"

        argv = [
            "generate",
            "--checkpoint-dir", str(self.checkpoint_dir),
            "--tokenizer-path", str(self.tokenizer_path),
            "--prompts", str(self.prompts_path),
            "--max-new-tokens", "10",
            "--greedy",
            "--seed", "42",
            "--output-file", str(out_json),
        ]

        exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_json.exists())

        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)
        self.assertIn("prompt_id", data[0])
        self.assertIn("generated_text", data[0])

    def test_cli_evaluate_command_on_curated_release(self):
        """Testa subcomando evaluate emitindo relatório JSON."""
        if not self.tokenizer_path.exists():
            self.skipTest("Artefato do tokenizer não disponível no ambiente")

        out_json = self.tmp_path / "cli_eval_out.json"

        argv = [
            "evaluate",
            "--checkpoint-dir", str(self.checkpoint_dir),
            "--tokenizer-path", str(self.tokenizer_path),
            "--split", "train",
            "--release-dir", "data/staging/curation/release_curated_gh_2.0.0",
            "--output-json", str(out_json),
        ]

        exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_json.exists())

        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["run_id"], "test_cli_run")
        self.assertEqual(data["split"], "train")
        self.assertIn("evaluation_metrics", data)
        self.assertIn("loss", data["evaluation_metrics"])
        self.assertIn("perplexity", data["evaluation_metrics"])
        self.assertIn("byte_nll_v1", data)

    def test_cli_evaluate_missing_checkpoint_raises(self):
        argv = [
            "evaluate",
            "--checkpoint-dir", "caminho_inexistente_12345",
        ]
        with self.assertRaises(FileNotFoundError):
            main(argv)

    def test_cli_refuses_empty_split_instead_of_reporting_zero_loss(self):
        if not self.tokenizer_path.exists():
            self.skipTest("Artefato do tokenizer não disponível no ambiente")
        argv = [
            "evaluate",
            "--checkpoint-dir", str(self.checkpoint_dir),
            "--tokenizer-path", str(self.tokenizer_path),
            "--split", "validation",
            "--release-dir", "data/staging/curation/release_curated_gh_2.0.0",
            "--output-json", str(self.tmp_path / "empty.json"),
        ]
        with self.assertRaisesRegex(ValueError, "não tem documentos/alvos elegíveis"):
            main(argv)

    def test_cli_does_not_fallback_to_fixture_when_release_missing(self):
        if not self.tokenizer_path.exists():
            self.skipTest("Artefato do tokenizer não disponível no ambiente")
        argv = [
            "evaluate",
            "--checkpoint-dir", str(self.checkpoint_dir),
            "--tokenizer-path", str(self.tokenizer_path),
            "--split", "train",
            "--release-dir", str(self.tmp_path / "missing-release"),
        ]
        with self.assertRaisesRegex(FileNotFoundError, "Release especificada não encontrada"):
            main(argv)

    def test_run_id_resolves_checkpoint_through_persistent_latest_pointer(self):
        run_root = Path(os.environ["DATA_ROOT"]) / "runs" / "run_pointer"
        checkpoint = run_root / "checkpoints" / "step_000010_final"
        checkpoint.mkdir(parents=True)
        (checkpoint / "manifest.json").write_text("{}", encoding="utf-8")
        (run_root / "latest.json").write_text(
            json.dumps({"run_id": "run_pointer", "checkpoint_id": "step_000010_final"}),
            encoding="utf-8",
        )
        original_cwd = Path.cwd()
        try:
            os.chdir(self.tmp_path)
            resolved = resolve_checkpoint_dir(None, "run_pointer")
        finally:
            os.chdir(original_cwd)
        self.assertEqual(resolved, Path(os.environ["DATA_ROOT"]) / "runs/run_pointer/checkpoints/step_000010_final")


if __name__ == "__main__":
    unittest.main()
