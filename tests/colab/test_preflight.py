"""
tests/colab/test_preflight.py
Testes unitários do módulo de preflight, auditoria de hardware, mock determinístico e termos do Colab.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from legislm.colab.preflight import (
    OFFICIAL_AI_PRO_POLICY_TERMS,
    probe_gpu_hardware,
    run_preflight,
    verify_drive_roundtrip_io,
)


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.drive_root = self.root / "drive_root"
        self.drive_root.mkdir()
        self.local_scratch = self.root / "local_scratch"
        self.local_scratch.mkdir()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_official_policy_terms_and_privacy(self):
        """Verifica se os termos normativos de docs/COLAB.md estão definidos sem expor dados pessoais."""
        self.assertIn("effective_terms_summary", OFFICIAL_AI_PRO_POLICY_TERMS)
        self.assertIn("documentation_sources", OFFICIAL_AI_PRO_POLICY_TERMS)

        summary_text = " ".join(OFFICIAL_AI_PRO_POLICY_TERMS["effective_terms_summary"])
        self.assertIn("200 CCUs", summary_text)
        self.assertIn("pt-BR", summary_text)
        self.assertIn("efêmeras", summary_text)
        self.assertIn("Privacidade estrita", summary_text)
        self.assertIn("a página pt-BR não menciona", summary_text)

        # Garante ausência de emails ou chaves
        self.assertNotIn("@", summary_text)

    def test_drive_rw_roundtrip_verification_success(self):
        """Testa o teste de escrita, leitura e validação SHA-256 no armazenamento do Drive."""
        res = verify_drive_roundtrip_io(self.drive_root)
        self.assertTrue(res["accessible"])
        self.assertTrue(res["read_write_verified"])
        self.assertGreater(res["payload_bytes"], 0)
        self.assertIsNotNone(res["sha256_verified"])

    def test_drive_rw_verification_nonexistent_directory(self):
        """Testa que diretório inexistente falha graciosamente."""
        nonexistent = self.root / "missing_dir"
        res = verify_drive_roundtrip_io(nonexistent)
        self.assertFalse(res["accessible"])
        self.assertIn("não existe", res["error"])

    def test_preflight_real_system_cpu_fallback(self):
        """Testa preflight no ambiente real com fallback para CPU aprovado."""
        cfg = {
            "session_name": "test_preflight_session",
            "drive_root": str(self.drive_root),
            "local_scratch_root": str(self.local_scratch),
            "preflight": {
                "check_gpu": True,
                "allow_cpu_fallback": True,
                "min_vram_gb": 8.0,
                "min_ram_gb": 4.0,
                "min_disk_free_gb": 1.0,
            },
        }
        report = run_preflight(config=cfg, allow_cpu_fallback=True)
        self.assertIn(report["status"], ("PASSED", "CPU_FALLBACK"))
        self.assertIn("hardware", report)
        self.assertIn("validation_checks", report)
        self.assertTrue(report["persistence_storage"]["read_write_verified"])

    def test_preflight_mock_hardware_cuda_success(self):
        """Testa auditoria simulada de hardware compatível com A100 e BF16."""
        mock_hw = {
            "gpu": {
                "available": True,
                "device_count": 1,
                "device_name": "NVIDIA A100-SXM4-40GB",
                "total_vram_gb": 40.0,
                "free_vram_gb": 39.5,
                "compute_capability": "8.0",
                "bf16_supported": True,
                "fp16_supported": True,
                "driver_version": "535.104.05",
                "nvidia_smi_output": "NVIDIA-SMI 535.104.05",
            },
            "ram": {"total_gb": 32.0, "available_gb": 28.0},
            "disk": {"total_gb": 150.0, "free_gb": 110.0},
        }

        cfg = {
            "session_name": "mock_cuda_session",
            "drive_root": str(self.drive_root),
            "local_scratch_root": str(self.local_scratch),
            "preflight": {
                "min_vram_gb": 16.0,
                "min_ram_gb": 16.0,
                "min_disk_free_gb": 20.0,
                "check_gpu": True,
                "allow_cpu_fallback": False,
            },
        }

        report = run_preflight(config=cfg, mock_hardware=mock_hw)
        self.assertEqual(report["status"], "PASSED")
        self.assertEqual(report["hardware"]["gpu"]["device_name"], "NVIDIA A100-SXM4-40GB")
        self.assertTrue(report["hardware"]["gpu"]["bf16_supported"])

    def test_preflight_mock_hardware_vram_insufficient_failure(self):
        """Testa que VRAM insuficiente causa status FAILED quando allow_cpu_fallback=False."""
        mock_hw = {
            "gpu": {
                "available": True,
                "device_count": 1,
                "device_name": "NVIDIA T4",
                "total_vram_gb": 15.0,
                "free_vram_gb": 14.5,
                "compute_capability": "7.5",
                "bf16_supported": False,
                "fp16_supported": True,
                "driver_version": "535.104.05",
                "nvidia_smi_output": "NVIDIA-SMI 535.104.05",
            },
            "ram": {"total_gb": 32.0, "available_gb": 28.0},
            "disk": {"total_gb": 150.0, "free_gb": 110.0},
        }

        cfg = {
            "session_name": "mock_t4_insufficient",
            "drive_root": str(self.drive_root),
            "local_scratch_root": str(self.local_scratch),
            "preflight": {
                "min_vram_gb": 24.0,  # Exige mais do que os 15GB disponíveis
                "check_gpu": True,
                "allow_cpu_fallback": False,
            },
        }

        report = run_preflight(config=cfg, mock_hardware=mock_hw, allow_cpu_fallback=False)
        self.assertEqual(report["status"], "FAILED")

    def test_preflight_report_serialization(self):
        """Testa que o relatório de preflight pode ser salvo em arquivo JSON."""
        out_json = self.root / "preflight_report.json"
        report = run_preflight(
            config={"drive_root": str(self.drive_root), "local_scratch_root": str(self.local_scratch)},
            allow_cpu_fallback=True,
            output_path=out_json,
        )
        self.assertTrue(out_json.exists())
        with open(out_json, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["session_id"], report["session_id"])


if __name__ == "__main__":
    unittest.main()
