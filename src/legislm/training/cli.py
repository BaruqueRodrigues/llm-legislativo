"""
src/legislm/training/cli.py
Interface de linha de comando para treinamento e benchmark do LLM legislativo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from legislm.training.benchmark import run_benchmark
from legislm.training.config import TrainingConfig
from legislm.training.data import create_synthetic_dataset
from legislm.tokenization.dataset import TokenDataset as ShardedTokenDataset
from legislm.training.engine import Trainer
from legislm.paths import require_data_root, resolve_output_path, resolve_persistent_path


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m legislm.training.cli",
        description="CLI do Pipeline de Treinamento e Benchmark do LLM Legislativo",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando train
    train_parser = subparsers.add_parser("train", help="Executa o treinamento do modelo")
    train_parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Caminho para o arquivo YAML de configuração de treino",
    )
    dataset_source = train_parser.add_mutually_exclusive_group(required=True)
    dataset_source.add_argument(
        "--token-dataset-dir",
        type=str,
        help="Diretório do dataset tokenizado (train/validation), dentro de DATA_ROOT",
    )
    dataset_source.add_argument(
        "--synthetic-smoke",
        action="store_true",
        help="Usa dados sintéticos apenas para smoke de engenharia, nunca como treino do corpus",
    )
    train_parser.add_argument(
        "--resume",
        type=str,
        default=None,
        help="ID do checkpoint ou 'latest' para retomar execução",
    )
    train_parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Sobrescreve o número máximo de passos de atualização",
    )
    train_parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Sobrescreve o dispositivo de hardware ('cpu', 'cuda', 'mps')",
    )

    # Subcomando benchmark
    bench_parser = subparsers.add_parser("benchmark", help="Executa o benchmark de treinamento")
    bench_parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Caminho para o arquivo YAML de configuração",
    )
    bench_parser.add_argument(
        "--warmup-steps",
        type=int,
        default=5,
        help="Quantidade de passos de aquecimento (default: 5)",
    )
    bench_parser.add_argument(
        "--timed-steps",
        type=int,
        default=20,
        help="Quantidade de passos cronometrados (default: 20)",
    )
    bench_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Caminho para salvar o relatório de benchmark em JSON",
    )

    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    parsed = parse_args(args)

    if parsed.command == "benchmark":
        require_data_root()
        config = TrainingConfig.from_yaml(parsed.config)
        config.persistence.runs_dir = str(resolve_persistent_path(config.persistence.runs_dir))
        print(f"Iniciando benchmark para run '{config.run_id}' no dispositivo '{config.device}'...")
        report = run_benchmark(
            config=config,
            warmup_updates=parsed.warmup_steps,
            timed_updates=parsed.timed_steps,
        )
        print(json.dumps(report, indent=2))
        if parsed.output:
            out_p = resolve_output_path(parsed.output, "reports/benchmark.json")
            out_p.parent.mkdir(parents=True, exist_ok=True)
            with open(out_p, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            print(f"Relatório de benchmark salvo em: {parsed.output}")
        return 0

    elif parsed.command == "train":
        require_data_root()
        config = TrainingConfig.from_yaml(parsed.config)
        config.persistence.runs_dir = str(resolve_persistent_path(config.persistence.runs_dir))
        if parsed.device is not None:
            config.device = parsed.device

        if parsed.synthetic_smoke:
            train_dataset = create_synthetic_dataset(
                num_docs=50,
                vocab_size=config.model.vocab_size,
                context_length=config.model.context_length,
                seed=config.training.seed,
            )
            eval_dataset = None
            print(f"Iniciando smoke sintético para run '{config.run_id}'...")
        else:
            data_root = require_data_root()
            dataset_dir = Path(parsed.token_dataset_dir).expanduser()
            if not dataset_dir.is_absolute():
                dataset_dir = data_root / dataset_dir
            dataset_dir = dataset_dir.resolve()
            if dataset_dir == data_root or not dataset_dir.is_relative_to(data_root):
                raise ValueError(f"--token-dataset-dir deve ficar dentro de DATA_ROOT: {dataset_dir}")
            if not (dataset_dir / "token_dataset_manifest.json").is_file():
                raise FileNotFoundError(
                    f"Manifesto do dataset tokenizado não encontrado: {dataset_dir / 'token_dataset_manifest.json'}"
                )
            train_dataset = ShardedTokenDataset.from_dataset_dir(dataset_dir, split="train")
            eval_dataset = ShardedTokenDataset.from_dataset_dir(dataset_dir, split="validation")
            if len(train_dataset) == 0:
                raise ValueError(f"O split train do dataset está vazio: {dataset_dir}")
            if len(eval_dataset) == 0:
                raise ValueError(f"O split validation do dataset está vazio: {dataset_dir}")
            expected_context = config.model.context_length
            if train_dataset.context_length != expected_context or eval_dataset.context_length != expected_context:
                raise ValueError(
                    "Contexto incompatível: config.model.context_length="
                    f"{expected_context}, train={train_dataset.context_length}, "
                    f"validation={eval_dataset.context_length}"
                )
            print(
                f"Iniciando treinamento para run '{config.run_id}' com dataset "
                f"'{dataset_dir}' (train={len(train_dataset)}, validation={len(eval_dataset)} janelas)..."
            )

        trainer = Trainer(
            config=config,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            session_max_steps=parsed.max_steps,
        )

        if parsed.resume:
            print(f"Retomando a partir do checkpoint '{parsed.resume}'...")
            trainer.resume_from_checkpoint(selector=parsed.resume)

        summary = trainer.run()
        print("Treinamento finalizado com sucesso:")
        print(json.dumps(summary, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
