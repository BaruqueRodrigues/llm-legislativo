"""
tests/training/test_benchmark_and_cli.py
Testes do benchmark de treinamento e da CLI python -m legislm.training.cli.
"""

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from unittest.mock import MagicMock, Mock, patch

from legislm.training.benchmark import run_benchmark
from legislm.training.cli import main
from legislm.training.config import (
    ModelArchitectureConfig,
    PersistenceConfig,
    TrainingConfig,
    TrainingHyperparameters,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestBenchmarkAndCLI(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

        self.cfg = TrainingConfig(
            run_id="bench_cli_test",
            corpus_version="corpus_v1",
            split_version="split_v1",
            tokenizer_id="bpe_byte_v1_8k",
            token_dataset_id="tok_dataset_v1",
            sequence_policy_version="doc_window_v1",
            model=ModelArchitectureConfig(
                vocab_size=128, context_length=32, d_model=64, n_layers=2, n_heads=2
            ),
            training=TrainingHyperparameters(
                seed=42,
                precision="fp32",
                micro_batch_size=2,
                grad_accum_steps=2,
                max_steps=10,
                learning_rate=0.001,
                min_learning_rate=0.0001,
                warmup_steps=2,
            ),
            persistence=PersistenceConfig(
                backend="local", runs_dir=str(self.root / "runs"), checkpoints_to_keep=2
            ),
            device="cpu",
        )

        self.cfg_yaml_path = self.root / "test_config.yaml"
        with open(self.cfg_yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(self.cfg.to_dict(), f)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_run_benchmark_execution_and_metrics(self):
        """Verifica a execução funcional do benchmark e valida todos os campos do relatório."""
        report = run_benchmark(
            config=self.cfg,
            warmup_updates=2,
            timed_updates=3,
        )

        self.assertIn("model_architecture", report)
        self.assertIn("parameter_counts", report)
        self.assertIn("timing_and_throughput", report)
        self.assertIn("checkpoint_performance", report)

        timing = report["timing_and_throughput"]
        self.assertTrue(timing["all_losses_finite"])
        self.assertGreater(timing["valid_targets_per_second"], 0.0)
        self.assertGreater(timing["positions_per_second"], 0.0)
        self.assertGreater(timing["latency_per_update_ms"], 0.0)

        ckpt_perf = report["checkpoint_performance"]
        self.assertGreater(ckpt_perf["checkpoint_size_bytes"], 0)
        self.assertGreater(ckpt_perf["save_and_publish_seconds"], 0.0)

    def test_cli_benchmark_subcommand(self):
        """Testa a invocação do subcomando benchmark via CLI."""
        out_json = self.root / "bench_report.json"
        exit_code = main(
            [
                "benchmark",
                "--config",
                str(self.cfg_yaml_path),
                "--warmup-steps",
                "1",
                "--timed-steps",
                "2",
                "--output",
                str(out_json),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_json.exists())

        with open(out_json, "r", encoding="utf-8") as f:
            saved_report = json.load(f)
        self.assertIn("timing_and_throughput", saved_report)

    def test_cli_train_subcommand(self):
        """Testa a invocação do subcomando train via CLI com override de max-steps."""
        exit_code = main(
            [
                "train",
                "--config",
                str(self.cfg_yaml_path),
                "--max-steps",
                "2",
                "--synthetic-smoke",
            ]
        )
        self.assertEqual(exit_code, 0)

        # Confirma que checkpoint final foi gerado
        latest_file = self.root / "runs" / "bench_cli_test" / "latest.json"
        self.assertTrue(latest_file.exists())

    def test_cli_train_requires_explicit_dataset_source(self):
        with self.assertRaises(SystemExit):
            main(["train", "--config", str(self.cfg_yaml_path)])

    def test_cli_train_loads_train_and_validation_shards(self):
        data_root = Path(__import__("os").environ["DATA_ROOT"])
        dataset_dir = data_root / "tokens" / "dataset_1"
        dataset_dir.mkdir(parents=True)
        (dataset_dir / "token_dataset_manifest.json").write_text("{}", encoding="utf-8")
        train_ds = MagicMock()
        train_ds.context_length = self.cfg.model.context_length
        train_ds.__len__.return_value = 3
        validation_ds = MagicMock()
        validation_ds.context_length = self.cfg.model.context_length
        validation_ds.__len__.return_value = 2
        trainer = Mock()
        trainer.run.return_value = {"status": "ok"}
        with patch("legislm.training.cli.ShardedTokenDataset.from_dataset_dir", side_effect=[train_ds, validation_ds]) as loader, patch(
            "legislm.training.cli.Trainer", return_value=trainer
        ) as trainer_cls:
            result = main(["train", "--config", str(self.cfg_yaml_path), "--token-dataset-dir", str(dataset_dir)])
        self.assertEqual(result, 0)
        self.assertEqual([call.kwargs["split"] for call in loader.call_args_list], ["train", "validation"])
        self.assertIs(trainer_cls.call_args.kwargs["train_dataset"], train_ds)
        self.assertIs(trainer_cls.call_args.kwargs["eval_dataset"], validation_ds)

    def test_cli_rejects_dataset_outside_data_root(self):
        with self.assertRaisesRegex(ValueError, "dentro de DATA_ROOT"):
            main(["train", "--config", str(self.cfg_yaml_path), "--token-dataset-dir", str(self.root / "outside")])


if __name__ == "__main__":
    unittest.main()
