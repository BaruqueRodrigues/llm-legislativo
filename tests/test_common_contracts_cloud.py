"""Failure cases for the cloud eviction boundary; no network or real data."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/cloud_storage.py"
spec = importlib.util.spec_from_file_location("cloud_storage", MODULE_PATH)
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


class CloudStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        config = self.root / "config.json"
        values = json.loads((cloud.REPO / "configs/storage/drive.json").read_text())
        values["minimum_age_seconds"] = 0
        values["minimum_free_gib"] = 0
        config.write_text(json.dumps(values))
        self.store = cloud.Store(argparse.Namespace(data_root=str(self.root), config=str(config), rclone="fake"))
        self.payload = b"%PDF-test-preservation\n"
        self.sha = hashlib.sha256(self.payload).hexdigest()
        self.relative = f"raw/sha256/{self.sha[:2]}/{self.sha}.bin"
        self.path = self.root / self.relative
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(self.payload)
        self.remote = {}
        self.store.command = self.command
        self.store.stream = self.stream

    def stream(self, remote_path, destination=None, offset=0, count=None):
        content = self.remote[remote_path][offset:]
        if count is not None:
            content = content[:count]
        if destination is not None:
            destination.write(content)
        return hashlib.sha256(content).hexdigest(), len(content)

    def command(self, *args, capture=False):
        if args[0] == "copyto":
            content = Path(args[1]).read_bytes()
            if str(args[2]) in self.remote and self.remote[str(args[2])] != content:
                raise subprocess.CalledProcessError(1, args)
            self.remote[str(args[2])] = content
        elif args[0] == "cat":
            return subprocess.CompletedProcess(args, 0, stdout=self.remote[str(args[1])])
        else:
            self.fail("Unexpected command")
        return subprocess.CompletedProcess(args, 0)

    def archive(self, evict=True):
        self.store.archive_batch(self.store.candidates(), evict)

    def test_verified_archive_evict_and_restore_exact_bytes(self):
        self.archive()
        self.assertFalse(self.path.exists())
        receipt = self.store.receipt(self.relative)
        self.assertEqual(receipt["sha256"], self.sha)
        self.assertIn(receipt["manifest_remote"], self.remote)
        self.store.fetch(self.relative)
        self.assertEqual(self.path.read_bytes(), self.payload)

    def test_upload_or_check_failure_preserves_local_file(self):
        for failure in ("copyto", "stream"):
            with self.subTest(failure=failure):
                def fail(*args, capture=False):
                    if args[0] == failure:
                        raise subprocess.CalledProcessError(1, args)
                    return self.command(*args, capture=capture)
                self.store.command = fail
                if failure == "stream":
                    self.store.stream = lambda *a, **kw: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "cat"))
                with self.assertRaises(subprocess.CalledProcessError):
                    self.archive()
                self.assertTrue(self.path.exists())
                self.assertIsNone(self.store.receipt(self.relative))

    def test_corrupt_manifest_readback_prevents_eviction(self):
        def corrupt(*args, capture=False):
            result = self.command(*args, capture=capture)
            if args[0] == "cat":
                result.stdout = b"corrupted"
            return result
        self.store.command = corrupt
        with self.assertRaises(ValueError):
            self.archive()
        self.assertTrue(self.path.exists())
        self.assertIsNone(self.store.receipt(self.relative))

    def test_corrupt_restore_is_not_promoted(self):
        self.archive()
        self.remote[self.store.receipt(self.relative)["remote_path"]] = b"bad"
        with self.assertRaises(ValueError):
            self.store.fetch(self.relative)
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.glob("*.part")), [])

    def test_local_corruption_prevents_upload_and_eviction(self):
        self.path.write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            self.archive()
        self.assertTrue(self.path.exists())
        self.assertEqual(self.remote, {})

    def test_pin_and_partial_files_are_excluded(self):
        self.store.fetch(self.relative, pin=True)
        (self.path.parent / "partial.part").write_bytes(b"resume me")
        self.assertEqual(self.store.candidates(), [])
        self.assertTrue(self.path.exists())

    def test_restore_honors_free_disk_reserve(self):
        self.archive()
        with patch.object(cloud.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(1, 1, 0)):
            with self.assertRaises(RuntimeError):
                self.store.fetch(self.relative)
        self.assertFalse(self.path.exists())

    def test_paths_cannot_escape_root_or_follow_symlinks(self):
        with self.assertRaises(ValueError):
            self.store.blob_path("../../file")
        destination = self.root / "outside.bin"
        destination.write_bytes(self.payload)
        self.path.unlink()
        self.path.symlink_to(destination)
        with self.assertRaises(ValueError):
            self.store.blob_path(self.relative)

    def test_range_restore_from_multi_document_pack(self):
        other = b"another document at a distinct offset\n"
        other_sha = hashlib.sha256(other).hexdigest()
        relative = f"raw/sha256/{other_sha[:2]}/{other_sha}.bin"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(other)
        self.archive()
        self.assertFalse(path.exists())
        self.store.fetch(relative)
        self.assertEqual(path.read_bytes(), other)
        self.assertFalse(self.path.exists())

    def test_retry_reuses_identical_pack_and_manifest(self):
        self.archive(evict=False)
        remote_count = len(self.remote)
        self.archive()
        self.assertEqual(len(self.remote), remote_count)
        self.assertFalse(self.path.exists())

    def test_bounded_offload_does_not_exceed_budget(self):
        args = argparse.Namespace(all=False, max_gib=1 / cloud.GIB, evict=True)
        self.store.offload(args)
        self.assertTrue(self.path.exists())
        self.assertEqual(self.remote, {})
        args.max_gib = len(self.payload) / cloud.GIB
        self.store.offload(args)
        self.assertFalse(self.path.exists())

    def test_state_snapshot_preserves_originals_and_excludes_partials(self):
        directory = self.root / "staging/downloads"
        directory.mkdir(parents=True)
        state = directory / "state.csv"
        state.write_text("status\nverified\n")
        partial = directory / "download.part"
        partial.write_bytes(b"unfinished")
        self.store.backup_state()
        remote = next(k for k in self.remote if "/state_snapshots/" in k)
        with tarfile.open(fileobj=io.BytesIO(self.remote[remote]), mode="r:gz") as archive:
            self.assertEqual(archive.getnames(), ["staging/downloads/state.csv"])
        self.assertTrue(state.exists())
        self.assertTrue(partial.exists())
        self.assertEqual(list((self.store.state / "snapshots").glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
