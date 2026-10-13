import csv
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "publication" / "process_archive_pdfs.py"


FAKE_RSCRIPT = r'''#!/usr/bin/env python3
import fcntl
import json
import os
import sys
import time
from pathlib import Path

if "-e" in sys.argv:
    raise SystemExit(0)  # Shared Swift preflight warm-up.

def option(name):
    return Path(sys.argv[sys.argv.index(name) + 1])

state_path = Path(os.environ["FAKE_RSCRIPT_STATE"])
lock_path = state_path.with_suffix(".lock")
with lock_path.open("a+") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "active": 0, "max_active": 0, "invocations": 0
    }
    state["active"] += 1
    state["max_active"] = max(state["max_active"], state["active"])
    state["invocations"] += 1
    state_path.write_text(json.dumps(state))

time.sleep(0.3)
output = option("--output-dir")
output.mkdir(parents=True, exist_ok=True)
(output / "extraction_manifest.json").write_text(json.dumps({
    "summary": {"fake": True}, "files": {}
}))

with lock_path.open("a+") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    state = json.loads(state_path.read_text())
    state["active"] -= 1
    state_path.write_text(json.dumps(state))
'''


class TestProcessArchivePDFs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.archive = self.root / "part001.tar"
        self.index = self.root / "indice.csv"
        self.fake_rscript = self.root / "fake-rscript"
        self.fake_rscript.write_text(FAKE_RSCRIPT, encoding="utf-8")
        self.fake_rscript.chmod(0o755)
        self.state = self.root / "worker-state.json"
        self._make_archive_and_index()

    def tearDown(self):
        self.tmp.cleanup()

    def _make_archive_and_index(self):
        rows = []
        with tarfile.open(self.archive, "w") as tar:
            for i in range(5):
                name = f"docs/doc-{i}.pdf"
                payload = f"%PDF-1.7 fake document {i}".encode()
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                import io

                tar.addfile(info, io.BytesIO(payload))
                rows.append({
                    "tar": self.archive.name,
                    "membro_tar": name,
                    "status": "listado",
                    "url": f"https://example.invalid/{i}",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "tamanho": str(len(payload)),
                })
        with self.index.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def _run(self, data_root: Path, workers: int):
        env = os.environ.copy()
        env["FAKE_RSCRIPT_STATE"] = str(self.state)
        subprocess.run(
            [
                os.fspath(Path(os.sys.executable)),
                os.fspath(SCRIPT),
                "--archive", str(self.archive),
                "--expected-archive-sha256", hashlib.sha256(self.archive.read_bytes()).hexdigest(),
                "--index", str(self.index),
                "--repo-root", str(self.repo),
                "--data-root", str(data_root),
                "--rscript", str(self.fake_rscript),
                "--batch-size", "2",
                "--workers", str(workers),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_workers_run_batches_concurrently_and_checkpoint_resumes(self):
        data_root = self.root / "data"
        self._run(data_root, workers=2)

        output = data_root / "staging" / "extraction" / "part001-batched"
        checkpoint = json.loads((output / "checkpoint.json").read_text())
        state = json.loads(self.state.read_text())
        self.assertEqual(checkpoint["completed_batches"], [1, 2, 3])
        self.assertEqual(checkpoint["processed_pdf_count"], 5)
        self.assertEqual(checkpoint["status"], "pdf_extraction_complete_non_pdf_pending")
        self.assertEqual(state["max_active"], 2)
        self.assertEqual(state["active"], 0)
        self.assertTrue((output / "COMPLETE.json").exists())
        self.assertFalse((output / ".process.lock").exists())

        self._run(data_root, workers=3)
        state_after_resume = json.loads(self.state.read_text())
        self.assertEqual(state_after_resume["invocations"], 3)
        self.assertEqual(state_after_resume["max_active"], 2)


if __name__ == "__main__":
    unittest.main()
