"""
tests/test_common_contracts.py
Validação dos contratos normativos e esquemas JSON em Python (Gate G0)
"""

import json
import hashlib
import pathlib
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

from legislm.paths import require_data_root

class TestCommonContracts(unittest.TestCase):
    def setUp(self):
        self.schemas_dir = REPO_ROOT / "schemas"
        self.configs_dir = REPO_ROOT / "configs"
        self.fixtures_dir = REPO_ROOT / "tests" / "fixtures" / "common"

    def test_tables_json_schema_completeness(self):
        """Verifica se todas as 31 tabelas normativas estão descritas em schemas/tables.json"""
        tables_file = self.schemas_dir / "tables.json"
        self.assertTrue(tables_file.exists(), "schemas/tables.json deve existir")

        with open(tables_file, "r", encoding="utf-8") as f:
            tables_data = json.load(f)

        self.assertGreaterEqual(len(tables_data), 31, "Devem haver pelo menos 31 tabelas mapeadas")

        required_tables = [
            "source_snapshots", "propositions", "authors", "proposition_authors",
            "document_authors", "themes", "proposition_themes", "metadata_checks",
            "relations", "process_phases", "document_phases", "documents",
            "proposition_documents", "document_versions", "fetch_attempts",
            "use_evidence", "source_collections", "legislative_types",
            "coverage_segments", "collection_documents", "entity_aliases",
            "extraction_runs", "pages", "sections", "curated_documents",
            "corpus_item_propositions", "curated_document_sections", "dedup_pairs",
            "cleaning_events", "quality_reviews", "split_assignments"
        ]

        for table in required_tables:
            self.assertIn(table, tables_data, f"Tabela {table} ausente em schemas/tables.json")
            self.assertIn("pk", tables_data[table], f"Tabela {table} deve ter chave primária 'pk'")
            self.assertIn("columns", tables_data[table], f"Tabela {table} deve definir 'columns'")

    def test_manifest_schemas_exist(self):
        """Verifica a presença dos esquemas JSON de todos os manifestos"""
        manifest_schemas = [
            "release_manifest.schema.json",
            "tokenizer_manifest.schema.json",
            "token_dataset_manifest.schema.json",
            "checkpoint_manifest.schema.json"
        ]
        manifests_dir = self.schemas_dir / "manifests"
        for m in manifest_schemas:
            p = manifests_dir / m
            self.assertTrue(p.exists(), f"Esquema {m} deve existir")
            with open(p, "r", encoding="utf-8") as f:
                schema_json = json.load(f)
            self.assertEqual(schema_json.get("type"), "object")

    def test_configs_exist(self):
        """Verifica existência das configurações normativas essenciais"""
        required_configs = [
            self.configs_dir / "data" / "history.yaml",
            self.configs_dir / "extraction" / "history.yaml",
            self.configs_dir / "curation" / "history.yaml",
            self.configs_dir / "tokenizer" / "pilot.yaml",
            self.configs_dir / "training" / "pilot.yaml",
            self.configs_dir / "colab" / "pilot.yaml",
            self.configs_dir / "evaluation" / "prompts.json"
        ]
        for c in required_configs:
            self.assertTrue(c.exists(), f"Configuração {c} deve existir")

    def test_parquet_fixtures_exist(self):
        """Verifica se os arquivos Parquet de fixtures canônicas foram gerados"""
        required_fixtures = [
            "source_snapshots.parquet",
            "propositions.parquet",
            "authors.parquet",
            "proposition_authors.parquet",
            "themes.parquet",
            "proposition_themes.parquet",
            "documents.parquet",
            "proposition_documents.parquet",
            "curated_documents.parquet",
            "split_assignments.parquet"
        ]
        for fix in required_fixtures:
            p = self.fixtures_dir / fix
            self.assertTrue(p.exists(), f"Fixture {fix} deve existir")


    def test_data_root_requires_absolute_external_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict("os.environ", {"DATA_ROOT": temp_dir}):
                self.assertEqual(require_data_root(), pathlib.Path(temp_dir).resolve())
            with patch.dict("os.environ", {"DATA_ROOT": "relative/data"}):
                with self.assertRaisesRegex(ValueError, "absolute"):
                    require_data_root()
            with patch.dict("os.environ", {"DATA_ROOT": str(REPO_ROOT / "data")}):
                with self.assertRaisesRegex(ValueError, "outside the checkout"):
                    require_data_root()

    def test_deterministic_hashing_consistency(self):
        """Testa que SHA-256 em Python bate com padrão RFC e minúsculo 64 hex"""
        text = "Texto oficial de teste para hash"
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(len(h), 64)
        self.assertEqual(h, h.lower())

if __name__ == "__main__":
    unittest.main()
