"""
tests/training/test_config.py
Testes de validação de configuração e invariância de hashes científicos vs de execução.
"""

import copy
import pathlib
import unittest

from legislm.training.config import TrainingConfig

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


class TestTrainingConfig(unittest.TestCase):
    def setUp(self):
        self.pilot_yaml_path = REPO_ROOT / "configs" / "training" / "pilot.yaml"

    def test_load_pilot_yaml(self):
        """Testa o carregamento da configuração padrão do piloto configs/training/pilot.yaml."""
        cfg = TrainingConfig.from_yaml(self.pilot_yaml_path)
        self.assertEqual(cfg.run_id, "pilot_cpu_smoke")
        self.assertEqual(cfg.model.vocab_size, 8192)
        self.assertEqual(cfg.model.context_length, 512)
        self.assertEqual(cfg.model.d_model, 384)
        self.assertEqual(cfg.training.micro_batch_size, 2)
        self.assertEqual(cfg.training.grad_accum_steps, 4)
        self.assertEqual(cfg.training.precision, "fp32")
        self.assertEqual(cfg.training.budget_counter, "successful_update_tokens")

    def test_hash_invariance_and_separation(self):
        """Verifica a separação estrita entre scientific_config_hash e execution_config_hash."""
        cfg1 = TrainingConfig.from_yaml(self.pilot_yaml_path)
        cfg_sha1, sci1, exec1 = cfg1.compute_hashes()

        self.assertEqual(len(cfg_sha1), 64)
        self.assertEqual(len(sci1), 64)
        self.assertEqual(len(exec1), 64)

        # Modificação estritamente de execução: micro_batch_size, grad_accum_steps e device
        dict2 = cfg1.to_dict()
        dict2["training"]["micro_batch_size"] = 4
        dict2["training"]["grad_accum_steps"] = 2
        dict2["device"] = "cuda:0"
        cfg2 = TrainingConfig.from_dict(dict2)
        _, sci2, exec2 = cfg2.compute_hashes()

        # O hash científico DEVE ser rigorosamente IDÊNTICO
        self.assertEqual(sci1, sci2, "scientific_config_hash não pode mudar com alteração de microbatch ou device")
        # O hash de execução DEVE ser diferente
        self.assertNotEqual(exec1, exec2, "execution_config_hash deve refletir a mudança de execução")

        # Modificação científica: alteração de taxa de aprendizado
        dict3 = cfg1.to_dict()
        dict3["training"]["learning_rate"] = 0.001
        cfg3 = TrainingConfig.from_dict(dict3)
        _, sci3, exec3 = cfg3.compute_hashes()

        # O hash científico DEVE ser alterado
        self.assertNotEqual(sci1, sci3, "scientific_config_hash deve mudar com alteração de learning_rate")

    def test_validation_errors(self):
        """Testa que valores inválidos ou ilegais disparam erros de validação imediatos."""
        base_dict = TrainingConfig.from_yaml(self.pilot_yaml_path).to_dict()

        # Precisão inválida
        d_bad_prec = copy.deepcopy(base_dict)
        d_bad_prec["training"]["precision"] = "fp8"
        with self.assertRaises(ValueError):
            TrainingConfig.from_dict(d_bad_prec)

        # Budget counter inválido
        d_bad_budget = copy.deepcopy(base_dict)
        d_bad_budget["training"]["budget_counter"] = "invalid_counter"
        with self.assertRaises(ValueError):
            TrainingConfig.from_dict(d_bad_budget)

        # LR negativo
        d_bad_lr = copy.deepcopy(base_dict)
        d_bad_lr["training"]["learning_rate"] = -0.01
        with self.assertRaises(ValueError):
            TrainingConfig.from_dict(d_bad_lr)

        # checkpoints_to_keep menor que 2
        d_bad_ckpts = copy.deepcopy(base_dict)
        d_bad_ckpts["persistence"]["checkpoints_to_keep"] = 1
        with self.assertRaises(ValueError):
            TrainingConfig.from_dict(d_bad_ckpts)


if __name__ == "__main__":
    unittest.main()
