#!/usr/bin/env python3
"""Publish and verify the unified legislative corpus and BPE tokenizer."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download


DEFAULT_REPO = "BaruqRodrigues/corpus-legislativo-pretraining"
MIT_LICENSE = """MIT License

Copyright (c) 2026 Quemuel Baruq Rodrigues

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_local_release(root: Path) -> None:
    manifest_path = root / "release_manifest.json"
    complete_path = root / "COMPLETE.json"
    manifest = json.loads(manifest_path.read_text())
    complete = json.loads(complete_path.read_text())
    manifest_sha = sha256_file(manifest_path)
    if complete.get("manifest_sha256") != manifest_sha:
        raise RuntimeError("release COMPLETE.json does not match release_manifest.json")
    if manifest.get("coverage_status") != "partial":
        raise RuntimeError("unexpected coverage status; review release card before publishing")
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["size_bytes"]:
            raise RuntimeError(f"release file missing or wrong size: {path}")
        if sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"release file SHA-256 mismatch: {path}")


def verify_local_tokenizer(root: Path) -> None:
    manifest_path = root / "tokenizer_manifest.json"
    complete_path = root / "COMPLETE.json"
    manifest = json.loads(manifest_path.read_text())
    complete = json.loads(complete_path.read_text())
    if complete.get("manifest_sha256") != sha256_file(manifest_path):
        raise RuntimeError("tokenizer COMPLETE.json does not match tokenizer_manifest.json")
    tokenizer_path = root / "tokenizer.json"
    if sha256_file(tokenizer_path) != manifest.get("tokenizer_file_sha256"):
        raise RuntimeError("tokenizer.json SHA-256 mismatch")


def remote_file_map(api: HfApi, repo: str) -> tuple[str, dict[str, object]]:
    info = api.repo_info(repo_id=repo, repo_type="dataset", files_metadata=True)
    if info.private:
        raise RuntimeError("target dataset repository is not public")
    return info.sha, {item.rfilename: item for item in info.siblings or []}


def verify_remote_tree(api: HfApi, repo: str, prefix: str, local_root: Path, *, include_complete: bool) -> str:
    revision, remote_files = remote_file_map(api, repo)
    for path in sorted(item for item in local_root.rglob("*") if item.is_file()):
        if not include_complete and path.name == "COMPLETE.json":
            continue
        relative = path.relative_to(local_root).as_posix()
        remote_path = f"{prefix.rstrip('/')}/{relative}"
        remote = remote_files.get(remote_path)
        if remote is None or remote.size != path.stat().st_size:
            raise RuntimeError(f"remote file missing or size mismatch: {remote_path}")
        lfs = getattr(remote, "lfs", None)
        remote_sha = getattr(lfs, "sha256", None) if lfs is not None else None
        if remote_sha is not None:
            if remote_sha != sha256_file(path):
                raise RuntimeError(f"remote SHA-256 mismatch: {remote_path}")
        elif path.stat().st_size <= 10 * 1024 * 1024:
            downloaded = Path(hf_hub_download(repo_id=repo, filename=remote_path, repo_type="dataset", revision=revision))
            if sha256_file(downloaded) != sha256_file(path):
                raise RuntimeError(f"downloaded remote SHA-256 mismatch: {remote_path}")
        else:
            raise RuntimeError(f"Hub exposes no remote SHA-256 metadata for large file: {remote_path}")
    return revision


def upload_tree(api: HfApi, repo: str, prefix: str, local_root: Path, label: str) -> str:
    api.upload_folder(
        repo_id=repo,
        repo_type="dataset",
        folder_path=str(local_root),
        path_in_repo=prefix,
        ignore_patterns=["COMPLETE.json"],
        commit_message=f"Publish {label} payload",
        commit_description="Payload is uploaded before its COMPLETE marker; local manifests and file hashes were validated.",
    )
    revision = verify_remote_tree(api, repo, prefix, local_root, include_complete=False)
    complete_path = local_root / "COMPLETE.json"
    api.upload_file(
        repo_id=repo,
        repo_type="dataset",
        path_or_fileobj=str(complete_path),
        path_in_repo=f"{prefix.rstrip('/')}/COMPLETE.json",
        commit_message=f"Mark {label} payload complete",
    )
    return verify_remote_tree(api, repo, prefix, local_root, include_complete=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--tokenizer-dir", required=True, type=Path)
    parser.add_argument("--card", default="docs/README_HF_INTEGRAL.md", type=Path)
    args = parser.parse_args()

    verify_local_release(args.release_dir)
    verify_local_tokenizer(args.tokenizer_dir)
    if not args.card.is_file():
        parser.error(f"dataset card missing: {args.card}")

    api = HfApi()
    api.create_repo(repo_id=args.repo_id, repo_type="dataset", private=False, exist_ok=True)
    info = api.repo_info(repo_id=args.repo_id, repo_type="dataset", token=True)
    if info.private:
        raise RuntimeError("target dataset repository must be public")

    api.upload_file(
        repo_id=args.repo_id,
        repo_type="dataset",
        path_or_fileobj=str(args.card),
        path_in_repo="README.md",
        commit_message="Add corpus card and MIT license metadata",
    )
    api.upload_file(
        repo_id=args.repo_id,
        repo_type="dataset",
        path_or_fileobj=io.BytesIO(MIT_LICENSE.encode("utf-8")),
        path_in_repo="LICENSE",
        commit_message="Add MIT license text",
    )

    release_revision = upload_tree(
        api, args.repo_id, "releases/curated/corpus-legislativo-current-v1", args.release_dir, "curated release"
    )
    tokenizer_revision = upload_tree(
        api, args.repo_id, "tokenizers/legislativo-atual-v1", args.tokenizer_dir, "tokenizer"
    )

    final_revision, remote_files = remote_file_map(api, args.repo_id)
    for path in ("README.md", "LICENSE"):
        if path not in remote_files:
            raise RuntimeError(f"publication file missing from remote repository: {path}")
    print(json.dumps({
        "repo_id": args.repo_id,
        "private": False,
        "release_verified_at": release_revision,
        "tokenizer_verified_at": tokenizer_revision,
        "final_revision": final_revision,
        "remote_file_count": len(remote_files),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
