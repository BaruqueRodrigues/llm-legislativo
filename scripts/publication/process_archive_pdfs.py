#!/usr/bin/env python3
"""Extract every indexed PDF from a verified archive in restartable batches."""

from __future__ import annotations

import argparse
import csv
import concurrent.futures
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path


MAX_WORKERS = 8


def validate_workers(workers: int) -> None:
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pdf_index(index_path: Path, archive_name: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    with index_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            member = row["membro_tar"]
            if row["tar"] != archive_name or row["status"] != "listado":
                continue
            media_type = (row.get("source_media_type") or "").strip().lower()
            if not member.lower().endswith(".pdf") and media_type not in {"pdf", "application/pdf"}:
                continue
            if row.get("content_eligible", "true").strip().lower() in {"0", "false", "no"}:
                continue
            if member.startswith("/") or ".." in Path(member).parts:
                raise ValueError(f"unsafe archive member path: {member}")
            if member in result:
                raise ValueError(f"duplicate member in source index: {member}")
            result[member] = row
    return result


def write_source_map(path: Path, rows: list[dict[str, str]], archive_sha: str) -> None:
    extra_fields = (
        "house", "source_namespace", "source_document_id", "document_id",
        "process_ids_json", "source_ids_json", "record_kinds_json", "query_years_json",
    )
    fields = ["archive", "archive_sha256", "member", "version_id", "source_url", "file_sha256", "size_bytes"]
    if any(any(row.get(field) for field in extra_fields) for row in rows):
        fields.extend(extra_fields)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            document_id = row.get("document_id", "")
            version_id = row.get("version_id", "") or "doc:v1:" + Path(row["membro_tar"]).stem
            writer.writerow(
                {
                    "archive": row["tar"],
                    "archive_sha256": archive_sha,
                    "member": row["membro_tar"],
                    "version_id": version_id,
                    "source_url": row["url"],
                    "file_sha256": row["sha256"],
                    "size_bytes": row["tamanho"],
                    **({field: row.get(field, "") for field in extra_fields} if document_id else {}),
                }
            )


def write_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(checkpoint, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--rscript", default="Rscript")
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--workers", type=int, default=1,
                        help=f"bounded concurrent PDFKit/Vision batch processes (1–{MAX_WORKERS})")
    parser.add_argument("--source-revision", default="")
    parser.add_argument("--house", choices=("camara", "senado"), default="camara")
    parser.add_argument("--source-raw-repo", default="BaruqRodrigues/camara-corpus-raw")
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    try:
        validate_workers(args.workers)
    except ValueError as exc:
        parser.error(f"--workers {exc}")

    archive_stem = args.archive.stem
    extraction_root = args.data_root / "staging" / "extraction"
    if args.house == "senado":
        extraction_root = extraction_root / "senado"
    output_root = extraction_root / f"{archive_stem}-batched"
    temp_root = extraction_root / f"{archive_stem}-work"
    output_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    lock_path = extraction_root / ".locks" / f"{archive_stem}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    driver_lock = lock_path.open("a", encoding="utf-8")
    try:
        fcntl.flock(driver_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        driver_lock.close()
        raise RuntimeError(f"another extraction driver holds {lock_path}") from exc

    actual_archive_sha = sha256_file(args.archive)
    if actual_archive_sha != args.expected_archive_sha256:
        raise RuntimeError(
            f"archive SHA-256 mismatch: expected {args.expected_archive_sha256}, got {actual_archive_sha}"
        )
    pdf_index = load_pdf_index(args.index, args.archive.name)
    if not pdf_index:
        raise RuntimeError("the source index has no eligible PDF members for this archive")
    with args.index.open(newline="", encoding="utf-8") as index_stream:
        eligible_non_pdf = {
            row["membro_tar"]
            for row in csv.DictReader(index_stream)
            if row["tar"] == args.archive.name
            and row["status"] == "listado"
            and not row["membro_tar"].lower().endswith(".pdf")
            and (row.get("source_media_type") or "").strip().lower() not in {"pdf", "application/pdf"}
            and row.get("content_eligible", "true").strip().lower() not in {"0", "false", "no"}
        }

    checkpoint_path = output_root / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {
        "archive": args.archive.name,
        "archive_sha256": actual_archive_sha,
        "expected_pdf_count": len(pdf_index),
        "batch_size": args.batch_size,
        "completed_batches": [],
        "processed_pdf_count": 0,
        "unsupported_non_pdf_count": 0,
    }
    if checkpoint["archive_sha256"] != actual_archive_sha:
        raise RuntimeError("checkpoint belongs to a different archive revision")
    if checkpoint.get("expected_pdf_count") != len(pdf_index):
        raise RuntimeError("checkpoint PDF count differs from the current source index")
    if checkpoint.get("batch_size") != args.batch_size:
        raise RuntimeError("checkpoint batch size differs; resume with its original --batch-size")
    completed = set(checkpoint["completed_batches"])
    current_rows: list[dict[str, str]] = []
    batch_number = 0
    pdf_number = 0
    non_pdf_count = 0

    def extract_batch(rows: list[dict[str, str]], number: int) -> None:
        batch_name = f"batch-{number:04d}"
        batch_input = temp_root / batch_name / "input"
        batch_output = output_root / batch_name
        if not batch_input.is_dir():
            raise RuntimeError(f"materialized input for {batch_name} is missing")
        if batch_output.exists():
            shutil.rmtree(batch_output)
        source_map = batch_input.parent / "source_members.csv"
        write_source_map(source_map, rows, actual_archive_sha)
        env = os.environ.copy()
        env["DATA_ROOT"] = str(args.data_root)
        command = [
            args.rscript,
            str(args.repo_root / "scripts" / "extract.R"),
            "--mode",
            "auto",
            "--input-dir",
            str(batch_input),
            "--output-dir",
            str(batch_output),
            "--run-id",
            f"{archive_stem}_batch_{number:04d}",
            "--skip-benchmark",
        ]
        subprocess.run(command, cwd=args.repo_root, env=env, check=True)
        shutil.copy2(source_map, batch_output / "source_members.csv")

    pending: dict[concurrent.futures.Future[None], tuple[int, int]] = {}

    def record_finished(block: bool) -> None:
        if not pending:
            return
        if block:
            done, _ = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
        else:
            done = {future for future in pending if future.done()}
        for future in done:
            number, row_count = pending.pop(future)
            future.result()
            checkpoint["completed_batches"].append(number)
            checkpoint["completed_batches"].sort()
            checkpoint["processed_pdf_count"] += row_count
            checkpoint["updated_at_utc"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()
            write_checkpoint(checkpoint_path, checkpoint)
            print(json.dumps({
                "event": "batch_complete",
                "batch": number,
                "pdfs": row_count,
                "total": checkpoint["processed_pdf_count"],
                "workers": args.workers,
            }), flush=True)
            shutil.rmtree(temp_root / f"batch-{number:04d}")

    def submit_batch(executor: concurrent.futures.ThreadPoolExecutor,
                     rows: list[dict[str, str]], number: int) -> None:
        if not rows or number in completed:
            return
        future = executor.submit(extract_batch, list(rows), number)
        pending[future] = (number, len(rows))

    # Warm the shared Swift helper once before concurrent R processes start. This
    # prevents two first-run workers racing to compile into the same DATA_ROOT cache.
    if args.workers > 1:
        env = os.environ.copy()
        env["DATA_ROOT"] = str(args.data_root)
        preflight = (
            "source('R/extraction/preflight.R'); "
            "p <- run_extraction_preflight(); "
            "if (!isTRUE(p$preflight_passed)) stop('Apple Vision preflight failed')"
        )
        compile_lock_path = args.data_root / "cache" / "macos" / "extraction" / ".preflight.lock"
        compile_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with compile_lock_path.open("a", encoding="utf-8") as compile_lock:
            fcntl.flock(compile_lock.fileno(), fcntl.LOCK_EX)
            subprocess.run(
                [args.rscript, "--vanilla", "-e", preflight],
                cwd=args.repo_root,
                env=env,
                check=True,
            )

    # One sequential TAR reader verifies and stages bounded batches; independent
    # R/PDFKit/Vision processes consume those batches with parent-owned checkpoints.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        with tarfile.open(args.archive, mode="r|") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                indexed = pdf_index.get(member.name)
                if indexed is None:
                    if member.name in eligible_non_pdf:
                        non_pdf_count += 1
                    continue
                this_batch = pdf_number // args.batch_size + 1
                if this_batch not in completed:
                    if pdf_number % args.batch_size == 0:
                        record_finished(block=False)
                        while len(pending) >= args.workers:
                            record_finished(block=True)
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise RuntimeError(f"could not read TAR member {member.name}")
                    destination = temp_root / f"batch-{this_batch:04d}" / "input" / (Path(member.name).stem + ".pdf")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with destination.open("wb") as output:
                        for block in iter(lambda: extracted.read(1024 * 1024), b""):
                            digest.update(block)
                            output.write(block)
                    if digest.hexdigest() != indexed["sha256"]:
                        raise RuntimeError(f"member SHA-256 mismatch for {member.name}")
                    current_rows.append(indexed)
                pdf_number += 1
                if pdf_number % args.batch_size == 0:
                    submit_batch(executor, current_rows, this_batch)
                    current_rows = []
            if pdf_number % args.batch_size:
                last_batch = (pdf_number - 1) // args.batch_size + 1
                submit_batch(executor, current_rows, last_batch)
            while pending:
                record_finished(block=True)

    if pdf_number != len(pdf_index):
        raise RuntimeError(f"TAR contained {pdf_number} indexed PDFs, index expects {len(pdf_index)}")
    checkpoint["unsupported_non_pdf_count"] = non_pdf_count
    checkpoint["status"] = "pdf_extraction_complete_non_pdf_pending"
    write_checkpoint(checkpoint_path, checkpoint)
    (output_root / "README.md").write_text(
        f"# Extração parcial do lote {args.archive.name}\n\n"
        f"TAR SHA-256: `{actual_archive_sha}`. Foram extraídos {pdf_number} PDFs em blocos retomáveis; "
        f"{non_pdf_count} membros não PDF permanecem pendentes de adaptadores e classificação. "
        "Este artefato não contém divisões globais de treino/validação/teste.\n"
    )
    non_pdf_path = output_root / "non_pdf_pending.csv"
    with non_pdf_path.open("w", newline="", encoding="utf-8") as stream:
        fields = ["archive", "member", "source_url", "file_sha256", "size_bytes", "status"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        with args.index.open(newline="", encoding="utf-8") as index_stream:
            for row in csv.DictReader(index_stream):
                if (row["tar"] == args.archive.name and row["status"] == "listado"
                    and not row["membro_tar"].lower().endswith(".pdf")
                    and (row.get("source_media_type") or "").strip().lower() not in {"pdf", "application/pdf"}
                    and row.get("content_eligible", "true").strip().lower() not in {"0", "false", "no"}):
                    writer.writerow({
                        "archive": row["tar"],
                        "member": row["membro_tar"],
                        "source_url": row["url"],
                        "file_sha256": row["sha256"],
                        "size_bytes": row["tamanho"],
                        "status": "pending_no_adapter_or_content_classification",
                    })
    batch_records = []
    for batch_dir in sorted(output_root.glob("batch-*")):
        batch_manifest_path = batch_dir / "extraction_manifest.json"
        if not batch_manifest_path.exists():
            continue
        batch_manifest = json.loads(batch_manifest_path.read_text())
        batch_records.append({
            "batch": batch_dir.name,
            "manifest_sha256": sha256_file(batch_manifest_path),
            "summary": batch_manifest["summary"],
            "files": batch_manifest["files"],
        })
    release_manifest = {
        "schema_version": "1.0.0",
        "stage": "partial_extraction",
        "source_archive": args.archive.name,
        "source_archive_sha256": actual_archive_sha,
        "source_raw_repo": args.source_raw_repo,
        "house": args.house,
        "source_raw_revision": args.source_revision or None,
        "source_index_sha256": sha256_file(args.index),
        "processed_format": "PDF",
        "processed_pdf_count": pdf_number,
        "pending_non_pdf_count": non_pdf_count,
        "global_train_validation_test_splits": False,
        "batches": batch_records,
    }
    release_manifest_path = output_root / "publication_manifest.json"
    release_manifest_path.write_text(json.dumps(release_manifest, indent=2) + "\n")
    complete = {
        "status": "complete_for_indexed_pdfs_only",
        "manifest": release_manifest_path.name,
        "manifest_sha256": sha256_file(release_manifest_path),
        "created_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
    (output_root / "COMPLETE.json").write_text(json.dumps(complete, indent=2) + "\n")
    print(json.dumps({"event": "archive_pdfs_complete", "pdfs": pdf_number, "non_pdf_pending": non_pdf_count}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
