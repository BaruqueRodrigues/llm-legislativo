#!/usr/bin/env python3
"""Verify one Câmara TAR against processo_hiago/indice_tar2.csv."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath


COLUMNS = (
    "url",
    "sha256",
    "tar",
    "membro_tar",
    "offset_bytes",
    "tamanho",
    "status",
)
REQUIRED_COLUMNS = set(COLUMNS)


def sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("index", type=Path)
    parser.add_argument("--part", required=True, help="TAR filename used in the index")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    rows = []
    with args.index.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        source_fields = list(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS.difference(source_fields)
        if missing:
            raise SystemExit(f"index is missing columns: {sorted(missing)}")
        output_fields = list(COLUMNS) + [field for field in source_fields if field not in COLUMNS]
        rows = [row for row in reader if row["tar"] == args.part]
    if not rows:
        raise SystemExit(f"no index rows for {args.part}")
    if any(row["status"] != "listado" for row in rows):
        raise SystemExit("TAR index contains rows that are not listed")

    expected = {}
    for row in rows:
        name = row["membro_tar"]
        if name in expected:
            raise SystemExit(f"duplicate indexed member: {name}")
        expected[name] = row

    with tarfile.open(args.archive, mode="r:") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        duplicate_names = [name for name, count in Counter(names).items() if count > 1]
        if duplicate_names:
            raise SystemExit(f"duplicate TAR member names: {duplicate_names[:10]}")
        regular = {}
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit(f"unsafe TAR member path: {member.name}")
            if member.isfile():
                regular[member.name] = member
            elif not member.isdir():
                raise SystemExit(f"unsupported TAR member type: {member.name}")

        missing_members = expected.keys() - regular.keys()
        extra_members = regular.keys() - expected.keys()
        if missing_members or extra_members:
            raise SystemExit(
                "member set differs from index: "
                f"missing={len(missing_members)}, extra={len(extra_members)}"
            )

        for i, (name, row) in enumerate(expected.items(), start=1):
            member = regular[name]
            if member.size != int(row["tamanho"]):
                raise SystemExit(f"size mismatch for {name}")
            if member.offset_data != int(row["offset_bytes"]):
                raise SystemExit(f"offset mismatch for {name}")
            with archive.extractfile(member) as content:
                observed = sha256_stream(content)
            if observed != row["sha256"].lower():
                raise SystemExit(f"SHA-256 mismatch for {name}")
            if i % 10000 == 0:
                print(f"verified {i}/{len(expected)} members", flush=True)

    archive_digest = hashlib.sha256()
    with args.archive.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            archive_digest.update(chunk)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    archive_key = Path(args.part).stem
    manifest_path = args.output_dir / f"{archive_key}.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "archive": args.part,
        "archive_bytes": args.archive.stat().st_size,
        "archive_sha256": archive_digest.hexdigest(),
        "indexed_members": len(expected),
        "verified_members": len(expected),
        "manifest": manifest_path.name,
        "status": "verified",
    }
    summary_path = args.output_dir / f"{archive_key}.verification.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
