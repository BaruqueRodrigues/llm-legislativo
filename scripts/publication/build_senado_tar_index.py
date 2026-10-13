#!/usr/bin/env python3
"""Build and verify a Senate TAR member index from its embedded manifesto.csv."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import ntpath
import re
import tarfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit


INDEX_FIELDS = (
    "url", "sha256", "tar", "membro_tar", "offset_bytes", "tamanho", "status",
    "house", "source_namespace", "source_document_id", "document_id", "version_id",
    "process_ids_json", "source_ids_json", "record_kinds_json", "query_years_json",
    "source_http_status", "source_media_type", "content_eligible", "member_role",
    "manifest_attempt_count", "archive_source_uri",
)
MANIFEST_REQUIRED = {"url", "status", "tipo", "bytes", "arquivo"}
LINK_REQUIRED = {"source_id", "process_id", "record_kind", "query_year", "document_url"}
CHUNK_BYTES = 8 * 1024 * 1024


def sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
        digest.update(block)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def normalize_document_url(value: str) -> tuple[str, str] | None:
    parsed = urlsplit(value.strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    document_ids = query.get("dm", [])
    path = parsed.path.rstrip("/")
    if not parsed.scheme or not parsed.netloc:
        return None
    if path == "/sdleg-getter/documento":
        if len(document_ids) != 1 or not document_ids[0].strip():
            return None
        return ("dm", document_ids[0].strip())
    match = re.fullmatch(r"/sdleg-getter/dadosabertos/documento/([^/]+)/([^/]+)", path, flags=re.IGNORECASE)
    if match:
        return ("dadosabertos", match.group(1).lower() + "/" + match.group(2))
    return None
    return None


def read_source_links(path: Path) -> dict[tuple[str, str], list[dict[str, str]]]:
    links: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = LINK_REQUIRED.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Senate link index is missing columns: {sorted(missing)}")
        for row in reader:
            key = normalize_document_url(row["document_url"])
            if key is None:
                continue
            links[key].append(row)
    for rows in links.values():
        rows.sort(key=lambda row: (row["process_id"], row["source_id"], row["record_kind"]))
    return links


def read_source_links_by_url_hash(path: Path) -> dict[str, list[dict[str, str]]]:
    links: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            url = (row.get("document_url") or "").strip()
            if normalize_document_url(url) is not None:
                links[hashlib.sha256(url.encode("utf-8")).hexdigest()].append(row)
    for rows in links.values():
        rows.sort(key=lambda row: (row["process_id"], row["source_id"], row["record_kind"]))
    return links


def read_archive_manifest(archive: tarfile.TarFile) -> tuple[list[dict[str, str]] | None, str | None]:
    all_matches = [member for member in archive.getmembers() if PurePosixPath(member.name).name == "manifesto.csv"]
    if not all_matches:
        return None, None
    matches = [member for member in all_matches if member.name == "manifesto.csv"]
    if len(all_matches) != 1 or len(matches) != 1 or not matches[0].isfile():
        raise ValueError("archive manifesto.csv is duplicated, nested, or not a regular file")
    manifest_member = matches[0]
    stream = archive.extractfile(manifest_member)
    if stream is None:
        raise ValueError("could not read archive manifesto.csv")
    import io

    reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
    missing = MANIFEST_REQUIRED.difference(reader.fieldnames or [])
    if missing:
        raise ValueError(f"embedded manifesto.csv is missing columns: {sorted(missing)}")
    rows = list(reader)
    return rows, manifest_member.name


def sniff_member_media_type(archive: tarfile.TarFile, member: tarfile.TarInfo) -> str:
    stream = archive.extractfile(member)
    if stream is None:
        return "application/octet-stream"
    sample = stream.read(8192)
    prefix = sample[:4096]
    stripped = prefix.lstrip().lower()
    if b"%pdf-" in prefix.lower():
        return "application/pdf"
    if stripped.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html"
    suffix = PurePosixPath(member.name).suffix.lower()
    known = {
        ".csv": "text/csv", ".json": "application/json", ".txt": "text/plain",
        ".xml": "application/xml", ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return known.get(suffix, "application/octet-stream")


def is_error_html_response(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bool:
    stream = archive.extractfile(member)
    if stream is None:
        return True
    sample = stream.read(16 * 1024).decode("utf-8", errors="ignore").lower()
    markers = (
        "502 bad gateway", "503 service unavailable", "404 not found", "whitelabel error page",
        "access denied", "internal server error", "página não encontrada", "recurso não localizado",
    )
    return any(marker in sample for marker in markers)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--link-index", required=True, type=Path)
    parser.add_argument("--part", required=True, help="Expected TAR basename, e.g. part016.tar")
    parser.add_argument("--archive-source-uri", required=True, help="Drive folder URL containing this TAR")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    if args.archive.name != args.part:
        raise ValueError(f"archive filename mismatch: expected {args.part}, got {args.archive.name}")
    source_links = read_source_links(args.link_index)
    source_links_by_hash = read_source_links_by_url_hash(args.link_index)
    index_rows: list[dict[str, str]] = []
    attempt_rows: list[dict[str, str]] = []
    seen_members: set[str] = set()
    matched_documents = 0
    unmatched_documents = 0
    manifest_present = False
    missing_manifest_members: list[str] = []
    unlisted_tar_member_count = 0
    error_response_candidate_count = 0
    unclassified_member_count = 0

    with tarfile.open(args.archive, mode="r:") as archive:
        manifest_rows, _ = read_archive_manifest(archive)
        manifest_present = manifest_rows is not None
        members = [member for member in archive.getmembers() if member.isfile()]
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                raise ValueError(f"unsafe or non-portable archive member path: {member.name}")
            if member.name in seen_members:
                raise ValueError(f"duplicate TAR member name: {member.name}")
            seen_members.add(member.name)

        records_by_member: dict[str, list[dict[str, str]]] = defaultdict(list)
        if manifest_rows is not None:
            for row in manifest_rows:
                filename = ntpath.basename((row.get("arquivo") or "").strip())
                if filename:
                    records_by_member[filename].append(row)
            missing_manifest_members = sorted(set(records_by_member) - seen_members)
            for filename in missing_manifest_members:
                for attempt_no, row in enumerate(records_by_member[filename], start=1):
                    attempt_rows.append({
                        "archive": args.part, "archive_member": filename,
                        "source_url": row.get("url", ""), "response_status": row.get("status", ""),
                        "reported_type": row.get("tipo", ""), "reported_bytes": row.get("bytes", ""),
                        "attempt_no": str(attempt_no), "download_seconds": row.get("segundos_download", ""),
                        "persistence_seconds": row.get("segundos_persistencia", ""),
                        "classification": "manifest_entry_missing_from_tar",
                    })

        for member in members:
            member_path = PurePosixPath(member.name)
            suffix = member_path.suffix.lower()
            member_records = records_by_member.get(member.name, [])
            if member.name == "manifesto.csv":
                member_records = []
                archive_url = args.archive_source_uri.rstrip("/") + "#" + args.part
                source_url = archive_url
                source_status = ""
                media_type = "text/csv"
                eligible = False
                role = "archive_control_manifest"
                attempt_count = 0
                document_id = ""
                source_document_id = ""
                process_ids: list[str] = []
                source_ids: list[str] = []
                record_kinds: list[str] = []
                query_years: list[str] = []
                source_namespace = "senado_archive_control"
            else:
                has_manifest_entry = bool(member_records)
                if not member_records:
                    if manifest_present:
                        unlisted_tar_member_count += 1
                    link_rows_by_hash = source_links_by_hash.get(member_path.stem.lower(), [])
                    source_urls_by_hash = {row.get("document_url", "").strip() for row in link_rows_by_hash}
                    if len(source_urls_by_hash) > 1:
                        raise ValueError(f"conflicting source URLs for hashed TAR member: {member.name}")
                    fallback_url = next(iter(source_urls_by_hash)) if source_urls_by_hash else (
                        args.archive_source_uri.rstrip("/") + f"#{args.part}/{member.name}"
                    )
                    observed_type = sniff_member_media_type(archive, member)
                    member_records = [{
                        "arquivo": member.name, "url": fallback_url, "status": "",
                        "tipo": observed_type, "bytes": str(member.size),
                    }]
                urls = {row.get("url", "").strip() for row in member_records}
                if len(urls) != 1 or not next(iter(urls)):
                    raise ValueError(f"conflicting source URLs for TAR member: {member.name}")
                source_url = next(iter(urls))
                sizes = {int(row.get("bytes") or -1) for row in member_records}
                if sizes != {member.size}:
                    raise ValueError(f"embedded manifesto size differs from TAR member: {member.name}")
                statuses = {row.get("status", "").strip() for row in member_records}
                media_types = {row.get("tipo", "").strip().lower() for row in member_records}
                if len(statuses) != 1 or len(media_types) != 1:
                    raise ValueError(f"conflicting response status/type for TAR member: {member.name}")
                source_status = next(iter(statuses))
                media_type = next(iter(media_types))
                attempt_count = len(member_records)
                is_pdf = suffix == ".pdf" or media_type in {"pdf", "application/pdf"}
                eligible = is_pdf and (
                    (source_status == "200" and media_type == "pdf")
                    if has_manifest_entry else media_type in {"pdf", "application/pdf"}
                )
                if suffix in {".html", ".htm"} and source_status == "200" and media_type == "html":
                    eligible = True  # retained for review, never automatically trainable
                if not has_manifest_entry and media_type == "text/html":
                    if is_error_html_response(archive, member):
                        eligible = False
                        role = "error_response_candidate"
                        error_response_candidate_count += 1
                    else:
                        eligible = True
                        role = "source_html_manual_review"
                elif not has_manifest_entry and not is_pdf:
                    if suffix == ".doc" and media_type == "application/msword":
                        eligible = True
                        role = "source_doc_manual_review"
                    else:
                        eligible = False
                        role = "unclassified_archive_member"
                        unclassified_member_count += 1
                else:
                    role = "source_document" if eligible else "source_fetch_response"
                document_id = ""
                source_document_id = ""
                process_ids = []
                source_ids = []
                record_kinds = []
                query_years = []
                source_namespace = "senado_processo_documento"
                if is_pdf and eligible:
                    doc_key = normalize_document_url(source_url)
                    link_rows = source_links.get(doc_key, []) if doc_key is not None else []
                    if link_rows:
                        matched_documents += 1
                        assert doc_key is not None
                        if doc_key[0] == "dm":
                            source_document_id = doc_key[1]
                        else:
                            official_ids = {row["source_id"].strip() for row in link_rows if row["source_id"].strip()}
                            source_document_id = next(iter(official_ids)) if len(official_ids) == 1 else ""
                        if source_document_id:
                            document_id = f"senado:doc:processo:{source_document_id}"
                        else:
                            identity_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
                            document_id = f"senado:doc:senado_processo_documento:url:{identity_hash}"
                        process_ids = sorted({row["process_id"].strip() for row in link_rows if row["process_id"].strip()})
                        source_ids = sorted({row["source_id"].strip() for row in link_rows if row["source_id"].strip()})
                        record_kinds = sorted({row["record_kind"].strip() for row in link_rows if row["record_kind"].strip()})
                        query_years = sorted({row["query_year"].strip() for row in link_rows if row["query_year"].strip()})
                    else:
                        unmatched_documents += 1
                        doc_key = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
                        document_id = f"senado:doc:senado_processo_documento:url:{doc_key}"
                        if not has_manifest_entry:
                            source_namespace = "senado_archive_member_unmapped"
                            source_document_id = member_path.stem
                            record_kinds = ["unmatched_pdf_archive_member"]

                if has_manifest_entry:
                    for attempt_no, row in enumerate(member_records, start=1):
                        attempt_rows.append({
                            "archive": args.part,
                            "archive_member": member.name,
                            "source_url": row.get("url", ""),
                            "response_status": row.get("status", ""),
                            "reported_type": row.get("tipo", ""),
                            "reported_bytes": row.get("bytes", ""),
                            "attempt_no": str(attempt_no),
                            "download_seconds": row.get("segundos_download", ""),
                            "persistence_seconds": row.get("segundos_persistencia", ""),
                            "classification": "embedded_manifest_attempt",
                        })
                elif not eligible:
                    attempt_rows.append({
                        "archive": args.part, "archive_member": member.name,
                        "source_url": source_url, "response_status": "",
                        "reported_type": media_type, "reported_bytes": str(member.size),
                        "attempt_no": "", "download_seconds": "", "persistence_seconds": "",
                        "classification": role,
                    })

            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"could not read member: {member.name}")
            content_sha = sha256_stream(stream)
            version_id = f"{document_id}:v:{content_sha}" if document_id else ""
            index_rows.append({
                "url": source_url,
                "sha256": content_sha,
                "tar": args.part,
                "membro_tar": member.name,
                "offset_bytes": str(member.offset_data),
                "tamanho": str(member.size),
                "status": "listado",
                "house": "senado",
                "source_namespace": source_namespace,
                "source_document_id": source_document_id,
                "document_id": document_id,
                "version_id": version_id,
                "process_ids_json": json.dumps(process_ids, ensure_ascii=False, separators=(",", ":")),
                "source_ids_json": json.dumps(source_ids, ensure_ascii=False, separators=(",", ":")),
                "record_kinds_json": json.dumps(record_kinds, ensure_ascii=False, separators=(",", ":")),
                "query_years_json": json.dumps(query_years, ensure_ascii=False, separators=(",", ":")),
                "source_http_status": source_status,
                "source_media_type": media_type,
                "content_eligible": str(eligible).lower(),
                "member_role": role,
                "manifest_attempt_count": str(attempt_count),
                "archive_source_uri": args.archive_source_uri,
            })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.part).stem
    index_path = args.output_dir / f"{stem}.csv"
    with index_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(index_rows)
    attempts_path = args.output_dir / f"{stem}.fetch_attempts.csv"
    with attempts_path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["archive", "archive_member", "source_url", "response_status", "reported_type", "reported_bytes", "attempt_no", "download_seconds", "persistence_seconds", "classification"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(attempt_rows)
    summary = {
        "archive": args.part,
        "archive_bytes": args.archive.stat().st_size,
        "archive_sha256": sha256_file(args.archive),
        "member_count": len(index_rows),
        "pdf_count": sum(row["source_media_type"] in {"pdf", "application/pdf"} for row in index_rows),
        "text_eligible_count": sum(row["content_eligible"] == "true" for row in index_rows),
        "source_link_match_count": matched_documents,
        "source_link_unmatched_count": unmatched_documents,
        "manifest_attempt_count": sum(row["classification"] == "embedded_manifest_attempt" for row in attempt_rows),
        "member_review_record_count": sum(row["classification"] != "embedded_manifest_attempt" for row in attempt_rows),
        "embedded_manifest_status": "present" if manifest_present else "missing_url_hash_fallback",
        "embedded_manifest_missing_member_count": len(missing_manifest_members),
        "embedded_manifest_missing_members": missing_manifest_members,
        "unlisted_tar_member_count": unlisted_tar_member_count,
        "error_response_candidate_count": error_response_candidate_count,
        "unclassified_member_count": unclassified_member_count,
        "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "fetch_attempts_sha256": hashlib.sha256(attempts_path.read_bytes()).hexdigest(),
        "status": "indexed",
    }
    summary_path = args.output_dir / f"{stem}.index_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
