"""
src/legislm/colab/staging.py
Módulo de staging local de alta velocidade e benchmark de I/O (Drive FUSE vs Disco Local).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def _safe_relative_path(root: Path, relative_path: str) -> Path:
    rel = Path(relative_path)
    if not relative_path or rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise ValueError(f"Caminho inválido no manifesto de staging: {relative_path!r}")
    base = root.resolve()
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Caminho do manifesto escapa da raiz: {relative_path!r}") from exc
    return candidate


def compute_file_sha256(file_path: Union[str, Path], chunk_size: int = 65536) -> str:
    """Calcula o hash SHA-256 de um arquivo em blocos determinísticos de 64KB."""
    p = Path(file_path)
    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def stage_file(
    source_path: Union[str, Path],
    target_path: Union[str, Path],
    expected_sha256: Optional[str] = None,
    verify_hashes: bool = True,
    force_overwrite: bool = False,
) -> Dict[str, Any]:
    """Copia um arquivo para o disco local rápido de forma atômica e verificada por SHA-256."""
    src = Path(source_path)
    dst = Path(target_path)

    if not src.exists():
        raise FileNotFoundError(f"Arquivo de origem não encontrado: {src}")

    src_size = src.stat().st_size
    dst.parent.mkdir(parents=True, exist_ok=True)
    source_sha256 = compute_file_sha256(src) if verify_hashes else expected_sha256
    if expected_sha256 is not None and verify_hashes and source_sha256 != expected_sha256:
        raise ValueError(
            f"Hash da origem diverge do manifesto para {src}. Esperado: {expected_sha256}, Obtido: {source_sha256}"
        )

    # 1. Verificação de Cache Idempotente (se já existe localmente e confere)
    if dst.exists() and not force_overwrite:
        if dst.stat().st_size == src_size:
            if not verify_hashes:
                return {
                    "path": str(dst),
                    "size_bytes": src_size,
                    "sha256": expected_sha256 or "unverified",
                    "cached": True,
                    "elapsed_seconds": 0.0,
                    "speed_mb_s": 0.0,
                }
            # Valida hash do arquivo já existente no cache
            existing_sha = compute_file_sha256(dst)
            if existing_sha == source_sha256:
                return {
                    "path": str(dst),
                    "size_bytes": src_size,
                    "sha256": existing_sha,
                    "cached": True,
                    "elapsed_seconds": 0.0,
                    "speed_mb_s": 0.0,
                }

    # 2. Cópia Atômica via arquivo temporário
    tmp_dst = dst.with_suffix(dst.suffix + f".staging_tmp_{uuid.uuid4().hex[:6]}")
    t0 = time.perf_counter()

    try:
        shutil.copyfile(src, tmp_dst)
        t_copy = time.perf_counter() - t0

        # Verificação de integridade pós-cópia
        actual_sha256 = compute_file_sha256(tmp_dst)
        if verify_hashes and actual_sha256 != source_sha256:
            raise ValueError(
                f"Falha de integridade SHA-256 ao transferir {src} para {dst}. "
                f"Esperado: {source_sha256}, Obtido: {actual_sha256}"
            )

        # Substituição atômica no destino final
        os.replace(tmp_dst, dst)
    except Exception:
        if tmp_dst.exists():
            tmp_dst.unlink(missing_ok=True)
        raise

    speed_mb_s = round((src_size / (1024**2)) / max(t_copy, 1e-6), 2)

    return {
        "path": str(dst),
        "size_bytes": src_size,
        "sha256": actual_sha256,
        "cached": False,
        "elapsed_seconds": round(t_copy, 4),
        "speed_mb_s": speed_mb_s,
    }


def stage_directory(
    source_dir: Union[str, Path],
    target_dir: Union[str, Path],
    manifest_path: Optional[Union[str, Path]] = None,
    verify_hashes: bool = True,
    force_overwrite: bool = False,
) -> Dict[str, Any]:
    """Transfere uma coleção ou diretório inteiro de shards para o disco local de alta velocidade."""
    src_dir = Path(source_dir)
    dst_dir = Path(target_dir)

    if not src_dir.exists():
        raise FileNotFoundError(f"Diretório de origem não existe: {src_dir}")

    dst_dir.mkdir(parents=True, exist_ok=True)

    # 1. Carrega manifesto se disponível
    file_map: Dict[str, Optional[str]] = {}
    if manifest_path is not None:
        if not Path(manifest_path).is_file():
            raise FileNotFoundError(f"Manifesto explícito não encontrado: {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
        items = manifest_data.get("files", [])
        if not isinstance(items, list) or not items:
            raise ValueError("Manifesto explícito deve conter uma lista 'files' não vazia")
        for item in items:
            rel = item["path"]
            _safe_relative_path(src_dir, rel)
            file_map[rel] = item.get("sha256")
    else:
        # Tenta manifesto padrão na origem
        default_manifest = src_dir / "manifest.json"
        if default_manifest.exists():
            with open(default_manifest, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            items = manifest_data.get("files", [])
            if not isinstance(items, list) or not items:
                raise ValueError(f"Manifesto inválido ou vazio: {default_manifest}")
            for item in items:
                rel = item["path"]
                _safe_relative_path(src_dir, rel)
                file_map[rel] = item.get("sha256")
        else:
            # Varredura recursiva de todos os arquivos
            for p in src_dir.rglob("*"):
                if p.is_file() and not p.name.startswith("."):
                    rel = str(p.relative_to(src_dir))
                    file_map[rel] = None

    t_start = time.perf_counter()
    total_bytes = 0
    copied_count = 0
    cached_count = 0
    details: List[Dict[str, Any]] = []

    for rel_path, expected_hash in file_map.items():
        src_file = _safe_relative_path(src_dir, rel_path)
        dst_file = _safe_relative_path(dst_dir, rel_path)

        res = stage_file(
            source_path=src_file,
            target_path=dst_file,
            expected_sha256=expected_hash,
            verify_hashes=verify_hashes,
            force_overwrite=force_overwrite,
        )
        total_bytes += res["size_bytes"]
        if res["cached"]:
            cached_count += 1
        else:
            copied_count += 1
        details.append(res)

    total_time = time.perf_counter() - t_start
    avg_speed_mb_s = round((total_bytes / (1024**2)) / max(total_time, 1e-6), 2)

    return {
        "source_dir": str(src_dir),
        "target_dir": str(dst_dir),
        "total_files": len(file_map),
        "files_copied": copied_count,
        "files_cached": cached_count,
        "total_bytes": total_bytes,
        "total_megabytes": round(total_bytes / (1024**2), 2),
        "elapsed_seconds": round(total_time, 4),
        "overall_speed_mb_s": avg_speed_mb_s,
        "staged_files": details,
    }


def _read_file_sequentially(file_path: Path, block_size_kb: int = 64) -> Tuple[int, float]:
    """Lê um arquivo inteiro sequencialmente em blocos e retorna (bytes_lidos, segundos)."""
    chunk_bytes = block_size_kb * 1024
    total_read = 0
    t0 = time.perf_counter()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_bytes):
            total_read += len(chunk)
    elapsed = time.perf_counter() - t0
    return total_read, elapsed


def benchmark_io(
    source_file_or_dir: Union[str, Path],
    local_target_dir: Union[str, Path],
    test_size_mb: float = 10.0,
    num_reads: int = 3,
    block_size_kb: int = 64,
) -> Dict[str, Any]:
    """Compara o throughput de leitura sequencial direta (ex: Google Drive) vs cópia para disco local rápido."""
    src_p = Path(source_file_or_dir)
    dst_dir = Path(local_target_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    generated_test_file = False
    if src_p.is_dir():
        # Encontra o maior arquivo existente ou cria um arquivo representativo de teste
        existing_files = [f for f in src_p.glob("*") if f.is_file() and not f.name.startswith(".")]
        if existing_files:
            test_src = max(existing_files, key=lambda f: f.stat().st_size)
        else:
            test_src = src_p / f"io_benchmark_test_{uuid.uuid4().hex[:6]}.bin"
            test_bytes = os.urandom(int(test_size_mb * 1024 * 1024))
            with open(test_src, "wb") as f:
                f.write(test_bytes)
            generated_test_file = True
    else:
        test_src = src_p

    file_size_bytes = test_src.stat().st_size
    file_size_mb_exact = file_size_bytes / (1024**2)
    file_size_mb = round(file_size_mb_exact, 2)

    # 1. Leituras Diretas na Origem (Google Drive)
    direct_read_times: List[float] = []
    direct_speeds: List[float] = []
    for _ in range(num_reads):
        bytes_read, t_read = _read_file_sequentially(test_src, block_size_kb=block_size_kb)
        direct_read_times.append(round(t_read, 6))
        direct_speeds.append(round(file_size_mb_exact / max(t_read, 1e-6), 2))


    # 2. Cópia/Staging para o Disco Local com Validação SHA-256
    local_staged_path = dst_dir / test_src.name
    stage_report = stage_file(
        source_path=test_src,
        target_path=local_staged_path,
        verify_hashes=True,
        force_overwrite=True,
    )

    # 3. Leituras Locais no Disco Rápido
    local_read_times: List[float] = []
    local_speeds: List[float] = []
    for _ in range(num_reads):
        bytes_read, t_read = _read_file_sequentially(local_staged_path, block_size_kb=block_size_kb)
        local_read_times.append(round(t_read, 6))
        local_speeds.append(round(file_size_mb_exact / max(t_read, 1e-6), 2))


    # Limpeza se foi arquivo gerado sob demanda
    if generated_test_file and test_src.exists():
        test_src.unlink(missing_ok=True)
    if local_staged_path.exists():
        local_staged_path.unlink(missing_ok=True)

    avg_direct_speed = round(sum(direct_speeds) / len(direct_speeds), 2)
    avg_local_speed = round(sum(local_speeds) / len(local_speeds), 2)
    speedup_ratio = round(avg_local_speed / max(avg_direct_speed, 1e-6), 2)

    recommendation = (
        "Neste payload e nesta sessão, staging local teve maior throughput observado; a amostra não "
        "generaliza para outros arquivos, sessões, cache ou volumes."
        if speedup_ratio > 1.0
        else "Neste payload e nesta sessão, não foi observado ganho de throughput do staging local."
    )

    return {
        "file_name": test_src.name,
        "file_size_mb": file_size_mb,
        "num_passes": num_reads,
        "block_size_kb": block_size_kb,
        "direct_io": {
            "read_times_s": direct_read_times,
            "speeds_mb_s": direct_speeds,
            "avg_speed_mb_s": avg_direct_speed,
        },
        "staging_transfer": {
            "copy_time_s": stage_report["elapsed_seconds"],
            "copy_speed_mb_s": stage_report["speed_mb_s"],
            "sha256_verified": stage_report["sha256"],
        },
        "local_staged_io": {
            "read_times_s": local_read_times,
            "speeds_mb_s": local_speeds,
            "avg_speed_mb_s": avg_local_speed,
        },
        "speedup_factor": speedup_ratio,
        "recommendation": recommendation,
    }
