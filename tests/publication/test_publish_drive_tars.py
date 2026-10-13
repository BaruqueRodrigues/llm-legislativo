import hashlib
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.publication.publish_drive_tars import (
    list_drive_sizes,
    prefetched_archives,
    run_overlapped,
    ensure_senado_release_manifest,
    validate_extraction_workers,
    verify_public_tree,
)
from scripts.publication.process_archive_pdfs import validate_workers


class TestPrefetchedArchives(unittest.TestCase):
    def test_starts_only_one_following_archive_before_yielding_current(self):
        started = []
        lock = threading.Lock()
        second_started = threading.Event()

        def download(part):
            with lock:
                started.append(part)
            if part == 2:
                second_started.set()
            return Path(f"part{part:03d}.tar")

        pipeline = prefetched_archives(range(1, 4), download, prefetch_count=1)
        self.assertEqual(next(pipeline), (1, Path("part001.tar")))
        self.assertTrue(second_started.wait(timeout=2))
        self.assertEqual(sorted(started), [1, 2])
        self.assertEqual(next(pipeline), (2, Path("part002.tar")))
        self.assertEqual(next(pipeline), (3, Path("part003.tar")))
        with self.assertRaises(StopIteration):
            next(pipeline)

    def test_disabling_prefetch_does_not_start_next_archive_early(self):
        started = []

        def download(part):
            started.append(part)
            return Path(f"part{part:03d}.tar")

        pipeline = prefetched_archives(range(1, 3), download, prefetch_count=0)
        self.assertEqual(next(pipeline), (1, Path("part001.tar")))
        self.assertEqual(started, [1])
        self.assertEqual(next(pipeline), (2, Path("part002.tar")))
        self.assertEqual(started, [1, 2])

    def test_two_downloads_can_be_in_flight_at_once(self):
        active = 0
        peak = 0
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def download(part):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            if part in (1, 2):
                barrier.wait(timeout=2)
            with lock:
                active -= 1
            return Path(f"part{part:03d}.tar")

        pipeline = prefetched_archives(range(1, 4), download, prefetch_count=2)
        self.assertEqual(next(pipeline), (1, Path("part001.tar")))
        self.assertEqual(peak, 2)
        self.assertEqual(next(pipeline), (2, Path("part002.tar")))
        self.assertEqual(next(pipeline), (3, Path("part003.tar")))


class TestOverlappedPublication(unittest.TestCase):
    def test_raw_upload_and_extraction_run_concurrently(self):
        barrier = threading.Barrier(2)

        def task(value):
            barrier.wait(timeout=2)
            return value

        self.assertEqual(
            run_overlapped(lambda: task("raw"), lambda: task("extraction")),
            ("raw", "extraction"),
        )


class TestWorkerLimits(unittest.TestCase):
    def test_both_pipeline_layers_accept_eight_workers_and_reject_nine(self):
        for validate in (validate_extraction_workers, validate_workers):
            self.assertIsNone(validate(8))
            with self.assertRaises(ValueError):
                validate(9)
            with self.assertRaises(ValueError):
                validate(0)


class TestSenadoReleaseManifest(unittest.TestCase):
    def test_initializes_once_and_preserves_progress_on_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release_manifest.json"
            ensure_senado_release_manifest(path, "senate-folder")
            initial = path.read_text()
            self.assertIn('"source_archive_count_expected": 16', initial)
            path.write_text(initial.replace('"status": "pending"', '"status": "partial"'))
            ensure_senado_release_manifest(path, "different-folder")
            self.assertIn('"status": "partial"', path.read_text())
            self.assertIn("senate-folder", path.read_text())


