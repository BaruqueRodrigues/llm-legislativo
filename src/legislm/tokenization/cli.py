"""
src/legislm/tokenization/cli.py
Interface de linha de comando para treinamento do BPE e geração de shards do LLM legislativo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional

from legislm.tokenization.bpe import (
    LegislativeBpeTokenizer,
    save_tokenizer_bundle,
    train_bpe_tokenizer,
)
from legislm.tokenization.config import TokenizerConfig
from legislm.tokenization.dataset import build_token_dataset
from legislm.tokenization.reader import CuratedReleaseReader
from legislm.paths import require_data_root, resolve_output_path


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m legislm.tokenization.cli",
        description="CLI do Tokenizer BPE e Dataset de Tokens do LLM Legislativo",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando train
    train_parser = subparsers.add_parser("train", help="Treina o BPE Byte-Level exclusivamente em train")
    train_parser.add_argument(
        "--config",
        type=str,
        default="configs/tokenizer/pilot.yaml",
        help="Caminho para o arquivo YAML de configuração do tokenizer (default: configs/tokenizer/pilot.yaml)",
    )
    train_parser.add_argument(
        "--release-dir",
        type=str,
        default=None,
        help="Diretório da release curada (obrigatório; fixtures devem ser passadas explicitamente)",
    )
    train_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Diretório de destino (default: DATA_ROOT/artifacts/tokenizer)",
    )
    train_parser.add_argument(
        "--vocab-size",
        type=int,
        default=None,
        help="Sobrescreve o tamanho do vocabulário alvo",
    )
    train_parser.add_argument(
        "--min-frequency",
        type=int,
        default=None,
        help="Sobrescreve a frequência mínima de subpalavras",
    )
    train_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Semente determinística de ordenação (default: 42)",
    )

    # Subcomando build
    build_parser = subparsers.add_parser("build", help="Gera shards .npy, índice Parquet e janelas de contexto")
    build_parser.add_argument(
        "--config",
        type=str,
        default="configs/tokenizer/pilot.yaml",
        help="Caminho para o arquivo YAML de configuração (default: configs/tokenizer/pilot.yaml)",
    )
    build_parser.add_argument(
        "--tokenizer-dir",
        type=str,
        default=None,
        help="Diretório do tokenizer (default: DATA_ROOT/artifacts/tokenizer)",
    )
    build_parser.add_argument(
        "--release-dir",
        type=str,
        default=None,
        help="Diretório da release curada (obrigatório; fixtures devem ser passadas explicitamente)",
    )
    build_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Diretório de destino (default: DATA_ROOT/artifacts/tokens)",
    )
    build_parser.add_argument(
        "--context-length",
        type=int,
        default=None,
        help="Sobrescreve o comprimento de contexto para derivação de janelas",
    )
    build_parser.add_argument(
        "--splits",
        type=str,
        default="train,validation,test",
        help="Partições separadas por vírgula para processar (default: train,validation,test)",
    )

    # Subcomando inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspeciona tokenizer e valida round-trip")
    inspect_parser.add_argument(
        "--tokenizer-dir",
        type=str,
        default=None,
        help="Diretório do tokenizer (default: DATA_ROOT/artifacts/tokenizer)",
    )
    inspect_parser.add_argument(
        "--text",
        type=str,
        default=None,
        help="Texto para teste de codificação e round-trip",
    )

    return parser.parse_args(args)


def run_train(args: argparse.Namespace) -> int:
    require_data_root()
    if not args.release_dir:
        raise ValueError("--release-dir é obrigatório; passe fixtures explicitamente para um piloto")
    args.output_dir = resolve_output_path(args.output_dir, "artifacts/tokenizer")
    config = TokenizerConfig.from_yaml(args.config)
    if args.vocab_size is not None:
        config.model.vocab_size = args.vocab_size
    if args.min_frequency is not None:
        config.model.min_frequency = args.min_frequency

    print(f"=== Treinamento BPE Byte-Level: {config.tokenizer_id} ===")
    print(f"Release dir: {args.release_dir}")
    print(f"Config hash: {config.compute_config_hash()[:16]}...")
    print(f"Vocabulário alvo: {config.model.vocab_size} (min_freq: {config.model.min_frequency})")

    reader = CuratedReleaseReader(args.release_dir)
    reader.validate_release_integrity()
    ids_hash = hashlib.sha256()
    texts_hash = hashlib.sha256()
    train_docs = 0
    train_bytes = 0
    for doc in reader.iter_documents(split="train", validate_integrity=False):
        ids_hash.update(doc.corpus_item_id.encode("utf-8") + b"\n")
        texts_hash.update(doc.text_sha256.encode("utf-8"))
        train_docs += 1
        train_bytes += doc.utf8_bytes
    if not train_docs:
        print("Erro: Nenhum documento de treino elegível encontrado!", file=sys.stderr)
        return 1
    item_ids_hash = ids_hash.hexdigest()
    text_hashes_hash = texts_hash.hexdigest()
    print(f"Documentos train elegíveis percorridos: {train_docs} ({train_bytes} bytes UTF-8)")
    print(f"Hash dos IDs de train: {item_ids_hash}")
    print(f"Hash dos textos de train: {text_hashes_hash}")

    tokenizer, metrics = train_bpe_tokenizer(
        texts=lambda: (
            doc.text for doc in reader.iter_documents(split="train", validate_integrity=False)
        ),
        config=config,
        show_progress=True,
    )

    print("\n--- Métricas de Treinamento e Compressão ---")
    print(f"Vocabulário efetivo: {metrics.vocab_size_effective} / {metrics.vocab_size_target}")
    print(f"Total de tokens gerados em treino: {metrics.total_training_tokens}")
    print(f"Taxa de compressão: {metrics.compression_bytes_per_token:.4f} bytes/token")
    print(f"Tokens por caractere: {metrics.tokens_per_character:.4f}")
    print(f"Distribuição de tokens/doc: min={metrics.min_doc_tokens}, p50={metrics.p50_doc_tokens}, p95={metrics.p95_doc_tokens}, max={metrics.max_doc_tokens}")

    tok_f, man_f, comp_f = save_tokenizer_bundle(
        tokenizer=tokenizer,
        metrics=metrics,
        config=config,
        output_dir=args.output_dir,
        training_item_ids_hash=item_ids_hash,
        training_text_hashes_hash=text_hashes_hash,
        training_bytes=train_bytes,
        seed=args.seed,
    )

    print("\n--- Artefatos Publicados ---")
    print(f"Tokenizer:  {tok_f}")
    print(f"Manifesto:  {man_f}")
    print(f"Marcador:   {comp_f}")
    return 0


def run_build(args: argparse.Namespace) -> int:
    require_data_root()
    if not args.release_dir:
        raise ValueError("--release-dir é obrigatório")
    args.tokenizer_dir = resolve_output_path(args.tokenizer_dir, "artifacts/tokenizer")
    args.output_dir = resolve_output_path(args.output_dir, "artifacts/tokens")
    config = TokenizerConfig.from_yaml(args.config)
    if args.context_length is not None:
        config.dataset.context_length = args.context_length

    tok_dir = Path(args.tokenizer_dir)
    tok_file = tok_dir / "tokenizer.json"
    tok_manifest_file = tok_dir / "tokenizer_manifest.json"

    if not tok_file.exists():
        print(f"Erro: Arquivo do tokenizer não encontrado em {tok_file}", file=sys.stderr)
        return 1
    if not tok_manifest_file.exists():
        print(f"Erro: Manifesto do tokenizer não encontrado em {tok_manifest_file}", file=sys.stderr)
        return 1

    tokenizer = LegislativeBpeTokenizer.load(tok_file)
    with open(tok_manifest_file, "r", encoding="utf-8") as f:
        tok_manifest = json.load(f)
    tok_sha256 = tok_manifest.get("tokenizer_file_sha256", "")

    print(f"=== Construção do Token Dataset: {config.token_dataset_id} ===")
    print(f"Tokenizer carregado de: {tok_dir} (Vocab: {tokenizer.get_vocab_size()})")
    print(f"Context length: {config.dataset.context_length}")

    reader = CuratedReleaseReader(args.release_dir)
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]

    reader.validate_release_integrity()
    docs_by_split = {s: reader.iter_documents(split=s, validate_integrity=False) for s in splits}

    idx_f, man_f, comp_f = build_token_dataset(
        docs_by_split=docs_by_split,
        tokenizer=tokenizer,
        config=config,
        output_dir=args.output_dir,
        tokenizer_file_sha256=tok_sha256,
    )

    print("\n--- Dataset de Tokens Publicado ---")
    print(f"Índice:     {idx_f}")
    print(f"Manifesto:  {man_f}")
    print(f"Marcador:   {comp_f}")
    return 0


def run_inspect(args: argparse.Namespace) -> int:
    args.tokenizer_dir = resolve_output_path(args.tokenizer_dir, "artifacts/tokenizer")
    tok_dir = Path(args.tokenizer_dir)
    tok_file = tok_dir / "tokenizer.json"
    if not tok_file.exists():
        print(f"Tokenizer não encontrado em {tok_file}", file=sys.stderr)
        return 1

    tokenizer = LegislativeBpeTokenizer.load(tok_file)
    print(f"Vocabulário efetivo: {tokenizer.get_vocab_size()}")
    print(f"PAD: {tokenizer.token_to_id('<pad>')}")
    print(f"BOS: {tokenizer.token_to_id('<bos>')}")
    print(f"EOS: {tokenizer.token_to_id('<eos>')}")

    sample_text = args.text or "PROJETO DE LEI Nº 1.234/2024\nArt. 1º Fica instituído o regime especial."
    ids = tokenizer.encode(sample_text)
    decoded = tokenizer.decode(ids)
    print("\n--- Teste de Codificação ---")
    print(f"Texto original: {sample_text}")
    print(f"IDs ({len(ids)} tokens): {ids[:20]}...")
    print(f"Decodificado:   {decoded}")
    print(f"Round-trip exato: {sample_text == decoded}")
    return 0


def main(args: Optional[List[str]] = None) -> int:
    parsed = parse_args(args)
    if parsed.command == "train":
        return run_train(parsed)
    elif parsed.command == "build":
        return run_build(parsed)
    elif parsed.command == "inspect":
        return run_inspect(parsed)
    else:
        print(f"Comando desconhecido: {parsed.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
