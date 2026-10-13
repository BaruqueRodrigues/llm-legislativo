#!/usr/bin/env python3
"""Download a Drive object in resumable byte ranges using rclone cat."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_range(
    executable: str,
    remote: str,
    remote_path: str,
    folder_id: str,
    destination: Path,
    offset: int,
    source_offset: int,
    count: int,
    retries: int,
    shared_with_me: bool = False,
) -> None:
    command = [
        executable,
        "cat",
        f"{remote}:{remote_path}",
        "--offset",
        str(source_offset + offset),
        "--count",
        str(count),
        "--drive-root-folder-id",
        folder_id,
        "--retries",
        "3",
        "--low-level-retries",
        "10",
        "--log-level",
        "ERROR",
    ]
    if shared_with_me:
        command.extend(["--drive-shared-with-me"])
    for attempt in range(retries + 1):
        written = 0
        process = subprocess.Popen(command, stdout=subprocess.PIPE)
        try:
            with destination.open("r+b") as target:
                target.seek(offset)
                while True:
                    block = process.stdout.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > count:
                        raise ValueError("rclone returned more bytes than the requested range")
                    target.write(block)
                target.flush()
                os.fsync(target.fileno())
            return_code = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            with destination.open("r+b") as target:
                target.truncate(offset)
            raise
        if return_code == 0 and written == count:
            return
        with destination.open("r+b") as target:
            target.truncate(offset)
        if attempt == retries:
            raise RuntimeError(
                f"range failed at {offset}: expected {count} bytes, got {written}; "
                f"rclone exit={return_code}"
            )
        time.sleep(min(2**attempt, 30))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--remote-path", required=True)
    parser.add_argument("--drive-root-folder-id", required=True)
    parser.add_argument("--drive-shared-with-me", action="store_true")
    parser.add_argument("--size-bytes", required=True, type=int)
    parser.add_argument("--source-offset", type=int, default=0)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--rclone", required=True)
    parser.add_argument("--chunk-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--retries", type=int, default=4)
    args = parser.parse_args()
    if args.size_bytes <= 0 or args.chunk_bytes <= 0 or args.source_offset < 0:
        parser.error("size and chunk size must be positive, source offset non-negative")

    destination = args.destination
    partial = destination.with_name(destination.name + ".partial")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size != args.size_bytes:
            raise SystemExit(f"destination exists with unexpected size: {destination}")
        digest = sha256_file(destination)
        if args.expected_sha256 and digest != args.expected_sha256.lower():
            raise SystemExit(f"existing destination SHA-256 mismatch: {destination}")
        print(json.dumps({"status": "already_complete", "bytes": args.size_bytes, "sha256": digest}))
        return 0

    if not partial.exists():
        partial.touch()
    size = partial.stat().st_size
    if size > args.size_bytes:
        raise SystemExit(f"partial file exceeds expected size: {partial}")
    if size == args.size_bytes:
        offset = size
    else:
        offset = (size // args.chunk_bytes) * args.chunk_bytes
        if size != offset:
            with partial.open("r+b") as target:
                target.truncate(offset)

    while offset < args.size_bytes:
        count = min(args.chunk_bytes, args.size_bytes - offset)
        fetch_range(
            args.rclone,
            args.remote,
            args.remote_path,
            args.drive_root_folder_id,
            partial,
            offset,
            args.source_offset,
            count,
            args.retries,
            args.drive_shared_with_me,
        )
        offset += count
        print(
            json.dumps(
                {
                    "event": "range_download_progress",
                    "remote_path": args.remote_path,
                    "bytes": offset,
                    "expected_bytes": args.size_bytes,
                }
            ),
            flush=True,
        )

    actual_size = partial.stat().st_size
    if actual_size != args.size_bytes:
        raise SystemExit(f"download size mismatch: expected {args.size_bytes}, got {actual_size}")
    digest = sha256_file(partial)
    if args.expected_sha256 and digest != args.expected_sha256.lower():
        quarantine = partial.with_name(partial.name + ".sha256-mismatch")
        os.replace(partial, quarantine)
        raise SystemExit(
            f"download SHA-256 mismatch: expected {args.expected_sha256}, got {digest}; "
            f"bytes retained at {quarantine}"
        )
    os.replace(partial, destination)
    summary = {
        "status": "downloaded",
        "remote": args.remote,
        "remote_path": args.remote_path,
        "size_bytes": actual_size,
        "sha256": digest,
        "source_offset": args.source_offset,
        "chunk_bytes": args.chunk_bytes,
    }
    destination.with_name(destination.name + ".download.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
