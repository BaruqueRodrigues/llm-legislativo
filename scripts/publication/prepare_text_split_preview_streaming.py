#!/usr/bin/env python3
"""Build a memory-bounded, provisional Câmara split preview across many TARs.

This uses the same family graph and R ``group_hash`` assignment as
prepare_text_split_preview.py, but stages document rows in SQLite and writes
Parquet in batches so a full multi-TAR preview does not retain all extracted
page text and document dictionaries in RAM.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

try:  # package import in tests; sibling import when run as a script
    from .prepare_text_split_preview import (
        SPLITS, UnionFind, build_graph, code_from_url, compact_json, sha256_bytes, sha256_file,
    )
except ImportError:
    from prepare_text_split_preview import (
        SPLITS, UnionFind, build_graph, code_from_url, compact_json, sha256_bytes, sha256_file,
    )


FLUSH_ROWS = 5000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", required=True, action="append", help="TAR stem; repeat for every included TAR")
    parser.add_argument("--source-index", required=True, type=Path)
    parser.add_argument("--part-index", required=True, action="append", type=Path)
    parser.add_argument("--propositions-zip", required=True, type=Path)
    parser.add_argument("--extraction-root", required=True, action="append", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed", default=42, type=int)
    parser.add_argument("--train", default=0.80, type=float)
    parser.add_argument("--validation", default=0.10, type=float)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--rscript", default="Rscript")
    return parser.parse_args()


def insert_doc(db: sqlite3.Connection, family_uf: UnionFind, doc: dict[str, object]) -> None:
    family = str(doc["family_id"])
    family_uf.add(family)
    text_hash = str(doc["text_sha256"]) if doc["text"] else ""
    if text_hash:
        prior = db.execute("SELECT family_id FROM text_families WHERE text_sha=?", (text_hash,)).fetchone()
        if prior:
            family_uf.union(family, str(prior[0]))
        else:
            db.execute("INSERT INTO text_families(text_sha,family_id) VALUES (?,?)", (text_hash, family))
    db.execute(
        "INSERT INTO docs(item_id,family_id,text_sha,eligible,payload) VALUES (?,?,?,?,?)",
        (
            str(doc["corpus_item_id"]), family, text_hash, int(bool(doc["include_in_dataset"])),
            json.dumps(doc, ensure_ascii=False, separators=(",", ":")),
        ),
    )


def mark_exact_duplicates(db: sqlite3.Connection) -> tuple[int, int]:
    duplicate_count = 0
    duplicate_groups = 0
    hashes = db.execute(
        "SELECT text_sha FROM docs WHERE text_sha<>'' GROUP BY text_sha HAVING COUNT(*)>1"
    )
    for (text_hash,) in hashes:
        rows = db.execute(
            "SELECT item_id,eligible,payload FROM docs WHERE text_sha=? ORDER BY eligible DESC,item_id ASC",
            (text_hash,),
        ).fetchall()
        if len(rows) < 2:
            continue
        duplicate_groups += 1
        representative = str(rows[0][0])
        for item_id, _eligible, payload_json in rows[1:]:
            payload = json.loads(payload_json)
            payload["duplicate_of_corpus_item_id"] = representative
            payload["include_in_dataset"] = False
            payload["quality_reasons_json"] = compact_json(
                ["exact_text_duplicate", str(payload["quality_reasons_json"])]
            )
            db.execute(
                "UPDATE docs SET eligible=0,duplicate_of=?,payload=? WHERE item_id=?",
                (representative, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), item_id),
            )
            duplicate_count += 1
    db.commit()
    return duplicate_groups, duplicate_count


def merged_family_ids(db: sqlite3.Connection, family_uf: UnionFind) -> tuple[dict[str, str], int]:
    members_by_root: dict[str, set[str]] = defaultdict(set)
    families = [str(row[0]) for row in db.execute("SELECT DISTINCT family_id FROM docs")]
    for family in families:
        members_by_root[family_uf.find(family)].add(family)
    merged: dict[str, str] = {}
    for members in members_by_root.values():
        ordered = sorted(members)
        final_id = ordered[0] if len(ordered) == 1 else "fam:" + sha256_bytes("|".join(ordered).encode("utf-8"))
        for family in ordered:
            merged[family] = final_id
    return merged, len(members_by_root)


def add_archive_docs(
    db: sqlite3.Connection,
    family_uf: UnionFind,
    part: str,
    part_index: Path,
    extraction_root: Path,
    code_family: dict[str, str],
    code_props: dict[str, list[str]],
    prop_metadata: dict[str, dict[str, str]],
) -> tuple[int, int]:
    if not extraction_root.name.startswith(part):
        raise RuntimeError(f"extraction root {extraction_root} does not correspond to {part}")
    source_rows: dict[tuple[str, str], dict[str, str]] = {}
    with part_index.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row.get("tar") == f"{part}.tar" and row.get("status") == "listado":
                source_rows[(f"{part}.tar", row["membro_tar"])] = row
    expected_pdf_keys = {key for key in source_rows if key[1].lower().endswith(".pdf")}
    seen_pdf_keys: set[tuple[str, str]] = set()
    pdf_count = 0
    non_pdf_count = 0

    for batch in sorted(extraction_root.glob("batch-*")):
        map_path = batch / "source_members.csv"
        if not map_path.exists():
            continue
        with map_path.open(newline="", encoding="utf-8") as stream:
            batch_sources = list(csv.DictReader(stream))
        run_table = pq.read_table(
            batch / "extraction_runs.parquet",
            columns=["extraction_id", "version_id", "status", "error_code"],
        )
        batch_runs = {r["version_id"]: r for r in run_table.to_pylist()}
        page_table = pq.read_table(
            batch / "pages.parquet",
            columns=["extraction_id", "page_index", "method", "raw_text", "quality_status"],
        )
        batch_pages: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in page_table.to_pylist():
            batch_pages[row["extraction_id"]].append(row)

        for source in batch_sources:
            member = source["member"]
            archive = source["archive"]
            key = (archive, member)
            indexed = source_rows.get(key)
            if not indexed or indexed["url"] != source["source_url"] or indexed["sha256"] != source["file_sha256"]:
                raise RuntimeError(f"source map does not match verified index: {archive}/{member}")
            if archive != f"{part}.tar":
                raise RuntimeError(f"source map archive mismatch: expected {part}.tar, got {archive}")
            run = batch_runs.get(source["version_id"])
            if not run:
                raise RuntimeError(f"missing extraction run for {archive}/{source['version_id']}")
            page_rows = sorted(batch_pages.get(run["extraction_id"], []), key=lambda r: int(r["page_index"]))
            text = "\n\f\n".join(str(r["raw_text"] or "") for r in page_rows)
            all_pass = bool(page_rows) and all(r["quality_status"] == "pass" and r["method"] != "none" for r in page_rows)
            accepted = run["status"] == "succeeded" and all_pass and bool(text.strip())
            url = source["source_url"]
            code = code_from_url(url)
            family = code_family.get(code or "") or "fam:" + sha256_bytes(
                f"camara:unmapped:{code or indexed['sha256']}".encode()
            )
            extraction_id = run["extraction_id"]
            doc_id = f"camara:doc:camara_api:codteor:{code}" if code else "camara:doc:url:" + sha256_bytes(url.encode())
            version_id = f"{doc_id}:v:{indexed['sha256'].lower()}"
            canonical_meta = {
                "document_id": doc_id, "version_id": version_id, "extraction_id": extraction_id,
                "logical_unit_id": doc_id, "composition_id": None,
            }
            linked_ids = sorted(code_props.get(code or "", []))
            meta = prop_metadata.get(linked_ids[0], {}) if linked_ids else {}
            reasons = [
                reason for reason, condition in [
                    ("extraction_not_succeeded", run["status"] != "succeeded"),
                    ("page_quality_or_method_gate_failed", not all_pass),
                    ("empty_text", not text.strip()),
                ] if condition
            ]
            doc = {
                "corpus_item_id": "item:" + sha256_bytes(compact_json(canonical_meta).encode("utf-8")),
                "document_id": doc_id, "version_id": version_id,
                "source_extraction_version_id": source["version_id"], "extraction_id": extraction_id,
                "source_archive": archive, "source_member": member, "source_url": url,
                "source_file_sha256": indexed["sha256"], "source_format": "pdf", "codteor": code or "",
                "proposition_ids_json": compact_json([f"camara:prop:{p}" for p in linked_ids]),
                "proposition_type": meta.get("sigla_tipo", ""), "proposition_number": meta.get("numero", ""),
                "proposition_year": meta.get("ano", ""), "presentation_date": meta.get("data_apresentacao", ""),
                "ementa": meta.get("ementa", ""), "family_id": family, "text": text,
                "text_sha256": sha256_bytes(text.encode("utf-8")), "character_count": len(text),
                "utf8_bytes": len(text.encode("utf-8")),
                "quality_status": "accepted" if accepted else "quarantined",
                "quality_reasons_json": compact_json(reasons), "include_in_dataset": accepted,
                "duplicate_of_corpus_item_id": "", "page_count": len(page_rows),
                "page_methods_json": compact_json(dict(Counter(str(r["method"]) for r in page_rows))),
                "page_quality_json": compact_json(dict(Counter(str(r["quality_status"]) for r in page_rows))),
            }
            insert_doc(db, family_uf, doc)
            seen_pdf_keys.add(key)
            pdf_count += 1
        batch_pages.clear()
        db.commit()

    if seen_pdf_keys != expected_pdf_keys:
        raise RuntimeError(
            f"PDF source coverage mismatch for {part}: mapped={len(seen_pdf_keys)}, expected={len(expected_pdf_keys)}"
        )

    non_pdf_path = extraction_root / "non_pdf_text.parquet"
    if non_pdf_path.exists():
        non_pdf_rows = pq.read_table(non_pdf_path).to_pylist()
        for src in non_pdf_rows:
            code = code_from_url(src.get("source_url"))
            family = code_family.get(code or "") or "fam:" + sha256_bytes(
                f"camara:unmapped:{code or src['file_sha256']}".encode()
            )
            raw_version_id = f"doc:v1:{Path(src['archive_member']).stem}"
            doc_id = f"camara:doc:camara_api:codteor:{code}" if code else "camara:doc:url:" + sha256_bytes(src["source_url"].encode())
            version_id = f"{doc_id}:v:{src['file_sha256'].lower()}"
            txt = src.get("text") or ""
            extraction_id = "nonpdf:" + raw_version_id + ":" + src["file_sha256"]
            canonical_meta = {
                "document_id": doc_id, "version_id": version_id, "extraction_id": extraction_id,
                "logical_unit_id": doc_id, "composition_id": None,
            }
            doc = {
                "corpus_item_id": "item:" + sha256_bytes(compact_json(canonical_meta).encode("utf-8")),
                "document_id": doc_id, "version_id": version_id,
                "source_extraction_version_id": raw_version_id, "extraction_id": extraction_id,
                "source_archive": src["archive"], "source_member": src["archive_member"],
                "source_url": src["source_url"], "source_file_sha256": src["file_sha256"],
                "source_format": src["format"], "codteor": code or "",
                "proposition_ids_json": compact_json([f"camara:prop:{p}" for p in sorted(code_props.get(code or "", []))]),
                "proposition_type": "", "proposition_number": "", "proposition_year": "",
                "presentation_date": "", "ementa": "", "family_id": family, "text": txt,
                "text_sha256": sha256_bytes(txt.encode("utf-8")), "character_count": len(txt),
                "utf8_bytes": len(txt.encode("utf-8")), "quality_status": "quarantined",
                "quality_reasons_json": compact_json([src.get("quality_status", "review"), src.get("review_status", "manual_review_pending")]),
                "include_in_dataset": False, "duplicate_of_corpus_item_id": "", "page_count": 1,
                "page_methods_json": compact_json({src.get("adapter", "nonpdf"): 1}),
                "page_quality_json": compact_json({src.get("quality_status", "review"): 1}),
            }
            insert_doc(db, family_uf, doc)
            non_pdf_count += 1
        db.commit()
    return pdf_count, non_pdf_count


def assign_splits_with_r(
    families: list[str], output_dir: Path, repo_root: Path, rscript: str, seed: int,
    train: float, validation: float,
) -> dict[str, tuple[str, str]]:
    input_path = output_dir.parent / f".{output_dir.name}.family-input.parquet"
    output_path = output_dir.parent / f".{output_dir.name}.family-assignment.parquet"
    script_path = output_dir.parent / f".{output_dir.name}.assign-families.R"
    pq.write_table(pa.Table.from_pylist([{"family_id": family} for family in families]), input_path)
    script_path.write_text(
        "args <- commandArgs(trailingOnly=TRUE)\n"
        "repo <- normalizePath(args[[1]])\nsetwd(repo)\n"
        "input <- arrow::read_parquet(args[[2]])\n"
        "seed_val <- as.integer(args[[4]])\n"
        "p_train <- as.numeric(args[[5]])\np_val <- as.numeric(args[[6]])\n"
        "families <- input$family_id\n"
        "hash_hex <- vapply(families, function(fam) digest::digest(paste0(fam, ':', seed_val), algo='sha256'), character(1))\n"
        "u_val <- as.numeric(paste0('0x', substr(hash_hex, 1, 8))) / 4294967296\n"
        "family_split <- ifelse(u_val < p_train, 'train', ifelse(u_val < p_train + p_val, 'validation', 'test'))\n"
        "out <- tibble::tibble(family_id=families, split=family_split, policy=rep('group_hash', length(families)), assignment_reason=sprintf('%s sorteada para %s via group_hash (seed %d, u=%.4f)', families, family_split, seed_val, u_val), seed=bit64::as.integer64(rep(seed_val, length(families))))\n"
        "arrow::write_parquet(out, args[[3]])\n"
    )
    try:
        subprocess.run(
            [rscript, str(script_path), str(repo_root.resolve()), str(input_path), str(output_path), str(seed), str(train), str(validation)],
            cwd=repo_root, check=True,
        )
        columns = pq.read_table(output_path).to_pydict()
        return {
            family: (split, reason)
            for family, split, reason in zip(columns["family_id"], columns["split"], columns["assignment_reason"])
        }
    finally:
        script_path.unlink(missing_ok=True)
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


def write_outputs(db: sqlite3.Connection, output_dir: Path, split_by_family: dict[str, tuple[str, str]], seed: int) -> dict[str, int]:
    paths = {
        "assignments": output_dir / "split_assignments.parquet",
        "train": output_dir / "train.parquet",
        "validation": output_dir / "validation.parquet",
        "test": output_dir / "test.parquet",
        "quarantine": output_dir / "quarantine.parquet",
        "duplicates": output_dir / "exact_duplicates.parquet",
    }
    sample = json.loads(db.execute("SELECT payload FROM docs ORDER BY rowid LIMIT 1").fetchone()[0])
    family = str(db.execute("SELECT family_id FROM docs ORDER BY rowid LIMIT 1").fetchone()[0])
    split, reason = split_by_family[family]
    sample.update({"split": split, "split_version": "split_preview_v1", "split_policy": "group_hash", "assignment_reason": reason, "seed": seed})
    schema = pa.Table.from_pylist([sample]).schema
    writers: dict[str, pq.ParquetWriter] = {}
    buffers: dict[str, list[dict[str, object]]] = {key: [] for key in paths}
    counts = {key: 0 for key in paths}

    def flush(key: str) -> None:
        if not buffers[key]:
            return
        table = pa.Table.from_pylist(buffers[key], schema=schema)
        writer = writers.get(key)
        if writer is None:
            writer = pq.ParquetWriter(paths[key], schema, compression="zstd")
            writers[key] = writer
        writer.write_table(table, row_group_size=FLUSH_ROWS)
        counts[key] += len(buffers[key])
        buffers[key].clear()

    cursor = db.execute("SELECT payload,family_id,split,assignment_reason,duplicate_of,eligible FROM docs ORDER BY rowid")
    for payload_json, family, split, reason, duplicate_of, eligible in cursor:
        doc = json.loads(payload_json)
        doc["family_id"] = str(family)
        doc["split"] = str(split)
        doc["split_version"] = "split_preview_v1"
        doc["split_policy"] = "group_hash"
        doc["assignment_reason"] = str(reason)
        doc["seed"] = seed
        buffers["assignments"].append(doc)
        if duplicate_of:
            buffers["duplicates"].append(doc)
        elif eligible:
            buffers[str(split)].append(doc)
        else:
            buffers["quarantine"].append(doc)
        for key in ("assignments", str(split) if eligible and not duplicate_of else "duplicates" if duplicate_of else "quarantine"):
            if len(buffers[key]) >= FLUSH_ROWS:
                flush(key)
    for key in paths:
        flush(key)
        if key not in writers:
            pq.write_table(pa.Table.from_pylist([], schema=schema), paths[key], compression="zstd")
    for writer in writers.values():
        writer.close()
    counts["documents"] = counts["assignments"]
    return counts


def main() -> int:
    args = parse_args()
    if not (len(args.part) == len(args.part_index) == len(args.extraction_root)):
        raise ValueError("repeat --part, --part-index, and --extraction-root the same number of times")
    if args.train <= 0 or args.validation <= 0 or args.train + args.validation >= 1:
        raise ValueError("train and validation proportions must be positive and leave a positive test share")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    work_path = args.output_dir.parent / f".{args.output_dir.name}.work.sqlite"
    if work_path.exists():
        raise FileExistsError(f"work database already exists; inspect before retrying: {work_path}")

    graph_db = args.output_dir.parent / f".{args.output_dir.name}.family-graph.sqlite"
    code_family, code_props, prop_metadata, graph_counts = build_graph(args.source_index, args.propositions_zip, graph_db)
    graph_db.unlink(missing_ok=True)

    db = sqlite3.connect(work_path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(
        "CREATE TABLE docs (item_id TEXT PRIMARY KEY, family_id TEXT NOT NULL, text_sha TEXT NOT NULL, "
        "eligible INTEGER NOT NULL, duplicate_of TEXT NOT NULL DEFAULT '', split TEXT, assignment_reason TEXT, payload TEXT NOT NULL);"
        "CREATE INDEX docs_text_sha ON docs(text_sha);"
        "CREATE INDEX docs_family ON docs(family_id);"
        "CREATE TABLE text_families (text_sha TEXT PRIMARY KEY, family_id TEXT NOT NULL);"
    )
    family_uf = UnionFind()
    source_archives = []
    pdf_count = 0
    non_pdf_count = 0
    for part, part_index, extraction_root in zip(args.part, args.part_index, args.extraction_root):
        complete_path = extraction_root / "COMPLETE.json"
        if not complete_path.exists():
            raise RuntimeError(f"missing extraction completion marker: {complete_path}")
        complete = json.loads(complete_path.read_text())
        if complete.get("status") not in {
            "complete_for_indexed_pdfs_only", "extraction_complete_manual_review_pending",
            "published_extraction_complete_manual_review_pending", "complete_for_indexed_archive",
        }:
            raise RuntimeError(f"archive is not complete for indexed PDFs: {extraction_root.name} ({complete.get('status')})")
        one_pdf, one_non_pdf = add_archive_docs(
            db, family_uf, part, part_index, extraction_root, code_family, code_props, prop_metadata
        )
        pdf_count += one_pdf
        non_pdf_count += one_non_pdf
        db.commit()
        extraction_manifest_path = extraction_root / "publication_manifest.json"
        extraction_manifest = json.loads(extraction_manifest_path.read_text()) if extraction_manifest_path.exists() else {}
        archive_path = extraction_root.parent.parent / "publication-download" / f"{part}.tar"
        source_archives.append({
            "archive": f"{part}.tar",
            "sha256": sha256_file(archive_path) if archive_path.exists() else extraction_manifest.get("source_archive_sha256"),
            "index_sha256": sha256_file(part_index),
            "raw_repo_revision": extraction_manifest.get("source_raw_revision"),
            "pdf_count": one_pdf,
            "non_pdf_count": one_non_pdf,
        })
        print(json.dumps({"event": "archive_staged", "archive": part, "pdfs": one_pdf, "non_pdf": one_non_pdf}, ensure_ascii=False), flush=True)

    duplicate_groups, duplicate_count = mark_exact_duplicates(db)
    merged_families, family_count = merged_family_ids(db, family_uf)
    db.executemany("UPDATE docs SET family_id=? WHERE family_id=?", [(final, base) for base, final in merged_families.items()])
    db.commit()

    family_ids = sorted(set(merged_families.values()))
    split_by_family = assign_splits_with_r(
        family_ids, args.output_dir, args.repo_root, args.rscript, args.seed, args.train, args.validation
    )
    db.executemany(
        "UPDATE docs SET split=?,assignment_reason=? WHERE family_id=?",
        [(split, reason, family) for family, (split, reason) in split_by_family.items()],
    )
    db.commit()

    # Explicitly verify that each family maps to exactly one split.
    family_split_counts = db.execute("SELECT COUNT(DISTINCT split) FROM docs GROUP BY family_id HAVING COUNT(DISTINCT split)>1").fetchone()
    if family_split_counts:
        raise RuntimeError("family leakage detected across splits")

    output_counts = write_outputs(db, args.output_dir, split_by_family, args.seed)
    manifest = {
        "schema_version": "1.0.0",
        "status": "provisional_family_split",
        "source_archives": source_archives,
        "full_source_index_sha256": sha256_file(args.source_index),
        "official_proposition_snapshot": args.propositions_zip.name,
        "official_proposition_snapshot_sha256": sha256_file(args.propositions_zip),
        "split_version": "split_preview_v1",
        "policy": "group_hash",
        "target_proportions": {"train": args.train, "validation": args.validation, "test": 1 - args.train - args.validation},
        "seed": args.seed,
        "family_graph": "official proposition links (uriPropAnterior/Principal/Posterior), shared codteor URLs, exact source SHA-256, and exact extracted-text SHA-256 across all selected parts",
        "family_count": family_count,
        "source_document_count": output_counts["documents"],
        "pdf_count": pdf_count,
        "non_pdf_count": non_pdf_count,
        "accepted_unique_text_counts": {split: output_counts[split] for split in SPLITS},
        "quarantine_count": output_counts["quarantine"],
        "exact_duplicate_count": duplicate_count,
        "exact_duplicate_group_count": duplicate_groups,
        "graph_input_counts": graph_counts,
        "limitations": [
            "This is a preview split, not the final corpus release.",
            "Near-duplicate and containment detection have not run.",
            "Manual/visual quality review has not run; only automatic page gates were applied.",
            "The project-owned collection complements have not been reconciled.",
            "All selected TARs are grouped before splitting; adding sources or relations requires recomputing this preview.",
            "All non-PDF records remain quarantined pending document review.",
        ],
        "files": {},
    }
    for path in sorted(args.output_dir.glob("*.parquet")):
        manifest["files"][path.name] = {
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "row_count": pq.ParquetFile(path).metadata.num_rows,
        }
    (args.output_dir / "publication_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "COMPLETE.json").write_text(json.dumps({
        "status": "provisional_family_split",
        "manifest": "publication_manifest.json",
        "manifest_sha256": sha256_file(args.output_dir / "publication_manifest.json"),
    }, indent=2) + "\n")
    first_part, last_part = args.part[0][-3:], args.part[-1][-3:]
    (args.output_dir / "README.md").write_text(
        f"# Prévia de divisões dos lotes {first_part}–{last_part}\n\n"
        "Parquets determinísticos 80/10/10 por família documental (`group_hash`, seed 42), calculados após agrupar conjuntamente todos os TARs listados no manifesto. "
        "A prévia é exploratória, não uma release final para treinamento: revisão aproximada/containment, revisão visual/manual, complementos da coleta própria e fechamento do escopo ainda estão pendentes. "
        "Itens não PDF e itens reprovados nos gates automáticos ficam em `quarantine.parquet`.\n"
    )
    db.close()
    work_path.unlink(missing_ok=True)
    Path(str(work_path) + "-wal").unlink(missing_ok=True)
    Path(str(work_path) + "-shm").unlink(missing_ok=True)
    print(json.dumps({"status": "provisional_family_split", "archives": len(source_archives), "pdfs": pdf_count, "non_pdf": non_pdf_count, "families": family_count, "counts": output_counts, "exact_duplicate_count": duplicate_count}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
