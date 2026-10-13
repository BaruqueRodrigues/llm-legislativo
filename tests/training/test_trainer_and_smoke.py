"""
tests/training/test_trainer_and_smoke.py
Testes do ciclo completo do Trainer, condições de parada de orçamento e logs JSONL.
"""

import json
import tempfile
import unittest
from pathlib import Path

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel
from legislm.training.config import (
    ModelArchitectureConfig,
    PersistenceConfig,
    TrainingConfig,
    TrainingHyperparameters,
)
from legislm.training.data import create_synthetic_dataset
from legislm.training.engine import Trainer
from legislm.training.persistence import LocalPersistenceBackend


class TestTrainerAndSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.runs_dir = self.root / "runs"
        self.staging_dir = self.root / "staging"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _get_base_config(self, max_steps=10, max_tokens=None, budget_counter="successful_update_tokens"):
        return TrainingConfig(
            run_id="trainer_smoke_run",
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
                max_steps=max_steps,
                max_tokens=max_tokens,
                budget_counter=budget_counter,
                learning_rate=0.001,
                min_learning_rate=0.0001,
                warmup_steps=2,
                weight_decay=0.01,
                evaluation_interval=4,
                checkpoint_interval_steps=5,
            ),
            persistence=PersistenceConfig(
                backend="local", runs_dir=str(self.runs_dir), checkpoints_to_keep=2
            ),
            device="cpu",
        )

    def test_trainer_run_stop_by_max_steps(self):
        """Verifica execução do Trainer com parada em max_steps e validação de logs JSONL."""
        cfg = self._get_base_config(max_steps=6)
        train_ds = create_synthetic_dataset(num_docs=20, vocab_size=128, context_length=32, seed=1)
        eval_ds = create_synthetic_dataset(num_docs=10, vocab_size=128, context_length=32, seed=2)

        trainer = Trainer(
            config=cfg,
            train_dataset=train_ds,
            eval_dataset=eval_ds,
            persistence_backend=LocalPersistenceBackend(checkpoints_to_keep=2),
            segment_id="smoke_seg",
        )
        trainer.persistent_run_root = self.runs_dir / "trainer_smoke_run"
        trainer.local_staging_root = self.staging_dir / "smoke"

        summary = trainer.run()
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(trainer.global_step, 6)
        self.assertGreater(trainer.tokens_seen, 0)
        self.assertGreater(trainer.tokens_for_successful_updates, 0)
        self.assertIsNotNone(trainer.best_val_loss)

        # Verifica arquivo de métricas append-only JSONL
        metrics_file = trainer.metrics_log_path
        self.assertTrue(metrics_file.exists(), f"Log de métricas {metrics_file} deve existir")

        with open(metrics_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        self.assertGreaterEqual(len(lines), 6)
        # Verifica estrutura dos eventos
        for ev in lines:
            self.assertIn("event_id", ev)
            self.assertIn("run_id", ev)
            self.assertIn("segment_id", ev)
            self.assertIn("global_step", ev)
            self.assertIn("timestamp_utc", ev)
            self.assertEqual(ev["run_id"], "trainer_smoke_run")
            self.assertEqual(ev["segment_id"], "smoke_seg")

        # Verifica se houve ao menos 1 evento de evaluation
        eval_events = [ev for ev in lines if ev.get("event_type") == "evaluation"]
        self.assertGreaterEqual(len(eval_events), 1)

    def test_trainer_run_stop_by_max_tokens_budget(self):
        """Testa parada exata pelo orçamento de tokens (successful_update_tokens)."""
        # Define limite de tokens bem curto
        target_tokens = 150
        cfg = self._get_base_config(max_steps=100, max_tokens=target_tokens)
        train_ds = create_synthetic_dataset(num_docs=20, vocab_size=128, context_length=32, seed=1)

        trainer = Trainer(
            config=cfg,
            train_dataset=train_ds,
            persistence_backend=LocalPersistenceBackend(checkpoints_to_keep=2),
            segment_id="budget_seg",
        )
        trainer.persistent_run_root = self.runs_dir / "trainer_budget_run"
        trainer.local_staging_root = self.staging_dir / "budget"

        summary = trainer.run()
        self.assertEqual(summary["status"], "completed")
        self.assertIn("max_tokens", summary["stop_reason"])
        self.assertGreaterEqual(trainer.tokens_for_successful_updates, target_tokens)
        self.assertLess(trainer.global_step, 100, "Deve ter parado por orçamento de tokens antes de max_steps")


if __name__ == "__main__":
    unittest.main()
