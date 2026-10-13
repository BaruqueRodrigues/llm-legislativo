"""
src/legislm/training/checkpoint.py
Serialização segura, manifestos normativos v1 e restauração exata de checkpoints.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import torch
import torch.nn as nn
from torch.optim import Optimizer

from legislm.training.config import TrainingConfig
from legislm.training.data import DeterministicSampler, StratifiedTracker
from legislm.training.optimizer import CosineAnnealingWarmupScheduler
from legislm.training.persistence import compute_file_sha256
from legislm.training.precision import PrecisionManager


def encode_numpy_rng() -> Dict[str, Any]:
    """Codifica o estado do RNG NumPy em tipos primitivos e tensores compatíveis com weights_only=True."""
    legacy_state = np.random.get_state()
    # legacy_state: (str, np.ndarray uint32, int, int, float)
    arr = legacy_state[1].astype(np.int64)
    return {
        "name": legacy_state[0],
        "keys": torch.from_numpy(arr),
        "pos": int(legacy_state[2]),
        "has_gauss": int(legacy_state[3]),
        "cached_gaussian": float(legacy_state[4]),
    }


def decode_numpy_rng(state_dict: Dict[str, Any]) -> None:
    """Restaura o estado do RNG NumPy a partir do formato seguro codificado."""
    keys_tensor = state_dict["keys"]
    if isinstance(keys_tensor, torch.Tensor):
        keys_arr = keys_tensor.numpy().astype(np.uint32)
    else:
        keys_arr = np.array(keys_tensor, dtype=np.uint32)

    restored_state = (
        str(state_dict["name"]),
        keys_arr,
        int(state_dict["pos"]),
        int(state_dict["has_gauss"]),
        float(state_dict["cached_gaussian"]),
    )
    np.random.set_state(restored_state)


def validate_checkpoint_manifest(manifest: Dict[str, Any]) -> None:
    """Valida o manifesto de checkpoint contra os contratos de checkpoint_manifest.schema.json."""
    required_fields = [
        "run_id",
        "checkpoint_id",
        "schema_version",
        "global_step",
        "tokens_seen",
        "tokens_for_successful_updates",
        "budget_counter",
        "segment_id",
        "config_file_sha256",
        "scientific_config_hash",
        "execution_config_hash",
        "files",
    ]
    for field in required_fields:
        if field not in manifest:
            raise ValueError(f"Campo obrigatório '{field}' ausente no manifesto de checkpoint")

    if manifest["schema_version"] != 1:
        raise ValueError(f"schema_version deve ser 1, obtido: {manifest['schema_version']}")

    if manifest["budget_counter"] not in ("successful_update_tokens", "consumed_tokens"):
        raise ValueError(f"budget_counter inválido: {manifest['budget_counter']}")

    files = manifest.get("files", [])
    if not isinstance(files, list) or len(files) == 0:
        raise ValueError("files deve ser uma lista não vazia de arquivos")

    for f in files:
        for f_key in ("path", "size_bytes", "sha256"):
            if f_key not in f:
                raise ValueError(f"Arquivo no manifesto sem campo obrigatório '{f_key}'")


def save_checkpoint(
    save_dir: Union[str, Path],
    config: TrainingConfig,
    model: nn.Module,
    optimizer: Optimizer,
    scheduler: CosineAnnealingWarmupScheduler,
    precision_mgr: PrecisionManager,
    sampler: DeterministicSampler,
    tracker: StratifiedTracker,
    global_step: int,
    tokens_seen: int,
    tokens_for_successful_updates: int,
    overflow_updates_count: int,
    total_positions_evaluated: int,
    segment_id: str,
    event_sequence: int,
    checkpoint_id: Optional[str] = None,
    best_val_loss: Optional[float] = None,
    extra_metrics: Optional[Dict[str, Any]] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """Serializa checkpoint seguro e gera manifesto com validação estrita."""
    d = Path(save_dir)
    d.mkdir(parents=True, exist_ok=True)

    if checkpoint_id is None:
        checkpoint_id = f"step_{global_step:06d}"

    cfg_file_sha, sci_hash, exec_hash = config.compute_hashes()

    # Estado de geradores de números aleatórios
    rng_states = {
        "python_rng": random.getstate(),
        "numpy_rng": encode_numpy_rng(),
        "torch_cpu_rng": torch.get_rng_state(),
    }
    if torch.cuda.is_available():
        rng_states["torch_cuda_rng"] = torch.cuda.get_rng_state_all()

    checkpoint_data = {
        "schema_version": 1,
        "run_id": config.run_id,
        "checkpoint_id": checkpoint_id,
        "global_step": global_step,
        "tokens_seen": tokens_seen,
        "tokens_for_successful_updates": tokens_for_successful_updates,
        "overflow_updates_count": overflow_updates_count,
        "total_positions_evaluated": total_positions_evaluated,
        "budget_counter": config.training.budget_counter,
        "segment_id": segment_id,
        "event_sequence": event_sequence,
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "precision_state": precision_mgr.state_dict(),
        "sampler_state": sampler.state_dict(),
        "tracker_state": tracker.state_dict(),
        "rng_states": rng_states,
        "best_val_loss": best_val_loss,
        "extra_metrics": extra_metrics or {},
        "config_dict": config.to_dict(),
        "config_file_sha256": cfg_file_sha,
        "scientific_config_hash": sci_hash,
        "execution_config_hash": exec_hash,
    }

    # Salva o arquivo binário .pt
    pt_path = d / "checkpoint.pt"
    torch.save(checkpoint_data, pt_path)

    pt_size = pt_path.stat().st_size
    pt_sha256 = compute_file_sha256(pt_path)

    manifest = {
        "run_id": config.run_id,
        "checkpoint_id": checkpoint_id,
        "schema_version": 1,
        "global_step": global_step,
        "tokens_seen": tokens_seen,
        "tokens_for_successful_updates": tokens_for_successful_updates,
        "budget_counter": config.training.budget_counter,
        "segment_id": segment_id,
        "config_file_sha256": cfg_file_sha,
        "scientific_config_hash": sci_hash,
        "execution_config_hash": exec_hash,
        "files": [
            {
                "path": "checkpoint.pt",
                "size_bytes": pt_size,
                "sha256": pt_sha256,
            }
        ],
    }
    validate_checkpoint_manifest(manifest)

    manifest_path = d / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return d, manifest


def load_checkpoint(
    checkpoint_dir: Union[str, Path],
    expected_scientific_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Carrega checkpoint seguro após validação estrita do manifesto e integridade SHA-256."""
    d = Path(checkpoint_dir)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifesto ausente em {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    validate_checkpoint_manifest(manifest)

    # Validação do hash científico para impedir retomada de experimento incompatível
    if expected_scientific_hash is not None:
        if manifest["scientific_config_hash"] != expected_scientific_hash:
            raise ValueError(
                f"Incompatibilidade científica no checkpoint. Esperado: {expected_scientific_hash}, "
                f"Obtido no checkpoint: {manifest['scientific_config_hash']}"
            )

    # Validação de hashes de arquivos
    for file_entry in manifest["files"]:
        target_f = d / file_entry["path"]
        if not target_f.exists():
            raise FileNotFoundError(f"Arquivo ausente: {target_f}")
        actual_sha = compute_file_sha256(target_f)
        if actual_sha != file_entry["sha256"]:
            raise ValueError(
                f"Integridade violada para {file_entry['path']}. Esperado: {file_entry['sha256']}, Obtido: {actual_sha}"
            )

    pt_path = d / "checkpoint.pt"
    # Carga estrita com weights_only=True
    ckpt_data = torch.load(pt_path, weights_only=True)
    return ckpt_data


def restore_training_state(
    ckpt_data: Dict[str, Any],
    model: nn.Module,
    optimizer: Optimizer,
    scheduler: CosineAnnealingWarmupScheduler,
    precision_mgr: PrecisionManager,
    sampler: DeterministicSampler,
    tracker: StratifiedTracker,
) -> None:
    """Restaura todos os estados de treinamento (modelo, otimizador, scheduler, sampler e RNGs)."""
    # 1. Estados numéricos principais
    model.load_state_dict(ckpt_data["model_state"])
    optimizer.load_state_dict(ckpt_data["optimizer_state"])
    scheduler.load_state_dict(ckpt_data["scheduler_state"])
    precision_mgr.load_state_dict(ckpt_data["precision_state"])

    # 2. Sampler e rastreamento de estratos
    sampler.load_state_dict(ckpt_data["sampler_state"])
    tracker.load_state_dict(ckpt_data["tracker_state"])

    # 3. Geradores pseudoaleatórios (RNG)
    rng_states = ckpt_data["rng_states"]
    random.setstate(rng_states["python_rng"])
    decode_numpy_rng(rng_states["numpy_rng"])
    torch.set_rng_state(rng_states["torch_cpu_rng"])
    if torch.cuda.is_available() and "torch_cuda_rng" in rng_states:
        torch.cuda.set_rng_state_all(rng_states["torch_cuda_rng"])
