"""
src/legislm/colab/preflight.py
Módulo de pré-voo (preflight) para auditoria de hardware, armazenamento e termos do Google Colab / Drive.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pyarrow as pa
import torch
import yaml

# Termos contratuais e normativos de elegibilidade (docs/COLAB.md)
OFFICIAL_AI_PRO_POLICY_TERMS: Dict[str, Any] = {
    "policy_version": "2.0.0-2026-10-07",
    "documentation_sources": {
        "google_one_ai_premium_en": "https://support.google.com/googleone/answer/14534406?hl=en",
        "google_one_ai_premium_pt_br": "https://support.google.com/googleone/answer/14534406?hl=pt-BR",
        "colab_faq": "https://research.google.com/colaboratory/faq.html",
        "brazil_eligibility": "https://support.google.com/googleone/answer/16476811?hl=en",
    },
    "effective_terms_summary": [
        "Na consulta de 2026-10-07, a página oficial em inglês lista 200 CCUs do Colab para Google AI Pro; a página pt-BR não menciona Google Colab nem CCUs.",
        "A elegibilidade do plano no Brasil não confirma o status ou saldo da conta individual; conferir benefício no Colab autenticado.",
        "O Brasil consta da lista oficial de países onde Google AI Pro está disponível.",
        "CCUs representam créditos de computação dinâmicos e NÃO garantem horas fixas de GPU ininterrupta.",
        "A alocação de GPU, memória e duração da sessão varia conforme a demanda global do cluster.",
        "Sessões de Colab são efêmeras e sujeitas a desconexões normais por timeout de inatividade ou limite de ciclo.",
        "O plano Google One AI Premium não equivale ao Colab Pro+ (não há garantia de execução em segundo plano).",
        "Assinaturas de armazenamento expandido no Drive (2TB+) NÃO aumentam o disco efêmero local (/content/).",
        "Privacidade estrita: nenhuma credencial pessoal ou email do pesquisador deve ser exposta ou gravada.",
    ],
}


def compute_bytes_sha256(data: bytes) -> str:
    """Calcula o hash SHA-256 de um buffer de bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(file_path: Union[str, Path]) -> str:
    """Calcula o hash SHA-256 de um arquivo em blocos de 64KB."""
    p = Path(file_path)
    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_system_ram_gb() -> Tuple[float, float]:
    """Retorna (total_ram_gb, available_ram_gb) da máquina atual."""
    # 1. Tentativa via /proc/meminfo (Linux / Colab)
    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            total_kb, avail_kb = 0.0, 0.0
            with open(meminfo_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total_kb = float(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        avail_kb = float(line.split()[1])
            if total_kb > 0:
                return round(total_kb / (1024**2), 2), round(avail_kb / (1024**2), 2)
        except Exception:
            pass

    # 2. Tentativa via sysctl (macOS)
    if platform.system() == "Darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            total_bytes = float(out)
            total_gb = round(total_bytes / (1024**3), 2)
            # Aproximação de RAM disponível no macOS
            return total_gb, round(total_gb * 0.6, 2)
        except Exception:
            pass

    # 3. Fallback via os.sysconf
    try:
        pagesize = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        avail_pages = os.sysconf("SC_AVPHYS_PAGES")
        total_gb = round((pagesize * phys_pages) / (1024**3), 2)
        avail_gb = round((pagesize * avail_pages) / (1024**3), 2)
        return total_gb, avail_gb
    except Exception:
        # Estimativa padrão segura se nenhuma chamada do SO for suportada
        return 16.0, 8.0


def probe_gpu_hardware(mock_hardware: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Audita a GPU e recursos CUDA instalados ou utiliza mock para testes determinísticos."""
    if mock_hardware is not None and "gpu" in mock_hardware:
        return dict(mock_hardware["gpu"])

    # Verificação física via PyTorch
    cuda_available = torch.cuda.is_available()
    if not cuda_available:
        return {
            "available": False,
            "device_count": 0,
            "device_name": None,
            "total_vram_gb": 0.0,
            "free_vram_gb": 0.0,
            "compute_capability": None,
            "bf16_supported": False,
            "fp16_supported": False,
            "driver_version": None,
            "nvidia_smi_output": None,
            "reason": "Nenhum acelerador NVIDIA CUDA detectado no ambiente atual.",
        }

    device_count = torch.cuda.device_count()
    device_name = torch.cuda.get_device_name(0)
    device_props = torch.cuda.get_device_properties(0)
    total_vram_gb = round(device_props.total_memory / (1024**3), 2)

    try:
        free_bytes, _ = torch.cuda.mem_get_info(0)
        free_vram_gb = round(free_bytes / (1024**3), 2)
    except Exception:
        free_vram_gb = total_vram_gb

    compute_cap = f"{device_props.major}.{device_props.minor}"
    bf16_supported = torch.cuda.is_bf16_supported() if hasattr(torch.cuda, "is_bf16_supported") else False

    # Consulta ao nvidia-smi para verificar coerência entre PyTorch e driver
    nvidia_smi_out = None
    driver_version = None
    try:
        smi_proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if smi_proc.returncode == 0:
            driver_version = smi_proc.stdout.strip()
            nvidia_smi_out = "nvidia-smi acessível com sucesso"
    except Exception:
        nvidia_smi_out = "nvidia-smi não disponível via subprocesso"

    return {
        "available": True,
        "device_count": device_count,
        "device_name": device_name,
        "total_vram_gb": total_vram_gb,
        "free_vram_gb": free_vram_gb,
        "compute_capability": compute_cap,
        "bf16_supported": bf16_supported,
        "fp16_supported": True,
        "driver_version": driver_version,
        "nvidia_smi_output": nvidia_smi_out,
    }


def verify_drive_roundtrip_io(drive_root: Path) -> Dict[str, Any]:
    """Executa teste de escrita, leitura e validação SHA-256 no armazenamento persistente do Drive."""
    drive_root = Path(drive_root)
    if not drive_root.exists():
        return {
            "accessible": False,
            "error": f"Diretório raiz persistente '{drive_root}' não existe ou não está montado.",
        }

    test_file = drive_root / f".preflight_io_test_{uuid.uuid4().hex[:8]}.tmp"
    test_payload = os.urandom(8192)  # 8 KB de bytes aleatórios
    expected_sha256 = compute_bytes_sha256(test_payload)

    start_write = time.perf_counter()
    try:
        with open(test_file, "wb") as f:
            f.write(test_payload)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        test_file.unlink(missing_ok=True)
        return {
            "accessible": False,
            "error": f"Falha na escrita no diretório persistente {drive_root}: {e}",
        }
    write_time = time.perf_counter() - start_write

    start_read = time.perf_counter()
    try:
        with open(test_file, "rb") as f:
            read_bytes = f.read()
    except Exception as e:
        if test_file.exists():
            test_file.unlink(missing_ok=True)
        return {
            "accessible": False,
            "error": f"Falha na releitura do arquivo de teste em {drive_root}: {e}",
        }
    read_time = time.perf_counter() - start_read

    # Limpeza do arquivo de prova
    test_file.unlink(missing_ok=True)

    actual_sha256 = compute_bytes_sha256(read_bytes)
    hash_matched = (actual_sha256 == expected_sha256)
    if not hash_matched:
        return {
            "accessible": True,
            "read_write_verified": False,
            "error": "Hash divergente após releitura do armazenamento persistente.",
            "payload_bytes": len(read_bytes),
            "sha256_expected": expected_sha256,
            "sha256_actual": actual_sha256,
        }

    # Medição de espaço no disco persistente
    try:
        drive_usage = shutil.disk_usage(drive_root)
        drive_free_gb = round(drive_usage.free / (1024**3), 2)
        drive_total_gb = round(drive_usage.total / (1024**3), 2)
    except Exception:
        drive_free_gb, drive_total_gb = None, None

    return {
        "accessible": True,
        "read_write_verified": hash_matched,
        "write_seconds": round(write_time, 4),
        "read_seconds": round(read_time, 4),
        "payload_bytes": len(test_payload),
        "sha256_verified": expected_sha256,
        "drive_free_gb": drive_free_gb,
        "drive_total_gb": drive_total_gb,
    }


def run_preflight(
    config: Optional[Union[Dict[str, Any], Path, str]] = None,
    mock_hardware: Optional[Dict[str, Any]] = None,
    allow_cpu_fallback: Optional[bool] = None,
    user_provided_ccu: Optional[float] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Executa auditoria completa de pré-voo em conformidade estrita com docs/COLAB.md."""
    cfg_data: Dict[str, Any] = {}
    if isinstance(config, (str, Path)):
        cfg_path = Path(config)
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_data = yaml.safe_load(f) or {}
    elif isinstance(config, dict):
        cfg_data = config.copy()

    # Parâmetros de pré-requisitos
    preflight_cfg = cfg_data.get("preflight", {})
    min_vram_gb = float(preflight_cfg.get("min_vram_gb", 8.0))
    min_ram_gb = float(preflight_cfg.get("min_ram_gb", 10.0))
    min_disk_free_gb = float(preflight_cfg.get("min_disk_free_gb", 20.0))
    check_gpu = bool(preflight_cfg.get("check_gpu", True))

    if allow_cpu_fallback is None:
        allow_cpu_fallback = bool(preflight_cfg.get("allow_cpu_fallback", False))

    drive_root_str = cfg_data.get("drive_root")
    local_scratch_str = cfg_data.get("local_scratch_root", "/content/llm_legislativo")
    session_name = cfg_data.get("session_name", f"session_{int(time.time())}")

    # 1. Auditoria de GPU / Hardware
    gpu_info = probe_gpu_hardware(mock_hardware=mock_hardware)

    # 2. Auditoria de Memória RAM do Sistema
    if mock_hardware is not None and "ram" in mock_hardware:
        total_ram_gb = float(mock_hardware["ram"]["total_gb"])
        avail_ram_gb = float(mock_hardware["ram"]["available_gb"])
    else:
        total_ram_gb, avail_ram_gb = get_system_ram_gb()

    # 3. Auditoria de Disco Local
    local_scratch = Path(local_scratch_str)
    try:
        local_scratch.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        # Em ambiente local (macOS/CI) onde /content não é gravável, usa fallback no diretório de trabalho/scratch
        local_scratch = Path.cwd() / "scratch" / "colab"
        local_scratch.mkdir(parents=True, exist_ok=True)

    if mock_hardware is not None and "disk" in mock_hardware:
        local_disk_total_gb = float(mock_hardware["disk"]["total_gb"])
        local_disk_free_gb = float(mock_hardware["disk"]["free_gb"])
    else:
        disk_usage = shutil.disk_usage(local_scratch)
        local_disk_total_gb = round(disk_usage.total / (1024**3), 2)
        local_disk_free_gb = round(disk_usage.free / (1024**3), 2)

    # 4. Auditoria de Persistência Drive (se configurado)
    drive_verification = None
    if drive_root_str:
        drive_path = Path(drive_root_str)
        # Se estiver em mock ou ambiente local de teste onde o drive_root foi criado
        if drive_path.exists():
            drive_verification = verify_drive_roundtrip_io(drive_path)
        else:
            drive_verification = {
                "accessible": False,
                "error": f"Caminho do Google Drive '{drive_root_str}' não acessível nesta sessão.",
            }

    # 5. Auditoria de Versões e Precisão Numérica
    software_env = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "numpy_version": np.__version__,
        "pyarrow_version": pa.__version__,
        "tf32_matmul_enabled": bool(torch.backends.cuda.matmul.allow_tf32) if hasattr(torch.backends.cuda.matmul, "allow_tf32") else False,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }

    # 6. Avaliação de Aprovação dos Gates de Hardware
    validation_checks: List[Dict[str, Any]] = []
    overall_status = "PASSED"

    # Checagem de GPU
    if check_gpu:
        if gpu_info["available"]:
            if gpu_info["total_vram_gb"] >= min_vram_gb:
                validation_checks.append(
                    {"gate": "gpu_vram", "passed": True, "detail": f"{gpu_info['total_vram_gb']}GB >= {min_vram_gb}GB"}
                )
            else:
                passed = allow_cpu_fallback
                validation_checks.append(
                    {
                        "gate": "gpu_vram",
                        "passed": passed,
                        "detail": f"VRAM insuficiente: {gpu_info['total_vram_gb']}GB < {min_vram_gb}GB (fallback: {allow_cpu_fallback})",
                    }
                )
                if not allow_cpu_fallback:
                    overall_status = "FAILED"
        else:
            if allow_cpu_fallback:
                overall_status = "CPU_FALLBACK"
                validation_checks.append(
                    {
                        "gate": "gpu_availability",
                        "passed": True,
                        "detail": "GPU não detectada; modo CPU Fallback explicitamente autorizado para smoke/testes.",
                    }
                )
            else:
                overall_status = "FAILED"
                validation_checks.append(
                    {
                        "gate": "gpu_availability",
                        "passed": False,
                        "detail": "GPU obrigatória mas não encontrada no ambiente atual.",
                    }
                )
    else:
        validation_checks.append(
            {"gate": "gpu_check", "passed": True, "detail": "Checagem de GPU desativada por configuração."}
        )

    # Checagem de RAM
    ram_ok = (total_ram_gb >= min_ram_gb)
    validation_checks.append(
        {"gate": "system_ram", "passed": ram_ok, "detail": f"RAM {total_ram_gb}GB (mínimo: {min_ram_gb}GB)"}
    )
    if not ram_ok and not allow_cpu_fallback:
        overall_status = "FAILED"

    # Checagem de Disco Local
    disk_ok = (local_disk_free_gb >= min_disk_free_gb)
    validation_checks.append(
        {"gate": "local_disk", "passed": disk_ok, "detail": f"Disco livre {local_disk_free_gb}GB (mínimo: {min_disk_free_gb}GB)"}
    )
    if not disk_ok and not allow_cpu_fallback:
        overall_status = "FAILED"

    # Checagem de Drive
    if drive_verification:
        drive_ok = drive_verification.get("read_write_verified", False)
        validation_checks.append(
            {
                "gate": "drive_rw_proof",
                "passed": drive_ok,
                "detail": "Escrita/leitura com verificação SHA-256 no Drive bem-sucedida"
                if drive_ok
                else drive_verification.get("error", "Falha no teste de Drive"),
            }
        )
        if not drive_ok and not allow_cpu_fallback:
            overall_status = "FAILED"

    # Consolidação do Relatório Final
    report = {
        "status": overall_status,
        "session_id": session_name,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "user_provided_ccu": user_provided_ccu,
        "account_policy": OFFICIAL_AI_PRO_POLICY_TERMS,
        "hardware": {
            "gpu": gpu_info,
            "system_ram_gb": total_ram_gb,
            "available_ram_gb": avail_ram_gb,
            "local_disk_total_gb": local_disk_total_gb,
            "local_disk_free_gb": local_disk_free_gb,
        },
        "persistence_storage": drive_verification,
        "software_environment": software_env,
        "validation_checks": validation_checks,
    }

    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    return report