class TestDriveSourceSelection(unittest.TestCase):
    def test_lists_requested_tar_under_shared_drive_prefix(self):
        result = SimpleNamespace(
            stdout="7056701440 2026-10-09 06:38:30.879000000 part023.tar\n"
        )
        with patch(
            "scripts.publication.publish_drive_tars.subprocess.run",
            return_value=result,
        ) as run_command:
            sizes = list_drive_sizes(
                "rclone",
                "legislm_drive",
                "folder-id",
                range(23, 24),
                remote_prefix="backup",
                shared_with_me=True,
            )
        self.assertEqual(sizes, {"part023.tar": 7056701440})
        self.assertIn("--drive-shared-with-me", run_command.call_args.args[0])
        self.assertIn("legislm_drive:backup", run_command.call_args.args[0])

    def test_rejects_missing_requested_tar(self):
        with patch(
            "scripts.publication.publish_drive_tars.subprocess.run",
            return_value=SimpleNamespace(stdout=""),
        ):
            with self.assertRaisesRegex(RuntimeError, "missing=.*part023.tar"):
                list_drive_sizes(
                    "rclone",
                    "legislm_drive",
                    "folder-id",
                    range(23, 24),
                    remote_prefix="backup",
                    shared_with_me=True,
                )

    def test_collapses_same_size_duplicate_drive_entries(self):
        listing = SimpleNamespace(
            stdout=(
                "7056701440 2026-10-09 06:38:30.879000000 backup/part023.tar\n"
                "7056701440 2026-10-09 06:38:30.879000000 part023.tar\n"
            )
        )
        with patch(
            "scripts.publication.publish_drive_tars.subprocess.run",
            return_value=listing,
        ):
            self.assertEqual(
                list_drive_sizes(
                    "rclone", "legislm_drive", "folder-id", range(23, 24),
                    remote_prefix="backup", shared_with_me=True,
                ),
                {"part023.tar": 7056701440},
            )

    def test_rejects_duplicate_drive_entries_with_conflicting_sizes(self):
        listing = SimpleNamespace(
            stdout=(
                "7056701440 2026-10-09 06:38:30.879000000 backup/part023.tar\n"
                "7056701441 2026-10-09 06:38:30.879000000 part023.tar\n"
            )
        )
        with patch(
            "scripts.publication.publish_drive_tars.subprocess.run",
            return_value=listing,
        ):
            with self.assertRaisesRegex(RuntimeError, "conflicting sizes"):
                list_drive_sizes(
                    "rclone", "legislm_drive", "folder-id", range(23, 24),
                    remote_prefix="backup", shared_with_me=True,
                )


class TestPublicTreeVerification(unittest.TestCase):
    def test_checks_uploaded_files_and_public_completion_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b"parquet bytes"
            (root / "part.parquet").write_bytes(payload)
            complete = b'{"status":"complete"}\n'
            (root / "COMPLETE.json").write_bytes(complete)
            siblings = [
                SimpleNamespace(
                    rfilename=f"extraction/part009/{name}",
                    size=len(content),
                    lfs=SimpleNamespace(sha256=hashlib.sha256(content).hexdigest()),
                )
                for name, content in (
                    ("part.parquet", payload),
                    ("COMPLETE.json", complete),
                )
            ]
            api = SimpleNamespace(
                repo_info=lambda *args, **kwargs: SimpleNamespace(
                    private=False, siblings=siblings, sha="revision123"
                )
            )
            response = SimpleNamespace(read=lambda: complete)
            with patch(
                "scripts.publication.publish_drive_tars.urllib.request.urlopen",
                return_value=nullcontext(response),
            ):
                revision = verify_public_tree(api, "owner/dataset", "extraction/part009", root)
            self.assertEqual(revision, "revision123")

    def test_rejects_public_file_with_wrong_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b"expected bytes"
            (root / "part.parquet").write_bytes(payload)
            sibling = SimpleNamespace(
                rfilename="extraction/part009/part.parquet",
                size=len(payload),
                lfs=SimpleNamespace(sha256="0" * 64),
            )
            api = SimpleNamespace(
                repo_info=lambda *args, **kwargs: SimpleNamespace(
                    private=False, siblings=[sibling], sha="revision123"
                )
            )
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                verify_public_tree(api, "owner/dataset", "extraction/part009", root)


if __name__ == "__main__":
    unittest.main()
