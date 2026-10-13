"""
src/legislm/colab/cli.py
Interface de linha de comando para preflight, staging, sincronização e benchmarks no Google Colab.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from legislm.colab.preflight import run_preflight
from legislm.colab.staging import benchmark_io, stage_directory
from legislm.colab.persistence import GoogleDrivePersistenceBackend


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m legislm.colab.cli",
        description="CLI de Staging, Preflight e Persistência do LLM Legislativo no Google Colab",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Subcomando preflight
    p_preflight = subparsers.add_parser("preflight", help="Executa auditoria de hardware, disco e termos do Colab")
    p_preflight.add_argument(
        "--config",
        type=str,
        default="configs/colab/pilot.yaml",
        help="Caminho do arquivo YAML de configuração do Colab (default: configs/colab/pilot.yaml)",
    )
    p_preflight.add_argument(
        "--allow-cpu",
        action="store_true",
        help="Autoriza fallback auditado para CPU caso nenhuma GPU seja detectada",
    )
    p_preflight.add_argument(
        "--ccu",
        type=float,
        default=None,
        help="Saldo de Compute Units (CCU) informado pelo pesquisador",
    )
    p_preflight.add_argument(
        "--output",
        type=str,
        default=None,
        help="Caminho para salvar o relatório de preflight em JSON",
    )

    # 2. Subcomando stage
    p_stage = subparsers.add_parser("stage", help="Transfere shards do Drive para o disco local de alta velocidade")
    p_stage.add_argument(
        "--config",
        type=str,
        default="configs/colab/pilot.yaml",
        help="Caminho do arquivo de configuração do Colab",
    )
    p_stage.add_argument(
        "--source",
        type=str,
        default=None,
        help="Diretório de origem no Drive (sobrescreve o config)",
    )
    p_stage.add_argument(
        "--target",
        type=str,
        default=None,
        help="Diretório de destino no disco local (sobrescreve o config)",
    )
    p_stage.add_argument(
        "--manifest",
        type=str,
        default=None,
        help="Caminho opcional para o manifesto de arquivos e hashes SHA-256",
    )
    p_stage.add_argument(
        "--no-verify-hashes",
        action="store_true",
        help="Desativa validação de integridade por hash SHA-256",
    )
    p_stage.add_argument(
        "--force",
        action="store_true",
        help="Força reescrita de arquivos existentes no cache local",
    )

    # 3. Subcomando sync
    p_sync = subparsers.add_parser("sync", help="Sincroniza checkpoints ou artefatos entre local e Drive")
    p_sync.add_argument("--run-id", type=str, required=True, help="ID da execução de treinamento")
    p_sync.add_argument(
        "--persistent-root",
        type=str,
        required=True,
        help="Diretório raiz persistente da run (ex: /content/drive/MyDrive/.../runs/RUN_ID)",
    )
    p_sync.add_argument(
        "--local-dir",
        type=str,
        required=True,
        help="Diretório local correspondente",
    )
    p_sync.add_argument(
        "--direction",
        choices=["to_drive", "from_drive"],
        default="to_drive",
        help="Sentido da sincronização ('to_drive' ou 'from_drive')",
    )

    # 4. Subcomando benchmark
    p_bench = subparsers.add_parser("benchmark", help="Executa benchmark de I/O (Drive vs Local) ou de GPU")
    p_bench.add_argument(
        "--config",
        type=str,
        default="configs/colab/pilot.yaml",
        help="Caminho do arquivo de configuração",
    )
    p_bench.add_argument(
        "--type",
        choices=["io", "gpu"],
        default="io",
        help="Tipo de benchmark a executar ('io' ou 'gpu')",
    )
    p_bench.add_argument(
        "--source",
        type=str,
        default=None,
        help="Caminho de origem para o teste de I/O",
    )
    p_bench.add_argument(
        "--target",
        type=str,
        default=None,
        help="Caminho local para o teste de I/O",
    )
    p_bench.add_argument(
        "--output",
        type=str,
        default=None,
        help="Caminho para salvar o resultado em JSON",
    )

    return parser.parse_args(args)


def main(args: Optional[List[str]] = None) -> int:
    parsed = parse_args(args)

    if parsed.command == "preflight":
        allow_cpu = True if parsed.allow_cpu else None
        report = run_preflight(
            config=parsed.config,
            allow_cpu_fallback=allow_cpu,
            user_provided_ccu=parsed.ccu,
            output_path=parsed.output,
        )
        print(json.dumps(report, indent=2))
        if report["status"] in ("PASSED", "CPU_FALLBACK"):
            return 0
        return 1

    elif parsed.command == "stage":
        source_dir = parsed.source
        target_dir = parsed.target
        if not source_dir or not target_dir:
            # Lê valores padrão do YAML
            cfg_p = Path(parsed.config)
            if cfg_p.exists():
                with open(cfg_p, "r", encoding="utf-8") as f:
                    cfg_data = yaml.safe_load(f) or {}
                if not source_dir:
                    source_dir = str(Path(cfg_data.get("drive_root", "")) / "releases")
                if not target_dir:
                    target_dir = str(Path(cfg_data.get("local_scratch_root", "/content/llm_legislativo")) / "staging")

        if not source_dir or not target_dir:
            print("Erro: source e target devem ser especificados via CLI ou arquivo de configuração.", file=sys.stderr)
            return 1

        print(f"Iniciando staging de '{source_dir}' para '{target_dir}'...")
        stage_report = stage_directory(
            source_dir=source_dir,
            target_dir=target_dir,
            manifest_path=parsed.manifest,
            verify_hashes=not parsed.no_verify_hashes,
            force_overwrite=parsed.force,
        )
        print(json.dumps(stage_report, indent=2))
        return 0

    elif parsed.command == "sync":
        backend = GoogleDrivePersistenceBackend()
        pers_root = Path(parsed.persistent_root)
        local_p = Path(parsed.local_dir)

        if parsed.direction == "to_drive":
            print(f"Sincronizando checkpoints locais de '{local_p}' para o Drive em '{pers_root}'...")
            manifest = backend.publish_checkpoint(local_checkpoint_dir=local_p, persistent_run_root=pers_root)
            print(f"Checkpoint publicado com sucesso: {manifest.get('checkpoint_id')}")
        else:
            print(f"Resolvendo e restaurando último checkpoint do Drive em '{pers_root}'...")
            resolved_dir = backend.resolve_checkpoint(persistent_run_root=pers_root, selector="latest")
            print(f"Checkpoint íntegro resolvido em: {resolved_dir}")
        return 0

    elif parsed.command == "benchmark":
        if parsed.type == "io":
            src = parsed.source
            dst = parsed.target
            if not src or not dst:
                cfg_p = Path(parsed.config)
                if cfg_p.exists():
                    with open(cfg_p, "r", encoding="utf-8") as f:
                        cfg_data = yaml.safe_load(f) or {}
                    if not src:
                        src = str(Path(cfg_data.get("drive_root", "")) / "releases")
                    if not dst:
                        dst = str(Path(cfg_data.get("local_scratch_root", "/content/llm_legislativo")) / "benchmark")

            if not src or not dst:
                print("Erro: caminhos de origem e destino necessários para benchmark de I/O.", file=sys.stderr)
                return 1

            bench_result = benchmark_io(source_file_or_dir=src, local_target_dir=dst)
            print(json.dumps(bench_result, indent=2))
            if parsed.output:
                out_p = Path(parsed.output)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                with open(out_p, "w", encoding="utf-8") as f:
                    json.dump(bench_result, f, indent=2)
            return 0

        elif parsed.type == "gpu":
            # Encaminha para o módulo de treinamento
            try:
                from legislm.training.cli import main as train_cli_main
                return train_cli_main(["benchmark", "--config", parsed.config])
            except Exception as e:
                print(f"Falha ao executar benchmark de GPU: {e}", file=sys.stderr)
                return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
