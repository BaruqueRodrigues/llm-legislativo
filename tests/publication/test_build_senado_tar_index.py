import csv
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/publication/build_senado_tar_index.py"


class TestBuildSenadoTarIndex(unittest.TestCase):
    def test_indexes_member_hashes_links_attempts_and_control_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "part016.tar"
            link_index = root / "links.csv"
            output_dir = root / "out"
            pdf_bytes = b"%PDF-1.7 synthetic senate document"
            error_bytes = b"<html><title>404 Not Found</title></html>"
            manifest_rows = [
                {"url": "https://legis.senado.leg.br/sdleg-getter/documento?dm=123",
                 "status": "200", "tipo": "pdf", "bytes": str(len(pdf_bytes)),
                 "arquivo": r"C:\\download\\doc-a.pdf", "segundos_download": "1.2",
                 "segundos_persistencia": "0.1"},
                {"url": "https://legis.senado.leg.br/sdleg-getter/documento?dm=123",
                 "status": "200", "tipo": "pdf", "bytes": str(len(pdf_bytes)),
                 "arquivo": "doc-a.pdf", "segundos_download": "1.1",
                 "segundos_persistencia": "0.1"},
                {"url": "https://legis.senado.leg.br/sdleg-getter/documento?dm=999",
                 "status": "404", "tipo": "html", "bytes": str(len(error_bytes)),
                 "arquivo": "error.html", "segundos_download": "0.2",
                 "segundos_persistencia": "0.0"},
            ]
            manifest = io.StringIO()
            writer = csv.DictWriter(manifest, fieldnames=manifest_rows[0].keys())
            writer.writeheader()
            writer.writerows(manifest_rows)
            manifest_bytes = manifest.getvalue().encode("utf-8")
            with tarfile.open(archive_path, "w") as archive:
                for name, content in (
                    ("doc-a.pdf", pdf_bytes),
                    ("error.html", error_bytes),
                    ("manifesto.csv", manifest_bytes),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))

            link_rows = [
                {"source_id": "123", "process_id": "PROC-A", "record_kind": "parecer",
                 "query_year": "2024", "document_url": manifest_rows[0]["url"]},
                {"source_id": "123", "process_id": "PROC-B", "record_kind": "voto",
                 "query_year": "2025", "document_url": manifest_rows[0]["url"]},
            ]
            with link_index.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=link_rows[0].keys())
                writer.writeheader()
                writer.writerows(link_rows)

            subprocess.run(
                [sys.executable, str(SCRIPT), str(archive_path), "--link-index", str(link_index),
                 "--part", archive_path.name,
                 "--archive-source-uri", "https://drive.google.com/drive/folders/example",
                 "--output-dir", str(output_dir)],
                check=True, capture_output=True, text=True,
            )

            with (output_dir / "part016.csv").open(newline="", encoding="utf-8") as stream:
                rows = {row["membro_tar"]: row for row in csv.DictReader(stream)}
            pdf = rows["doc-a.pdf"]
            self.assertEqual(pdf["sha256"], hashlib.sha256(pdf_bytes).hexdigest())
            self.assertEqual(pdf["document_id"], "senado:doc:processo:123")
            self.assertEqual(json.loads(pdf["process_ids_json"]), ["PROC-A", "PROC-B"])
            self.assertEqual(json.loads(pdf["record_kinds_json"]), ["parecer", "voto"])
            self.assertEqual(pdf["manifest_attempt_count"], "2")
            self.assertEqual(rows["error.html"]["content_eligible"], "false")
            self.assertEqual(rows["error.html"]["member_role"], "source_fetch_response")
            self.assertEqual(rows["manifesto.csv"]["member_role"], "archive_control_manifest")

            attempts = list(csv.DictReader((output_dir / "part016.fetch_attempts.csv").open(newline="")))
            self.assertEqual(len(attempts), 3)
            summary = json.loads((output_dir / "part016.index_summary.json").read_text())
            self.assertEqual(summary["member_count"], 3)
            self.assertEqual(summary["source_link_match_count"], 1)
            self.assertEqual(summary["source_link_unmatched_count"], 0)


if __name__ == "__main__":
    unittest.main()
