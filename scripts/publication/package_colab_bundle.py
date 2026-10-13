#!/usr/bin/env python3
"""Package the minimal, hash-manifested source bundle needed by integral Colab."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


FILES = (
    Path("README.md"),
    Path("pyproject.toml"),
    Path("requirements-base.lock"),
    Path("src/legislm"),
    Path("configs/tokenizer/integral.yaml"),
    Path("configs/training/integral.yaml"),
    Path("configs/colab/integral.yaml"),
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True, help="Pasta de saída em DATA_ROOT")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    output = args.output_dir.expanduser().resolve()
    if output == repo or output.is_relative_to(repo):
        raise ValueError("Bundle de execução deve ficar fora do checkout")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Pasta de saída não está vazia: {output}")
    output.mkdir(parents=True, exist_ok=True)

    included: list[Path] = []
    for rel in FILES:
        source = repo / rel
        if not source.exists():
            raise FileNotFoundError(source)
        targets = sorted(
            p for p in source.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        ) if source.is_dir() else [source]
        for file in targets:
            rel_file = file.relative_to(repo)
            dest = output / rel_file
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dest)
            included.append(rel_file)

    entries = []
    for rel_file in sorted(set(included)):
        target = output / rel_file
        entries.append({"path": rel_file.as_posix(), "size_bytes": target.stat().st_size, "sha256": sha256_file(target)})
    manifest = {"schema_version": "1.0.0", "files": entries}
    manifest_path = output / "bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_sha = sha256_file(manifest_path)
    complete = {"status": "complete", "manifest_sha256": manifest_sha, "file_count": len(entries)}
    (output / "BUNDLE_COMPLETE.json").write_text(json.dumps(complete, indent=2) + "\n", encoding="utf-8")

    archive = output.parent / (output.name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for rel_file in sorted(set(included)):
            bundle.write(output / rel_file, rel_file.as_posix())
        bundle.write(manifest_path, manifest_path.name)
        bundle.write(output / "BUNDLE_COMPLETE.json", "BUNDLE_COMPLETE.json")
    print(json.dumps({"bundle_dir": str(output), "bundle_zip": str(archive), "bundle_manifest_sha256": manifest_sha,
                      "files": len(entries), "bytes": sum(e["size_bytes"] for e in entries)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
