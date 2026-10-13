#!/usr/bin/env python3
"""Assemble completed Senate extraction batches into a deduplicated split Parquet release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            first, second = sorted((left_root, right_root))
            self.parent[second] = first


def deterministic_split(family_key: str, seed: int) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{family_key}".encode()).hexdigest()[:8], 16) % 10_000
    return "train" if bucket < 9000 else "validation" if bucket < 9500 else "test"


def read_source_rows(extraction_root: Path, expected_archives: int) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    archives = sorted(extraction_root.glob("part[0-9][0-9][0-9]-batched"))
    if len(archives) != expected_archives:
        raise RuntimeError(f"expected {expected_archives} completed archive directories, found {len(archives)}")
    sources: dict[str, dict[str, str]] = {}
    provenance: list[dict[str, str]] = []
    for archive_dir in archives:
        complete_path = archive_dir / "COMPLETE.json"
        if not complete_path.exists():
            raise RuntimeError(f"missing extraction completion marker: {complete_path}")
        complete = json.loads(complete_path.read_text(encoding="utf-8"))
        if complete.get("status") not in {"complete_for_indexed_pdfs_only", "extraction_complete_manual_review_pending"}:
            raise RuntimeError(f"archive is not complete for indexed PDFs: {archive_dir.name}")
        for batch_dir in sorted(archive_dir.glob("batch-*")):
            source_map = batch_dir / "source_members.csv"
            if not source_map.exists():
                continue
            with source_map.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    version_id = row["version_id"]
                    if version_id in sources and sources[version_id]["file_sha256"] != row["file_sha256"]:
                        raise RuntimeError(f"version ID has conflicting source hashes: {version_id}")
                    provenance.append({**row, "version_id": version_id})
                    sources.setdefault(version_id, row)
    if not sources:
        raise RuntimeError("no source_members.csv records found")
    return sources, provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-archives", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    sources, provenance_rows = read_source_rows(args.extraction_root, args.expected_archives)
    provenance_by_version: dict[str, list[dict[str, str]]] = defaultdict(list)
    for provenance_row in provenance_rows:
        provenance_by_version[provenance_row["version_id"]].append(provenance_row)

    runs: dict[str, dict[str, str]] = {}
    duplicate_extraction_ids: set[str] = set()
    page_rows: list[dict] = []
    section_rows: list[dict] = []
    non_pdf_rows: list[dict] = []
    for archive_dir in sorted(args.extraction_root.glob("part[0-9][0-9][0-9]-batched")):
        for parquet_path in sorted(archive_dir.glob("batch-*/extraction_runs.parquet")):
            for row in pq.read_table(parquet_path).to_pylist():
                if row["version_id"] in runs:
                    duplicate_extraction_ids.add(row["extraction_id"])
                else:
                    runs[row["version_id"]] = row
        for parquet_path in sorted(archive_dir.glob("batch-*/pages.parquet")):
            page_rows.extend(pq.read_table(parquet_path).to_pylist())
        for parquet_path in sorted(archive_dir.glob("batch-*/sections.parquet")):
            section_rows.extend(pq.read_table(parquet_path).to_pylist())
        non_pdf_path = archive_dir / "non_pdf_text.parquet"
        if non_pdf_path.exists():
            non_pdf_rows.extend(pq.read_table(non_pdf_path).to_pylist())
    if set(runs) != set(sources):
        raise RuntimeError(f"source/extraction version mismatch: missing={len(set(sources)-set(runs))}, extra={len(set(runs)-set(sources))}")

    ext_to_version = {row["extraction_id"]: version for version, row in runs.items()}
    page_rows = [row for row in page_rows if row["extraction_id"] not in duplicate_extraction_ids]
    section_rows = [row for row in section_rows if row["extraction_id"] not in duplicate_extraction_ids]
    pages_by_version: dict[str, list[dict]] = defaultdict(list)
    for page in page_rows:
        if page["extraction_id"] in duplicate_extraction_ids:
            continue
        version_id = ext_to_version.get(page["extraction_id"])
        if version_id is None:
            raise RuntimeError(f"page has no extraction run: {page['extraction_id']}")
        page["version_id"] = version_id
        pages_by_version[version_id].append(page)
    sections_by_version: dict[str, list[dict]] = defaultdict(list)
    for section in section_rows:
        if section["extraction_id"] in duplicate_extraction_ids:
            continue
        version_id = ext_to_version.get(section["extraction_id"])
        if version_id is None:
            raise RuntimeError(f"section has no extraction run: {section['extraction_id']}")
        sections_by_version[version_id].append(section)

    non_pdf_by_version = {row["version_id"]: row for row in non_pdf_rows}
    if len(non_pdf_by_version) != len(non_pdf_rows) or set(non_pdf_by_version).intersection(sources):
        raise RuntimeError("duplicate version ID across PDF and non-PDF extraction outputs")
    all_sources = dict(sources)
    all_sources.update(non_pdf_by_version)
    union = UnionFind()
    family_tokens: dict[str, list[str]] = defaultdict(list)
    for version_id, source in all_sources.items():
        document_id = source.get("document_id") or version_id
        tokens = [f"doc:{document_id}", f"sha:{source['file_sha256']}"]
        for process_id in json.loads(source.get("process_ids_json") or "[]"):
            tokens.append(f"process:{process_id}")
        for token in tokens:
            union.union(version_id, token)
        family_tokens[version_id] = tokens
    family_members: dict[str, list[str]] = defaultdict(list)
    for version_id in all_sources:
        family_members[union.find(version_id)].append(version_id)
    family_ids = {
        version: "senado:family:" + hashlib.sha256("\n".join(sorted(members)).encode()).hexdigest()
        for members in family_members.values()
        for version in members
    }

    document_rows = []
    split_rows = []
    split_by_version = {}
    for version_id, source in sorted(sources.items()):
        ordered_pages = sorted(pages_by_version.get(version_id, []), key=lambda row: row["page_index"])
        text = "\n\n".join((row.get("raw_text") or "").strip() for row in ordered_pages if (row.get("raw_text") or "").strip())
        family_id = family_ids[version_id]
        split = deterministic_split(family_id, args.seed) if text else "quarantine"
        split_by_version[version_id] = split
        quality = [row for row in ordered_pages if row.get("quality_status")]
        document_id = source.get("document_id") or version_id
        document_rows.append({
            "document_id": document_id,
            "version_id": version_id,
            "family_id": family_id,
            "split": split,
            "house": source.get("house", "senado"),
            "source_namespace": source.get("source_namespace", ""),
            "source_document_id": source.get("source_document_id", ""),
            "source_url": source.get("source_url", ""),
            "archive": source.get("archive", ""),
            "archive_member": source.get("member", ""),
            "provenance_count": len(provenance_by_version[version_id]),
            "provenance_json": json.dumps(
                provenance_by_version[version_id],
                ensure_ascii=False, sort_keys=True,
            ),
            "file_sha256": source.get("file_sha256", ""),
            "process_ids_json": source.get("process_ids_json", "[]"),
            "source_ids_json": source.get("source_ids_json", "[]"),
            "record_kinds_json": source.get("record_kinds_json", "[]"),
            "query_years_json": source.get("query_years_json", "[]"),
            "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "page_count": len(ordered_pages),
            "character_count": len(text),
            "quality_pass_page_count": sum(row.get("quality_status") == "pass" for row in quality),
            "quality_review_page_count": sum(row.get("quality_status") == "review" for row in quality),
            "quality_fail_page_count": sum(row.get("quality_status") == "fail" for row in quality),
            "include_in_training": bool(text) and split in {"train", "validation", "test"},
        })
        split_rows.append({"version_id": version_id, "family_id": family_id, "split": split, "seed": args.seed})

    for version_id, source in sorted(non_pdf_by_version.items()):
        family_id = family_ids[version_id]
        document_rows.append({
            "document_id": source.get("document_id") or version_id,
            "version_id": version_id,
            "family_id": family_id,
            "split": "quarantine",
            "house": source.get("house", "senado"),
            "source_namespace": "senado_processo_documento",
            "source_document_id": "",
            "source_url": source.get("source_url", ""),
            "archive": source.get("archive", ""),
            "archive_member": source.get("archive_member", ""),
            "file_sha256": source.get("file_sha256", ""),
            "process_ids_json": source.get("process_ids_json", "[]"),
            "source_ids_json": source.get("source_ids_json", "[]"),
            "record_kinds_json": source.get("record_kinds_json", "[]"),
            "query_years_json": "[]",
            "text": source.get("text", ""),
            "text_sha256": source.get("text_sha256", ""),
            "page_count": 0,
            "character_count": int(source.get("character_count") or 0),
            "quality_pass_page_count": 0,
            "quality_review_page_count": int(source.get("quality_status") == "review"),
            "quality_fail_page_count": int(source.get("quality_status") == "fail"),
            "include_in_training": False,
        })
        split_rows.append({"version_id": version_id, "family_id": family_id, "split": "quarantine", "seed": args.seed})

    args.output_dir.mkdir(parents=True, exist_ok=True)
    documents_path = args.output_dir / "documents.parquet"
    splits_path = args.output_dir / "splits.parquet"
    pages_path = args.output_dir / "pages.parquet"
    sections_path = args.output_dir / "sections.parquet"
    provenance_path = args.output_dir / "source_provenance.parquet"
    pq.write_table(pa.Table.from_pylist(document_rows), documents_path, compression="zstd")
    pq.write_table(pa.Table.from_pylist(split_rows), splits_path, compression="zstd")
    for row in page_rows:
        version_id = row.get("version_id")
        if version_id not in split_by_version:
            raise RuntimeError(f"page version has no curated split: {version_id!r}")
        row["split"] = split_by_version[version_id]
    pq.write_table(pa.Table.from_pylist(page_rows), pages_path, compression="zstd")
    for row in section_rows:
        version = ext_to_version[row["extraction_id"]]
        row["version_id"] = version
        row["split"] = split_by_version[version]
    pq.write_table(pa.Table.from_pylist(section_rows), sections_path, compression="zstd")
    pq.write_table(pa.Table.from_pylist(provenance_rows), provenance_path, compression="zstd")
    summary = {
        "house": "senado", "expected_archives": args.expected_archives,
        "documents": len(document_rows), "families": len(family_members),
        "split_counts": {name: sum(row["split"] == name for row in document_rows) for name in ("train", "validation", "test", "quarantine")},
        "split_policy": "connected components of official process IDs, document IDs and exact source hashes; deterministic SHA-256 bucket",
        "seed": args.seed,
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (documents_path, splits_path, pages_path, sections_path, provenance_path)},
        "status": "curated",
    }
    summary_path = args.output_dir / "release_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    complete = {
        "status": "curated",
        "house": "senado",
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (documents_path, splits_path, pages_path, sections_path, provenance_path, summary_path)},
    }
    (args.output_dir / "COMPLETE.json").write_text(json.dumps(complete, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
