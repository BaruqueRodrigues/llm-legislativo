#!/usr/bin/env python3
"""Build the Câmara-only candidate catalog for verified raw supplements."""

from __future__ import annotations

import argparse
import csv
import json
import tarfile
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


SOURCE_LEDGER_PREFIX = "staging/downloads/camara_annual_csv/"
VALID_STATUSES = {"verified", "resumed_verified", "reused_verified"}
SOURCE_FIELDS = (
    "requested_url",
    "resolved_url",
    "http_status",
    "content_type",
    "status",
    "attempt_count",
    "record_key",
    "source_ledger_path",
)


def read_received_hashes(path: Path) -> set[str]:
    received = set()
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if row.get("status") == "listado":
                received.add(row["sha256"].strip().lower())
    return received


def read_camara_ledger_rows(snapshot: Path) -> tuple[list[dict], set[str]]:
    rows = []
    ledger_hashes = set()
    with tarfile.open(snapshot, mode="r:gz") as archive:
        ledgers = [
            member
            for member in archive.getmembers()
            if member.name.startswith(SOURCE_LEDGER_PREFIX)
            and member.name.endswith("/ledger.csv")
        ]
        for member in ledgers:
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"cannot read ledger: {member.name}")
            reader = csv.DictReader(
                line.decode("utf-8-sig") for line in stream
            )
            for row in reader:
                digest = (row.get("sha256") or "").strip().lower()
                status = (row.get("status") or "").strip()
                if not digest:
                    continue
                ledger_hashes.add(digest)
                if status not in VALID_STATUSES:
                    continue
                row["sha256"] = digest
                row["source_ledger_path"] = member.name
                rows.append(row)
    return rows, ledger_hashes


def read_pack_manifests(directory: Path) -> dict[str, dict]:
    entries: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(directory.glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        pack_hash = manifest["pack_sha256"]
        if manifest.get("storage_kind") != "pack_v1":
            raise ValueError(f"unsupported storage kind in {path.name}")
        if not manifest["remote_path"].endswith(f"/{pack_hash}.pack"):
            raise ValueError(f"pack path/hash mismatch in {path.name}")
        pack_size = int(manifest["pack_size_bytes"])
        for item in manifest["files"]:
            digest = item["sha256"].lower()
            offset = int(item["offset_bytes"])
            size = int(item["size_bytes"])
            if offset < 0 or size <= 0 or offset + size > pack_size:
                raise ValueError(f"invalid byte range for SHA-256 {digest} in {path.name}")
            entries[digest].append(
                {
                    "raw_path": item["raw_path"],
                    "size_bytes": size,
                    "pack_remote_path": manifest["remote_path"],
                    "pack_sha256": pack_hash,
                    "pack_size_bytes": pack_size,
                    "pack_offset_bytes": offset,
                }
            )

    result = {}
    for digest, candidates in entries.items():
        sizes = {candidate["size_bytes"] for candidate in candidates}
        raw_paths = {candidate["raw_path"] for candidate in candidates}
        if len(sizes) != 1 or len(raw_paths) != 1:
            raise ValueError(f"inconsistent pack records for SHA-256 {digest}")
        result[digest] = min(
            candidates,
            key=lambda item: (item["pack_remote_path"], item["pack_offset_bytes"]),
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--pack-manifests", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()

    received = read_received_hashes(args.index)
    ledger_rows, all_ledger_hashes = read_camara_ledger_rows(args.snapshot)
    pack_entries = read_pack_manifests(args.pack_manifests)

    source_records: dict[str, list[dict]] = defaultdict(list)
    for row in ledger_rows:
        source_records[row["sha256"]].append(
            {
                key: row.get(key, "") or ""
                for key in SOURCE_FIELDS
            }
        )

    candidates = sorted(set(source_records) - received)
    absent_from_packs = [digest for digest in candidates if digest not in pack_entries]
    if absent_from_packs:
        raise ValueError(
            f"{len(absent_from_packs)} verified Câmara hashes have no pack record"
        )

    records = []
    for digest in candidates:
        pack = pack_entries[digest]
        records.append(
            {
                "sha256": digest,
                **pack,
                "source_records": source_records[digest],
            }
        )

    source_type = pa.struct(
        [
            pa.field("requested_url", pa.string()),
            pa.field("resolved_url", pa.string()),
            pa.field("http_status", pa.string()),
            pa.field("content_type", pa.string()),
            pa.field("status", pa.string()),
            pa.field("attempt_count", pa.string()),
            pa.field("record_key", pa.string()),
            pa.field("source_ledger_path", pa.string()),
        ]
    )
    schema = pa.schema(
        [
            pa.field("sha256", pa.string(), nullable=False),
            pa.field("raw_path", pa.string(), nullable=False),
            pa.field("size_bytes", pa.int64(), nullable=False),
            pa.field("pack_remote_path", pa.string(), nullable=False),
            pa.field("pack_sha256", pa.string(), nullable=False),
            pa.field("pack_size_bytes", pa.int64(), nullable=False),
            pa.field("pack_offset_bytes", pa.int64(), nullable=False),
            pa.field("source_records", pa.list_(source_type), nullable=False),
        ]
    )
    table = pa.Table.from_pylist(records, schema=schema)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, args.output, compression="zstd", version="2.6")

    summary = {
        "status": "candidate_catalog_built",
        "source_ledgers": "Câmara annual download ledgers in owned state snapshot",
        "ledger_unique_hashes_with_provenance": len(all_ledger_hashes),
        "verified_ledger_rows": len(ledger_rows),
        "verified_unique_hashes": len(source_records),
        "received_unique_hashes": len(received),
        "pack_manifest_unique_hashes": len(pack_entries),
        "unreferenced_pack_hashes_excluded": len(set(pack_entries) - all_ledger_hashes),
        "candidate_supplement_hashes": len(candidates),
        "candidate_supplement_bytes": sum(
            pack_entries[digest]["size_bytes"] for digest in candidates
        ),
        "candidate_supplement_rows": sum(
            len(source_records[digest]) for digest in candidates
        ),
        "physically_fetched_and_hashed": False,
        "output": str(args.output),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
