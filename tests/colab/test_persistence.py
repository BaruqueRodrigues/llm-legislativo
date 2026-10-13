"""
tests/colab/test_persistence.py
Testes unitários de persistência Google Drive, escrita atômica, rollback automático,
política de retenção segura (últimos 2 + best) e reinício em sessão limpa.
"""

import json
import tempfile
import unittest
from pathlib import Path

import torch

from legislm.colab.persistence import (
    GoogleDrivePersistenceBackend,
    list_complete_checkpoints,
    publish_checkpoint,
    resolve_checkpoint,
)
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
from legislm.training.data import (
    DeterministicSampler,
    StratifiedTracker,
    create_synthetic_dataset,
)
from legislm.training.engine import Trainer
from legislm.training.optimizer import CosineAnnealingWarmupScheduler, configure_optimizer
from legislm.training.persistence import compute_file_sha256
from legislm.training.precision import PrecisionManager


class TestGoogleDrivePersistence(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.runs_root = self.root / "drive_runs" / "colab_run_01"
        self.staging_root = self.root / "staging"

        self.cfg = TrainingConfig(
            run_id="colab_run_01",
            corpus_version="corpus_v1",
            split_version="split_v1",
            tokenizer_id="bpe_byte_v1_8k",
            token_dataset_id="tok_dataset_v1",
            sequence_policy_version="doc_window_v1",
            model=ModelArchitectureConfig(
                vocab_size=64, context_length=16, d_model=32, n_layers=2, n_heads=2
            ),
            training=TrainingHyperparameters(seed=42, precision="fp32"),
            persistence=PersistenceConfig(backend="drive", runs_dir=str(self.root / "drive_runs")),
        )
        self.model = GPTModel(self.cfg.model.to_gpt_config())
        self.opt = configure_optimizer(self.model, self.cfg.training)
        self.sched = CosineAnnealingWarmupScheduler(
            self.opt,
            learning_rate=0.001,
            min_learning_rate=0.0001,
            warmup_steps=2,
            max_steps=20,
        )
        self.pm = PrecisionManager(precision="fp32")
        self.sampler = DeterministicSampler(num_items=10, seed=42)
        self.tracker = StratifiedTracker(total_eligible_items=10)
        self.backend = GoogleDrivePersistenceBackend(checkpoints_to_keep=2, keep_best=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _create_and_publish(self, step: int, ckpt_id: str, best_val_loss: float = None):
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
            segment_id="colab_seg",
            event_sequence=step,
            checkpoint_id=ckpt_id,
            best_val_loss=best_val_loss,
        )
        return self.backend.publish_checkpoint(local_dir, self.runs_root)

    def test_publish_creates_complete_and_latest(self):
        """Testa que publish_checkpoint cria estrutura completa com COMPLETE.json e latest.json."""
        manifest = self._create_and_publish(step=10, ckpt_id="step_000010")

        validate_checkpoint_manifest(manifest)

        ckpt_dir = self.runs_root / "checkpoints" / "step_000010"
        self.assertTrue((ckpt_dir / "checkpoint.pt").exists())
        self.assertTrue((ckpt_dir / "manifest.json").exists())
        self.assertTrue((ckpt_dir / "COMPLETE.json").exists())
        self.assertTrue((self.runs_root / "latest.json").exists())

        # Verifica conteúdo e hash do COMPLETE.json
        with open(ckpt_dir / "COMPLETE.json", "r", encoding="utf-8") as f:
            comp = json.load(f)
        self.assertEqual(comp["run_id"], "colab_run_01")
        self.assertEqual(comp["checkpoint_id"], "step_000010")
        self.assertEqual(comp["manifest_sha256"], compute_file_sha256(ckpt_dir / "manifest.json"))

        # latest.json aponta para step_000010
        with open(self.runs_root / "latest.json", "r", encoding="utf-8") as f:
            latest = json.load(f)
        self.assertEqual(latest["checkpoint_id"], "step_000010")

    def test_resolve_latest_and_by_id(self):
        """Testa resolução pelo seletor 'latest' e por ID explícito."""
        self._create_and_publish(step=10, ckpt_id="step_000010")
        self._create_and_publish(step=20, ckpt_id="step_000020")

        res_latest = self.backend.resolve_checkpoint(self.runs_root, "latest")
        self.assertEqual(res_latest.name, "step_000020")

        res_10 = self.backend.resolve_checkpoint(self.runs_root, "step_000010")
        self.assertEqual(res_10.name, "step_000010")

    def test_automatic_rollback_on_corrupted_checkpoint_bytes(self):
        """Testa rollback automático para o checkpoint íntegro anterior quando latest é corrompido."""
        self._create_and_publish(step=10, ckpt_id="step_000010")
        self._create_and_publish(step=20, ckpt_id="step_000020")

        # Corrompe step_000020 alterando bytes do checkpoint.pt
        ckpt20_pt = self.runs_root / "checkpoints" / "step_000020" / "checkpoint.pt"
        with open(ckpt20_pt, "ab") as f:
            f.write(b"CORRUPTED_BYTES_IN_DRIVE")

        # O resolver deve detectar hash incorreto e acionar rollback automático para step_000010
        resolved = self.backend.resolve_checkpoint(self.runs_root, "latest")
        self.assertEqual(
            resolved.name,
            "step_000010",
            "O backend deve recuperar step_000010 após corrupção em step_000020",
        )

    def test_automatic_rollback_on_missing_complete_marker(self):
        """Testa rollback automático caso COMPLETE.json esteja ausente no checkpoint mais recente."""
        self._create_and_publish(step=10, ckpt_id="step_000010")
        self._create_and_publish(step=20, ckpt_id="step_000020")

        # Remove COMPLETE.json de step_000020
        complete_file = self.runs_root / "checkpoints" / "step_000020" / "COMPLETE.json"
        complete_file.unlink()

        resolved = self.backend.resolve_checkpoint(self.runs_root, "latest")
        self.assertEqual(
            resolved.name,
            "step_000010",
            "Checkpoint sem marcador COMPLETE deve ser descartado com recuo para step_000010",
        )

    def test_latest_pointer_manifest_hash_mismatch_falls_back(self):
        self._create_and_publish(step=10, ckpt_id="step_000010")
        self._create_and_publish(step=20, ckpt_id="step_000020")
        latest_file = self.runs_root / "latest.json"
        latest = json.loads(latest_file.read_text(encoding="utf-8"))
        latest["manifest_sha256"] = "0" * 64
        latest_file.write_text(json.dumps(latest), encoding="utf-8")
        self.assertEqual(self.backend.resolve_checkpoint(self.runs_root).name, "step_000020")

    def test_explicit_checkpoint_selector_rejects_traversal(self):
        with self.assertRaises(ValueError):
            self.backend.resolve_checkpoint(self.runs_root, "../outside")

    def test_safe_retention_policy_pruning_and_best_checkpoint(self):
        """Testa que a política de retenção mantém os 2 mais recentes + o melhor checkpoint (best.json)."""
        # Step 5 com a menor perda de validação (best)
        self._create_and_publish(step=5, ckpt_id="step_000005", best_val_loss=1.80)
        # Step 10 com perda maior
        self._create_and_publish(step=10, ckpt_id="step_000010", best_val_loss=2.50)
        # Step 15
        self._create_and_publish(step=15, ckpt_id="step_000015", best_val_loss=2.20)
        # Step 20
        self._create_and_publish(step=20, ckpt_id="step_000020", best_val_loss=2.10)

        valid_ids = self.backend.list_complete_checkpoints(self.runs_root)

        # Deve conter:
        # - step_000005 (preservado como BEST por ter loss 1.80)
        # - step_000015 e step_000020 (os 2 mais recentes)
        # step_000010 deve ter sido podado com segurança!
        self.assertIn("step_000005", valid_ids)
        self.assertIn("step_000015", valid_ids)
        self.assertIn("step_000020", valid_ids)
        self.assertNotIn("step_000010", valid_ids)

        # Verifica best.json
        best_file = self.runs_root / "best.json"
        self.assertTrue(best_file.exists())
        with open(best_file, "r", encoding="utf-8") as f:
            best_info = json.load(f)
        self.assertEqual(best_info["checkpoint_id"], "step_000005")
        self.assertEqual(best_info["val_loss"], 1.80)

    def test_retention_keeps_milestones_and_reports_unmet_quota_without_deleting_them(self):
        self.backend = GoogleDrivePersistenceBackend(
            checkpoints_to_keep=2,
            keep_best=False,
            max_storage_bytes=1,
            milestone_interval_steps=20,
        )
        for step in (10, 20, 30, 40, 50):
            self._create_and_publish(step=step, ckpt_id=f"step_{step:06d}")
        retained = self.backend.list_complete_checkpoints(self.runs_root)
        self.assertEqual(retained, ["step_000020", "step_000040", "step_000050"])
        self.assertFalse(self.backend.last_retention_status["quota_met"])
        self.assertGreater(self.backend.last_retention_status["retained_bytes"], 1)

    def test_trainer_integration_and_clean_session_resumption(self):
        """Simulação ponta a ponta: treino com salvamento no Drive e retomada em nova sessão limpa."""
        dataset = create_synthetic_dataset(
            num_docs=20,
            vocab_size=self.cfg.model.vocab_size,
            context_length=self.cfg.model.context_length,
            seed=42,
        )

        # 1. Sessão Inicial: treina até o passo 4 via session_max_steps
        self.cfg.training.max_steps = 10
        self.cfg.training.checkpoint_interval_steps = 2
        trainer_session_1 = Trainer(
            config=self.cfg,
            train_dataset=dataset,
            persistence_backend=self.backend,
            session_max_steps=4,
        )
        summary_1 = trainer_session_1.run()
        self.assertEqual(summary_1["global_step"], 4)

        # Verifica que step_000004 foi publicado no Drive
        pers_ckpts = self.backend.list_complete_checkpoints(self.runs_root)
        self.assertIn("step_000004", pers_ckpts)

        # 2. Nova Sessão Limpa (Novo Runtime Colab) com idêntica configuração científica
        fresh_cfg = TrainingConfig(
            run_id=self.cfg.run_id,
            corpus_version=self.cfg.corpus_version,
            split_version=self.cfg.split_version,
            tokenizer_id=self.cfg.tokenizer_id,
            token_dataset_id=self.cfg.token_dataset_id,
            sequence_policy_version=self.cfg.sequence_policy_version,
            model=self.cfg.model,
            training=TrainingHyperparameters(seed=42, precision="fp32", max_steps=10),
            persistence=PersistenceConfig(backend="drive", runs_dir=str(self.root / "drive_runs")),
        )
        trainer_session_2 = Trainer(
            config=fresh_cfg,
            train_dataset=dataset,
            persistence_backend=self.backend,
            session_max_steps=7,
        )

        # Restaura do último checkpoint
        trainer_session_2.resume_from_checkpoint(selector="latest")
        self.assertEqual(trainer_session_2.global_step, 4)

        # Continua o treinamento por mais 3 passos (até session_max_steps = 7)
        summary_2 = trainer_session_2.run()
        self.assertEqual(summary_2["global_step"], 7)



    def test_functional_api_module_helpers(self):
        """Testa as funções de conveniência em nível de módulo."""
        local_dir = self.staging_root / "step_000001"
        save_checkpoint(
            save_dir=local_dir,
            config=self.cfg,
            model=self.model,
            optimizer=self.opt,
            scheduler=self.sched,
            precision_mgr=self.pm,
            sampler=self.sampler,
            tracker=self.tracker,
            global_step=1,
            tokens_seen=100,
            tokens_for_successful_updates=100,
            overflow_updates_count=0,
            total_positions_evaluated=200,
            segment_id="colab_seg",
            event_sequence=1,
            checkpoint_id="step_000001",
        )

        m = publish_checkpoint(local_dir, self.runs_root)
        self.assertEqual(m["checkpoint_id"], "step_000001")

        ckpts = list_complete_checkpoints(self.runs_root)
        self.assertIn("step_000001", ckpts)

        res = resolve_checkpoint(self.runs_root, "latest")
        self.assertEqual(res.name, "step_000001")

    def test_manifest_path_traversal_is_rejected(self):
        local_dir = self.staging_root / "step_000030"
        _, manifest = save_checkpoint(
            save_dir=local_dir,
            config=self.cfg,
            model=self.model,
            optimizer=self.opt,
            scheduler=self.sched,
            precision_mgr=self.pm,
            sampler=self.sampler,
            tracker=self.tracker,
            global_step=30,
            tokens_seen=3000,
            tokens_for_successful_updates=3000,
            overflow_updates_count=0,
            total_positions_evaluated=6000,
            segment_id="colab_seg",
            event_sequence=30,
            checkpoint_id="step_000030",
        )
        manifest["files"][0]["path"] = "../../outside.pt"
        with open(local_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        with self.assertRaises(ValueError):
            self.backend.publish_checkpoint(local_dir, self.runs_root)

    def test_checkpoint_ids_are_immutable(self):
        self._create_and_publish(step=10, ckpt_id="step_000010")
        checkpoint_file = self.runs_root / "checkpoints" / "step_000010" / "checkpoint.pt"
        original_bytes = checkpoint_file.read_bytes()

        # Reusing an ID for different bytes must not replace the already-restorable copy.
        with open(self.staging_root / "step_000010" / "checkpoint.pt", "ab") as f:
            f.write(b"different payload")
        with self.assertRaises(ValueError):
            self.backend.publish_checkpoint(self.staging_root / "step_000010", self.runs_root)
        self.assertEqual(checkpoint_file.read_bytes(), original_bytes)
        self.assertEqual(self.backend.resolve_checkpoint(self.runs_root).name, "step_000010")


if __name__ == "__main__":
    unittest.main()
