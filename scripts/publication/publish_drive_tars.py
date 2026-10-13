#!/usr/bin/env python3
"""Fetch Câmara TARs with bounded prefetch, validate, publish, and optionally extract."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import quote

from huggingface_hub import HfApi


MAX_EXTRACTION_WORKERS = 8


def validate_extraction_workers(workers: int) -> None:
    if not 1 <= workers <= MAX_EXTRACTION_WORKERS:
        raise ValueError(
            f"extraction workers must be between 1 and {MAX_EXTRACTION_WORKERS}"
        )


def run(command: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, check=True, text=True)
    return completed.stdout or ""


def list_drive_sizes(
    rclone: str,
    remote: str,
    folder_id: str,
    parts: range,
    remote_prefix: str = "",
    shared_with_me: bool = False,
) -> dict[str, int]:
    listing_root = f"{remote}:{remote_prefix.rstrip('/')}" if remote_prefix else f"{remote}:"
    command = [
        rclone,
        "lsl",
        listing_root,
        "--drive-root-folder-id",
        folder_id,
        "--log-level",
        "ERROR",
    ]
    if shared_with_me:
        command.append("--drive-shared-with-me")
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = {f"part{i:03d}.tar" for i in parts}
    sizes = {}
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) != 4:
            continue
        remote_path = fields[3]
        prefix = f"{remote_prefix.rstrip('/')}/"
        if remote_prefix and remote_path.startswith(prefix):
            remote_path = remote_path[len(remote_prefix.rstrip('/')) + 1 :]
        if remote_path in expected:
            if remote_path in sizes:
                if sizes[remote_path] != int(fields[0]):
                    raise RuntimeError(
                        f"Drive source contains conflicting sizes for {remote_path}: "
                        f"{sizes[remote_path]} and {fields[0]}"
                    )
                continue
            sizes[remote_path] = int(fields[0])
    if sizes.keys() != expected:
        raise RuntimeError(
            f"Drive source differs from the requested TARs: "
            f"missing={sorted(expected - sizes.keys())}, extra={sorted(sizes.keys() - expected)}"
        )
    return sizes


def verify_public_file(api: HfApi, repo: str, path: str, size: int, sha256: str) -> str:
    info = api.repo_info(repo, repo_type="dataset", files_metadata=True)
    if info.private:
        raise RuntimeError("target dataset is not public")
    remote = next((item for item in info.siblings if item.rfilename == path), None)
    if remote is None:
        raise RuntimeError(f"uploaded file is absent from the public repository: {path}")
    if remote.size != size or not remote.lfs or remote.lfs.sha256 != sha256:
        raise RuntimeError(f"remote size/SHA-256 mismatch for {path}")
    return info.sha


def verify_public_manifest(repo: str, revision: str, local_path: Path) -> None:
    url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/release_manifest.json"
    with urllib.request.urlopen(url, timeout=60) as response:
        remote_bytes = response.read()
    if remote_bytes != local_path.read_bytes():
        raise RuntimeError("public release_manifest.json differs from the staged manifest")


def verify_public_tree(api: HfApi, repo: str, revision_prefix: str, local_root: Path) -> str:
    info = api.repo_info(repo, repo_type="dataset", files_metadata=True)
    if info.private:
        raise RuntimeError("processed dataset is not public")
    remote_files = {item.rfilename: item for item in info.siblings}
    for local_path in sorted(path for path in local_root.rglob("*") if path.is_file()):
        relative = local_path.relative_to(local_root).as_posix()
        remote_path = f"{revision_prefix.rstrip('/')}/{relative}"
        remote = remote_files.get(remote_path)
        if remote is None or remote.size != local_path.stat().st_size:
            raise RuntimeError(f"processed file missing or size mismatch in public repo: {remote_path}")
        if remote.lfs and remote.lfs.sha256 != sha256_file(local_path):
            raise RuntimeError(f"processed file SHA-256 mismatch in public repo: {remote_path}")
    complete_path = local_root / "COMPLETE.json"
    if complete_path.exists():
        url = f"https://huggingface.co/datasets/{repo}/resolve/{info.sha}/{quote(revision_prefix.rstrip('/') + '/COMPLETE.json')}"
        with urllib.request.urlopen(url, timeout=60) as response:
            if response.read() != complete_path.read_bytes():
                raise RuntimeError("public processed COMPLETE.json differs from local file")
    return info.sha


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_senado_release_manifest(path: Path, folder_id: str) -> None:
    """Create the Senate release manifest once; never replace existing progress."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    release = {
        "schema_version": "1.0.0",
        "dataset": "BaruqRodrigues/senado-corpus-raw",
        "release_id": "senado-raw-drive-2026-10-11",
        "house": "senado",
        "scope": "Senado Federal; TARs originais e manifesto de membros/tentativas",
        "source_uri": f"https://drive.google.com/drive/folders/{folder_id}",
        "source_archive_count_expected": 16,
        "source_archive_count_verified": 0,
        "source_archive_count_published": 0,
        "published_archives": [],
        "status": "pending",
    }
    path.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prefetched_archives(parts: range, download, prefetch_count: int = 1):
    """Yield ordered downloads while keeping a bounded number in flight."""
    part_list = list(parts)
    if not part_list:
        return
    if prefetch_count < 0:
        raise ValueError("prefetch_count cannot be negative")
    if prefetch_count == 0:
        for part in part_list:
            yield part, download(part)
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=prefetch_count) as executor:
        futures = {}
        next_index = 0
        while next_index < min(prefetch_count, len(part_list)):
            futures[next_index] = executor.submit(download, part_list[next_index])
            next_index += 1
        for index, part in enumerate(part_list):
            download_path = futures.pop(index).result()
            if next_index < len(part_list):
                futures[next_index] = executor.submit(download, part_list[next_index])
                next_index += 1
            yield part, download_path


