#!/usr/bin/env python3
"""Add recognized archive-control members omitted from a Câmara member index."""

from __future__ import annotations

import argparse
import csv
import hashlib
import tarfile
from pathlib import Path, PurePosixPath


BASE_FIELDS = ("url", "sha256", "tar", "membro_tar", "offset_bytes", "tamanho", "status")
CONTROL_FIELDS = ("house", "content_eligible", "member_role")


def sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    while block := stream.read(8 * 1024 * 1024):
        digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("index", type=Path)
    parser.add_argument("--part", required=True)
    parser.add_argument("--archive-source-uri", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    with args.index.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        source_fields = list(reader.fieldnames or [])
        missing = set(BASE_FIELDS).difference(source_fields)
        if missing:
            raise ValueError(f"source index missing required columns: {sorted(missing)}")
        rows = [row for row in reader if row["tar"] == args.part]
    if not rows:
        raise ValueError(f"source index has no rows for {args.part}")
    indexed_names = {row["membro_tar"] for row in rows}
    if len(indexed_names) != len(rows):
        raise ValueError(f"source index has duplicate members for {args.part}")

    control_rows = []
    with tarfile.open(args.archive, "r:") as archive:
        regular_members = {member.name: member for member in archive.getmembers() if member.isfile()}
        extras = regular_members.keys() - indexed_names
        missing_members = indexed_names - regular_members.keys()
        if missing_members:
            raise ValueError(f"archive is missing indexed members: {len(missing_members)}")
        unknown = extras - {"manifesto.csv"}
        if unknown:
            raise ValueError(f"archive has unrecognized extra members: {sorted(unknown)[:10]}")
        for name in sorted(extras):
            member = regular_members[name]
            if name != "manifesto.csv" or PurePosixPath(name).parts != ("manifesto.csv",):
                raise ValueError(f"unrecognized control member: {name}")
            content = archive.extractfile(member)
            if content is None:
                raise ValueError(f"could not read control member: {name}")
            control_rows.append({
                "url": args.archive_source_uri.rstrip("/") + "#" + args.part,
                "sha256": sha256_stream(content),
                "tar": args.part,
                "membro_tar": member.name,
                "offset_bytes": str(member.offset_data),
                "tamanho": str(member.size),
                "status": "listado",
                "house": "camara",
                "content_eligible": "false",
                "member_role": "archive_control_manifest",
            })

    output_fields = source_fields + [field for field in CONTROL_FIELDS if field not in source_fields]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{Path(args.part).stem}.csv"
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(rows)
        writer.writerows(control_rows)
    print(f"indexed {len(rows)} source members and {len(control_rows)} archive control members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
