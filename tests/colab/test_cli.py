"""
tests/colab/test_cli.py
Testes unitários da interface de linha de comando `python -m legislm.colab.cli`.
"""

import json
import tempfile
import unittest
from pathlib import Path

from legislm.colab.cli import main
from legislm.training.checkpoint import save_checkpoint
from legislm.training.config import (
    ModelArchitectureConfig,
    PersistenceConfig,
    TrainingConfig,
    TrainingHyperparameters,
)
from legislm.training.data import DeterministicSampler, StratifiedTracker
from legislm.training.optimizer import CosineAnnealingWarmupScheduler, configure_optimizer
from legislm.training.precision import PrecisionManager
from legislm.model.gpt import GPTModel


class TestColabCLI(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.drive_root = self.root / "drive_root"
        self.drive_root.mkdir()
        self.local_root = self.root / "local_root"
        self.local_root.mkdir()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_cli_preflight_with_cpu_fallback(self):
        """Testa o comando CLI preflight com allow-cpu e gravação em arquivo JSON."""
        out_file = self.root / "preflight_cli_out.json"
        cfg_file = self.root / "colab_cfg.yaml"
        cfg_content = f"""
session_name: "cli_preflight_test"
drive_root: "{self.drive_root}"
local_scratch_root: "{self.local_root}"
preflight:
  check_gpu: false
  allow_cpu_fallback: true
"""
        cfg_file.write_text(cfg_content, encoding="utf-8")

        exit_code = main(
            [
                "preflight",
                "--config",
                str(cfg_file),
                "--allow-cpu",
                "--ccu",
                "185.5",
                "--output",
                str(out_file),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_file.exists())

        with open(out_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["session_id"], "cli_preflight_test")
        self.assertEqual(data["user_provided_ccu"], 185.5)
        self.assertIn(data["status"], ("PASSED", "CPU_FALLBACK"))

    def test_cli_stage_command(self):
        """Testa o subcomando stage via CLI."""
        src_dir = self.root / "shards_src"
        src_dir.mkdir()
        f1 = src_dir / "shard_001.bin"
        f1.write_bytes(b"TEST_CLI_STAGE_DATA_" * 100)

        target_dir = self.root / "shards_dst"

        exit_code = main(
            [
                "stage",
                "--source",
                str(src_dir),
                "--target",
                str(target_dir),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue((target_dir / "shard_001.bin").exists())

    def test_cli_benchmark_io_command(self):
        """Testa o subcomando benchmark com type io via CLI."""
        src_file = self.root / "bench_src.bin"
        src_file.write_bytes(b"BENCH_CLI_DATA_" * 500)
        bench_dst = self.root / "bench_target"
        out_json = self.root / "bench_cli_report.json"

        exit_code = main(
            [
                "benchmark",
                "--type",
                "io",
                "--source",
                str(src_file),
                "--target",
                str(bench_dst),
                "--output",
                str(out_json),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(out_json.exists())
        with open(out_json, "r", encoding="utf-8") as f:
            rep = json.load(f)
        self.assertIn("speedup_factor", rep)
        self.assertIn("direct_io", rep)
        self.assertIn("local_staged_io", rep)

    def test_cli_sync_command(self):
        """Testa sincronização e publicação de checkpoint via CLI."""
        runs_root = self.drive_root / "runs" / "cli_run_01"
        staging_dir = self.local_root / "step_000001"

        cfg = TrainingConfig(
            run_id="cli_run_01",
            corpus_version="corpus_v1",
            split_version="split_v1",
            tokenizer_id="bpe_byte_v1_8k",
            token_dataset_id="tok_dataset_v1",
            sequence_policy_version="doc_window_v1",
            model=ModelArchitectureConfig(
                vocab_size=64, context_length=16, d_model=32, n_layers=2, n_heads=2
            ),
            training=TrainingHyperparameters(seed=42, precision="fp32"),
            persistence=PersistenceConfig(backend="drive", runs_dir=str(self.drive_root / "runs")),
        )
        model = GPTModel(cfg.model.to_gpt_config())
        opt = configure_optimizer(model, cfg.training)
        sched = CosineAnnealingWarmupScheduler(opt, learning_rate=0.001, min_learning_rate=0.0001, warmup_steps=1, max_steps=10)
        pm = PrecisionManager(precision="fp32")
        sampler = DeterministicSampler(num_items=5, seed=42)
        tracker = StratifiedTracker(total_eligible_items=5)

        save_checkpoint(
            save_dir=staging_dir,
            config=cfg,
            model=model,
            optimizer=opt,
            scheduler=sched,
            precision_mgr=pm,
            sampler=sampler,
            tracker=tracker,
            global_step=1,
            tokens_seen=50,
            tokens_for_successful_updates=50,
            overflow_updates_count=0,
            total_positions_evaluated=100,
            segment_id="cli_seg",
            event_sequence=1,
            checkpoint_id="step_000001",
        )

        # 1. Sync to Drive
        exit_code_publish = main(
            [
                "sync",
                "--run-id",
                "cli_run_01",
                "--persistent-root",
                str(runs_root),
                "--local-dir",
                str(staging_dir),
                "--direction",
                "to_drive",
            ]
        )
        self.assertEqual(exit_code_publish, 0)
        self.assertTrue((runs_root / "checkpoints" / "step_000001" / "COMPLETE.json").exists())

        # 2. Sync from Drive (resolução de latest)
        exit_code_resolve = main(
            [
                "sync",
                "--run-id",
                "cli_run_01",
                "--persistent-root",
                str(runs_root),
                "--local-dir",
                str(self.local_root),
                "--direction",
                "from_drive",
            ]
        )
        self.assertEqual(exit_code_resolve, 0)


if __name__ == "__main__":
    unittest.main()
