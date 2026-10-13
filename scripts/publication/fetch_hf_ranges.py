#!/usr/bin/env python3
"""Resume a public Hugging Face file download using validated HTTP ranges."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path


def fetch_range(url: str, destination: Path, start: int, end: int, size: int) -> None:
    expected_range = f"bytes {start}-{end}/{size}"
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(request, timeout=180) as response:
                if response.status != 206 or response.headers.get("Content-Range") != expected_range:
                    raise RuntimeError(
                        f"unexpected range response for {start}-{end}: "
                        f"status={response.status}, content_range={response.headers.get('Content-Range')}"
                    )
                payload = response.read()
            if len(payload) != end - start + 1:
                raise RuntimeError(f"short range body for {start}-{end}: {len(payload)} bytes")
            with destination.open("r+b") as output:
                output.seek(start)
                output.write(payload)
            return
        except Exception as error:
            last_error = error
            if attempt < 4:
                time.sleep(2**attempt)
    raise RuntimeError(f"range {start}-{end} failed after retries: {last_error}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--size-bytes", required=True, type=int)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--chunk-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--resume-prefix-bytes", type=int, default=0)
    args = parser.parse_args()
    if args.size_bytes < 1 or args.chunk_bytes < 1 or args.workers < 1:
        parser.error("size, chunk size, and worker count must be positive")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    existing = min(args.resume_prefix_bytes, args.size_bytes)
    if args.resume_prefix_bytes < 0 or args.resume_prefix_bytes > args.size_bytes:
        raise RuntimeError("partial file exceeds expected archive size")
    state_path = args.destination.with_name(args.destination.name + ".ranges.json")
    identity = {"url": args.url, "size_bytes": args.size_bytes, "sha256": args.sha256, "chunk_bytes": args.chunk_bytes}
    state = json.loads(state_path.read_text()) if state_path.exists() else {**identity, "completed": {}}
    if any(state.get(key) != value for key, value in identity.items()):
        raise RuntimeError("range checkpoint belongs to a different source or chunk layout")
    with args.destination.open("a+b") as output:
        output.truncate(args.size_bytes)
    ranges = []
    for start in range(0, args.size_bytes, args.chunk_bytes):
        end = min(args.size_bytes - 1, start + args.chunk_bytes - 1)
        range_id = str(start)
        known_hash = state["completed"].get(range_id)
        if known_hash:
            with args.destination.open("rb") as source:
                source.seek(start)
                payload = source.read(end - start + 1)
            if hashlib.sha256(payload).hexdigest() == known_hash:
                continue
            del state["completed"][range_id]
        if end + 1 <= existing:
            with args.destination.open("rb") as source:
                payload = source.read(end - start + 1)
            state["completed"][range_id] = hashlib.sha256(payload).hexdigest()
            continue
        ranges.append((start, end))
    print(json.dumps({"event": "range_download_start", "existing_prefix_bytes": existing, "ranges_to_fetch": len(ranges), "workers": args.workers}), flush=True)
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(fetch_range, args.url, args.destination, start, end, args.size_bytes) for start, end in ranges]
        for future in concurrent.futures.as_completed(futures):
            future.result()
            # Record verified completed ranges atomically so a restart can skip them.
            start, end = next(item for item, submitted in zip(ranges, futures) if submitted is future)
            with args.destination.open("rb") as source:
                source.seek(start)
                payload = source.read(end - start + 1)
            state["completed"][str(start)] = hashlib.sha256(payload).hexdigest()
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.destination.parent, delete=False) as temporary:
                json.dump(state, temporary, sort_keys=True)
                temporary.write("\n")
                temp_name = temporary.name
            os.replace(temp_name, state_path)
            completed += 1
            if completed % 8 == 0 or completed == len(ranges):
                print(json.dumps({"event": "range_download_progress", "completed_ranges": completed, "total_ranges": len(ranges)}), flush=True)
    actual_sha = sha256_file(args.destination)
    if actual_sha != args.sha256:
        raise RuntimeError(f"archive SHA-256 mismatch: expected {args.sha256}, got {actual_sha}")
    print(json.dumps({"event": "archive_verified", "size_bytes": args.destination.stat().st_size, "sha256": actual_sha}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
