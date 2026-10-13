#!/usr/bin/env python3
"""Fetch and hash-check the Câmara-only supplement candidates from Drive packs."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def sniff_media_type(path: Path) -> str:
    with path.open("rb") as source:
        prefix = source.read(4096)
    if prefix.startswith(b"%PDF"):
        return "application/pdf"
    if prefix.startswith(b"{\\rtf"):
        return "application/rtf"
    if prefix.startswith(b"PK\x03\x04"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if prefix.startswith(b"\xd0\xcf\x11\xe0"):
        return "application/msword"
    sample = prefix.decode("latin-1", errors="replace").lower()
    if re.search(r"<!doctype\s+html|<html|<head(?:[\s>])|<meta(?:[\s>])|<body(?:[\s>])", sample):
        return "text/html"
    if sample.lstrip().startswith("<?xml"):
        return "application/xml"
    if prefix and all(byte in b"\t\n\r" or 0x20 <= byte <= 0x7E for byte in prefix):
        return "text/plain"
    return "application/octet-stream"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_one(
    row: dict,
    *,
    remote: str,
    folder_id: str,
    rclone: str,
    fetch_script: Path,
    destination_root: Path,
    chunk_bytes: int,
) -> dict:
    packed_remote = row["pack_remote_path"]
    prefix = f"{remote}:"
    if not packed_remote.startswith(prefix):
        raise ValueError(f"unexpected pack remote: {packed_remote}")
    remote_path = packed_remote[len(prefix):]
    digest = row["sha256"]
    destination = destination_root / digest[:2] / f"{digest}.bin"
    command = [
        sys.executable,
        str(fetch_script),
        "--remote",
        remote,
        "--remote-path",
        remote_path,
        "--drive-root-folder-id",
        folder_id,
        "--size-bytes",
        str(row["size_bytes"]),
        "--source-offset",
        str(row["pack_offset_bytes"]),
        "--expected-sha256",
        digest,
        "--destination",
        str(destination),
        "--rclone",
        rclone,
        "--chunk-bytes",
        str(chunk_bytes),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"fetch failed for {digest}: {completed.stderr[-1200:]}"
        )
    actual = sha256_file(destination)
    if actual != digest or destination.stat().st_size != row["size_bytes"]:
        raise ValueError(f"physical validation mismatch for {digest}")
    return {
        "sha256": digest,
        "size_bytes": row["size_bytes"],
        "public_path": f"raw/supplements/sha256/{digest[:2]}/{digest}.bin",
        "actual_sha256": actual,
        "detected_media_type": sniff_media_type(destination),
        "physical_sha256_verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--destination-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--public-manifest", required=True, type=Path)
    parser.add_argument("--remote", default="legislm_drive")
    parser.add_argument("--drive-folder-id", required=True)
    parser.add_argument("--rclone", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args()
    if args.workers < 1 or args.chunk_bytes < 1:
        parser.error("workers and chunk size must be positive")

    repo_root = Path(__file__).resolve().parents[2]
    fetch_script = Path(__file__).with_name("fetch_rclone_range.py")
    table = pq.read_table(args.catalog)
    rows = table.to_pylist()
    args.destination_root.mkdir(parents=True, exist_ok=True)
    results = {}
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_one,
                row,
                remote=args.remote,
                folder_id=args.drive_folder_id,
                rclone=args.rclone,
                fetch_script=fetch_script,
                destination_root=args.destination_root,
                chunk_bytes=args.chunk_bytes,
            ): row["sha256"]
            for row in rows
        }
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            digest = futures[future]
            try:
                results[digest] = future.result()
                print(
                    json.dumps(
                        {
                            "event": "supplement_verified",
                            "completed": index,
                            "total": len(rows),
                            "sha256": digest,
                            "bytes": results[digest]["size_bytes"],
                        }
                    ),
                    flush=True,
                )
            except Exception as error:
                failures.append({"sha256": digest, "error": str(error)})
                print(
                    json.dumps(
                        {
                            "event": "supplement_failed",
                            "completed": index,
                            "total": len(rows),
                            "sha256": digest,
                            "error": str(error),
                        }
                    ),
                    flush=True,
                )

    report = {
        "status": "verified" if not failures and len(results) == len(rows) else "incomplete",
        "candidate_count": len(rows),
        "verified_count": len(results),
        "verified_bytes": sum(item["size_bytes"] for item in results.values()),
        "failure_count": len(failures),
        "failures": failures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failures or len(results) != len(rows):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    by_hash = {row["sha256"]: row for row in rows}
    source_type = pa.struct(
        [
            pa.field("requested_url", pa.string()),
            pa.field("resolved_url", pa.string()),
            pa.field("http_status", pa.string()),
            pa.field("content_type", pa.string()),
            pa.field("status", pa.string()),
            pa.field("attempt_count", pa.string()),
            pa.field("record_key", pa.string()),
        ]
    )
    schema = pa.schema(
        [
            pa.field("sha256", pa.string(), nullable=False),
            pa.field("size_bytes", pa.int64(), nullable=False),
            pa.field("raw_path", pa.string(), nullable=False),
            pa.field("source_pack_sha256", pa.string(), nullable=False),
            pa.field("source_pack_offset_bytes", pa.int64(), nullable=False),
            pa.field("source_pack_size_bytes", pa.int64(), nullable=False),
            pa.field("source_records", pa.list_(source_type), nullable=False),
            pa.field("public_path", pa.string(), nullable=False),
            pa.field("actual_sha256", pa.string(), nullable=False),
            pa.field("detected_media_type", pa.string(), nullable=False),
            pa.field("physical_sha256_verified", pa.bool_(), nullable=False),
        ]
    )
    public_records = []
    for digest, result in sorted(results.items()):
        source = by_hash[digest]
        public_records.append(
            {
                "sha256": digest,
                "size_bytes": source["size_bytes"],
                "raw_path": source["raw_path"],
                "source_pack_sha256": source["pack_sha256"],
                "source_pack_offset_bytes": source["pack_offset_bytes"],
                "source_pack_size_bytes": source["pack_size_bytes"],
                "source_records": [
                    {key: value for key, value in item.items() if key != "source_ledger_path"}
                    for item in source["source_records"]
                ],
                **result,
            }
        )
    public_table = pa.Table.from_pylist(public_records, schema=schema)
    args.public_manifest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(public_table, args.public_manifest, compression="zstd", version="2.6")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
