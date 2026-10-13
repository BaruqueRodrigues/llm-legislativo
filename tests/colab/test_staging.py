"""
tests/colab/test_staging.py
Testes unitários de staging local com verificação SHA-256, cache idempotente e benchmark de I/O.
"""

import json
import tempfile
import unittest
from pathlib import Path

from legislm.colab.staging import (
    benchmark_io,
    compute_file_sha256,
    stage_directory,
    stage_file,
)


class TestStaging(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.source_dir = self.root / "drive_source"
        self.source_dir.mkdir()
        self.target_dir = self.root / "local_target"
        self.target_dir.mkdir()

        # Cria arquivos de teste
        self.sample_file = self.source_dir / "shard_0001.bin"
        self.sample_payload = b"LEGISLATIVO_BRASILEIRO_AMOSTRA_TOKENIZADA_" * 500
        self.sample_file.write_bytes(self.sample_payload)
        self.sample_sha256 = compute_file_sha256(self.sample_file)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_stage_file_copies_and_verifies_sha256(self):
        """Testa cópia atômica com cálculo e validação exata de SHA-256."""
        dst = self.target_dir / "shard_0001.bin"
        res = stage_file(
            source_path=self.sample_file,
            target_path=dst,
            expected_sha256=self.sample_sha256,
            verify_hashes=True,
        )

        self.assertTrue(dst.exists())
        self.assertFalse(res["cached"])
        self.assertEqual(res["size_bytes"], len(self.sample_payload))
        self.assertEqual(res["sha256"], self.sample_sha256)
        self.assertEqual(compute_file_sha256(dst), self.sample_sha256)

    def test_stage_file_idempotent_caching(self):
        """Testa que arquivo idêntico no destino é detectado no cache sem re-cópia."""
        dst = self.target_dir / "shard_0001.bin"
        # Primeira cópia
        res1 = stage_file(self.sample_file, dst, expected_sha256=self.sample_sha256)
        self.assertFalse(res1["cached"])

        # Segunda invocação (deve bater no cache)
        res2 = stage_file(self.sample_file, dst, expected_sha256=self.sample_sha256)
        self.assertTrue(res2["cached"])
        self.assertEqual(res2["elapsed_seconds"], 0.0)

    def test_stage_file_detects_hash_mismatch(self):
        """Testa que hash esperado incorreto rejeita o arquivo e limpa arquivo temporário."""
        dst = self.target_dir / "shard_corrupted.bin"
        bogus_hash = "0" * 64

        with self.assertRaises(ValueError) as ctx:
            stage_file(
                source_path=self.sample_file,
                target_path=dst,
                expected_sha256=bogus_hash,
                verify_hashes=True,
            )

        self.assertIn("Hash da origem diverge do manifesto", str(ctx.exception))
        # O arquivo de destino final não deve ter sido criado
        self.assertFalse(dst.exists())
        # Nenhum arquivo temporário deve sobrar no diretório de destino
        temp_files = list(self.target_dir.glob("*.staging_tmp_*"))
        self.assertEqual(len(temp_files), 0)

    def test_stage_file_replaces_same_size_corrupt_cache_without_manifest_hash(self):
        dst = self.target_dir / "shard_0001.bin"
        dst.write_bytes(b"X" * len(self.sample_payload))
        res = stage_file(self.sample_file, dst, verify_hashes=True)
        self.assertFalse(res["cached"])
        self.assertEqual(dst.read_bytes(), self.sample_payload)
        self.assertEqual(res["sha256"], self.sample_sha256)

    def test_stage_file_missing_source_raises(self):
        """Testa erro imediato caso o arquivo de origem não exista."""
        missing = self.source_dir / "nonexistent.bin"
        dst = self.target_dir / "out.bin"
        with self.assertRaises(FileNotFoundError):
            stage_file(missing, dst)

    def test_stage_directory_recursive(self):
        """Testa transferência de diretório completo com subpastas."""
        sub_dir = self.source_dir / "nested"
        sub_dir.mkdir()
        f2 = sub_dir / "shard_0002.bin"
        f2.write_bytes(b"SUB_SHARD_DATA_" * 100)

        res = stage_directory(self.source_dir, self.target_dir)
        self.assertEqual(res["total_files"], 2)
        self.assertEqual(res["files_copied"], 2)
        self.assertEqual(res["files_cached"], 0)
        self.assertTrue((self.target_dir / "shard_0001.bin").exists())
        self.assertTrue((self.target_dir / "nested" / "shard_0002.bin").exists())

        # Execução subsequente: todos devem ser detectados no cache
        res_cached = stage_directory(self.source_dir, self.target_dir)
        self.assertEqual(res_cached["files_cached"], 2)
        self.assertEqual(res_cached["files_copied"], 0)

    def test_stage_directory_with_manifest(self):
        """Testa staging guiado por manifesto explícito com validação de hashes."""
        manifest_data = {
            "files": [
                {
                    "path": "shard_0001.bin",
                    "size_bytes": len(self.sample_payload),
                    "sha256": self.sample_sha256,
                }
            ]
        }
        manifest_file = self.source_dir / "manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        res = stage_directory(self.source_dir, self.target_dir, manifest_path=manifest_file)
        self.assertEqual(res["total_files"], 1)
        self.assertEqual(res["files_copied"], 1)

    def test_stage_directory_rejects_manifest_path_traversal(self):
        outside = self.root / "outside.bin"
        outside.write_bytes(b"must not be staged")
        manifest_file = self.source_dir / "unsafe_manifest.json"
        manifest_file.write_text(
            json.dumps({"files": [{"path": "../outside.bin", "sha256": compute_file_sha256(outside)}]}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            stage_directory(self.source_dir, self.target_dir, manifest_path=manifest_file)
        self.assertEqual(outside.read_bytes(), b"must not be staged")
        self.assertFalse((self.target_dir / "outside.bin").exists())

    def test_stage_directory_missing_explicit_manifest_fails_closed(self):
        missing_manifest = self.root / "missing-manifest.json"
        with self.assertRaises(FileNotFoundError):
            stage_directory(self.source_dir, self.target_dir, manifest_path=missing_manifest)

    def test_benchmark_io_execution(self):
        """Testa benchmark de I/O medindo throughput na origem e no destino local."""
        bench_dst = self.root / "bench_staging"
        report = benchmark_io(
            source_file_or_dir=self.source_dir,
            local_target_dir=bench_dst,
            test_size_mb=1.0,
            num_reads=2,
            block_size_kb=32,
        )

        self.assertIn("direct_io", report)
        self.assertIn("staging_transfer", report)
        self.assertIn("local_staged_io", report)
        self.assertIn("speedup_factor", report)
        self.assertIn("recommendation", report)
        self.assertGreater(report["direct_io"]["avg_speed_mb_s"], 0)
        self.assertGreater(report["local_staged_io"]["avg_speed_mb_s"], 0)


if __name__ == "__main__":
    unittest.main()
