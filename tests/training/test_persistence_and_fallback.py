"""
tests/training/test_persistence_and_fallback.py
Testes do backend de persistência, validação de integridade, poda e fallback diante de corrupção.
"""

import json
import tempfile
import unittest
from pathlib import Path

import torch

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel
from legislm.training.checkpoint import (
    save_checkpoint,
    validate_checkpoint_manifest,
)
from legislm.training.config import (
    ModelArchitectureConfig,
    PersistenceConfig,
    TrainingConfig,
    TrainingHyperparameters,
)
from legislm.training.data import DeterministicSampler, StratifiedTracker
from legislm.training.optimizer import CosineAnnealingWarmupScheduler, configure_optimizer
from legislm.training.persistence import LocalPersistenceBackend, compute_file_sha256
from legislm.training.precision import PrecisionManager

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestPersistenceAndFallback(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.runs_root = self.root / "runs" / "test_run"
        self.staging_root = self.root / "staging"

        self.cfg = TrainingConfig(
            run_id="test_run",
            corpus_version="corpus_v1",
            split_version="split_v1",
            tokenizer_id="bpe_byte_v1_8k",
            token_dataset_id="tok_dataset_v1",
            sequence_policy_version="doc_window_v1",
            model=ModelArchitectureConfig(
                vocab_size=64, context_length=16, d_model=32, n_layers=2, n_heads=2
            ),
            training=TrainingHyperparameters(seed=42, precision="fp32"),
            persistence=PersistenceConfig(backend="local", runs_dir=str(self.root / "runs")),
        )
        self.model = GPTModel(self.cfg.model.to_gpt_config())
        self.opt = configure_optimizer(self.model, self.cfg.training)
        self.sched = CosineAnnealingWarmupScheduler(
            self.opt,
            learning_rate=0.001,
            min_learning_rate=0.0001,
            warmup_steps=5,
            max_steps=50,
        )
        self.pm = PrecisionManager(precision="fp32")
        self.sampler = DeterministicSampler(num_items=10, seed=42)
        self.tracker = StratifiedTracker(total_eligible_items=10)
        self.backend = LocalPersistenceBackend(checkpoints_to_keep=2)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _create_and_publish(self, step: int, ckpt_id: str):
        local_dir = self.staging_root / ckpt_id
        save_checkpoint(
            save_dir=local_dir,
            config=self.cfg,
            model=self.model,
            optimizer=self.opt,
            scheduler=self.sched,
            precision_mgr=self.pm,
            sampler=self.sampler,
            tracker=self.tracker,
            global_step=step,
            tokens_seen=step * 100,
            tokens_for_successful_updates=step * 100,
            overflow_updates_count=0,
            total_positions_evaluated=step * 200,
            segment_id="test_seg",
            event_sequence=step,
            checkpoint_id=ckpt_id,
        )
        return self.backend.publish_checkpoint(local_dir, self.runs_root)

    def test_publish_and_manifest_schema_validation(self):
        """Valida que o checkpoint publicado satisfaz rigorosamente schemas/manifests/checkpoint_manifest.schema.json."""
        manifest = self._create_and_publish(step=10, ckpt_id="step_000010")

        # Validação semântica e contratual
        validate_checkpoint_manifest(manifest)

        # Confirma existência dos arquivos físicos
        ckpt_dir = self.runs_root / "checkpoints" / "step_000010"
        self.assertTrue((ckpt_dir / "checkpoint.pt").exists())
        self.assertTrue((ckpt_dir / "manifest.json").exists())
        self.assertTrue((ckpt_dir / "COMPLETE.json").exists())
        self.assertTrue((self.runs_root / "latest.json").exists())

        # Verifica conteúdo de COMPLETE.json
        with open(ckpt_dir / "COMPLETE.json", "r", encoding="utf-8") as f:
            comp = json.load(f)
        self.assertEqual(comp["run_id"], "test_run")
        self.assertEqual(comp["checkpoint_id"], "step_000010")
        self.assertEqual(comp["manifest_sha256"], compute_file_sha256(ckpt_dir / "manifest.json"))

    def test_pruning_policy_preserves_at_least_two(self):
        """Testa que a política de poda mantém no mínimo 2 checkpoints válidos e não remove o latest."""
        self._create_and_publish(step=10, ckpt_id="step_000010")
        self._create_and_publish(step=20, ckpt_id="step_000020")
        self._create_and_publish(step=30, ckpt_id="step_000030")
        self._create_and_publish(step=40, ckpt_id="step_000040")

        valid_ckpts = self.backend.list_complete_checkpoints(self.runs_root)
        # Deve manter os 2 mais recentes: step_000030 e step_000040
        self.assertEqual(len(valid_ckpts), 2)
        self.assertIn("step_000030", valid_ckpts)
        self.assertIn("step_000040", valid_ckpts)
        self.assertNotIn("step_000010", valid_ckpts)

        # latest deve apontar para o step 40
        resolved = self.backend.resolve_checkpoint(self.runs_root, "latest")
        self.assertEqual(resolved.name, "step_000040")

    def test_fallback_on_corrupted_checkpoint(self):
        """Testa que corrupção em latest (hash alterado ou COMPLETE ausente) ativa fallback para o checkpoint íntegro anterior."""
        self._create_and_publish(step=10, ckpt_id="step_000010")
        self._create_and_publish(step=20, ckpt_id="step_000020")

        # Corrompe o checkpoint mais recente step_000020 (alterando bytes de checkpoint.pt)
        ckpt20_pt = self.runs_root / "checkpoints" / "step_000020" / "checkpoint.pt"
        with open(ckpt20_pt, "ab") as f:
            f.write(b"corrupted_bytes")

        # Ao resolver "latest", a corrupção é detectada e o sistema deve fazer fallback para step_000010
        resolved = self.backend.resolve_checkpoint(self.runs_root, "latest")
        self.assertEqual(
            resolved.name,
            "step_000010",
            "O resolver deve recuperar o checkpoint íntegro anterior após falha no latest",
        )

    def test_missing_complete_marker_rejection(self):
        """Verifica que diretório de checkpoint sem COMPLETE.json é rejeitado como incompleto."""
        self._create_and_publish(step=10, ckpt_id="step_000010")
        comp_file = self.runs_root / "checkpoints" / "step_000010" / "COMPLETE.json"
        comp_file.unlink()

        # O checkpoint não pode ser listado como completo
        complete_list = self.backend.list_complete_checkpoints(self.runs_root)
        self.assertNotIn("step_000010", complete_list)


if __name__ == "__main__":
    unittest.main()
