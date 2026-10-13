#!/usr/bin/env python3
"""Upload and verify the final curated Senate Parquet release on Hugging Face."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import HfApi

from publish_drive_tars import verify_public_tree


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default="BaruqRodrigues/senado-corpus-text")
    parser.add_argument("--release-dir", required=True, type=Path)
    args = parser.parse_args()
    complete_path = args.release_dir / "COMPLETE.json"
    if not complete_path.exists():
        parser.error("release directory has no COMPLETE.json; curate it first")
    api = HfApi()
    api.create_repo(repo_id=args.repo_id, repo_type="dataset", private=False, exist_ok=True)
    if api.repo_info(args.repo_id, repo_type="dataset").private:
        raise RuntimeError(f"target dataset must be public: {args.repo_id}")
    api.upload_folder(
        repo_id=args.repo_id,
        repo_type="dataset",
        folder_path=str(args.release_dir),
        path_in_repo="curated",
        commit_message="Publish curated Senate Parquet release",
        commit_description="Documents, pages, sections, quality metadata, family-safe splits, and completion manifest.",
    )
    revision = verify_public_tree(api, args.repo_id, "curated", args.release_dir)
    print(f"verified public Senate release {args.repo_id}@{revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
