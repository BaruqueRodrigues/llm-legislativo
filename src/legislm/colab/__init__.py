"""
src/legislm/colab/__init__.py
Módulo de integração com Google Colab e persistência do LLM Legislativo Brasileiro.
"""

from legislm.colab.preflight import run_preflight
from legislm.colab.staging import stage_file, stage_directory, benchmark_io
from legislm.colab.persistence import (
    GoogleDrivePersistenceBackend,
    publish_checkpoint,
    resolve_checkpoint,
    list_complete_checkpoints,
)

__all__ = [
    "run_preflight",
    "stage_file",
    "stage_directory",
    "benchmark_io",
    "GoogleDrivePersistenceBackend",
    "publish_checkpoint",
    "resolve_checkpoint",
    "list_complete_checkpoints",
]
