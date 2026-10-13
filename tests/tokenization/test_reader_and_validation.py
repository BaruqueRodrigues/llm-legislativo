"""
tests/tokenization/test_reader_and_validation.py
Testes unitários para CuratedReleaseReader e validação de integridade.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from legislm.tokenization.reader import CuratedReleaseReader


class TestReaderAndValidation(unittest.TestCase):
    def setUp(self):
        self.common_fixtures_dir = Path("tests/fixtures/common")
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_load_documents_from_common_fixtures(self):
        """Valida que o leitor carrega com sucesso as fixtures canônicas existentes."""
        reader = CuratedReleaseReader(self.common_fixtures_dir)
        train_docs, summary = reader.load_documents(split="train")

        self.assertGreater(len(train_docs), 0)
        self.assertEqual(summary.split, "train")
        self.assertEqual(summary.total_documents, len(train_docs))
        self.assertGreater(summary.total_utf8_bytes, 0)
        self.assertEqual(len(summary.item_ids_hash), 64)
        self.assertEqual(len(summary.text_hashes_hash), 64)

        for doc in train_docs:
            self.assertEqual(doc.split, "train")
            self.assertEqual(doc.quality_status, "accepted")
            self.assertTrue(doc.include_in_dataset)
            self.assertEqual(doc.representative_item_id, doc.corpus_item_id)
            self.assertEqual(hashlib.sha256(doc.text.encode("utf-8")).hexdigest(), doc.text_sha256)

    def test_dedup_and_quarantine_exclusion(self):
        """Valida que documentos duplicados (include_in_dataset=False) e de quarentena não entram em train."""
        reader = CuratedReleaseReader(self.common_fixtures_dir)
        train_docs, _ = reader.load_documents(split="train")
        train_ids = {d.corpus_item_id for d in train_docs}

        # syn002 é duplicata de syn001 (include_in_dataset=False)
        self.assertNotIn("item:syn002:231efa959ded", train_ids)
        # syn005 e syn006 estão em quarantine
        self.assertNotIn("item:syn005:222131e2a695", train_ids)
        self.assertNotIn("item:syn006:b7a6908e39b4", train_ids)

    def test_checksum_corruption_detection(self):
        """Valida que documento com text_sha256 divergente levanta ValueError."""
        # Cria cópia modificada com hash corrompido
        curated_src = pq.read_table(self.common_fixtures_dir / "curated_documents.parquet")
        split_src = pq.read_table(self.common_fixtures_dir / "split_assignments.parquet")

        curated_dict = curated_src.to_pydict()
        # Corrompe o hash do primeiro documento
        curated_dict["text_sha256"][0] = "0" * 64

        corrupted_curated_path = self.tmp_path / "curated_documents.parquet"
        pq.write_table(pa.Table.from_pydict(curated_dict, schema=curated_src.schema), corrupted_curated_path)
        pq.write_table(split_src, self.tmp_path / "split_assignments.parquet")

        reader = CuratedReleaseReader(self.tmp_path)
        with self.assertRaises(ValueError) as ctx:
            reader.load_documents(split="train", verify_checksums=True)
        self.assertIn("Checksum do texto corrompido", str(ctx.exception))

    def test_utf8_bytes_divergence_detection(self):
        """Valida que divergência entre utf8_bytes e tamanho real levanta ValueError."""
        curated_src = pq.read_table(self.common_fixtures_dir / "curated_documents.parquet")
        split_src = pq.read_table(self.common_fixtures_dir / "split_assignments.parquet")

        curated_dict = curated_src.to_pydict()
        curated_dict["utf8_bytes"][0] = curated_dict["utf8_bytes"][0] + 999

        pq.write_table(pa.Table.from_pydict(curated_dict, schema=curated_src.schema), self.tmp_path / "curated_documents.parquet")
        pq.write_table(split_src, self.tmp_path / "split_assignments.parquet")

        reader = CuratedReleaseReader(self.tmp_path)
        with self.assertRaises(ValueError) as ctx:
            reader.load_documents(split="train", verify_checksums=True)
        self.assertIn("Contagem de bytes UTF-8 divergente", str(ctx.exception))

    def test_missing_column_schema_validation(self):
        """Valida rejeição quando colunas obrigatórias estão ausentes."""
        split_src = pq.read_table(self.common_fixtures_dir / "split_assignments.parquet")
        pq.write_table(split_src, self.tmp_path / "split_assignments.parquet")

        # curated_documents sem coluna text_sha256
        incomplete_table = pa.Table.from_pydict({
            "corpus_item_id": ["item:1"],
            "text": ["exemplo"],
            "utf8_bytes": [7],
            "quality_status": ["accepted"],
            "family_id": ["f1"],
            "representative_item_id": ["item:1"],
            "include_in_dataset": [True],
            "house": ["camara"],
            "normalized_kind": ["PL"],
        })
        pq.write_table(incomplete_table, self.tmp_path / "curated_documents.parquet")

        reader = CuratedReleaseReader(self.tmp_path)
        with self.assertRaises(ValueError) as ctx:
            reader.load_documents(split="train")
        self.assertIn("Colunas obrigatórias ausentes", str(ctx.exception))

    def test_manifest_and_complete_marker_validation(self):
        """Valida verificação completa de release_manifest.json e COMPLETE.json."""
        curated_src = pq.read_table(self.common_fixtures_dir / "curated_documents.parquet")
        split_src = pq.read_table(self.common_fixtures_dir / "split_assignments.parquet")

        curated_p = self.tmp_path / "curated_documents.parquet"
        split_p = self.tmp_path / "split_assignments.parquet"
        pq.write_table(curated_src, curated_p)
        pq.write_table(split_src, split_p)

        manifest_data = {
            "schema_version": "2.0.0",
            "corpus_version": "corpus_v1",
            "split_version": "split_v1",
            "files": [
                {
                    "path": "curated_documents.parquet",
                    "table_name": "curated_documents",
                    "size_bytes": curated_p.stat().st_size,
                    "sha256": hashlib.sha256(curated_p.read_bytes()).hexdigest(),
                },
                {
                    "path": "split_assignments.parquet",
                    "table_name": "split_assignments",
                    "size_bytes": split_p.stat().st_size,
                    "sha256": hashlib.sha256(split_p.read_bytes()).hexdigest(),
                },
            ],
        }

        manifest_p = self.tmp_path / "release_manifest.json"
        with open(manifest_p, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        man_hash = hashlib.sha256(manifest_p.read_bytes()).hexdigest()
        complete_p = self.tmp_path / "COMPLETE.json"
        with open(complete_p, "w", encoding="utf-8") as f:
            json.dump({"manifest_sha256": man_hash}, f)

        reader = CuratedReleaseReader(self.tmp_path)
        docs, _ = reader.load_documents(split="train")
        self.assertGreater(len(docs), 0)

        # Agora testa corrupção do COMPLETE.json
        with open(complete_p, "w", encoding="utf-8") as f:
            json.dump({"manifest_sha256": "f" * 64}, f)

        with self.assertRaises(ValueError) as ctx:
            reader.load_documents(split="train")
        self.assertIn("Hash divergente no release_manifest.json", str(ctx.exception))

    def test_manifest_files_as_dict_and_subpath_fallback(self):
        """Valida manifesto com files no formato dict e resolução de subpaths."""
        curated_src = pq.read_table(self.common_fixtures_dir / "curated_documents.parquet")
        split_src = pq.read_table(self.common_fixtures_dir / "split_assignments.parquet")

        curated_p = self.tmp_path / "curated_documents.parquet"
        split_p = self.tmp_path / "split_assignments.parquet"
        pq.write_table(curated_src, curated_p)
        pq.write_table(split_src, split_p)

        manifest_data = {
            "schema_version": "2.0.0",
            "corpus_version": "corpus_v1",
            "split_version": "split_v1",
            "files": {
                "curated_documents": {
                    "path": "staging/curation/batch_01/curated_documents.parquet",
                    "table_name": "curated_documents",
                    "size_bytes": curated_p.stat().st_size,
                    "sha256": hashlib.sha256(curated_p.read_bytes()).hexdigest(),
                },
                "split_assignments": {
                    "path": "staging/curation/batch_01/split_assignments.parquet",
                    "table_name": "split_assignments",
                    "size_bytes": split_p.stat().st_size,
                    "sha256": hashlib.sha256(split_p.read_bytes()).hexdigest(),
                },
            },
        }

        manifest_p = self.tmp_path / "release_manifest.json"
        with open(manifest_p, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        man_hash = hashlib.sha256(manifest_p.read_bytes()).hexdigest()
        complete_p = self.tmp_path / "COMPLETE.json"
        with open(complete_p, "w", encoding="utf-8") as f:
            json.dump({"manifest_sha256": man_hash}, f)

        reader = CuratedReleaseReader(self.tmp_path)
        docs, summary = reader.load_documents(split="train")
        self.assertGreater(len(docs), 0)

    def test_load_real_curation_release_if_available(self):
        """Valida carregamento direto da release curada publicada em data/staging/curation/."""
        release_dir = Path("data/staging/curation/release_curated_gh_2.0.0")
        if not release_dir.exists():
            return

        reader = CuratedReleaseReader(release_dir)
        docs, summary = reader.load_documents(split="train")
        self.assertEqual(len(docs), 4)
        self.assertEqual(summary.total_utf8_bytes, 2820)
        self.assertEqual(summary.split, "train")


if __name__ == "__main__":
    unittest.main()
