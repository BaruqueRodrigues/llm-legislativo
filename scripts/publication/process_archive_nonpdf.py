#!/usr/bin/env python3
"""Extract legacy DOC and HTML members into reviewable Parquet records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
import tarfile
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class VisibleTextParser(HTMLParser):
    BLOCK_TAGS = {"address", "article", "br", "div", "h1", "h2", "h3", "li", "p", "section", "td", "th", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1
        elif not self.hidden_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif not self.hidden_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def decode_html(data: bytes) -> str:
    head = data[:4096].decode("ascii", errors="ignore")
    match = re.search(r"charset\s*=\s*['\"]?([\w.-]+)", head, flags=re.IGNORECASE)
    encoding = match.group(1) if match else "utf-8"
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def extract_html(data: bytes) -> str:
    parser = VisibleTextParser()
    parser.feed(decode_html(data))
    value = html.unescape("".join(parser.parts))
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def textutil_doc(data: bytes, temp_dir: Path, member_name: str) -> tuple[str, str | None]:
    source = temp_dir / Path(member_name).name
    source.write_bytes(data)
    result = subprocess.run(
        ["/usr/bin/textutil", "-convert", "txt", "-stdout", str(source)],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return "", (result.stderr or b"textutil conversion failed").decode("utf-8", errors="replace")[:500]
    return result.stdout.decode("utf-8", errors="replace"), None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    index_rows: dict[str, dict[str, str]] = {}
    with args.index.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            media_type = (row.get("source_media_type") or "").strip().lower()
            if (row["tar"] == args.archive.name and row["status"] == "listado"
                and not row["membro_tar"].lower().endswith(".pdf")
                and media_type not in {"pdf", "application/pdf"}):
                if row.get("content_eligible", "true").strip().lower() in {"0", "false", "no"}:
                    continue
                index_rows[row["membro_tar"]] = row
    if not index_rows:
        raise RuntimeError("no indexed non-PDF members found")

    records = []
    source_map = []
    error_markers = re.compile(
        r"\b(404|403|500|502|503)\b|not found|access denied|service unavailable|internal server error|"
        r"page cannot be displayed|página não encontrada|erro ao processar|recurso não localizado",
        flags=re.IGNORECASE,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="doc-convert-") as temporary:
        temporary_dir = Path(temporary)
        with tarfile.open(args.archive, mode="r:") as archive:
            for member_name, row in index_rows.items():
                try:
                    member = archive.getmember(member_name)
                except KeyError as error:
                    raise RuntimeError(f"indexed member is missing from TAR: {member_name}") from error
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"could not read TAR member: {member_name}")
                raw = stream.read()
                actual_sha = sha256_bytes(raw)
                if actual_sha != row["sha256"] or len(raw) != int(row["tamanho"]):
                    raise RuntimeError(f"size/hash mismatch for TAR member {member_name}")
                suffix = Path(member_name).suffix.lower()
                error = None
                if suffix in {".html", ".htm"}:
                    text = extract_html(raw)
                    adapter = "python_htmlparser_v1"
                elif suffix == ".doc":
                    text, error = textutil_doc(raw, temporary_dir, member_name)
                    adapter = "macos_textutil_1"
                else:
                    text = ""
                    error = "unsupported_member_format"
                    adapter = "none"
                text = text.replace("\x00", "")
                char_count = len(text)
                printable_ratio = (sum(ch.isprintable() or ch.isspace() for ch in text) / char_count) if char_count else 0.0
                replacement_ratio = (text.count("\ufffd") / char_count) if char_count else 0.0
                candidate_error = bool(suffix in {".html", ".htm"} and error_markers.search(text[:20000]))
                quality_status = "fail" if error or not text.strip() else "review"
                review_status = "possible_error_or_placeholder" if candidate_error else "manual_document_review_required"
                version_id = row.get("version_id") or "doc:v1:" + Path(member_name).stem
                records.append(
                    {
                        "version_id": version_id,
                        "document_id": row.get("document_id", ""),
                        "process_ids_json": row.get("process_ids_json", "[]"),
                        "source_ids_json": row.get("source_ids_json", "[]"),
                        "record_kinds_json": row.get("record_kinds_json", "[]"),
                        "house": row.get("house", "camara"),
                        "source_url": row["url"],
                        "archive": row["tar"],
                        "archive_member": member_name,
                        "file_sha256": actual_sha,
                        "format": suffix.lstrip("."),
                        "adapter": adapter,
                        "text": text,
                        "text_sha256": sha256_bytes(text.encode("utf-8")),
                        "input_bytes": len(raw),
                        "utf8_bytes": len(text.encode("utf-8")),
                        "character_count": char_count,
                        "printable_ratio": printable_ratio,
                        "replacement_char_ratio": replacement_ratio,
                        "quality_status": quality_status,
                        "review_status": review_status,
                        "include_in_training": False,
                        "error": error,
                    }
                )
                source_map.append(
                    {
                        "version_id": version_id,
                        "document_id": row.get("document_id", ""),
                        "process_ids_json": row.get("process_ids_json", "[]"),
                        "source_url": row["url"],
                        "archive": row["tar"],
                        "archive_member": member_name,
                        "file_sha256": actual_sha,
                        "size_bytes": len(raw),
                    }
                )

    schema = pa.schema(
        [
            ("version_id", pa.string()), ("document_id", pa.string()),
            ("process_ids_json", pa.string()), ("source_ids_json", pa.string()),
            ("record_kinds_json", pa.string()), ("house", pa.string()),
            ("source_url", pa.string()), ("archive", pa.string()),
            ("archive_member", pa.string()), ("file_sha256", pa.string()), ("format", pa.string()),
            ("adapter", pa.string()), ("text", pa.string()), ("text_sha256", pa.string()),
            ("input_bytes", pa.int64()), ("utf8_bytes", pa.int64()), ("character_count", pa.int64()),
            ("printable_ratio", pa.float64()), ("replacement_char_ratio", pa.float64()),
            ("quality_status", pa.string()), ("review_status", pa.string()),
            ("include_in_training", pa.bool_()), ("error", pa.string()),
        ]
    )
    table = pa.Table.from_pylist(records, schema=schema)
    parquet_path = args.output_dir / "non_pdf_text.parquet"
    pq.write_table(table, parquet_path, compression="zstd")
    source_map_path = args.output_dir / "non_pdf_source_map.csv"
    with source_map_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(source_map[0]))
        writer.writeheader()
        writer.writerows(source_map)
    manifest = {
        "archive": args.archive.name,
        "archive_sha256": args.expected_archive_sha256,
        "source_index_sha256": hashlib.sha256(args.index.read_bytes()).hexdigest(),
        "record_count": len(records),
        "format_counts": {fmt: sum(record["format"] == fmt for record in records) for fmt in sorted({r["format"] for r in records})},
        "quality_status_counts": {status: sum(record["quality_status"] == status for record in records) for status in sorted({r["quality_status"] for r in records})},
        "review_status_counts": {status: sum(record["review_status"] == status for record in records) for status in sorted({r["review_status"] for r in records})},
        "include_in_training_count": 0,
        "files": {
            "non_pdf_text.parquet": {"size_bytes": parquet_path.stat().st_size, "sha256": sha256_bytes(parquet_path.read_bytes())},
            "non_pdf_source_map.csv": {"size_bytes": source_map_path.stat().st_size, "sha256": sha256_bytes(source_map_path.read_bytes())},
        },
    }
    (args.output_dir / "non_pdf_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    pending_path = args.output_dir / "non_pdf_pending.csv"
    with pending_path.open("w", newline="", encoding="utf-8") as stream:
        fields = ["version_id", "source_url", "archive_member", "file_sha256", "format", "review_status", "quality_status"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record[field] for field in fields})

    release_manifest_path = args.output_dir / "publication_manifest.json"
    if release_manifest_path.exists():
        release_manifest = json.loads(release_manifest_path.read_text())
        release_manifest["processed_non_pdf_count"] = len(records)
        release_manifest["pending_non_pdf_count"] = 0
        release_manifest["manual_review_pending_count"] = len(records)
        release_manifest["processed_formats"] = ["pdf", "html", "doc"]
        release_manifest["non_pdf_manifest_sha256"] = sha256_bytes((args.output_dir / "non_pdf_manifest.json").read_bytes())
        release_manifest["non_pdf_review_status_counts"] = manifest["review_status_counts"]
        release_manifest["non_pdf_training_eligible_count"] = 0
        release_manifest_path.write_text(json.dumps(release_manifest, indent=2) + "\n")
        complete = {
            "status": "extraction_complete_manual_review_pending",
            "manifest": release_manifest_path.name,
            "manifest_sha256": sha256_bytes(release_manifest_path.read_bytes()),
        }
        (args.output_dir / "COMPLETE.json").write_text(json.dumps(complete, indent=2) + "\n")
        pdf_count = int(release_manifest["processed_pdf_count"])
        (args.output_dir / "README.md").write_text(
            f"# Extração parcial do lote {args.archive.name}\n\n"
            f"Arquivo raw SHA-256: `{args.expected_archive_sha256}`. Foram processados {pdf_count} PDFs e "
            f"{len(records)} membros HTML/DOC com PDFKit + Apple Vision seletivo para PDF, HTMLParser e textutil no macOS. "
            "Os HTML/DOC permanecem com revisão documental pendente e `include_in_training=false`. "
            "Este artefato não contém splits globais de treino/validação/teste e não deve ser tratado como release curada.\n"
        )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