def run_overlapped(raw_upload, extraction):
    """Run raw publication and extraction together, then wait for both results."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        upload_future = executor.submit(raw_upload)
        extraction_future = executor.submit(extraction)
        upload_result = upload_future.result()
        extraction_result = extraction_future.result()
    return upload_result, extraction_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=2)
    parser.add_argument("--end", type=int, default=43)
    parser.add_argument("--remote", default="legislm_drive")
    parser.add_argument("--drive-folder-id", required=True)
    parser.add_argument("--drive-shared-with-me", action="store_true")
    parser.add_argument("--remote-prefix", default="")
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument(
        "--index-mode", choices=("camara", "senado"), default="camara",
        help="camara: existing per-member index; senado: build from each TAR manifesto and link inventory",
    )
    parser.add_argument("--rclone", required=True)
    parser.add_argument("--hf-cli", help="deprecated; uploads use the authenticated HfApi client")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--download-dir", required=True, type=Path)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--batch-dir", required=True, type=Path)
    parser.add_argument("--chunk-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument(
        "--prefetch-count", type=int, default=1, choices=range(0, 3),
        metavar="{0,1,2}",
        help="number of concurrent TAR downloads (0 disables overlap; maximum 2)",
    )
    parser.add_argument(
        "--no-prefetch-next", action="store_const", const=0,
        dest="prefetch_count", help=argparse.SUPPRESS,
    )
    parser.add_argument("--text-repo-id", help="also extract and publish processed Parquet to this dataset repo")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--rscript", default="Rscript")
    parser.add_argument("--extraction-workers", type=int, default=2)
    parser.add_argument("--min-free-gib", type=float, default=10.0)
    args = parser.parse_args()
    max_part = 16 if args.index_mode == "senado" else 43
    if args.index_mode == "camara" and not args.hf_cli:
        parser.error("--hf-cli is required for the existing Câmara publication flow")
    if not (1 <= args.start <= args.end <= max_part):
        parser.error(f"part range must be within 1..{max_part}")
    try:
        validate_extraction_workers(args.extraction_workers)
    except ValueError as exc:
        parser.error(f"--extraction-workers {exc}")
    if args.min_free_gib <= 0:
        parser.error("--min-free-gib must be positive")
    if args.text_repo_id and args.data_root is None:
        parser.error("--data-root is required with --text-repo-id")
    if args.text_repo_id and args.text_repo_id == args.repo_id:
        parser.error("raw and processed repositories must be different")

    repo_root = Path(__file__).resolve().parents[2]
    fetch_script = Path(__file__).with_name("fetch_rclone_range.py")
    verify_script = Path(__file__).with_name("verify_tar_index.py")
    register_script = Path(__file__).with_name("register_verified_archive.py")
    release_manifest = args.release_dir / "release_manifest.json"
    if args.index_mode == "senado":
        ensure_senado_release_manifest(release_manifest, args.drive_folder_id)
    api = HfApi()
    for target_repo in (args.repo_id, args.text_repo_id):
        if not target_repo:
            continue
        api.create_repo(repo_id=target_repo, repo_type="dataset", private=False, exist_ok=True)
        if api.repo_info(target_repo, repo_type="dataset").private:
            raise RuntimeError(f"target dataset must be public: {target_repo}")
    requested_parts = range(args.start, args.end + 1)
    sizes = list_drive_sizes(
        args.rclone,
        args.remote,
        args.drive_folder_id,
        requested_parts,
        remote_prefix=args.remote_prefix,
        shared_with_me=args.drive_shared_with_me,
    )
    args.download_dir.mkdir(parents=True, exist_ok=True)
    raw_stage_dir = args.release_dir / "raw" / "drive_tarballs"
    raw_stage_dir.mkdir(parents=True, exist_ok=True)
    args.batch_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_devices = {
        args.download_dir.stat().st_dev,
        raw_stage_dir.stat().st_dev,
        args.batch_dir.parent.stat().st_dev,
    }
    if len(staging_devices) != 1:
        raise RuntimeError(
            "download, raw staging, and upload batch directories must share one filesystem "
            "to avoid temporary full-TAR copies"
        )

    active_downloads: dict[int, tuple[int, Path]] = {}
    disk_reservation_lock = threading.Lock()

    def download_archive(part: int) -> Path:
        name = f"part{part:03d}.tar"
        download_path = args.download_dir / name
        partial_path = download_path.with_name(download_path.name + ".partial")
        if download_path.exists() and download_path.stat().st_size == sizes[name]:
            bytes_to_fetch = 0
        else:
            partial_size = partial_path.stat().st_size if partial_path.exists() else 0
            bytes_to_fetch = max(0, sizes[name] - partial_size)
        with disk_reservation_lock:
            outstanding = sum(
                max(0, expected - (partial.stat().st_size if partial.exists() else 0))
                for expected, partial in active_downloads.values()
            )
            required_free = outstanding + bytes_to_fetch + int(args.min_free_gib * 1024**3)
            free_bytes = shutil.disk_usage(args.download_dir).free
            if free_bytes < required_free:
                raise RuntimeError(
                    f"insufficient free disk for {name} with concurrent downloads: "
                    f"need {required_free} bytes including reserve, have {free_bytes}"
                )
            active_downloads[part] = (sizes[name], partial_path)
        print(json.dumps({"event": "archive_download_start", "archive": name}), flush=True)
        try:
            run(
            [
                sys.executable,
                str(fetch_script),
                "--remote",
                args.remote,
                "--remote-path",
                f"{args.remote_prefix.rstrip('/')}/{name}".lstrip("/"),
                "--drive-root-folder-id",
                args.drive_folder_id,
                "--size-bytes",
                str(sizes[name]),
                "--destination",
                str(download_path),
                "--rclone",
                args.rclone,
                "--chunk-bytes",
                str(args.chunk_bytes),
                *(["--drive-shared-with-me"] if args.drive_shared_with_me else []),
            ],
                cwd=repo_root,
            )
            return download_path
        finally:
            with disk_reservation_lock:
                active_downloads.pop(part, None)

    parts = range(args.start, args.end + 1)
    for part, download_path in prefetched_archives(parts, download_archive, args.prefetch_count):
        name = f"part{part:03d}.tar"
        print(json.dumps({"event": "archive_start", "archive": name}), flush=True)
        previous_manifest = release_manifest.read_bytes()

        if args.index_mode == "senado":
            run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("build_senado_tar_index.py")),
                    str(download_path),
                    "--link-index", str(args.index),
                    "--part", name,
                    "--archive-source-uri", f"https://drive.google.com/drive/folders/{args.drive_folder_id}",
                    "--output-dir", str(args.release_dir / "manifests"),
                ],
                cwd=repo_root,
            )
            effective_index = args.release_dir / "manifests" / f"part{part:03d}.csv"
        else:
            run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("complete_camara_tar_index.py")),
                    str(download_path), str(args.index),
                    "--part", name,
                    "--archive-source-uri", f"https://drive.google.com/drive/folders/{args.drive_folder_id}",
                    "--output-dir", str(args.release_dir / "manifests"),
                ],
                cwd=repo_root,
            )
            effective_index = args.release_dir / "manifests" / f"part{part:03d}.csv"
        run(
            [
                sys.executable,
                str(verify_script),
                str(download_path),
                str(effective_index),
                "--part",
                name,
                "--output-dir",
                str(args.release_dir / "manifests"),
            ],
            cwd=repo_root,
        )
        summary_path = args.release_dir / "manifests" / f"part{part:03d}.verification.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary["archive_bytes"] != sizes[name]:
            raise RuntimeError(f"Drive size differs from the verified archive size for {name}")

        shutil.move(
            str(download_path),
            str(args.release_dir / "raw/drive_tarballs" / name),
        )
        run(
            [
                sys.executable,
                str(register_script),
                str(release_manifest),
                str(summary_path),
            ],
            cwd=repo_root,
        )

        if args.batch_dir.exists():
            shutil.rmtree(args.batch_dir)
        batch_tar = args.batch_dir / "raw/drive_tarballs" / name
        batch_tar.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(
            str(args.release_dir / "raw/drive_tarballs" / name), str(batch_tar)
        )
        batch_manifests = args.batch_dir / "manifests"
        batch_manifests.mkdir(parents=True, exist_ok=True)
        manifest_suffixes = [f"part{part:03d}.csv", f"part{part:03d}.verification.json"]
        if args.index_mode == "senado":
            manifest_suffixes.extend((f"part{part:03d}.fetch_attempts.csv", f"part{part:03d}.index_summary.json"))
        for suffix in manifest_suffixes:
            shutil.copy2(args.release_dir / "manifests" / suffix, batch_manifests / suffix)
        shutil.copy2(release_manifest, args.batch_dir / "release_manifest.json")

        extraction_dir = None

        def upload_raw() -> str:
            if args.index_mode == "senado":
                api.upload_folder(
                    repo_id=args.repo_id,
                    repo_type="dataset",
                    folder_path=str(args.batch_dir),
                    path_in_repo=".",
                    commit_message=f"Publish verified {args.index_mode} raw archive {name}",
                    commit_description=f"Original {args.index_mode} TAR with complete member hash/size/offset validation.",
                )
            else:
                run(
                    [args.hf_cli, "upload", args.repo_id, str(args.batch_dir), ".",
                     "--repo-type", "dataset", "--commit-message",
                     f"Publish verified {args.index_mode} raw archive {name}",
                     "--commit-description",
                     f"Original {args.index_mode} TAR with complete member hash/size/offset validation."],
                    cwd=repo_root,
                )
            archive_path = f"raw/drive_tarballs/{name}"
            raw_revision = verify_public_file(
                api,
                args.repo_id,
                archive_path,
                summary["archive_bytes"],
                summary["archive_sha256"],
            )
            verify_public_manifest(args.repo_id, raw_revision, release_manifest)
            return raw_revision

        def extract_archive() -> Path | None:
            if not args.text_repo_id:
                return None
            assert args.data_root is not None
            extraction_root = args.data_root / "staging" / "extraction"
            if args.index_mode == "senado":
                extraction_root = extraction_root / "senado"
            output_dir = extraction_root / f"part{part:03d}-batched"
            run(
                [
                    sys.executable,
                    str(repo_root / "scripts/publication/process_archive_pdfs.py"),
                    "--archive", str(batch_tar),
                    "--expected-archive-sha256", summary["archive_sha256"],
                    "--index", str(effective_index),
                    "--repo-root", str(repo_root),
                    "--data-root", str(args.data_root),
                    "--rscript", args.rscript,
                    "--workers", str(args.extraction_workers),
                    "--house", args.index_mode,
                    "--source-raw-repo", args.repo_id,
                ],
                cwd=repo_root,
            )
            with effective_index.open(newline="", encoding="utf-8") as index_stream:
                has_non_pdf = any(
                    row["tar"] == name
                    and row["status"] == "listado"
                    and not row["membro_tar"].lower().endswith(".pdf")
                    and (row.get("source_media_type") or "").strip().lower() not in {"pdf", "application/pdf"}
                    and row.get("content_eligible", "true").strip().lower() not in {"0", "false", "no"}
                    for row in csv.DictReader(index_stream)
                )
            if has_non_pdf:
                run(
                    [
                        sys.executable,
                        str(repo_root / "scripts/publication/process_archive_nonpdf.py"),
                        "--archive", str(batch_tar),
                        "--expected-archive-sha256", summary["archive_sha256"],
                        "--index", str(effective_index),
                        "--output-dir", str(output_dir),
                    ],
                    cwd=repo_root,
                )
            return output_dir

        raw_published = False
        try:
            if args.text_repo_id:
                # Both tasks read the same verified TAR. Keep its local copy until
                # both finish so either failure remains safely retryable.
                revision, extraction_dir = run_overlapped(upload_raw, extract_archive)
            else:
                revision = upload_raw()
            raw_published = True
        except BaseException:
            release_manifest.write_bytes(previous_manifest)
            args.download_dir.mkdir(parents=True, exist_ok=True)
            if batch_tar.exists():
                shutil.move(str(batch_tar), str(download_path))
            raise

        text_revision = None
        try:
            if args.text_repo_id:
                assert extraction_dir is not None
                if args.index_mode == "senado":
                    api.upload_folder(
                        repo_id=args.text_repo_id,
                        repo_type="dataset",
                        folder_path=str(extraction_dir),
                        path_in_repo=f"extraction/part{part:03d}",
                        commit_message=f"Publish processed {args.index_mode} archive {name}",
                        commit_description="Processed records derived from the verified public raw TAR.",
                    )
                else:
                    run(
                        [args.hf_cli, "upload", args.text_repo_id, str(extraction_dir),
                         f"extraction/part{part:03d}", "--repo-type", "dataset",
                         "--commit-message", f"Publish processed {args.index_mode} archive {name}",
                         "--commit-description", "Processed records derived from the verified public raw TAR."],
                        cwd=repo_root,
                    )
                text_revision = verify_public_tree(
                    api, args.text_repo_id, f"extraction/part{part:03d}", extraction_dir
                )
        except BaseException:
            # Keep the sole local TAR available for a safe retry if extraction or
            # processed publication fails after the raw copy is already public.
            args.download_dir.mkdir(parents=True, exist_ok=True)
            if batch_tar.exists():
                shutil.move(str(batch_tar), str(download_path))
            raise
        finally:
            if args.batch_dir.exists():
                shutil.rmtree(args.batch_dir)

        (args.download_dir / f"{name}.download.json").unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "event": "archive_published_and_verified",
                    "archive": name,
                    "sha256": summary["archive_sha256"],
                    "bytes": summary["archive_bytes"],
                    "revision": revision,
                }
            ),
            flush=True,
        )
        if raw_published and args.text_repo_id:
            print(
                json.dumps(
                    {
                        "event": "archive_processed_and_published",
                        "archive": name,
                        "repo_id": args.text_repo_id,
                        "revision": text_revision,
                        "workers": args.extraction_workers,
                    }
                ),
                flush=True,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
