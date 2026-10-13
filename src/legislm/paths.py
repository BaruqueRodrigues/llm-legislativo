"""External storage path resolution for production CLIs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, Path]


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def require_data_root() -> Path:
    raw = os.environ.get("DATA_ROOT", "").strip()
    if not raw:
        raise ValueError("DATA_ROOT is required and must be an absolute path outside the checkout")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise ValueError("DATA_ROOT must be an absolute path")
    root = root.resolve()
    repo = repository_root()
    if root == repo or root.is_relative_to(repo):
        raise ValueError(f"DATA_ROOT must be outside the checkout: {root}")
    return root


def resolve_output_path(path: Optional[PathLike], default_relative: PathLike) -> Path:
    """Resolve a writable path, mapping relative values below DATA_ROOT."""
    root = require_data_root()
    candidate = Path(path).expanduser() if path is not None else Path(default_relative)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    repo = repository_root()
    if candidate == repo or candidate.is_relative_to(repo):
        raise ValueError(f"Output path must be outside the checkout: {candidate}")
    return candidate


def resolve_persistent_path(path: PathLike) -> Path:
    """Resolve a configured persistence root; relative roots live in DATA_ROOT."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = require_data_root() / candidate
    candidate = candidate.resolve()
    repo = repository_root()
    if candidate == repo or candidate.is_relative_to(repo):
        raise ValueError(f"Persistence path must be outside the checkout: {candidate}")
    return candidate


def resolve_read_path(path: Optional[PathLike], default_relative: PathLike) -> Path:
    """Resolve a read-only input; relative paths retain the caller's cwd semantics."""
    if path is None:
        return (require_data_root() / Path(default_relative)).resolve()
    return Path(path).expanduser().resolve()
