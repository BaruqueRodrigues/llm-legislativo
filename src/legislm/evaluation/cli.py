"""
src/legislm/evaluation/cli.py
CLI com subcomandos evaluate e generate para o LLM Legislativo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from legislm.evaluation.evaluator import EvaluationMetrics, StrictEvaluator
from legislm.evaluation.generator import ControlledGenerator, GenerationResult
from legislm.evaluation.metrics import ByteNllResult, compute_byte_nll_v1
from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel
from legislm.tokenization.bpe import LegislativeBpeTokenizer
from legislm.tokenization.reader import CuratedReleaseReader
from legislm.training.checkpoint import load_checkpoint
from legislm.paths import require_data_root, resolve_output_path, resolve_persistent_path, resolve_read_path


def resolve_checkpoint_dir(checkpoint_dir: Optional[str], run_id: Optional[str]) -> Path:
    """Localiza o diretório do checkpoint a partir do caminho direto ou run_id."""
    if checkpoint_dir:
        require_data_root()
        p = resolve_read_path(checkpoint_dir, "runs")
        if p.exists():
            return p
        raise FileNotFoundError(f"Diretório de checkpoint especificado não encontrado: {checkpoint_dir}")

    if not run_id:
        raise ValueError("É necessário informar ao menos --checkpoint-dir ou --run-id")

    data_root = require_data_root()
    candidate_locations: List[Path] = []

    # Busca checkpoints somente na raiz externa de dados.
    for base in [data_root / "runs" / run_id / "checkpoints", data_root / "staging" / "checkpoints" / run_id]:
        if base.exists():
            latest_file = base.parent / "latest.json" if base.name == "checkpoints" else None
            if latest_file is not None and latest_file.exists():
                try:
                    latest = json.loads(latest_file.read_text(encoding="utf-8"))
                    checkpoint_id = str(latest["checkpoint_id"])
                    if latest.get("run_id") == run_id and Path(checkpoint_id).name == checkpoint_id:
                        candidate_locations.append(base / checkpoint_id)
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            steps = sorted(
                (p for p in base.iterdir() if p.is_dir() and (p / "manifest.json").exists()),
                key=lambda x: x.name,
                reverse=True,
            )
            candidate_locations.extend(steps)

    for loc in candidate_locations:
        if loc.exists() and (loc / "manifest.json").exists():
            return loc

    raise FileNotFoundError(
        f"Nenhum checkpoint com manifest.json encontrado para run_id='{run_id}'. "
        f"Locais pesquisados: {[str(c) for c in candidate_locations]}"
    )


def load_model_from_checkpoint(
    checkpoint_dir: Path,
    device: torch.device,
) -> tuple[GPTModel, Dict[str, Any]]:
    """Carrega checkpoint e instancia GPTModel com os pesos restaurados."""
    ckpt_data = load_checkpoint(checkpoint_dir)
    cfg_dict = ckpt_data.get("config_dict", {})
    model_cfg_dict = cfg_dict.get("model", {})

    if not model_cfg_dict:
        raise ValueError(f"Configuração do modelo ('model') ausente no checkpoint em {checkpoint_dir}")

    # Cria configuração GPTConfig e instancia modelo
    gpt_cfg = GPTConfig(
        vocab_size=model_cfg_dict.get("vocab_size", 1080),
        context_length=model_cfg_dict.get("context_length", 512),
        d_model=model_cfg_dict.get("d_model", 128),
        n_layers=model_cfg_dict.get("n_layers", 2),
        n_heads=model_cfg_dict.get("n_heads", 2),
        dropout=0.0,  # Avaliação sempre com dropout desativado
        tie_embeddings=model_cfg_dict.get("tie_embeddings", True),
        layer_norm_eps=model_cfg_dict.get("layer_norm_eps", 1e-5),
    )

    model = GPTModel(gpt_cfg).to(device)
    model.load_state_dict(ckpt_data["model_state"])
    model.eval()

    return model, ckpt_data


def persistent_run_root(checkpoint_dir: Path, ckpt_data: Dict[str, Any], run_id: str) -> Path:
    """Resolve o diretório persistente desta run sem cruzar para outra run."""
    persistence = ckpt_data.get("config_dict", {}).get("persistence", {})
    configured = persistence.get("runs_dir")
    if configured:
        return resolve_persistent_path(configured) / run_id
    # Layout do backend: RUN_ROOT/checkpoints/CHECKPOINT_ID.
    if checkpoint_dir.parent.name == "checkpoints":
        return checkpoint_dir.parent.parent
    return require_data_root() / "runs" / run_id


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_evaluate(args: argparse.Namespace) -> int:
    """Executa o subcomando de avaliação científica nos splits informados."""
    require_data_root()
    device = torch.device(args.device)
    ckpt_dir = resolve_checkpoint_dir(args.checkpoint_dir, args.run_id)
    if not args.release_dir:
        raise ValueError("--release-dir é obrigatório para avaliação reproduzível")
    print(f"[*] Carregando checkpoint de: {ckpt_dir}")

    model, ckpt_data = load_model_from_checkpoint(ckpt_dir, device)
    if args.run_id and ckpt_data.get("run_id") != args.run_id:
        raise ValueError(
            f"Checkpoint pertence à run '{ckpt_data.get('run_id')}', não à run solicitada '{args.run_id}'"
        )
    run_id = ckpt_data.get("run_id", args.run_id or "unknown_run")
    ckpt_id = ckpt_data.get("checkpoint_id", ckpt_dir.name)
    step = ckpt_data.get("global_step", 0)

    # Carrega Tokenizer
    tok_path = resolve_read_path(args.tokenizer_path, "artifacts/tokenizer/tokenizer.json")
    print(f"[*] Carregando tokenizer de: {tok_path}")
    tokenizer = LegislativeBpeTokenizer.load(tok_path)
    if tokenizer.get_vocab_size() != model.config.vocab_size:
        raise ValueError(
            f"Tokenizer vocab_size={tokenizer.get_vocab_size()} incompatível com "
            f"model vocab_size={model.config.vocab_size}"
        )

    # Localiza release curada
    rel_dir = resolve_read_path(args.release_dir, "staging/curation")
    if not rel_dir.exists():
        raise FileNotFoundError(f"Release especificada não encontrada: {rel_dir}")

    print(f"[*] Avaliando split '{args.split}' na release: {rel_dir}")
    evaluator = StrictEvaluator(
        model=model,
        device=device,
        vocab_size=model.config.vocab_size,
    )

    # 1. Avaliação Rigorosa de Perda e Perplexidade
    eval_metrics = evaluator.evaluate_from_release(
        release_dir=rel_dir,
        tokenizer=tokenizer,
        split_name=args.split,
        context_length=model.config.context_length,
        micro_batch_size=args.batch_size,
    )
    if eval_metrics.total_valid_targets == 0 or eval_metrics.total_documents == 0:
        raise ValueError(
            f"Avaliação interrompida: split '{args.split}' não tem documentos/alvos elegíveis "
            f"({eval_metrics.extra_metadata}). Nenhuma métrica científica foi produzida."
        )

    # 2. Avaliação de Métrica Independente byte_nll_v1
    byte_result: Optional[ByteNllResult] = None
    reader = CuratedReleaseReader(rel_dir)
    docs, split_summary = reader.load_documents(split=args.split)
    if not docs:
        raise ValueError(f"byte_nll_v1 não executada: split '{args.split}' vazio")
    print(f"[*] Calculando métrica byte_nll_v1 sobre {len(docs)} documentos...")
    byte_result = compute_byte_nll_v1(
        model=model,
        tokenizer=tokenizer,
        documents=docs,
        k_bytes=args.k_bytes,
        device=device,
    )

    # Relatório Consolidado
    report: Dict[str, Any] = {
        "run_id": run_id,
        "checkpoint_id": ckpt_id,
        "checkpoint_dir": str(ckpt_dir),
        "global_step": step,
        "split": args.split,
        "release_dir": str(rel_dir),
        "tokenizer_vocab_size": tokenizer.get_vocab_size(),
        "tokenizer_file_sha256": hashlib.sha256(tok_path.read_bytes()).hexdigest(),
        "model_context_length": model.config.context_length,
        "split_summary": {
            "total_documents": split_summary.total_documents,
            "total_utf8_bytes": split_summary.total_utf8_bytes,
            "item_ids_sha256": split_summary.item_ids_hash,
            "text_hashes_sha256": split_summary.text_hashes_hash,
            "houses": split_summary.houses,
            "kinds": split_summary.kinds,
            "years": split_summary.years,
        },
        "evaluation_metrics": eval_metrics.to_dict(),
        "byte_nll_v1": byte_result.to_dict() if byte_result else None,
    }

    # Impressão de Resultados
    print("\n" + "=" * 60)
    print("RELATÓRIO CIENTÍFICO DE AVALIAÇÃO DO MODELO LEGISLATIVO")
    print("=" * 60)
    print(f"Run ID:                 {run_id}")
    print(f"Checkpoint ID:          {ckpt_id} (Global Step {step})")
    print(f"Split:                  {args.split}")
    print(f"Documentos Elegíveis:   {eval_metrics.total_documents}")
    print(f"Alvos Válidos:          {eval_metrics.total_valid_targets}")
    print(f"Perda Ponderada (NLL):  {eval_metrics.loss:.4f} nats/token")
    print(f"Perplexidade por Token: {eval_metrics.perplexity:.2f}")
    if eval_metrics.word_perplexity is not None:
        print(f"Perplexidade por Palavra:{eval_metrics.word_perplexity:.2f}")
    if eval_metrics.text_loss is not None:
        print(f"Perda sem EOS (Texto):  {eval_metrics.text_loss:.4f} (PPL: {eval_metrics.text_perplexity:.2f})")
    print(f"Proporção de Padding:   {eval_metrics.padding_ratio * 100:.2f}%")

    if byte_result:
        print("\n--- Métrica Universal byte_nll_v1 ---")
        print(f"K (Bytes por Segmento): {byte_result.k_bytes}")
        print(f"Total Bytes Avaliados:  {byte_result.total_bytes}")
        print(f"Total Tokens Texto:     {byte_result.total_tokens}")
        print(f"Nats por Byte:          {byte_result.nats_per_byte:.4f}")
        print(f"Bits por Byte (BPB):    {byte_result.bits_per_byte:.4f}")
        print(f"Compressão (Bytes/Tok): {byte_result.compression_bytes_per_token:.2f}")

    if eval_metrics.strata_metrics:
        print("\n--- Desempenho por Estrato (Perplexidade por Token) ---")
        for strata_type, items in eval_metrics.strata_metrics.items():
            print(f"[{strata_type.upper()}]:")
            for k, m in items.items():
                print(f"  - {k}: PPL={m['perplexity']:.2f} (alvos={m['valid_targets']}, loss={m['loss']:.4f})")
    print("=" * 60 + "\n")

    run_root = persistent_run_root(ckpt_dir, ckpt_data, run_id)
    out_p = resolve_output_path(
        args.output_json,
        run_root / "evaluation" / f"evaluate_{ckpt_id}_{args.split}.json",
    )
    _write_json(out_p, report)
    print(f"[+] Relatório salvo com sucesso em: {out_p}")

    return 0


def run_generate(args: argparse.Namespace) -> int:
    """Executa o subcomando de geração autorregressiva controlada."""
    require_data_root()
    device = torch.device(args.device)
    ckpt_dir = resolve_checkpoint_dir(args.checkpoint_dir, args.run_id)
    print(f"[*] Carregando checkpoint de: {ckpt_dir}")

    model, ckpt_data = load_model_from_checkpoint(ckpt_dir, device)
    if args.run_id and ckpt_data.get("run_id") != args.run_id:
        raise ValueError(
            f"Checkpoint pertence à run '{ckpt_data.get('run_id')}', não à run solicitada '{args.run_id}'"
        )
    run_id = ckpt_data.get("run_id", args.run_id or "unknown_run")
    ckpt_id = ckpt_data.get("checkpoint_id", ckpt_dir.name)

    tok_path = resolve_read_path(args.tokenizer_path, "artifacts/tokenizer/tokenizer.json")
    print(f"[*] Carregando tokenizer de: {tok_path}")
    tokenizer = LegislativeBpeTokenizer.load(tok_path)
    if tokenizer.get_vocab_size() != model.config.vocab_size:
        raise ValueError(
            f"Tokenizer vocab_size={tokenizer.get_vocab_size()} incompatível com "
            f"model vocab_size={model.config.vocab_size}"
        )

    prompts_file = Path(args.prompts)

    print(f"[*] Lendo prompts oficiais de: {prompts_file}")
    generator = ControlledGenerator(
        model=model,
        tokenizer=tokenizer,
        device=device,
        run_id=run_id,
        checkpoint_id=ckpt_id,
    )

    results = generator.generate_from_prompts_file(
        prompts_path=prompts_file,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_k=args.top_k,
        greedy=args.greedy,
        seed=args.seed,
    )
    generation_config = {
        "max_new_tokens": args.max_new_tokens,
        "temperature": args.temperature,
        "top_k": args.top_k,
        "greedy": args.greedy,
        "seed": args.seed,
    }
    config_hash = hashlib.sha256(
        json.dumps(generation_config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    checkpoint_manifest = ckpt_dir / "manifest.json"
    checkpoint_manifest_sha = (
        hashlib.sha256(checkpoint_manifest.read_bytes()).hexdigest()
        if checkpoint_manifest.exists() else None
    )
    prompts_sha = hashlib.sha256(prompts_file.read_bytes()).hexdigest()
    tokenizer_sha = hashlib.sha256(tok_path.read_bytes()).hexdigest()
    for result in results:
        result.checkpoint_manifest_sha256 = checkpoint_manifest_sha
        result.tokenizer_file_sha256 = tokenizer_sha
        result.prompts_file_sha256 = prompts_sha
        result.generation_config_sha256 = config_hash

    print("\n" + "=" * 60)
    print(f"GERAÇÕES AUTORREGRESSIVAS DO MODELO (Seed {args.seed})")
    print("=" * 60)
    for i, r in enumerate(results, start=1):
        print(f"\n[{i}/{len(results)}] Prompt ID: {r.prompt_id}")
        print(f"Descrição: {r.prompt_description}")
        print("-" * 40)
        print(f"Prompt:\n{r.prompt_text}")
        print("-" * 40)
        print(f"Continuação Gerada:\n{r.generated_text}")
        print("-" * 40)

    run_root = persistent_run_root(ckpt_dir, ckpt_data, run_id)
    out_p = resolve_output_path(
        args.output_file,
        run_root / "evaluation" / f"generate_{ckpt_id}.json",
    )
    if out_p.suffix.lower() == ".md":
        generator.save_results_markdown(results, out_p)
    else:
        generator.save_results_json(results, out_p)
    print(f"\n[+] Resultados exportados para: {out_p}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de linha de comando."""
    parser = argparse.ArgumentParser(
        prog="python -m legislm.evaluation.cli",
        description="CLI de Avaliação e Geração do LLM Legislativo Brasileiro",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando evaluate
    eval_p = subparsers.add_parser("evaluate", help="Avalia modelo nos dados curados e emite métricas")
    eval_p.add_argument("--checkpoint-dir", type=str, default=None, help="Caminho para diretório de checkpoint")
    eval_p.add_argument("--run-id", type=str, default=None, help="Identificador do experimento")
    eval_p.add_argument("--split", type=str, default="validation", help="Split a avaliar (validation, test, train)")
    eval_p.add_argument("--release-dir", type=str, default=None, help="Diretório da release curada (obrigatório)")
    eval_p.add_argument("--tokenizer-path", type=str, default=None, help="Caminho do tokenizer (default: DATA_ROOT/artifacts/tokenizer/tokenizer.json)")
    eval_p.add_argument("--k-bytes", type=int, default=None, help="K congelado para byte_nll_v1; padrão min(512, L-1)")
    eval_p.add_argument("--batch-size", type=int, default=4, help="Micro-batch size")
    eval_p.add_argument("--device", type=str, default="cpu", help="Dispositivo (cpu, cuda, mps)")
    eval_p.add_argument("--output-json", type=str, default=None, help="Caminho de saída para JSON de métricas")

    # Subcomando generate
    gen_p = subparsers.add_parser("generate", help="Gera continuações a partir de prompts oficiais")
    gen_p.add_argument("--checkpoint-dir", type=str, default=None, help="Caminho para diretório de checkpoint")
    gen_p.add_argument("--run-id", type=str, default=None, help="Identificador do experimento")
    gen_p.add_argument("--prompts", type=str, default="configs/evaluation/prompts.json", help="Arquivo JSON de prompts")
    gen_p.add_argument("--tokenizer-path", type=str, default=None, help="Caminho do tokenizer (default: DATA_ROOT/artifacts/tokenizer/tokenizer.json)")
    gen_p.add_argument("--max-new-tokens", type=int, default=64, help="Tokens máximos a gerar")
    gen_p.add_argument("--temperature", type=float, default=0.7, help="Temperatura de amostragem")
    gen_p.add_argument("--top-k", type=int, default=40, help="Filtro Top-K")
    gen_p.add_argument("--greedy", action="store_true", help="Amostragem gulosa determinística")
    gen_p.add_argument("--seed", type=int, default=42, help="Semente pseudoaleatória")
    gen_p.add_argument("--device", type=str, default="cpu", help="Dispositivo (cpu, cuda, mps)")
    gen_p.add_argument("--output-file", type=str, default=None, help="Arquivo de saída (.json ou .md)")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "evaluate":
        return run_evaluate(args)
    elif args.command == "generate":
        return run_generate(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
