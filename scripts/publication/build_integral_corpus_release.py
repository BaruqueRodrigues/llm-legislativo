#!/usr/bin/env python3
"""Unify the current Câmara and Senado curation outputs as a formal corpus release.

The bridge is disk-backed: SQLite stores only identifiers, family keys and
eligibility while PyArrow streams document text in batches. It keeps houses in
separate family domains, removes exact-text duplicates within each house,
reassigns all eligible families with the project's 80/10/10 group-hash policy,
and routes unresolved quality records to quarantine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq


SPLIT_VERSION = "split_integral_80_10_10_v1"
SEED = 42
BATCH_SIZE = 2_000


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            first, second = sorted((ra, rb))
            self.parent[second] = first


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_files(camara_dir: Path, senate_dir: Path) -> list[tuple[str, Path]]:
    camara = [
        ("camara", camara_dir / name)
        for name in ("train.parquet", "validation.parquet", "test.parquet", "quarantine.parquet", "exact_duplicates.parquet")
    ]
    senate = [("senado", senate_dir / "documents.parquet")]
    missing = [str(path) for _, path in camara + senate if not path.is_file()]
    if missing:
        raise FileNotFoundError("Input parquet ausente: " + ", ".join(missing))
    return camara + senate


def base_family(house: str, value: str | None) -> str:
    raw = value or ""
    if not raw:
        raw = "unlinked:" + hashlib.sha256((house + ":missing-family").encode()).hexdigest()
    if raw.startswith(house + ":family:"):
        return raw
    return house + ":family:" + hashlib.sha256((house + ":" + raw).encode()).hexdigest()


def canonical_item_id(house: str, value: str | None) -> str:
    raw = value or ""
    if not raw:
        raise ValueError("Registro sem identificador")
    prefix = house + ":item:"
    if raw.startswith(prefix):
        return raw
    return prefix + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def eligible(house: str, row: dict[str, Any]) -> bool:
    text = row.get("text") or ""
    if not text.strip():
        return False
    if house == "camara":
        return row.get("quality_status") == "accepted" and (
            bool(row.get("include_in_dataset")) or bool(row.get("duplicate_of_corpus_item_id"))
        )
    return (
        bool(row.get("include_in_training"))
        and int(row.get("page_count") or 0) > 0
        and int(row.get("quality_review_page_count") or 0) == 0
        and int(row.get("quality_fail_page_count") or 0) == 0
    )


def get_text_hash(row: dict[str, Any]) -> str:
    value = row.get("text_sha256") or ""
    if value:
        return str(value)
    return hashlib.sha256((row.get("text") or "").encode("utf-8")).hexdigest()


def split_for(family_id: str) -> tuple[str, float]:
    h = hashlib.sha256(f"{family_id}:{SEED}".encode("utf-8")).hexdigest()[:8]
    u = int(h, 16) / 4_294_967_296
    return ("train" if u < 0.8 else "validation" if u < 0.9 else "test", u)


def json_safe_metadata(house: str, row: dict[str, Any]) -> str:
    if house == "camara":
        fields = (
            "document_id", "source_url", "source_archive", "source_member", "source_file_sha256",
            "source_format", "codteor", "proposition_ids_json", "proposition_type",
            "proposition_number", "proposition_year", "presentation_date", "ementa",
            "page_count", "page_methods_json", "page_quality_json", "quality_reasons_json",
        )
    else:
        fields = (
            "document_id", "source_namespace", "source_document_id", "source_url", "archive",
            "archive_member", "file_sha256", "process_ids_json", "source_ids_json",
            "record_kinds_json", "query_years_json", "provenance_json", "page_count",
            "quality_pass_page_count", "quality_review_page_count", "quality_fail_page_count",
        )
    return json.dumps({key: row.get(key) for key in fields}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=BATCH_SIZE):
        yield from batch.to_pylist()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camara-dir", type=Path, required=True)
    parser.add_argument("--senado-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, default=None)
    args = parser.parse_args()
    inputs = source_files(args.camara_dir, args.senado_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scratch = args.scratch_dir or args.output_dir / ".bridge-work"
    scratch.mkdir(parents=True, exist_ok=True)
    db_path = scratch / "bridge.sqlite3"
    if db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("PRAGMA temp_store=FILE")
    db.execute("CREATE TABLE docs (item_id TEXT PRIMARY KEY, house TEXT, base_family TEXT, text_sha TEXT, eligible INTEGER, representative TEXT, family TEXT, split TEXT, reason TEXT)")
    db.execute("CREATE INDEX docs_hash ON docs(house,text_sha)")
    db.execute("CREATE INDEX docs_family ON docs(house,base_family)")
    input_rows = Counter()

    # Pass 1: compact eligibility and family index, validating stable IDs.
    for house, path in inputs:
        for row in iter_rows(path):
            source_item_id = str(row.get("corpus_item_id") or row.get("version_id") or "")
            item_id = canonical_item_id(house, source_item_id)
            fam = base_family(house, row.get("family_id"))
            text = row.get("text") or ""
            is_eligible = eligible(house, row)
            text_hash = get_text_hash(row) if text else ""
            try:
                db.execute(
                    "INSERT INTO docs(item_id,house,base_family,text_sha,eligible,representative,family,split,reason) VALUES (?,?,?,?,?,?,NULL,NULL,NULL)",
                    (item_id, house, fam, text_hash, int(is_eligible), item_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"corpus_item_id duplicado na entrada: {item_id}") from exc
            input_rows[house] += 1
        db.commit()

    # House-local exact dedup. The API contract means no inter-house identity graph.
    duplicate_groups = Counter()
    duplicate_rows = Counter()
    for house in ("camara", "senado"):
        hashes = db.execute(
            "SELECT text_sha FROM docs WHERE house=? AND eligible=1 AND text_sha<>'' GROUP BY text_sha HAVING COUNT(*)>1",
            (house,),
        )
        for (text_hash,) in hashes:
            members = db.execute(
                "SELECT item_id FROM docs WHERE house=? AND eligible=1 AND text_sha=? ORDER BY item_id",
                (house, text_hash),
            ).fetchall()
            representative = str(members[0][0])
            for (item_id,) in members:
                if item_id != representative:
                    db.execute("UPDATE docs SET representative=? WHERE item_id=?", (representative, item_id))
                    duplicate_rows[house] += 1
            duplicate_groups[house] += 1
        db.commit()

    # Join base families transitively where multiple exact hashes connect them.
    # Exact-hash groups are canonicalized above; build deterministic components by family key.
    uf = UnionFind()
    for house in ("camara", "senado"):
        fams = [str(r[0]) for r in db.execute("SELECT DISTINCT base_family FROM docs WHERE house=? AND eligible=1", (house,))]
        for fam in fams:
            uf.find(fam)
        by_hash: dict[str, str] = {}
        for fam, text_hash in db.execute(
            "SELECT DISTINCT base_family,text_sha FROM docs WHERE house=? AND eligible=1 AND text_sha<>''", (house,)
        ):
            previous = by_hash.get(text_hash)
            if previous:
                uf.union(str(fam), previous)
            else:
                by_hash[text_hash] = str(fam)
        roots: dict[str, list[str]] = defaultdict(list)
        for fam in fams:
            roots[uf.find(fam)].append(fam)
        component_ids = {}
        for members in roots.values():
            ordered = sorted(members)
            final_id = ordered[0] if len(ordered) == 1 else f"{house}:family:" + hashlib.sha256("\n".join(ordered).encode()).hexdigest()
            for member in ordered:
                component_ids[member] = final_id
        for fam, final_id in component_ids.items():
            split, u = split_for(final_id)
            reason = f"{final_id} sorteada para {split} via group_hash (seed {SEED}, u={u:.8f})"
            db.execute("UPDATE docs SET family=?,split=?,reason=? WHERE house=? AND base_family=? AND eligible=1", (final_id, split, reason, house, fam))
    db.execute("UPDATE docs SET family=base_family,split='quarantine',reason='quality_or_text_gate_not_met; excluded from training' WHERE eligible=0")
    db.commit()

    # Preserve house-local identities and do not deduplicate across houses. If text
    # hashes coincide, keep the two family IDs separate but assign the whole split
    # component together so identical text cannot land in train and held-out data.
    cross_house_hashes = db.execute(
        "SELECT text_sha FROM docs WHERE eligible=1 AND text_sha<>'' GROUP BY text_sha HAVING COUNT(DISTINCT house)>1"
    )
    cross_house_families = UnionFind()
    cross_house = 0
    for (text_hash,) in cross_house_hashes:
        fam_rows = db.execute(
            "SELECT DISTINCT family FROM docs WHERE eligible=1 AND text_sha=? ORDER BY family", (text_hash,)
        ).fetchall()
        if len({str(r[0]).split(":", 1)[0] for r in fam_rows}) < 2:
            continue
        cross_house += 1
        families = [str(r[0]) for r in fam_rows]
        for family in families:
            cross_house_families.find(family)
        for family in families[1:]:
            cross_house_families.union(families[0], family)
    split_components: dict[str, list[str]] = defaultdict(list)
    for family in cross_house_families.parent:
        split_components[cross_house_families.find(family)].append(family)
    for members in split_components.values():
        ordered = sorted(members)
        if len(ordered) < 2:
            continue
        split_key = "cross-house-exact-text:" + hashlib.sha256("\n".join(ordered).encode()).hexdigest()
        split, u = split_for(split_key)
        reason = f"famílias preservadas por casa; split alinhado por hash textual exato entre casas ({split_key}) via group_hash, seed {SEED}, u={u:.8f}"
        for family in ordered:
            db.execute("UPDATE docs SET split=?,reason=? WHERE family=? AND eligible=1", (split, reason, family))
    db.commit()

    out_docs = args.output_dir / "curated_documents.parquet"
    out_splits = args.output_dir / "split_assignments.parquet"
    quarantine_path = args.output_dir / "quarantine.parquet"
    duplicates_path = args.output_dir / "exact_duplicates.parquet"
    doc_schema = pa.schema([
        ("corpus_item_id", pa.string()), ("document_id", pa.string()), ("version_id", pa.string()),
        ("text", pa.string()), ("text_sha256", pa.string()), ("utf8_bytes", pa.int64()),
        ("character_count", pa.int64()), ("house", pa.string()), ("normalized_kind", pa.string()),
        ("family_id", pa.string()), ("quality_status", pa.string()), ("include_in_dataset", pa.bool_()),
        ("representative_item_id", pa.string()), ("content_date", pa.string()),
        ("metadata_json", pa.string()), ("source_release", pa.string()),
    ])
    split_schema = pa.schema([
        ("split_version", pa.string()), ("corpus_item_id", pa.string()), ("family_id", pa.string()),
        ("split", pa.string()), ("policy", pa.string()), ("assignment_reason", pa.string()), ("seed", pa.int64()),
    ])
    quarantine_schema = pa.schema([
        ("corpus_item_id", pa.string()), ("house", pa.string()), ("family_id", pa.string()),
        ("reason", pa.string()), ("text_sha256", pa.string()), ("utf8_bytes", pa.int64()), ("metadata_json", pa.string()),
    ])
    duplicate_schema = pa.schema([
        ("house", pa.string()), ("duplicate_item_id", pa.string()), ("representative_item_id", pa.string()),
        ("family_id", pa.string()), ("text_sha256", pa.string()), ("method", pa.string()),
    ])
    doc_writer = pq.ParquetWriter(out_docs, doc_schema, compression="zstd")
    split_writer = pq.ParquetWriter(out_splits, split_schema, compression="zstd")
    quarantine_writer = pq.ParquetWriter(quarantine_path, quarantine_schema, compression="zstd")
    duplicate_writer = pq.ParquetWriter(duplicates_path, duplicate_schema, compression="zstd")
    counts = Counter(); bytes_by_split = Counter(); kind_counts = Counter(); duplicate_written = 0

    def write_rows(writer: pq.ParquetWriter, schema: pa.Schema, rows: list[dict[str, Any]]) -> None:
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, schema=schema))

    # Pass 2: materialize canonical rows while streaming source text.
    doc_buffer: list[dict[str, Any]] = []; split_buffer: list[dict[str, Any]] = []
    quarantine_buffer: list[dict[str, Any]] = []; duplicate_buffer: list[dict[str, Any]] = []
    for house, path in inputs:
        for row in iter_rows(path):
            source_item_id = str(row.get("corpus_item_id") or row.get("version_id"))
            item_id = canonical_item_id(house, source_item_id)
            plan = db.execute("SELECT family,split,reason,representative,eligible FROM docs WHERE item_id=?", (item_id,)).fetchone()
            family, split, reason, representative, is_eligible = plan
            text = row.get("text") or ""
            text_hash = get_text_hash(row) if text else ""
            metadata = json_safe_metadata(house, row)
            metadata_json = json.loads(metadata)
            metadata_json["source_corpus_item_id"] = source_item_id
            metadata = json.dumps(metadata_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            normalized_kind = (row.get("proposition_type") or "unknown") if house == "camara" else "senado_documento_legislativo"
            quality = "accepted" if is_eligible else "quarantined"
            doc_buffer.append({
                "corpus_item_id": item_id,
                "document_id": row.get("document_id") or row.get("version_id") or item_id,
                "version_id": row.get("version_id") or item_id,
                "text": text,
                "text_sha256": text_hash,
                "utf8_bytes": len(text.encode("utf-8")),
                "character_count": len(text),
                "house": house,
                "normalized_kind": normalized_kind,
                "family_id": family,
                "quality_status": quality,
                "include_in_dataset": bool(is_eligible and item_id == representative),
                "representative_item_id": representative,
                "content_date": row.get("presentation_date") if house == "camara" else None,
                "metadata_json": metadata,
                "source_release": path.parent.name,
            })
            split_buffer.append({"split_version": SPLIT_VERSION, "corpus_item_id": item_id, "family_id": family,
                                 "split": split, "policy": "group_hash" if is_eligible else "quarantine",
                                 "assignment_reason": reason, "seed": SEED})
            counts[(house, split)] += 1
            bytes_by_split[split] += len(text.encode("utf-8")) if split != "quarantine" else 0
            kind_counts[(house, normalized_kind)] += 1
            if split == "quarantine":
                quarantine_buffer.append({"corpus_item_id": item_id, "house": house, "family_id": family,
                                          "reason": reason, "text_sha256": text_hash,
                                          "utf8_bytes": len(text.encode("utf-8")), "metadata_json": metadata})
            if is_eligible and item_id != representative:
                duplicate_buffer.append({"house": house, "duplicate_item_id": item_id,
                                         "representative_item_id": representative, "family_id": family,
                                         "text_sha256": text_hash, "method": "exact_text_sha256"})
                duplicate_written += 1
            if len(doc_buffer) >= BATCH_SIZE:
                write_rows(doc_writer, doc_schema, doc_buffer); doc_buffer.clear()
                write_rows(split_writer, split_schema, split_buffer); split_buffer.clear()
                write_rows(quarantine_writer, quarantine_schema, quarantine_buffer); quarantine_buffer.clear()
                write_rows(duplicate_writer, duplicate_schema, duplicate_buffer); duplicate_buffer.clear()
    write_rows(doc_writer, doc_schema, doc_buffer); write_rows(split_writer, split_schema, split_buffer)
    write_rows(quarantine_writer, quarantine_schema, quarantine_buffer); write_rows(duplicate_writer, duplicate_schema, duplicate_buffer)
    doc_writer.close(); split_writer.close(); quarantine_writer.close(); duplicate_writer.close()

    source_manifest_paths = [args.camara_dir / "publication_manifest.json", args.senado_dir / "release_summary.json"]
    source_summaries = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in source_manifest_paths if p.exists()}
    output_files = [out_docs, out_splits, quarantine_path, duplicates_path]
    file_entries = []
    for path in output_files:
        file_entries.append({"path": path.name, "table_name": path.stem, "row_count": pq.ParquetFile(path).metadata.num_rows,
                             "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {
        "schema_version": "1.0.0", "corpus_version": "legislativo_atual_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "cohort_definition": "Current available Câmara parts 001-043 preview plus current completed Senate release; accepted text only; unresolved quality records excluded to quarantine.",
        "source_snapshot_ids": ["camara:parts001-043-preview", "senado:senado-release"],
        "snapshot_cutoff_utc": "2026-10-11T00:00:00Z", "history_scope": "all_available",
        "houses": ["camara", "senado"], "source_collection_ids": ["camara:parts001-043", "senado:archives001-016"],
        "coverage_segment_ids": ["camara:downloaded_parts001-043", "senado:downloaded_archives001-016"],
        "coverage_status": "partial", "document_type_mapping_version": "source-preserved-v1",
        "selection_policy": "accepted nonempty documents; Senate documents with any page review/fail and empty records go to quarantine; exact duplicates deduplicated within each house; house-local family IDs preserved across houses; identical text hashes across houses, if any, align split assignment without merging identities.",
        "extraction_config_hash": "source_manifests_preserved", "cleaning_version": "source-curation-preserved",
        "dedup_policy_version": "exact_sha256_house_local_v1", "split_version": SPLIT_VERSION, "seed": SEED,
        "code_revision": "source_sha256:" + sha256_file(Path(__file__).resolve()),
        "permission_summary": {"training_use": "not independently asserted by this build; source permission evidence must be reviewed before publication", "provenance": "source metadata preserved"},
        "counts": {"input_by_house": dict(input_rows), "output_by_house_and_split": {f"{h}.{s}": n for (h,s),n in sorted(counts.items())},
                   "duplicate_rows_by_house": dict(duplicate_rows), "duplicate_groups_by_house": dict(duplicate_groups),
                   "exact_duplicate_rows_written": duplicate_written, "cross_house_exact_text_hash_groups": cross_house,
                   "families": db.execute("SELECT COUNT(DISTINCT family) FROM docs WHERE eligible=1").fetchone()[0]},
        "utf8_bytes": dict(bytes_by_split), "files": file_entries,
        "source_manifests": source_summaries,
        "limitations": ["Historical coverage is partial: this release only covers the listed downloaded inputs.",
                        "Near-duplicate and containment review was not recomputed in this bridge.",
                        "Câmara quarantine and Senado page-review documents remain excluded pending review.",
                        "The current source release does not assert a complete historical corpus."],
    }
    manifest_path = args.output_dir / "release_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    complete = {"status": "complete_for_declared_scope", "manifest_sha256": sha256_file(manifest_path),
                "files": {entry["path"]: entry["sha256"] for entry in file_entries}}
    (args.output_dir / "COMPLETE.json").write_text(json.dumps(complete, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    db.close()
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    try:
        scratch.rmdir()
    except OSError:
        pass
    print(json.dumps({"output_dir": str(args.output_dir), "counts": manifest["counts"], "coverage_status": "partial",
                      "files": file_entries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
