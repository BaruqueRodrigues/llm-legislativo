import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.publication.curate_senado_release import main


class TestCurateSenadoRelease(unittest.TestCase):
    def test_builds_provenanced_parquet_and_keeps_process_families_in_one_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extraction_root = root / "extraction"
            archive_dir = extraction_root / "part001-batched"
            batch_dir = archive_dir / "batch-0001"
            batch_dir.mkdir(parents=True)
            (archive_dir / "COMPLETE.json").write_text(json.dumps({"status": "complete_for_indexed_pdfs_only"}))
            sources = [
                {"archive": "part001.tar", "member": "a.pdf", "version_id": "senado:doc:processo:1:v:a",
                 "source_url": "https://example/a", "file_sha256": "a" * 64,
                 "document_id": "senado:doc:processo:1", "house": "senado", "source_namespace": "senado_processo_documento",
                 "source_document_id": "1", "process_ids_json": '["PROC-X"]', "source_ids_json": '["1"]',
                 "record_kinds_json": '["parecer"]', "query_years_json": '["2024"]'},
                {"archive": "part001.tar", "member": "b.pdf", "version_id": "senado:doc:processo:2:v:b",
                 "source_url": "https://example/b", "file_sha256": "b" * 64,
                 "document_id": "senado:doc:processo:2", "house": "senado", "source_namespace": "senado_processo_documento",
                 "source_document_id": "2", "process_ids_json": '["PROC-X"]', "source_ids_json": '["2"]',
                 "record_kinds_json": '["voto"]', "query_years_json": '["2024"]'},
            ]
            with (batch_dir / "source_members.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=sources[0].keys())
                writer.writeheader()
                writer.writerows(sources)
            runs = [{"version_id": row["version_id"], "extraction_id": f"{row['version_id']}:ext:1", "status": "complete"} for row in sources]
            pq.write_table(pa.Table.from_pylist(runs), batch_dir / "extraction_runs.parquet")
            pages = [
                {"extraction_id": run["extraction_id"], "page_index": 1, "raw_text": f"texto {i}",
                 "quality_status": "pass", "character_count": 7}
                for i, run in enumerate(runs)
            ]
            pq.write_table(pa.Table.from_pylist(pages), batch_dir / "pages.parquet")
            pq.write_table(pa.Table.from_pylist([]), batch_dir / "sections.parquet")
            pq.write_table(pa.Table.from_pylist([{
                "version_id": "senado:doc:html:3:v:c", "document_id": "senado:doc:html:3",
                "process_ids_json": '["PROC-X"]', "source_ids_json": '["3"]',
                "record_kinds_json": '["html"]', "house": "senado",
                "source_url": "https://example/c", "archive": "part001.tar",
                "archive_member": "c.html", "file_sha256": "c" * 64,
                "text": "texto em revisão", "text_sha256": "d" * 64,
                "character_count": 16, "quality_status": "review",
            }]), archive_dir / "non_pdf_text.parquet")

            output_dir = root / "curated"
            with patch("sys.argv", ["curate_senado_release", "--extraction-root", str(extraction_root),
                                     "--output-dir", str(output_dir), "--expected-archives", "1"]):
                self.assertEqual(main(), 0)
            documents = pq.read_table(output_dir / "documents.parquet").to_pylist()
            self.assertEqual(len(documents), 3)
            self.assertEqual(documents[0]["family_id"], documents[1]["family_id"])
            self.assertEqual(documents[0]["split"], documents[1]["split"])
            self.assertEqual(documents[0]["house"], "senado")
            non_pdf = next(row for row in documents if row["version_id"].endswith(":v:c"))
            self.assertEqual(non_pdf["family_id"], documents[0]["family_id"])
            self.assertEqual(non_pdf["split"], "quarantine")
            self.assertFalse(non_pdf["include_in_training"])
            self.assertEqual(sum(row["include_in_training"] for row in documents), 2)
            self.assertTrue((output_dir / "pages.parquet").exists())
            self.assertTrue((output_dir / "sections.parquet").exists())


if __name__ == "__main__":
    unittest.main()
