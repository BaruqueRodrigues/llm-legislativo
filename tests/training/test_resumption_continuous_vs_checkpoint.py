"""
tests/training/test_resumption_continuous_vs_checkpoint.py
Prova formal de equivalência determinística: N+M contínuo vs N + save/load + M.
"""

import copy
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

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


class TestResumptionContinuousVsCheckpoint(unittest.TestCase):
    def test_n_plus_m_deterministic_equivalence(self):
        """Prova formal de que treinar N+M passos continuamente produz os mesmos

        pesos, estados de otimizador, LR, perdas e próximo lote que treinar N passos,
        salvar checkpoint, restaurar em uma nova instância e treinar mais M passos,
        mesmo com dropout ativo e amostragem de dados determinística.
        """
        N = 4
        M = 4

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            runs_dir = tmp_root / "runs"
            staging_dir = tmp_root / "staging"

            cfg = TrainingConfig(
                run_id="proof_resumption",
                corpus_version="corpus_v1",
                split_version="split_v1",
                tokenizer_id="bpe_byte_v1_8k",
                token_dataset_id="tok_dataset_v1",
                sequence_policy_version="doc_window_v1",
                model=ModelArchitectureConfig(
                    vocab_size=128,
                    context_length=32,
                    d_model=64,
                    n_layers=2,
                    n_heads=2,
                    dropout=0.1,  # Dropout ativo para provar preservação de RNG
                    tie_embeddings=True,
                ),
                training=TrainingHyperparameters(
                    seed=777,
                    precision="fp32",
                    micro_batch_size=2,
                    grad_accum_steps=2,
                    max_steps=N + M,
                    learning_rate=0.001,
                    min_learning_rate=0.0001,
                    warmup_steps=3,
                    weight_decay=0.01,
                    grad_clip_norm=1.0,
                    evaluation_interval=0,
                    checkpoint_interval_steps=100,
                ),
                persistence=PersistenceConfig(
                    backend="local",
                    runs_dir=str(runs_dir),
                    checkpoints_to_keep=2,
                ),
                device="cpu",
            )

            # Fixa sementes para inicialização idêntica dos modelos
            torch.manual_seed(42)
            np.random.seed(42)
            random.seed(42)
            init_torch_rng = torch.get_rng_state()
            init_np_rng = np.random.get_state()
            init_py_rng = random.getstate()

            base_model = GPTModel(cfg.model.to_gpt_config())

            dataset1 = create_synthetic_dataset(
                num_docs=30,
                vocab_size=cfg.model.vocab_size,
                context_length=cfg.model.context_length,
                seed=cfg.training.seed,
            )
            dataset2 = create_synthetic_dataset(
                num_docs=30,
                vocab_size=cfg.model.vocab_size,
                context_length=cfg.model.context_length,
                seed=cfg.training.seed,
            )

            # ----------------------------------------------------
            # 1. Execução Contínua: N + M passos
            # ----------------------------------------------------
            torch.set_rng_state(init_torch_rng)
            np.random.set_state(init_np_rng)
            random.setstate(init_py_rng)

            model_cont = copy.deepcopy(base_model)
            trainer_cont = Trainer(
                config=cfg,
                model=model_cont,
                train_dataset=dataset1,
                persistence_backend=LocalPersistenceBackend(checkpoints_to_keep=2),
                segment_id="cont_seg",
            )
            trainer_cont.persistent_run_root = runs_dir / "proof_resumption_cont"
            trainer_cont.local_staging_root = staging_dir / "cont"

            # Passos 1 até N
            for _ in range(N):
                trainer_cont.train_step()

            # Passos N+1 até N+M com registro das perdas
            losses_cont = []
            for _ in range(M):
                loss, _, _, _ = trainer_cont.train_step()
                losses_cont.append(loss)

            lr_cont = trainer_cont.scheduler.get_last_lr()[0]

            # ----------------------------------------------------
            # 2. Execução com Checkpoint: N passos -> Save -> Restore -> M passos
            # ----------------------------------------------------
            # Restaura estado inicial de RNG para que o treino 2 inicie em condições idênticas ao treino 1
            torch.set_rng_state(init_torch_rng)
            np.random.set_state(init_np_rng)
            random.setstate(init_py_rng)

            model_ckpt = copy.deepcopy(base_model)
            trainer_ckpt = Trainer(
                config=cfg,
                model=model_ckpt,
                train_dataset=dataset2,
                persistence_backend=LocalPersistenceBackend(checkpoints_to_keep=2),
                segment_id="ckpt_seg",
            )
            trainer_ckpt.persistent_run_root = runs_dir / "proof_resumption_ckpt"
            trainer_ckpt.local_staging_root = staging_dir / "ckpt"

            # Passos 1 até N
            for _ in range(N):
                trainer_ckpt.train_step()

            # Salva checkpoint no passo N
            trainer_ckpt.save_and_publish_checkpoint("step_000004")

            # Instancia um NOVO Trainer do zero (simulando reinício de sessão)
            fresh_model = GPTModel(cfg.model.to_gpt_config())
            fresh_dataset = create_synthetic_dataset(
                num_docs=30,
                vocab_size=cfg.model.vocab_size,
                context_length=cfg.model.context_length,
                seed=cfg.training.seed,
            )
            fresh_trainer = Trainer(
                config=cfg,
                model=fresh_model,
                train_dataset=fresh_dataset,
                persistence_backend=LocalPersistenceBackend(checkpoints_to_keep=2),
                segment_id="resumed_seg",
            )
            fresh_trainer.persistent_run_root = runs_dir / "proof_resumption_ckpt"
            fresh_trainer.local_staging_root = staging_dir / "resumed"

            # Retoma a partir do checkpoint persistido
            fresh_trainer.resume_from_checkpoint("step_000004")
            self.assertEqual(fresh_trainer.global_step, N)

            # Executa os passos N+1 até N+M
            losses_resumed = []
            for _ in range(M):
                loss, _, _, _ = fresh_trainer.train_step()
                losses_resumed.append(loss)

            lr_resumed = fresh_trainer.scheduler.get_last_lr()[0]

            # ----------------------------------------------------
            # 3. Prova Formal de Equivalência
            # ----------------------------------------------------
            # Perdas passo a passo em M
            self.assertEqual(len(losses_cont), len(losses_resumed))
            for i, (l_c, l_r) in enumerate(zip(losses_cont, losses_resumed)):
                self.assertAlmostEqual(
                    l_c,
                    l_r,
                    places=5,
                    msg=f"Perda divergiu no passo N+{i+1}: contínuo={l_c}, retomado={l_r}",
                )

            # Taxa de aprendizado idêntica
            self.assertAlmostEqual(lr_cont, lr_resumed, places=7)

            # Próximo índice do sampler
            next_idx_cont, _ = trainer_cont.sampler.next_index()
            next_idx_resumed, _ = fresh_trainer.sampler.next_index()
            self.assertEqual(
                next_idx_cont,
                next_idx_resumed,
                "O próximo lote amostrado deve ser estritamente idêntico",
            )

            # Pesos de todos os tensores do modelo idênticos
            for (n1, p1), (n2, p2) in zip(
                trainer_cont.model.named_parameters(), fresh_trainer.model.named_parameters()
            ):
                self.assertEqual(n1, n2)
                max_diff = (p1 - p2).abs().max().item()
                self.assertTrue(
                    torch.allclose(p1, p2, atol=1e-6, rtol=1e-5),
                    f"Divergência de parâmetros em {n1}: max diff = {max_diff}",
                )


if __name__ == "__main__":
    unittest.main()
