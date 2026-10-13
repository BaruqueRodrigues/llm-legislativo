#!/usr/bin/env python3
"""Archive immutable blobs on Drive, verify bytes, then optionally evict locally.

Only raw/sha256/<prefix>/<sha256>.bin can be evicted. Download checkpoints,
partial files and annual CSVs remain local. Credentials belong to rclone's
private user configuration, never to this repository.
"""
import argparse
from collections import deque
import contextlib
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3
BLOB = re.compile(r"raw/sha256/([0-9a-f]{2})/([0-9a-f]{64})\.bin\Z")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        with temporary.open("x") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Store:
    def __init__(self, args):
        self.root = Path(args.data_root).expanduser().resolve()
        if not Path(args.data_root).expanduser().is_absolute():
            raise ValueError("DATA_ROOT precisa ser absoluto.")
        if self.root == REPO or REPO in self.root.parents or not self.root.is_dir():
            raise ValueError("DATA_ROOT precisa existir e ficar fora do checkout.")
        self.config = json.loads(Path(args.config).read_text())
        self.state = self.root / "staging/cloud_storage"
        bundled = REPO / ".venv/bin/rclone"
        self.executable = args.rclone or (str(bundled) if bundled.exists() else shutil.which("rclone"))
        self.remote = self.config["remote"] + ":" + self.config["remote_data_dir"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.config["remote"]):
            raise ValueError("Nome de remote inválido.")

    def argv(self, *args):
        if not self.executable:
            raise RuntimeError("rclone não instalado. Consulte docs/ARMAZENAMENTO_NUVEM.md.")
        return [self.executable, *map(str, args),
                "--drive-root-folder-id", self.config["folder_id"],
                "--retries", "3", "--low-level-retries", "10"]

    def command(self, *args, capture=False):
        return subprocess.run(self.argv(*args),
                              check=True, stdout=subprocess.PIPE if capture else None)

    def stream(self, remote_path, destination=None, offset=0, count=None):
        """Hash remote bytes with bounded RAM, optionally restoring one range."""
        args = ["cat", remote_path, "--offset", offset]
        if count is not None:
            args.extend(["--count", count])
        digest = hashlib.sha256()
        size = 0
        process = subprocess.Popen(self.argv(*args), stdout=subprocess.PIPE)
        try:
            for block in iter(lambda: process.stdout.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
                if count is not None and size > count:
                    raise ValueError("Resposta excede o intervalo solicitado.")
                if destination is not None:
                    destination.write(block)
            if process.wait() != 0:
                raise subprocess.CalledProcessError(process.returncode, args)
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
                process.wait()
        return digest.hexdigest(), size

    def blob_path(self, relative):
        match = BLOB.fullmatch(relative)
        if not match or match[1] != match[2][:2]:
            raise ValueError("Caminho não é um blob imutável canônico.")
        path = self.root / relative
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Symlinks não são permitidos no armazenamento de blobs.")
        return path, match[2]

    def receipt_path(self, relative):
        self.blob_path(relative)
        return self.state / "objects" / (relative + ".json")

    def pin_path(self, relative):
        self.blob_path(relative)
        return self.state / "pins" / (relative + ".pin")

    def receipt(self, relative):
        path = self.receipt_path(relative)
        if not path.exists():
            return None
        value = json.loads(path.read_text())
        _, expected = self.blob_path(relative)
        if (value.get("status") != "verified" or value.get("sha256") != expected
                or value.get("raw_path") != relative or value.get("folder_id") != self.config["folder_id"]
                or value.get("remote") != self.config["remote"] or value.get("size_bytes", 0) <= 0
                or value.get("storage_kind") != "pack_v1"
                or value.get("verification") != "sha256_remote_stream"
                or not re.fullmatch(re.escape(self.remote) + r"/packs/[0-9a-f]{64}\.pack", value.get("remote_path", ""))
                or not isinstance(value.get("offset_bytes"), int) or value["offset_bytes"] < 0):
            raise ValueError("Recibo inválido: " + relative)
        return value

    @contextlib.contextmanager
    def lock(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "storage.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Outra operação de armazenamento está em andamento.")
            yield

    def candidates(self):
        result = []
        for path in (self.root / "raw/sha256").glob("*/*.bin"):
            relative = path.relative_to(self.root).as_posix()
            self.blob_path(relative)
            stat = path.stat()
            if (stat.st_size > 0 and time.time() - stat.st_mtime >= self.config["minimum_age_seconds"]
                    and not self.pin_path(relative).exists()):
                result.append((stat.st_mtime, relative, stat.st_size))
        return sorted(result)

    def status(self):
        candidates = self.candidates()
        receipts = list((self.state / "objects").glob("raw/sha256/*/*.bin.json"))
        archived = sum(1 for p in receipts if not (self.root / p.relative_to(self.state / "objects").as_posix()[:-5]).exists())
        print(json.dumps({"local_eligible_files": len(candidates),
                          "local_eligible_gib": round(sum(x[2] for x in candidates) / GIB, 3),
                          "verified_receipts": len(receipts), "archived_only_files": archived,
                          "free_gib": round(shutil.disk_usage(self.root).free / GIB, 3),
                          "folder_id": self.config["folder_id"]}, indent=2), flush=True)

    def offload(self, args):
        total = 0
        candidates = deque(self.candidates())
        limit = math.inf if args.all else args.max_gib * GIB
        while candidates and total < limit:
            batch = []
            size = 0
            while candidates:
                item = candidates[0]
                if size + item[2] > min(self.config["batch_gib"] * GIB, limit - total):
                    if not batch:
                        if item[2] > self.config["batch_gib"] * GIB:
                            raise RuntimeError("Blob excede batch_gib. Aumente o lote em configs/storage/drive.json.")
                        # A bounded invocation must stop normally at its byte budget.
                        self.status()
                        return
                    break
                candidates.popleft()
                batch.append(item)
                size += item[2]
            self.archive_batch(batch, args.evict)
            total += size
            print(json.dumps({"event": "batch_complete", "processed_gib": round(total / GIB, 3),
                              "free_gib": round(shutil.disk_usage(self.root).free / GIB, 3)}), flush=True)
        self.status()

    def archive_batch(self, batch, evict):
        batch_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
        directory = self.state / "batches" / batch_id
        directory.mkdir(parents=True)
        pack_path = directory / "pack.part"
        try:
            self.publish_pack(batch, evict, batch_id, directory, pack_path)
        finally:
            # Original blobs remain intact until publication; scratch can always go.
            pack_path.unlink(missing_ok=True)

    def publish_pack(self, batch, evict, batch_id, directory, pack_path):
        total_bytes = sum(item[2] for item in batch)
        if shutil.disk_usage(self.root).free < total_bytes + self.config["minimum_free_gib"] * GIB:
            raise RuntimeError("Espaço insuficiente para montar o pacote mantendo a reserva.")
        manifest_path = directory / "manifest.json"
        records = []
        pack_digest = hashlib.sha256()
        with pack_path.open("xb") as output:
            for _, relative, size in batch:
                path, expected = self.blob_path(relative)
                offset = output.tell()
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                        pack_digest.update(block)
                        output.write(block)
                if output.tell() - offset != size or digest.hexdigest() != expected:
                    raise ValueError("Blob local corrompido ou alterado: " + relative)
                records.append({"raw_path": relative, "sha256": expected, "size_bytes": size,
                                "offset_bytes": offset})
            output.flush()
            os.fsync(output.fileno())
        pack_hash = pack_digest.hexdigest()
        pack_remote = self.remote + "/packs/" + pack_hash + ".pack"
        manifest_remote = self.remote + "/manifests/cloud/" + pack_hash + ".json"
        print(json.dumps({"event": "upload", "batch_id": batch_id, "files": len(records),
                          "gib": round(total_bytes / GIB, 3)}), flush=True)
        self.command("copyto", pack_path, pack_remote, "--checksum", "--immutable",
                     "--stats", "30s", "--stats-one-line", "--stats-log-level", "NOTICE",
                     "--log-level", "NOTICE")
        print(json.dumps({"event": "verify_remote", "batch_id": batch_id}), flush=True)
        remote_hash, remote_size = self.stream(pack_remote)
        if remote_hash != pack_hash or remote_size != total_bytes:
            raise ValueError("Pacote remoto não passou na releitura SHA-256/tamanho.")
        atomic_json(manifest_path, {"version": 1,
                    "folder_id": self.config["folder_id"], "storage_kind": "pack_v1",
                    "pack_sha256": pack_hash, "pack_size_bytes": total_bytes,
                    "remote_path": pack_remote, "verification": "sha256_remote_stream", "files": records})
        manifest_hash = sha256(manifest_path)
        self.command("copyto", manifest_path, manifest_remote, "--checksum", "--immutable")
        remote_manifest = self.command("cat", manifest_remote, capture=True).stdout
        if hashlib.sha256(remote_manifest).hexdigest() != manifest_hash:
            raise ValueError("Manifesto remoto não passou na releitura SHA-256.")
        evicted_bytes = 0
        for record in records:
            relative = record["raw_path"]
            receipt = dict(record, status="verified", remote=self.config["remote"],
                           folder_id=self.config["folder_id"], remote_path=pack_remote,
                           storage_kind="pack_v1", verification="sha256_remote_stream", verified_at=now(),
                           manifest_remote=manifest_remote, manifest_sha256=manifest_hash)
            atomic_json(self.receipt_path(relative), receipt)
            # Publish the receipt before deleting, so a crash cannot lose the location.
            path, expected = self.blob_path(relative)
            if evict and not self.pin_path(relative).exists():
                if path.stat().st_size != record["size_bytes"] or sha256(path) != expected:
                    raise ValueError("Blob mudou durante o upload: " + relative)
                path.unlink()
                evicted_bytes += record["size_bytes"]
        print(json.dumps({"event": "verified", "batch_id": batch_id,
                          "pack_sha256": pack_hash, "evicted_bytes": evicted_bytes}), flush=True)

    def fetch(self, relative, pin=False):
        path, expected = self.blob_path(relative)
        receipt = self.receipt(relative)
        if path.exists():
            if sha256(path) != expected:
                raise ValueError("Blob local corrompido: " + relative)
        else:
            if receipt is None:
                raise ValueError("Não há recibo verificado para este blob.")
            size = receipt["size_bytes"]
            if shutil.disk_usage(self.root).free < size + self.config["minimum_free_gib"] * GIB:
                raise RuntimeError("Espaço insuficiente para recuperar o blob mantendo a reserva.")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".restore." + uuid.uuid4().hex + ".part")
            try:
                with temporary.open("xb") as target:
                    restored_hash, restored_size = self.stream(receipt["remote_path"], target,
                                                              receipt["offset_bytes"], size)
                    target.flush()
                    os.fsync(target.fileno())
                if restored_size != size or restored_hash != expected:
                    raise ValueError("Falha de SHA-256/tamanho ao recuperar " + relative)
                os.replace(temporary, path)
                os.utime(path, None)
            finally:
                temporary.unlink(missing_ok=True)
        if pin:
            target = self.pin_path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        print(path, flush=True)

    def backup_state(self):
        """Snapshot inventory and resume metadata; partial payloads stay local."""
        allowed = {".csv", ".rds", ".parquet", ".json", ".jsonl", ".txt", ".yaml", ".yml"}
        sources = []
        for directory in ("raw/camara", "raw/snapshots", "staging"):
            for path in (self.root / directory).rglob("*"):
                if (path.is_file() and not path.is_symlink() and path.suffix.lower() in allowed
                        and not path.name.startswith(".") and self.state not in path.parents
                        and path.resolve() == path):
                    sources.append(path)
        total = sum(path.stat().st_size for path in sources)
        if shutil.disk_usage(self.root).free < total + self.config["minimum_free_gib"] * GIB:
            raise RuntimeError("Espaço insuficiente para snapshot de estado.")
        snapshots = self.state / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        target = snapshots / (uuid.uuid4().hex + ".tar.gz.part")
        try:
            with tarfile.open(target, "w:gz", compresslevel=1) as archive:
                for path in sorted(sources):
                    archive.add(path, arcname=path.relative_to(self.root).as_posix(), recursive=False)
            expected = sha256(target)
            remote = self.remote + "/state_snapshots/" + expected + ".tar.gz"
            self.command("copyto", target, remote, "--checksum", "--immutable")
            actual, size = self.stream(remote)
            if actual != expected or size != target.stat().st_size:
                raise ValueError("Snapshot de estado falhou na releitura remota.")
            atomic_json(snapshots / (expected + ".json"),
                        {"status": "verified", "sha256": expected, "remote_path": remote,
                         "size_bytes": size, "file_count": len(sources), "verified_at": now()})
            print(json.dumps({"event": "state_snapshot_verified", "remote_path": remote,
                              "file_count": len(sources), "size_bytes": size}), flush=True)
        finally:
            target.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=os.environ.get("DATA_ROOT"))
    parser.add_argument("--config", default=str(REPO / "configs/storage/drive.json"))
    parser.add_argument("--rclone")
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("status")
    sub.add_parser("backup-state")
    archive = sub.add_parser("offload")
    archive.add_argument("--max-gib", type=float, default=2)
    archive.add_argument("--all", action="store_true")
    archive.add_argument("--evict", action="store_true", help="Remove somente após cópia e verificação remota")
    fetch = sub.add_parser("fetch")
    fetch.add_argument("raw_path")
    fetch.add_argument("--pin", action="store_true", help="Protege o blob até executar unpin")
    release = sub.add_parser("unpin")
    release.add_argument("raw_path")
    args = parser.parse_args()
    if not args.data_root:
        parser.error("Informe DATA_ROOT ou --data-root.")
    if args.operation == "offload" and (not math.isfinite(args.max_gib) or args.max_gib <= 0):
        parser.error("--max-gib deve ser positivo e finito.")
    store = Store(args)
    if args.operation == "status":
        store.status()
        return
    with store.lock():
        if args.operation == "offload":
            store.offload(args)
        elif args.operation == "fetch":
            store.fetch(args.raw_path, args.pin)
        elif args.operation == "backup-state":
            store.backup_state()
        else:
            store.pin_path(args.raw_path).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print("cloud_storage: " + str(error), file=sys.stderr)
        sys.exit(1)
