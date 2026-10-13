import csv
import hashlib
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/publication/complete_camara_tar_index.py"


class TestCompleteCamaraTarIndex(unittest.TestCase):
    def test_adds_manifesto_as_hashed_control_member_and_rejects_other_extras(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "part043.tar"
            index = root / "index.csv"
            output = root / "manifests"
            pdf = b"%PDF-1.7 synthetic"
            manifesto = b"file,url,status\n"
            with tarfile.open(archive, "w") as tar:
                for name, payload in (("doc.pdf", pdf), ("manifesto.csv", manifesto)):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
            with index.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=("url", "sha256", "tar", "membro_tar", "offset_bytes", "tamanho", "status"))
                writer.writeheader()
                writer.writerow({"url": "https://example/doc.pdf", "sha256": hashlib.sha256(pdf).hexdigest(),
                                 "tar": "part043.tar", "membro_tar": "doc.pdf", "offset_bytes": "512",
                                 "tamanho": len(pdf), "status": "listado"})
            subprocess.run([sys.executable, str(SCRIPT), str(archive), str(index), "--part", "part043.tar",
                            "--archive-source-uri", "https://drive.google.com/drive/folders/example",
                            "--output-dir", str(output)], check=True, capture_output=True, text=True)
            with (output / "part043.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            control = next(row for row in rows if row["membro_tar"] == "manifesto.csv")
            self.assertEqual(control["sha256"], hashlib.sha256(manifesto).hexdigest())
            self.assertEqual(control["content_eligible"], "false")
            self.assertEqual(control["member_role"], "archive_control_manifest")

            bad_archive = root / "part043-bad.tar"
            with tarfile.open(bad_archive, "w") as tar:
                for name, payload in (("doc.pdf", pdf), ("unexpected.bin", b"x")):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
            result = subprocess.run([sys.executable, str(SCRIPT), str(bad_archive), str(index), "--part", "part043.tar",
                                     "--archive-source-uri", "https://example", "--output-dir", str(root / "bad")],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unrecognized extra members", result.stderr)


if __name__ == "__main__":
    unittest.main()
