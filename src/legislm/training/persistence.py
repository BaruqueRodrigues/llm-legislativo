"""
src/legislm/training/persistence.py
Interface abstrata de persistência e backend local de checkpoints com validação e fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def compute_file_sha256(file_path: Union[str, Path]) -> str:
    """Calcula o hash SHA-256 de um arquivo em blocos de 64KB."""
    p = Path(file_path)
    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class PersistenceBackend(ABC):
    """Interface abstrata de persistência de checkpoints (compartilhada com Frente 08)."""

    @abstractmethod
    def publish_checkpoint(
        self,
        local_checkpoint_dir: Union[str, Path],
        persistent_run_root: Union[str, Path],
    ) -> Dict[str, Any]:
        """Publica um checkpoint local no repositório persistente após validação estrita."""
        pass

    @abstractmethod
    def resolve_checkpoint(
        self,
        persistent_run_root: Union[str, Path],
        selector: str = "latest",
    ) -> Path:
        """Resolve e valida um checkpoint no repositório persistente (com suporte a fallback)."""
        pass

    @abstractmethod
    def list_complete_checkpoints(
        self,
        persistent_run_root: Union[str, Path],
    ) -> List[str]:
        """Lista os IDs de todos os checkpoints com marcador COMPLETE.json válido."""
        pass


class LocalPersistenceBackend(PersistenceBackend):
    """Backend de persistência local para execução em CPU/disco local e testes."""

    def __init__(self, checkpoints_to_keep: int = 2) -> None:
        self.checkpoints_to_keep = max(2, checkpoints_to_keep)

    def publish_checkpoint(
        self,
        local_checkpoint_dir: Union[str, Path],
        persistent_run_root: Union[str, Path],
    ) -> Dict[str, Any]:
        src_dir = Path(local_checkpoint_dir)
        run_root = Path(persistent_run_root)
        manifest_file = src_dir / "manifest.json"

        if not manifest_file.exists():
            raise FileNotFoundError(f"Manifesto não encontrado em {manifest_file}")

        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        run_id = manifest["run_id"]
        checkpoint_id = manifest["checkpoint_id"]
        manifest_sha256 = compute_file_sha256(manifest_file)

        # 1. Valida integridade de todos os arquivos descritos no manifesto
        for file_entry in manifest.get("files", []):
            rel_path = file_entry["path"]
            expected_sha256 = file_entry["sha256"]
            actual_file = src_dir / rel_path
            if not actual_file.exists():
                raise FileNotFoundError(f"Arquivo ausente no checkpoint: {actual_file}")
            actual_sha256 = compute_file_sha256(actual_file)
            if actual_sha256 != expected_sha256:
                raise ValueError(
                    f"Hash incorreto para {rel_path}. Esperado: {expected_sha256}, Obtido: {actual_sha256}"
                )

        # 2. Copia para o destino persistente sob staging / destino final
        dst_dir = run_root / "checkpoints" / checkpoint_id
        dst_dir.mkdir(parents=True, exist_ok=True)

        for file_entry in manifest.get("files", []):
            rel_path = file_entry["path"]
            src_f = src_dir / rel_path
            dst_f = dst_dir / rel_path
            shutil.copy2(src_f, dst_f)

        # Copia o manifesto
        shutil.copy2(manifest_file, dst_dir / "manifest.json")

        # 3. Publica marcador COMPLETE.json por último
        complete_data = {
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "manifest_sha256": manifest_sha256,
        }
        complete_file = dst_dir / "COMPLETE.json"
        with open(complete_file, "w", encoding="utf-8") as f:
            json.dump(complete_data, f, indent=2)

        # 4. Atualiza ponteiro latest.json em persistent_run_root
        latest_data = {
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "manifest_sha256": manifest_sha256,
            "manifest_path": f"checkpoints/{checkpoint_id}/manifest.json",
        }
        latest_file = run_root / "latest.json"
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump(latest_data, f, indent=2)

        # 5. Política de poda segura: mantém ao menos checkpoints_to_keep válidos
        self._prune_old_checkpoints(run_root, preserve_id=checkpoint_id)

        return manifest

    def _validate_checkpoint_dir(self, ckpt_dir: Path) -> bool:
        """Verifica se um diretório possui COMPLETE.json válido e todos os arquivos intactos."""
        complete_file = ckpt_dir / "COMPLETE.json"
        manifest_file = ckpt_dir / "manifest.json"
        if not complete_file.exists() or not manifest_file.exists():
            return False

        try:
            with open(complete_file, "r", encoding="utf-8") as f:
                comp = json.load(f)
            manifest_sha = compute_file_sha256(manifest_file)
            if comp.get("manifest_sha256") != manifest_sha:
                return False

            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            for file_entry in manifest.get("files", []):
                file_path = ckpt_dir / file_entry["path"]
                if not file_path.exists():
                    return False
                if compute_file_sha256(file_path) != file_entry["sha256"]:
                    return False

            return True
        except Exception:
            return False

    def list_complete_checkpoints(self, persistent_run_root: Union[str, Path]) -> List[str]:
        run_root = Path(persistent_run_root)
        ckpts_root = run_root / "checkpoints"
        if not ckpts_root.exists():
            return []

        valid_ids: List[str] = []
        for entry in ckpts_root.iterdir():
            if entry.is_dir() and self._validate_checkpoint_dir(entry):
                valid_ids.append(entry.name)

        return sorted(valid_ids)

    def resolve_checkpoint(
        self,
        persistent_run_root: Union[str, Path],
        selector: str = "latest",
    ) -> Path:
        run_root = Path(persistent_run_root)
        ckpts_root = run_root / "checkpoints"

        if selector == "latest":
            latest_file = run_root / "latest.json"
            if latest_file.exists():
                try:
                    with open(latest_file, "r", encoding="utf-8") as f:
                        latest_data = json.load(f)
                    cand_id = latest_data["checkpoint_id"]
                    cand_dir = ckpts_root / cand_id
                    if self._validate_checkpoint_dir(cand_dir):
                        return cand_dir
                except Exception:
                    pass  # latest.json corrompido, tenta fallback

            # Fallback para o checkpoint completo mais recente disponível
            all_valid = self.list_complete_checkpoints(run_root)
            if not all_valid:
                raise FileNotFoundError(
                    f"Nenhum checkpoint completo e válido encontrado em {persistent_run_root}"
                )
            return ckpts_root / all_valid[-1]

        # Seletor explícito de ID de checkpoint
        target_dir = ckpts_root / selector
        if not target_dir.exists():
            raise FileNotFoundError(f"Checkpoint {selector} não existe em {ckpts_root}")
        if not self._validate_checkpoint_dir(target_dir):
            raise ValueError(f"Checkpoint {selector} está corrompido ou incompleto (COMPLETE ausente ou hash divergente)")

        return target_dir

    def _prune_old_checkpoints(self, run_root: Path, preserve_id: str) -> None:
        """Remove checkpoints antigos excedentes, mantendo ao menos 'checkpoints_to_keep' íntegros."""
        valid_ids = self.list_complete_checkpoints(run_root)
        if len(valid_ids) <= self.checkpoints_to_keep:
            return

        to_remove = valid_ids[: -self.checkpoints_to_keep]
        for rem_id in to_remove:
            if rem_id == preserve_id:
                continue
            rem_dir = run_root / "checkpoints" / rem_id
            try:
                shutil.rmtree(rem_dir)
            except Exception:
                pass


def get_persistence_backend(backend: str = "local", **kwargs: Any) -> PersistenceBackend:
    """Fábrica de backend de persistência com import tardio para integração com Colab (Frente 08)."""
    if backend == "local":
        return LocalPersistenceBackend(**kwargs)
    elif backend in ("drive", "colab"):
        try:
            from legislm.colab.persistence import GoogleDrivePersistenceBackend

            return GoogleDrivePersistenceBackend(**kwargs)  # type: ignore[no-any-return]
        except (ImportError, ModuleNotFoundError) as err:
            raise NotImplementedError(
                f"Backend '{backend}' requer src.legislm.colab.persistence (Frente 08): {err}"
            )
    else:
        raise ValueError(f"Backend de persistência desconhecido: {backend}")
