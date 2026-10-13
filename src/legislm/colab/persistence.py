"""
src/legislm/colab/persistence.py
Backend de persistência seguro para Google Drive / Colab com escrita atômica,
verificação de integridade pós-cópia, rollback automático contra corrupção e retenção segura.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from legislm.training.checkpoint import validate_checkpoint_manifest
from legislm.training.persistence import PersistenceBackend, compute_file_sha256

logger = logging.getLogger(__name__)


def _safe_relative_file(root: Path, relative_path: str) -> Path:
    """Resolve a manifest path without permitting absolute paths or traversal."""
    rel = Path(relative_path)
    if not relative_path or rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError(f"Caminho inválido no manifesto: {relative_path!r}")
    base = root.resolve()
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Caminho do manifesto escapa do checkpoint: {relative_path!r}") from exc
    if candidate.name in {"manifest.json", "COMPLETE.json"}:
        raise ValueError(f"Caminho reservado no manifesto: {relative_path!r}")
    return candidate


def _safe_checkpoint_id(checkpoint_id: str) -> str:
    if not isinstance(checkpoint_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", checkpoint_id):
        raise ValueError(f"checkpoint_id inválido: {checkpoint_id!r}")
    return checkpoint_id


class GoogleDrivePersistenceBackend(PersistenceBackend):
    """Backend de persistência para Google Drive e ambientes em nuvem efêmeros (Frente 08 / Gate G5).

    Características:
    - Escrita em diretório candidato temporário para evitar estados parciais em falhas de conexão/timeout.
    - Releitura completa e cálculo de SHA-256 no armazenamento remoto antes de comitar.
    - Emissão atômica de COMPLETE.json e atualização transacional do ponteiro latest.json.
    - Rollback automático para o checkpoint íntegro anterior se o mais recente for corrompido.
    - Política de retenção segura: mantém os 2 mais recentes válidos + melhor checkpoint + marcos.
    """

    def __init__(
        self,
        checkpoints_to_keep: int = 2,
        keep_best: bool = True,
        max_storage_bytes: Optional[int] = None,
        milestone_interval_steps: Optional[int] = None,
        drive_root: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        self.checkpoints_to_keep = max(2, checkpoints_to_keep)
        self.keep_best = keep_best
        if max_storage_bytes is not None and max_storage_bytes <= 0:
            raise ValueError("max_storage_bytes deve ser um inteiro positivo")
        if milestone_interval_steps is not None and milestone_interval_steps <= 0:
            raise ValueError("milestone_interval_steps deve ser um inteiro positivo")
        self.max_storage_bytes = max_storage_bytes
        self.milestone_interval_steps = milestone_interval_steps
        self.last_retention_status: Dict[str, Any] = {}
        self.drive_root = Path(drive_root) if drive_root else None

    def publish_checkpoint(
        self,
        local_checkpoint_dir: Union[str, Path],
        persistent_run_root: Union[str, Path],
    ) -> Dict[str, Any]:
        """Publica um checkpoint do staging local para o Google Drive com verificação estrita."""
        src_dir = Path(local_checkpoint_dir)
        run_root = Path(persistent_run_root)
        manifest_file = src_dir / "manifest.json"

        if not manifest_file.exists():
            raise FileNotFoundError(f"Manifesto de checkpoint não encontrado em: {manifest_file}")

        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        # 1. Validação estrita contra o esquema normativo v1
        validate_checkpoint_manifest(manifest)

        run_id = manifest["run_id"]
        checkpoint_id = _safe_checkpoint_id(manifest["checkpoint_id"])
        entries = manifest.get("files", [])
        paths = [_safe_relative_file(src_dir, entry["path"]) for entry in entries]
        if len(set(paths)) != len(paths):
            raise ValueError("Manifesto contém caminhos duplicados")
        manifest_sha256 = compute_file_sha256(manifest_file)

        # 2. Validação prévia de integridade no disco local antes do envio
        for file_entry in manifest.get("files", []):
            rel_path = file_entry["path"]
            expected_sha = file_entry["sha256"]
            expected_size = file_entry["size_bytes"]
            local_f = _safe_relative_file(src_dir, rel_path)
            if not local_f.exists():
                raise FileNotFoundError(f"Arquivo local ausente para publicação: {local_f}")
            actual_sha = compute_file_sha256(local_f)
            if local_f.stat().st_size != expected_size:
                raise ValueError(f"Tamanho local divergente para {rel_path}")
            if actual_sha != expected_sha:
                raise ValueError(
                    f"Hash local divergente para {rel_path}. Esperado: {expected_sha}, Obtido: {actual_sha}"
                )

        # 3. Preparação do diretório candidato temporário no Drive
        ckpts_root = run_root / "checkpoints"
        ckpts_root.mkdir(parents=True, exist_ok=True)
        final_ckpt_dir = ckpts_root / checkpoint_id
        if final_ckpt_dir.exists():
            if self._validate_checkpoint_dir(final_ckpt_dir):
                existing_sha = compute_file_sha256(final_ckpt_dir / "manifest.json")
                if existing_sha == manifest_sha256:
                    return manifest
                raise FileExistsError(
                    f"Checkpoint completo {checkpoint_id!r} já existe com outro manifesto; IDs são imutáveis."
                )
            # Preserve também cópias danificadas para auditoria; IDs não são reutilizados.
            raise FileExistsError(
                f"Já existe o diretório {checkpoint_id!r}, mas ele está incompleto/corrompido; "
                "publique com outro checkpoint_id após investigar a falha."
            )

        candidate_dir = ckpts_root / f".tmp_{checkpoint_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        candidate_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 4. Cópia de todos os arquivos e do manifesto para o candidato
            for file_entry in manifest.get("files", []):
                rel_path = file_entry["path"]
                src_f = _safe_relative_file(src_dir, rel_path)
                dst_f = _safe_relative_file(candidate_dir, rel_path)
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_f, dst_f)

            shutil.copy2(manifest_file, candidate_dir / "manifest.json")

            # 5. RELEITURA E VERIFICAÇÃO CRIPTOGRÁFICA NO DRIVE (crítico para FUSE/Drive)
            cand_manifest_sha = compute_file_sha256(candidate_dir / "manifest.json")
            if cand_manifest_sha != manifest_sha256:
                raise ValueError(
                    f"Integridade do manifesto violada durante a gravação no Drive: "
                    f"Esperado {manifest_sha256}, Obtido no Drive {cand_manifest_sha}"
                )

            for file_entry in manifest.get("files", []):
                rel_path = file_entry["path"]
                expected_sha = file_entry["sha256"]
                cand_file = candidate_dir / rel_path
                if not cand_file.exists():
                    raise FileNotFoundError(f"Arquivo ausente na releitura do Drive: {cand_file}")
                if cand_file.stat().st_size != file_entry["size_bytes"]:
                    raise ValueError(f"Tamanho divergente na releitura do Drive para {rel_path}")
                cand_sha = compute_file_sha256(cand_file)
                if cand_sha != expected_sha:
                    raise ValueError(
                        f"Integridade violada na releitura do Drive para {rel_path}: "
                        f"Esperado {expected_sha}, Obtido {cand_sha}"
                    )

            # 6. Efetivação atômica: substituição do diretório final
            # Drive/FUSE não oferece contrato de rename atômico. Cria o destino final
            # ainda incompleto e publica COMPLETE somente após uma segunda releitura.
            final_ckpt_dir.mkdir()
            for file_entry in manifest.get("files", []):
                rel_path = file_entry["path"]
                src_f = _safe_relative_file(candidate_dir, rel_path)
                dst_f = _safe_relative_file(final_ckpt_dir, rel_path)
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_f, dst_f)
            shutil.copy2(candidate_dir / "manifest.json", final_ckpt_dir / "manifest.json")

            if compute_file_sha256(final_ckpt_dir / "manifest.json") != manifest_sha256:
                raise ValueError("Manifesto divergente na releitura do destino persistente")
            for file_entry in manifest.get("files", []):
                final_file = _safe_relative_file(final_ckpt_dir, file_entry["path"])
                if compute_file_sha256(final_file) != file_entry["sha256"]:
                    raise ValueError(f"Hash divergente na releitura persistente: {file_entry['path']}")

        except Exception as e:
            if candidate_dir.exists():
                shutil.rmtree(candidate_dir, ignore_errors=True)
            raise e

        # 7. Emissão do marcador atômico COMPLETE.json
        complete_data = {
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "manifest_sha256": manifest_sha256,
            "schema_version": 1,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        complete_file = final_ckpt_dir / "COMPLETE.json"
        with open(complete_file, "x", encoding="utf-8") as f:
            json.dump(complete_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if not self._validate_checkpoint_dir(final_ckpt_dir):
            raise ValueError("Checkpoint não passou validação após publicar COMPLETE")

        # 8. Atualização atômica do ponteiro latest.json em persistent_run_root
        latest_data = {
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "manifest_sha256": manifest_sha256,
            "manifest_path": f"checkpoints/{checkpoint_id}/manifest.json",
            "global_step": manifest.get("global_step", 0),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        latest_file = run_root / "latest.json"
        # latest é somente um índice recuperável: em caso de escrita interrompida,
        # resolve_checkpoint varre os marcadores COMPLETE e escolhe o step válido.
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump(latest_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        # 9. Rastreamento e preservação do melhor checkpoint (best.json)
        best_id: Optional[str] = None
        if self.keep_best:
            best_id = self._update_best_checkpoint(
                run_root=run_root,
                manifest=manifest,
                checkpoint_id=checkpoint_id,
                manifest_sha256=manifest_sha256,
                ckpt_dir=final_ckpt_dir,
            )

        # 10. Política de retenção segura: poda somente após sucesso comprovado
        self._prune_old_checkpoints(run_root, preserve_id=checkpoint_id, best_id=best_id)

        return manifest

    def _update_best_checkpoint(
        self,
        run_root: Path,
        manifest: Dict[str, Any],
        checkpoint_id: str,
        manifest_sha256: str,
        ckpt_dir: Optional[Path] = None,
    ) -> Optional[str]:
        """Atualiza o registro do melhor checkpoint caso uma métrica de validação esteja presente."""
        best_file = run_root / "best.json"
        current_loss = manifest.get("best_val_loss")

        # Se manifest não possui best_val_loss direta, tenta carregar de métricas extras
        if current_loss is None:
            extra = manifest.get("extra_metrics", {})
            current_loss = extra.get("eval_loss") or extra.get("val_loss")

        # Se ainda for None, inspeciona checkpoint.pt
        if current_loss is None and ckpt_dir is not None:
            pt_path = ckpt_dir / "checkpoint.pt"
            if pt_path.exists():
                try:
                    import torch
                    pt_data = torch.load(pt_path, weights_only=True)
                    current_loss = pt_data.get("best_val_loss")
                except Exception:
                    pass


        if current_loss is None:
            if best_file.exists():
                try:
                    with open(best_file, "r", encoding="utf-8") as f:
                        b_data = json.load(f)
                    return str(b_data.get("checkpoint_id"))
                except Exception:
                    pass
            return None

        current_loss = float(current_loss)
        is_new_best = True

        if best_file.exists():
            try:
                with open(best_file, "r", encoding="utf-8") as f:
                    b_data = json.load(f)
                prev_best = float(b_data.get("val_loss", float("inf")))
                if current_loss >= prev_best:
                    is_new_best = False
                    return str(b_data.get("checkpoint_id"))
            except Exception:
                pass

        if is_new_best:
            best_payload = {
                "checkpoint_id": checkpoint_id,
                "manifest_sha256": manifest_sha256,
                "val_loss": current_loss,
                "global_step": manifest.get("global_step", 0),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            tmp_best = run_root / ".best.json.tmp"
            with open(tmp_best, "w", encoding="utf-8") as f:
                json.dump(best_payload, f, indent=2)
            os.replace(tmp_best, best_file)
            return checkpoint_id

        return None

    def _validate_checkpoint_dir(self, ckpt_dir: Path) -> bool:
        """Verifica se um diretório possui COMPLETE.json válido e todos os arquivos intactos."""
        if not ckpt_dir.exists() or not ckpt_dir.is_dir():
            return False

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

            if comp.get("run_id") != manifest.get("run_id") or comp.get("checkpoint_id") != manifest.get("checkpoint_id"):
                return False
            if ckpt_dir.name != manifest.get("checkpoint_id"):
                return False
            _safe_checkpoint_id(manifest["checkpoint_id"])
            entries = manifest.get("files", [])
            resolved = [_safe_relative_file(ckpt_dir, entry["path"]) for entry in entries]
            if not entries or len(set(resolved)) != len(resolved):
                return False
            for file_entry, file_path in zip(entries, resolved):
                if not file_path.exists():
                    return False
                if file_path.stat().st_size != file_entry.get("size_bytes"):
                    return False
                if compute_file_sha256(file_path) != file_entry["sha256"]:
                    return False

            return True
        except Exception:
            return False

    def list_complete_checkpoints(self, persistent_run_root: Union[str, Path]) -> List[str]:
        """Lista os IDs de todos os checkpoints com marcador COMPLETE.json válido, ordenados por step."""
        run_root = Path(persistent_run_root)
        ckpts_root = run_root / "checkpoints"
        if not ckpts_root.exists():
            return []

        valid_entries: List[Tuple[int, str]] = []
        for entry in ckpts_root.iterdir():
            if entry.is_dir() and not entry.name.startswith(".") and self._validate_checkpoint_dir(entry):
                # Extrai global_step do manifest para ordenação consistente
                step = 0
                try:
                    with open(entry / "manifest.json", "r", encoding="utf-8") as f:
                        m = json.load(f)
                    step = int(m.get("global_step", 0))
                except Exception:
                    pass
                valid_entries.append((step, entry.name))

        valid_entries.sort(key=lambda x: (x[0], x[1]))
        return [name for _, name in valid_entries]

    def resolve_checkpoint(
        self,
        persistent_run_root: Union[str, Path],
        selector: str = "latest",
    ) -> Path:
        """Resolve e valida um checkpoint no Drive, acionando rollback automático em caso de corrupção."""
        run_root = Path(persistent_run_root)
        ckpts_root = run_root / "checkpoints"

        if selector == "latest":
            latest_file = run_root / "latest.json"
            if latest_file.exists():
                try:
                    with open(latest_file, "r", encoding="utf-8") as f:
                        latest_data = json.load(f)
                    cand_id = _safe_checkpoint_id(latest_data["checkpoint_id"])
                    cand_dir = ckpts_root / cand_id
                    manifest_file = cand_dir / "manifest.json"
                    if (
                        self._validate_checkpoint_dir(cand_dir)
                        and latest_data.get("run_id") == json.loads(manifest_file.read_text(encoding="utf-8")).get("run_id")
                        and latest_data.get("manifest_sha256") == compute_file_sha256(manifest_file)
                    ):
                        return cand_dir
                    else:
                        logger.warning(
                            f"Checkpoint '{cand_id}' apontado por latest.json está corrompido ou incompleto. "
                            f"Iniciando rollback automático para checkpoint íntegro anterior."
                        )
                except Exception as err:
                    logger.warning(f"Erro ao ler latest.json ({err}). Iniciando busca por fallback.")

            # Rollback automático para o checkpoint completo mais recente disponível
            all_valid = self.list_complete_checkpoints(run_root)
            if not all_valid:
                raise FileNotFoundError(
                    f"Nenhum checkpoint completo e íntegro encontrado em {persistent_run_root}."
                )
            recovered_id = all_valid[-1]
            logger.info(f"Rollback concluído: recuperado checkpoint íntegro '{recovered_id}'.")
            return ckpts_root / recovered_id

        # Seletor explícito de ID de checkpoint
        target_dir = ckpts_root / _safe_checkpoint_id(selector)
        if not target_dir.exists():
            raise FileNotFoundError(f"Checkpoint '{selector}' não existe em {ckpts_root}")
        if not self._validate_checkpoint_dir(target_dir):
            raise ValueError(
                f"Checkpoint '{selector}' está corrompido ou incompleto (COMPLETE ausente ou hash divergente)"
            )

        return target_dir

    def _prune_old_checkpoints(
        self,
        run_root: Path,
        preserve_id: str,
        best_id: Optional[str] = None,
    ) -> None:
        """Remove versões antigas mantendo ao menos 'checkpoints_to_keep' válidos + melhor checkpoint."""
        valid_ids = self.list_complete_checkpoints(run_root)
        if not valid_ids:
            return

        ckpts_root = run_root / "checkpoints"
        records: Dict[str, Dict[str, int]] = {}
        for ckpt_id in valid_ids:
            ckpt_dir = ckpts_root / ckpt_id
            manifest = json.loads((ckpt_dir / "manifest.json").read_text(encoding="utf-8"))
            size = sum(
                _safe_relative_file(ckpt_dir, entry["path"]).stat().st_size
                for entry in manifest.get("files", [])
            ) + (ckpt_dir / "manifest.json").stat().st_size + (ckpt_dir / "COMPLETE.json").stat().st_size
            records[ckpt_id] = {"step": int(manifest.get("global_step", 0)), "size": size}

        protected = set(valid_ids[-self.checkpoints_to_keep :])
        protected.add(preserve_id)
        if best_id is not None and best_id in records:
            protected.add(best_id)
        if self.milestone_interval_steps is not None:
            protected.update(
                ckpt_id
                for ckpt_id, record in records.items()
                if record["step"] > 0 and record["step"] % self.milestone_interval_steps == 0
            )

        total_bytes = sum(record["size"] for record in records.values())
        removable = [ckpt_id for ckpt_id in valid_ids if ckpt_id not in protected]
        # Remove oldest non-protected copies only after the newly published checkpoint
        # and all required recovery/best/milestone copies have been verified.
        for rem_id in removable:
            if self.max_storage_bytes is None and len(records) <= len(protected):
                break
            if self.max_storage_bytes is not None and total_bytes <= self.max_storage_bytes:
                break
            rem_dir = ckpts_root / rem_id
            try:
                shutil.rmtree(rem_dir)
                total_bytes -= records.pop(rem_id)["size"]
                logger.info("Checkpoint antigo podado após validar novas cópias: %s", rem_id)
            except Exception as e:
                logger.warning("Não foi possível remover checkpoint antigo %s: %s", rem_id, e)

        quota_met = self.max_storage_bytes is None or total_bytes <= self.max_storage_bytes
        self.last_retention_status = {
            "quota_bytes": self.max_storage_bytes,
            "retained_bytes": total_bytes,
            "quota_met": quota_met,
            "retained_checkpoint_ids": sorted(records),
        }
        if not quota_met:
            logger.warning(
                "Quota de checkpoints excedida (%s > %s bytes); cópias protegidas não foram removidas.",
                total_bytes,
                self.max_storage_bytes,
            )


# Funções convenientes de nível de módulo compatíveis com a especificação funcional
def publish_checkpoint(
    local_checkpoint_dir: Union[str, Path],
    persistent_run_root: Union[str, Path],
    checkpoints_to_keep: int = 2,
    keep_best: bool = True,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Publica checkpoint local no Google Drive através do GoogleDrivePersistenceBackend."""
    backend = GoogleDrivePersistenceBackend(
        checkpoints_to_keep=checkpoints_to_keep,
        keep_best=keep_best,
        **kwargs,
    )
    return backend.publish_checkpoint(local_checkpoint_dir, persistent_run_root)


def resolve_checkpoint(
    persistent_run_root: Union[str, Path],
    selector: str = "latest",
    **kwargs: Any,
) -> Path:
    """Resolve e valida checkpoint no Google Drive com suporte a rollback automático."""
    backend = GoogleDrivePersistenceBackend(**kwargs)
    return backend.resolve_checkpoint(persistent_run_root, selector=selector)


def list_complete_checkpoints(
    persistent_run_root: Union[str, Path],
    **kwargs: Any,
) -> List[str]:
    """Lista todos os checkpoints íntegros e completos no Google Drive."""
    backend = GoogleDrivePersistenceBackend(**kwargs)
    return backend.list_complete_checkpoints(persistent_run_root)
