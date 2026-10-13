"""
src/legislm/evaluation/generator.py
Geração autorregressiva controlada, reprodutível e registrada do LLM Legislativo.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from legislm.tokenization.bpe import LegislativeBpeTokenizer


@dataclass
class GenerationResult:
    """Registro estruturado e reprodutível de uma geração autorregressiva."""

    prompt_id: str
    prompt_description: str
    prompt_text: str
    prompt_tokens: List[int]
    prompt_token_count: int
    generated_tokens: List[int]
    generated_token_count: int
    generated_text: str
    full_text: str
    stopped_on_eos: bool
    temperature: float
    top_k: Optional[int]
    greedy: bool
    seed: Optional[int]
    run_id: Optional[str] = None
    checkpoint_id: Optional[str] = None
    checkpoint_manifest_sha256: Optional[str] = None
    tokenizer_file_sha256: Optional[str] = None
    prompts_file_sha256: Optional[str] = None
    generation_config_sha256: Optional[str] = None
    timestamp_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "prompt_description": self.prompt_description,
            "prompt_text": self.prompt_text,
            "prompt_tokens": self.prompt_tokens,
            "prompt_token_count": self.prompt_token_count,
            "generated_tokens": self.generated_tokens,
            "generated_token_count": self.generated_token_count,
            "generated_text": self.generated_text,
            "full_text": self.full_text,
            "stopped_on_eos": self.stopped_on_eos,
            "temperature": self.temperature,
            "top_k": self.top_k,
            "greedy": self.greedy,
            "seed": self.seed,
            "run_id": self.run_id,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_manifest_sha256": self.checkpoint_manifest_sha256,
            "tokenizer_file_sha256": self.tokenizer_file_sha256,
            "prompts_file_sha256": self.prompts_file_sha256,
            "generation_config_sha256": self.generation_config_sha256,
            "timestamp_utc": self.timestamp_utc,
        }


class ControlledGenerator:
    """Gerador autorregressivo determinístico com registro integral de procedência."""

    def __init__(
        self,
        model: nn.Module,
        tokenizer: LegislativeBpeTokenizer,
        device: Optional[Union[torch.device, str]] = None,
        run_id: Optional[str] = None,
        checkpoint_id: Optional[str] = None,
        eos_token_id: int = 2,
    ) -> None:
        self.model = model
        self.tokenizer = tokenizer
        if device is not None:
            self.device = torch.device(device)
        else:
            try:
                self.device = next(model.parameters()).device
            except StopIteration:
                self.device = torch.device("cpu")
        self.run_id = run_id
        self.checkpoint_id = checkpoint_id
        self.eos_token_id = eos_token_id
        self.context_length = getattr(model.config, "context_length", 512)

    def generate_single(
        self,
        prompt_text: str,
        prompt_id: str = "custom",
        prompt_description: str = "",
        max_new_tokens: int = 64,
        temperature: float = 0.7,
        top_k: Optional[int] = 40,
        greedy: bool = False,
        seed: Optional[int] = None,
    ) -> GenerationResult:
        """Gera continuação para um prompt individual com rastreabilidade total."""
        if seed is not None:
            torch.manual_seed(seed)

        # 1. Codificação dos tokens do prompt
        prompt_tokens = self.tokenizer.encode(prompt_text)
        if not prompt_tokens:
            prompt_tokens = [1]  # Fallback para BOS se prompt for vazio

        idx = torch.tensor([prompt_tokens], dtype=torch.long, device=self.device)

        model_was_training = self.model.training
        self.model.eval()

        generated_token_ids: List[int] = []
        stopped_on_eos = False

        with torch.no_grad():
            for _ in range(max_new_tokens):
                # Truncamento de contexto se exceder context_length (mantendo janela mais recente)
                idx_cond = idx if idx.size(1) <= self.context_length else idx[:, -self.context_length:]

                logits = self.model(idx_cond)
                next_token_logits = logits[:, -1, :]  # [1, vocab_size]

                if greedy or temperature <= 0.0:
                    next_token = torch.argmax(next_token_logits, dim=-1, keepdim=True)
                else:
                    scaled_logits = next_token_logits / max(temperature, 1e-5)
                    if top_k is not None and top_k > 0:
                        k = min(top_k, scaled_logits.size(-1))
                        val, _ = torch.topk(scaled_logits, k)
                        cutoff = val[:, [-1]]
                        scaled_logits = scaled_logits.masked_fill(scaled_logits < cutoff, float("-inf"))

                    probs = F.softmax(scaled_logits, dim=-1)
                    next_token = torch.multinomial(probs, num_samples=1)

                token_val = int(next_token.item())

                if token_val == self.eos_token_id:
                    stopped_on_eos = True
                    break

                generated_token_ids.append(token_val)
                idx = torch.cat((idx, next_token), dim=1)

        if model_was_training:
            self.model.train()

        generated_text = self.tokenizer.decode(generated_token_ids, skip_special_tokens=True)
        full_text = prompt_text + generated_text

        return GenerationResult(
            prompt_id=prompt_id,
            prompt_description=prompt_description,
            prompt_text=prompt_text,
            prompt_tokens=prompt_tokens,
            prompt_token_count=len(prompt_tokens),
            generated_tokens=generated_token_ids,
            generated_token_count=len(generated_token_ids),
            generated_text=generated_text,
            full_text=full_text,
            stopped_on_eos=stopped_on_eos,
            temperature=temperature,
            top_k=top_k,
            greedy=greedy,
            seed=seed,
            run_id=self.run_id,
            checkpoint_id=self.checkpoint_id,
        )

    def generate_from_prompts_file(
        self,
        prompts_path: Union[str, Path],
        max_new_tokens: int = 64,
        temperature: float = 0.7,
        top_k: Optional[int] = 40,
        greedy: bool = False,
        seed: Optional[int] = 42,
    ) -> List[GenerationResult]:
        """Carrega lista de prompts oficiais em JSON e gera continuações para cada um."""
        p_path = Path(prompts_path)
        if not p_path.exists():
            raise FileNotFoundError(f"Arquivo de prompts não encontrado: {p_path}")

        with open(p_path, "r", encoding="utf-8") as f:
            prompts_data = json.load(f)

        if not isinstance(prompts_data, list):
            raise ValueError(f"Formato inválido de prompts. Esperada lista de objetos, obtido: {type(prompts_data)}")

        results: List[GenerationResult] = []
        for p_item in prompts_data:
            p_id = p_item.get("id", "prompt_unknown")
            p_text = p_item.get("prompt", "")
            p_desc = p_item.get("description", "")

            # Se seed for fixo, podemos usar o mesmo seed ou variar deterministicamente por índice
            res = self.generate_single(
                prompt_text=p_text,
                prompt_id=p_id,
                prompt_description=p_desc,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_k=top_k,
                greedy=greedy,
                seed=seed,
            )
            results.append(res)

        return results

    @staticmethod
    def save_results_json(
        results: Sequence[GenerationResult],
        output_path: Union[str, Path],
    ) -> Path:
        """Salva as gerações registradas em formato JSON padronizado."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = [r.to_dict() for r in results]
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return out

    @staticmethod
    def save_results_markdown(
        results: Sequence[GenerationResult],
        output_path: Union[str, Path],
        title: str = "Registro Oficial de Gerações do LLM Legislativo",
    ) -> Path:
        """Exporta relatório legível das gerações em formato Markdown."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        lines: List[str] = [
            f"# {title}",
            "",
            f"**Data de Geração:** {datetime.datetime.now(datetime.timezone.utc).isoformat()}  ",
            f"**Total de Prompts:** {len(results)}  ",
            "",
            "---",
            "",
        ]

        for i, r in enumerate(results, start=1):
            lines.extend([
                f"## {i}. Prompt: `{r.prompt_id}`",
                "",
                f"- **Descrição:** {r.prompt_description}",
                f"- **Configuração:** greedy={r.greedy}, temp={r.temperature}, top_k={r.top_k}, seed={r.seed}",
                f"- **Tokens gerados:** {r.generated_token_count} (EOS: {r.stopped_on_eos})",
                f"- **Origem:** Run `{r.run_id or 'n/a'}` | Checkpoint `{r.checkpoint_id or 'n/a'}`",
                "",
                "### Prompt Original:",
                "```text",
                r.prompt_text,
                "```",
                "",
                "### Continuação Gerada:",
                "```text",
                r.generated_text if r.generated_text else "[vazio / EOS imediato]",
                "```",
                "",
                "### Texto Consolidado:",
                "```text",
                r.full_text,
                "```",
                "",
                "---",
                "",
            ])

        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return out
