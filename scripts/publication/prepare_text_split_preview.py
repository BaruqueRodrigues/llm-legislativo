#!/usr/bin/env python3
"""Build a reproducible, explicitly provisional family split for one extracted TAR.

The family graph is built from the complete received TAR index plus the official
annual Câmara proposition snapshots. This prevents known proposition relations,
document URLs, and exact raw-file duplicates from crossing splits. Text-identical
documents in the selected extraction are also joined before assignment.

This is a split preview, not the canonical curated release: near-duplicate review,
manual quality review, own-collection complements, and final whole-corpus
reconciliation remain required.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import subprocess
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import pyarrow as pa
import pyarrow.parquet as pq


CODE_RE = re.compile(r"[?&]codteor=([^&#]+)", re.IGNORECASE)
PROP_RE = re.compile(r"/proposicoes/(\d+)(?:[/?#]|$)", re.IGNORECASE)
RELATION_FIELDS = ("uriPropAnterior", "uriPropPrincipal", "uriPropPosterior")
SPLITS = ("train", "validation", "test")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_from_url(value: str | None) -> str | None:
    match = CODE_RE.search(value or "")
    return match.group(1) if match else None


def prop_id_from_uri(value: str | None) -> str | None:
    match = PROP_RE.search(value or "")
    return match.group(1) if match else None


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def add(self, item: str) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0

    def find(self, item: str) -> str:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left == root_right:
            return
        if self.rank[root_left] < self.rank[root_right]:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left
        if self.rank[root_left] == self.rank[root_right]:
            self.rank[root_left] += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", required=True, action="append", help="TAR stem; repeat for a combined preview")
    parser.add_argument("--source-index", required=True, type=Path, help="Full indice_tar2.csv")
    parser.add_argument("--part-index", required=True, action="append", type=Path, help="Verified per-TAR manifest CSV; pair with --part")
    parser.add_argument("--propositions-zip", required=True, type=Path)
    parser.add_argument("--extraction-root", required=True, action="append", type=Path, help="Processed TAR root; repeat for combined preview")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed", default=42, type=int)
    parser.add_argument("--train", default=0.80, type=float)
    parser.add_argument("--validation", default=0.10, type=float)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--rscript", default="Rscript")
    return parser.parse_args()


def build_graph(source_index: Path, props_zip: Path, work_db: Path) -> tuple[dict[str, str], dict[str, list[str]], dict[str, dict[str, str]], dict[str, int]]:
    """Return codteor->family, codteor->proposal IDs, proposal metadata, counters."""
    if work_db.exists():
        work_db.unlink()
    db = sqlite3.connect(work_db)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("CREATE TABLE raw_docs (code TEXT, sha256 TEXT, part TEXT, status TEXT)")
    code_set: set[str] = set()
    raw_count = 0
    no_code_count = 0
    with source_index.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        buffer = []
        for row in reader:
            if row.get("status") != "listado":
                continue
            raw_count += 1
            code = code_from_url(row.get("url"))
            if not code:
                no_code_count += 1
                continue
            code_set.add(code)
            buffer.append((code, row["sha256"].lower(), row["tar"], row["status"]))
            if len(buffer) >= 20_000:
                db.executemany("INSERT INTO raw_docs VALUES (?,?,?,?)", buffer)
                buffer.clear()
        if buffer:
            db.executemany("INSERT INTO raw_docs VALUES (?,?,?,?)", buffer)
    db.commit()
    db.execute("CREATE INDEX raw_docs_code ON raw_docs(code)")
    db.execute("CREATE INDEX raw_docs_sha ON raw_docs(sha256)")
    db.execute("CREATE TABLE doc_prop (code TEXT, proposition_id TEXT)")

    uf = UnionFind()
    code_props: dict[str, list[str]] = defaultdict(list)
    prop_metadata: dict[str, dict[str, str]] = {}
    relation_rows = 0
    scanned_props = 0
    with zipfile.ZipFile(props_zip) as archive:
        csv_names = [n for n in archive.namelist() if n.endswith(".csv")]
        for name in csv_names:
            with archive.open(name) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""), delimiter=";")
                for row in reader:
                    pid = (row.get("id") or "").strip()
                    if not pid:
                        continue
                    scanned_props += 1
                    pid = pid.removeprefix("camara:prop:")
                    uf.add(pid)
                    for field in RELATION_FIELDS:
                        related = prop_id_from_uri(row.get(field))
                        if related:
                            uf.union(pid, related)
                            relation_rows += 1
                    code = code_from_url(row.get("urlInteiroTeor"))
                    if code and code in code_set:
                        code_props[code].append(pid)
                        prop_metadata[pid] = {
                            "sigla_tipo": row.get("siglaTipo") or "",
                            "numero": row.get("numero") or "",
                            "ano": row.get("ano") or "",
                            "data_apresentacao": row.get("dataApresentacao") or "",
                            "ementa": row.get("ementa") or "",
                        }

    for code, ids in code_props.items():
        for pid in ids[1:]:
            uf.union(ids[0], pid)

    # Equal source bytes are one family edge even if recorded under different URLs.
    first_prop_for_sha: dict[str, str] = {}
    cur = db.execute("SELECT code, sha256 FROM raw_docs ORDER BY rowid")
    for code, file_sha in cur:
        pids = code_props.get(code)
        if not pids:
            continue
        prior = first_prop_for_sha.get(file_sha)
        if prior:
            uf.union(prior, pids[0])
        else:
            first_prop_for_sha[file_sha] = pids[0]
    db.close()

    component_members: dict[str, list[str]] = defaultdict(list)
    for pid in uf.parent:
        component_members[uf.find(pid)].append(f"camara:prop:{pid}")
    root_family: dict[str, str] = {}
    for root, members in component_members.items():
        member_string = "|".join(sorted(set(members)))
        root_family[root] = "fam:" + sha256_bytes(member_string.encode("utf-8"))
    code_family: dict[str, str] = {}
    for code, ids in code_props.items():
        roots = {uf.find(pid) for pid in ids}
        if len(roots) != 1:
            raise RuntimeError(f"official proposition links were not united for codteor={code}")
        code_family[code] = root_family[next(iter(roots))]
    counters = {
        "raw_listed_member_count": raw_count,
        "raw_members_without_codteor": no_code_count,
        "official_proposition_rows_scanned": scanned_props,
        "official_relation_edges_seen": relation_rows,
        "raw_codteor_count": len(code_set),
        "codteor_with_proposition_match": len(code_props),
        "proposition_family_count": len(component_members),
    }
    return code_family, code_props, prop_metadata, counters


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def main() -> int:
    args = parse_args()
    if args.train <= 0 or args.validation <= 0 or args.train + args.validation >= 1:
        raise ValueError("train and validation proportions must be positive and leave a positive test share")
    if not (len(args.part) == len(args.part_index) == len(args.extraction_root)):
        raise ValueError("repeat --part, --part-index, and --extraction-root the same number of times")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    graph_db = out.parent / f".{out.name}.family-graph.sqlite"
    code_family, code_props, prop_metadata, graph_counts = build_graph(
        args.source_index, args.propositions_zip, graph_db
    )
    graph_db.unlink(missing_ok=True)

    # Pair each selected part with its verified index and extraction root.
    source_rows: dict[tuple[str, str], dict[str, str]] = {}
    for part, part_index in zip(args.part, args.part_index):
        with part_index.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                if row.get("tar") == f"{part}.tar" and row.get("status") == "listado":
                    source_rows[(f"{part}.tar", row["membro_tar"])] = row

    expected_pdf_keys = {
        key for key, row in source_rows.items() if row["membro_tar"].lower().endswith(".pdf")
    }
    pdf_records: list[tuple[dict[str, str], dict[str, str], dict[str, object], list[dict[str, object]]]] = []
    non_pdf: list[dict[str, object]] = []
    seen_pdf_keys: set[tuple[str, str]] = set()
    for part, root in zip(args.part, args.extraction_root):
        if not root.name.startswith(part):
            raise RuntimeError(f"extraction root {root} does not correspond to {part}")
        for batch in sorted(root.glob("batch-*")):
            map_path = batch / "source_members.csv"
            with map_path.open(newline="", encoding="utf-8") as stream:
                batch_sources = list(csv.DictReader(stream))
            run_table = pq.read_table(batch / "extraction_runs.parquet", columns=["extraction_id", "version_id", "status", "error_code"])
            batch_runs = {r["version_id"]: r for r in run_table.to_pylist()}
            page_table = pq.read_table(batch / "pages.parquet", columns=["extraction_id", "page_index", "method", "raw_text", "quality_status"])
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
                pdf_records.append((source, indexed, run, page_rows))
                seen_pdf_keys.add(key)
            batch_pages.clear()
        non_pdf.extend(pq.read_table(root / "non_pdf_text.parquet").to_pylist())
    if seen_pdf_keys != expected_pdf_keys:
        raise RuntimeError(f"PDF source coverage mismatch: mapped={len(seen_pdf_keys)}, expected={len(expected_pdf_keys)}")

    docs: list[dict[str, object]] = []
    for source, indexed, run, page_rows in sorted(pdf_records, key=lambda r: (r[0]["archive"], r[0]["member"])):
        raw_version_id = source["version_id"]
        text = "\n\f\n".join(str(r["raw_text"] or "") for r in page_rows)
        all_pass = bool(page_rows) and all(r["quality_status"] == "pass" and r["method"] != "none" for r in page_rows)
        accepted = run["status"] == "succeeded" and all_pass and bool(text.strip())
        url = source["source_url"]
        code = code_from_url(url)
        family = code_family.get(code or "") or "fam:" + sha256_bytes(f"camara:unmapped:{code or indexed['sha256']}".encode())
        extraction_id = run["extraction_id"]
        doc_id = f"camara:doc:camara_api:codteor:{code}" if code else "camara:doc:url:" + sha256_bytes(url.encode())
        version_id = f"{doc_id}:v:{indexed['sha256'].lower()}"
        canonical_meta = {"document_id": doc_id, "version_id": version_id, "extraction_id": extraction_id, "logical_unit_id": doc_id, "composition_id": None}
        item_id = "item:" + sha256_bytes(compact_json(canonical_meta).encode("utf-8"))
        text_sha = sha256_bytes(text.encode("utf-8"))
        linked_ids = sorted(code_props.get(code or "", []))
        meta = prop_metadata.get(linked_ids[0], {}) if linked_ids else {}
        docs.append({
            "corpus_item_id": item_id,
            "document_id": doc_id,
            "version_id": version_id,
            "source_extraction_version_id": raw_version_id,
            "extraction_id": extraction_id,
            "source_archive": source["archive"],
            "source_member": source["member"],
            "source_url": url,
            "source_file_sha256": indexed["sha256"],
            "source_format": "pdf",
            "codteor": code or "",
            "proposition_ids_json": compact_json([f"camara:prop:{p}" for p in linked_ids]),
            "proposition_type": meta.get("sigla_tipo", ""), "proposition_number": meta.get("numero", ""),
            "proposition_year": meta.get("ano", ""), "presentation_date": meta.get("data_apresentacao", ""),
            "ementa": meta.get("ementa", ""),
            "family_id": family,
            "text": text, "text_sha256": text_sha, "character_count": len(text), "utf8_bytes": len(text.encode("utf-8")),
            "quality_status": "accepted" if accepted else "quarantined",
            "quality_reasons_json": compact_json([] if accepted else [
                reason for reason, condition in [
                    ("extraction_not_succeeded", run["status"] != "succeeded"),
                    ("page_quality_or_method_gate_failed", not all_pass),
                    ("empty_text", not text.strip()),
                ] if condition
            ]),
            "include_in_dataset": accepted, "duplicate_of_corpus_item_id": "", "page_count": len(page_rows),
            "page_methods_json": compact_json(dict(Counter(str(r["method"]) for r in page_rows))),
            "page_quality_json": compact_json(dict(Counter(str(r["quality_status"]) for r in page_rows))),
        })

    # Include HTML/DOC source records in the assignment/quarantine sidecar, but
    # never promote them to train before their declared manual review is done.
    for src in non_pdf:
        code = code_from_url(src.get("source_url"))
        family = code_family.get(code or "")
        if not family:
            family = "fam:" + sha256_bytes(f"camara:unmapped:{code or src['file_sha256']}".encode())
        raw_version_id = f"doc:v1:{Path(src['archive_member']).stem}"
        doc_id = f"camara:doc:camara_api:codteor:{code}" if code else "camara:doc:url:" + sha256_bytes(src["source_url"].encode())
        version_id = f"{doc_id}:v:{src['file_sha256'].lower()}"
        txt = src.get("text") or ""
        extraction_id = "nonpdf:" + raw_version_id + ":" + src["file_sha256"]
        canonical_meta = {"document_id": doc_id, "version_id": version_id, "extraction_id": extraction_id, "logical_unit_id": doc_id, "composition_id": None}
        docs.append({
            "corpus_item_id": "item:" + sha256_bytes(compact_json(canonical_meta).encode("utf-8")),
            "document_id": doc_id,
            "version_id": version_id,
            "source_extraction_version_id": raw_version_id,
            "extraction_id": extraction_id,
            "source_archive": src["archive"],
            "source_member": src["archive_member"],
            "source_url": src["source_url"],
            "source_file_sha256": src["file_sha256"],
            "source_format": src["format"],
            "codteor": code or "",
            "proposition_ids_json": compact_json([f"camara:prop:{p}" for p in sorted(code_props.get(code or "", []))]),
            "proposition_type": "", "proposition_number": "", "proposition_year": "", "presentation_date": "", "ementa": "",
            "family_id": family,
            "text": txt,
            "text_sha256": sha256_bytes(txt.encode("utf-8")),
            "character_count": len(txt),
            "utf8_bytes": len(txt.encode("utf-8")),
            "quality_status": "quarantined",
            "quality_reasons_json": compact_json([src.get("quality_status", "review"), src.get("review_status", "manual_review_pending")]),
            "include_in_dataset": False,
            "duplicate_of_corpus_item_id": "",
            "page_count": 1,
            "page_methods_json": compact_json({src.get("adapter", "nonpdf"): 1}),
            "page_quality_json": compact_json({src.get("quality_status", "review"): 1}),
        })

    # Exact text duplicates are linked before assigning families, preventing
    # identical contents from crossing train/validation/test.
    by_text: dict[str, list[int]] = defaultdict(list)
    for i, doc in enumerate(docs):
        if doc["text"]:
            by_text[str(doc["text_sha256"])].append(i)
    family_uf = UnionFind()
    for doc in docs:
        family_uf.add(str(doc["family_id"]))
    for ids in by_text.values():
        for i in ids[1:]:
            family_uf.union(str(docs[ids[0]]["family_id"]), str(docs[i]["family_id"]))
    merged_family_members: dict[str, set[str]] = defaultdict(set)
    for doc in docs:
        base = str(doc["family_id"])
        merged_family_members[family_uf.find(base)].add(base)
    merged_to_id = {
        root: members.pop() if len(members) == 1 else "fam:" + sha256_bytes("|".join(sorted(members)).encode("utf-8"))
        for root, members in merged_family_members.items()
    }
    for doc in docs:
        doc["family_id"] = merged_to_id[family_uf.find(str(doc["family_id"]))]

    # Pick exactly one eligible representative per exact-text cluster.
    for ids in by_text.values():
        if len(ids) < 2:
            continue
        candidates = sorted(ids, key=lambda i: (not bool(docs[i]["include_in_dataset"]), str(docs[i]["corpus_item_id"])))
        representative = candidates[0]
        for i in candidates[1:]:
            docs[i]["duplicate_of_corpus_item_id"] = str(docs[representative]["corpus_item_id"])
            docs[i]["include_in_dataset"] = False
            docs[i]["quality_reasons_json"] = compact_json(["exact_text_duplicate", str(docs[i]["quality_reasons_json"])])

    # Apply the repository's canonical R group_hash rule once per unique
    # family. Calling assign_splits() on every document repeatedly filters the
    # full 80k-row table per family (quadratic work), even though group_hash is
    # solely a function of (family_id, seed). Retaining R digest/hex math here
    # gives exactly the same assignments without changing split_engine.R.
    split_input = out.parent / f".{out.name}.split-input.parquet"
    split_result = out.parent / f".{out.name}.split-assignments.parquet"
    pq.write_table(
        pa.Table.from_pylist([{"corpus_item_id": d["corpus_item_id"], "family_id": d["family_id"]} for d in docs]),
        split_input,
    )
    r_script = out.parent / f".{out.name}.assign-splits.R"
    r_script.write_text(
        "args <- commandArgs(trailingOnly=TRUE)\n"
        "repo <- normalizePath(args[[1]])\n"
        "setwd(repo)\n"
        "source(file.path(repo, 'R', 'curation', 'split_engine.R'))\n"
        "input <- arrow::read_parquet(args[[2]])\n"
        "seed_val <- as.integer(args[[4]])\n"
        "p_train <- as.numeric(args[[5]])\n"
        "p_val <- as.numeric(args[[6]])\n"
        "families <- unique(input$family_id)\n"
        "hash_hex <- vapply(families, function(fam) digest::digest(paste0(fam, ':', seed_val), algo='sha256'), character(1))\n"
        "u_val <- as.numeric(paste0('0x', substr(hash_hex, 1, 8))) / 4294967296\n"
        "family_split <- ifelse(u_val < p_train, 'train', ifelse(u_val < p_train + p_val, 'validation', 'test'))\n"
        "row_family <- match(input$family_id, families)\n"
        "out <- tibble::tibble(split_version=rep('split_preview_v1', nrow(input)), corpus_item_id=input$corpus_item_id, family_id=input$family_id, split=family_split[row_family], policy=rep('group_hash', nrow(input)), assignment_reason=sprintf('%s sorteada para %s via group_hash (seed %d, u=%.4f)', input$family_id, family_split[row_family], seed_val, u_val[row_family]), seed=bit64::as.integer64(rep(seed_val, nrow(input))), temporal_cut_train=as.Date(rep(NA, nrow(input))), temporal_cut_validation=as.Date(rep(NA, nrow(input))))\n"
        "arrow::write_parquet(out, args[[3]])\n"
    )
    try:
        subprocess.run(
            [args.rscript, str(r_script), str(args.repo_root.resolve()), str(split_input), str(split_result), str(args.seed), str(args.train), str(args.validation)],
            cwd=args.repo_root,
            check=True,
        )
    finally:
        r_script.unlink(missing_ok=True)
        split_input.unlink(missing_ok=True)
    assignments = {r["corpus_item_id"]: r for r in pq.read_table(split_result).to_pylist()}
    split_result.unlink(missing_ok=True)
    if len(assignments) != len(docs):
        raise RuntimeError(f"R split engine returned {len(assignments)} assignments for {len(docs)} documents")
    for doc in docs:
        assignment = assignments[str(doc["corpus_item_id"])]
        doc["split"] = assignment["split"]
        doc["split_version"] = assignment["split_version"]
        doc["split_policy"] = assignment["policy"]
        doc["assignment_reason"] = assignment["assignment_reason"]
        doc["seed"] = int(assignment["seed"])

    # Invariant: a family gets exactly one split.
    family_splits: dict[str, set[str]] = defaultdict(set)
    for doc in docs:
        family_splits[str(doc["family_id"])].add(str(doc["split"]))
    if any(len(splits) != 1 for splits in family_splits.values()):
        raise RuntimeError("family leakage detected across splits")

    table = pa.Table.from_pylist(docs)
    pq.write_table(table, out / "split_assignments.parquet", compression="zstd")
    eligible = [d for d in docs if d["include_in_dataset"] and not d["duplicate_of_corpus_item_id"]]
    counts: dict[str, int] = {}
    for split in SPLITS:
        selected = [d for d in eligible if d["split"] == split]
        counts[split] = len(selected)
        pq.write_table(pa.Table.from_pylist(selected), out / f"{split}.parquet", compression="zstd")
    quarantine = [d for d in docs if not d["include_in_dataset"] and not d["duplicate_of_corpus_item_id"]]
    duplicates = [d for d in docs if d["duplicate_of_corpus_item_id"]]
    pq.write_table(pa.Table.from_pylist(quarantine), out / "quarantine.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(duplicates), out / "exact_duplicates.parquet", compression="zstd")

    source_archives = []
    for part, part_index, root in zip(args.part, args.part_index, args.extraction_root):
        archive_path = root.parent.parent / "publication-download" / f"{part}.tar"
        extraction_manifest_path = root / "publication_manifest.json"
        extraction_manifest = json.loads(extraction_manifest_path.read_text()) if extraction_manifest_path.exists() else {}
        archive_sha256 = (
            sha256_file(archive_path)
            if archive_path.exists()
            else extraction_manifest.get("source_archive_sha256")
        )
        source_archives.append({
            "archive": f"{part}.tar",
            "sha256": archive_sha256,
            "index_sha256": sha256_file(part_index),
            "raw_repo_revision": extraction_manifest.get("source_raw_revision"),
        })
    part_label = "+".join(args.part)
    manifest = {
        "schema_version": "1.0.0",
        "status": "provisional_family_split",
        "source_archives": source_archives,
        "full_source_index_sha256": sha256_file(args.source_index),
        "official_proposition_snapshot": str(args.propositions_zip.name),
        "official_proposition_snapshot_sha256": sha256_file(args.propositions_zip),
        "split_version": "split_preview_v1",
        "policy": "group_hash",
        "target_proportions": {"train": args.train, "validation": args.validation, "test": 1 - args.train - args.validation},
        "seed": args.seed,
        "family_graph": "official proposition links (uriPropAnterior/Principal/Posterior), shared codteor URLs, exact source SHA-256, and exact extracted-text SHA-256 across all selected parts",
        "family_count": len(family_splits),
        "source_document_count": len(docs),
        "pdf_count": len(pdf_records),
        "non_pdf_count": len(non_pdf),
        "accepted_unique_text_counts": counts,
        "quarantine_count": len(quarantine),
        "exact_duplicate_count": len(duplicates),
        "graph_input_counts": graph_counts,
        "limitations": [
            "This is a preview split, not the final corpus release.",
            "Near-duplicate and containment detection have not run.",
            "Manual/visual quality review has not run; only automatic page gates were applied.",
            "The project-owned collection complements have not been reconciled.",
            "After each TAR is processed, exact-text and family links are recomputed across processed parts; final splits are frozen only after corpus scope closes.",
            "All non-PDF records remain quarantined pending document review.",
        ],
        "files": {},
    }
    for path in sorted(out.glob("*.parquet")):
        manifest["files"][path.name] = {"size_bytes": path.stat().st_size, "sha256": sha256_file(path), "row_count": pq.ParquetFile(path).metadata.num_rows}
    (out / "publication_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (out / "COMPLETE.json").write_text(json.dumps({"status": "provisional_family_split", "manifest": "publication_manifest.json", "manifest_sha256": sha256_file(out / "publication_manifest.json")}, indent=2) + "\n")
    (out / "README.md").write_text(
        "# Divisões provisórias dos lotes " + part_label + "\n\n"
        "Partições determinísticas 80/10/10 por família documental (group_hash, seed 42). "
        "Esta prévia usa relações oficiais das proposições, codteor, hashes binários da fonte e hashes de texto idêntico entre todos os lotes já extraídos. "
        "Não é uma release final para treinamento: deduplicação aproximada/containment, revisão visual/manual, complementos da coleta própria e reconciliação de todos os lotes ainda estão pendentes. "
        "Os registros não PDF e itens reprovados automaticamente ficam em quarantine.parquet.\n"
    )
    print(json.dumps({"status": "provisional_family_split", "documents": len(docs), "families": len(family_splits), "eligible_unique_texts": counts, "quarantine": len(quarantine), "exact_duplicates": len(duplicates), "manifest_sha256": sha256_file(out / "publication_manifest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
