#!/usr/bin/env python3
"""Add a verified TAR to the staged raw release manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_manifest", type=Path)
    parser.add_argument("verification", type=Path)
    args = parser.parse_args()

    release = json.loads(args.release_manifest.read_text(encoding="utf-8"))
    verified = json.loads(args.verification.read_text(encoding="utf-8"))
    if verified.get("status") != "verified":
        raise SystemExit("archive does not have a successful verification report")
    name = verified["archive"]
    part_number = int(Path(name).stem.removeprefix("part"))
    entry = {
        "path": f"raw/drive_tarballs/{name}",
        "sha256": verified["archive_sha256"],
        "size_bytes": verified["archive_bytes"],
        "member_count": verified["verified_members"],
        "member_manifest": f"manifests/part{part_number:03d}.csv",
        "validation": "sha256_size_offset_and_member_set",
        "status": "verified",
    }
    archives = [a for a in release["published_archives"] if a["path"] != entry["path"]]
    archives.append(entry)
    archives.sort(key=lambda item: int(Path(item["path"]).stem.removeprefix("part")))
    release["published_archives"] = archives
    release["source_archive_count_verified"] = len(archives)
    release["source_archive_count_published"] = len(archives)
    if len(archives) < release["source_archive_count_expected"]:
        release["status"] = "partial"
    elif release.get("house") == "senado":
        release["status"] = "complete"
    else:
        release["status"] = "partial_supplements_pending"
    args.release_manifest.write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "registered", "archive": name, "count": len(archives)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
