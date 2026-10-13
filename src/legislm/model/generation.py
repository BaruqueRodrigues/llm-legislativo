"""
src/legislm/model/generation.py
Utilitário de geração autorregressiva com suporte a amostragem gulosa (greedy), temperatura, top-k, parada em EOS e semente determinística.
"""

from __future__ import annotations

from typing import List, Optional, Union

import torch
import torch.nn.functional as F


def generate(
    model: torch.nn.Module,
    prompt_tokens: Union[torch.Tensor, List[int]],
    max_new_tokens: int,
    temperature: float = 1.0,
    top_k: Optional[int] = None,
    eos_token_id: Optional[int] = None,
    greedy: bool = False,
    seed: Optional[int] = None,
) -> torch.Tensor:
    """Gera tokens autorregressivamente a partir de um prompt inicial.

    Args:
        model: Modelo GPT instanciado (deve ter atributo config com context_length).
        prompt_tokens: Tensor 2D [batch_size, seq_len] ou 1D [seq_len], ou lista de inteiros.
        max_new_tokens: Quantidade máxima de novos tokens a gerar.
        temperature: Temperatura para escalonar logits antes do softmax (padrão 1.0).
        top_k: Se fornecido, filtra a amostragem apenas entre os k tokens mais prováveis.
        eos_token_id: ID do token de término para encerramento antecipado.
        greedy: Se True, seleciona deterministicamente o token com maior logit (argmax).
        seed: Semente aleatória opcional para reprodutibilidade estrita.

    Returns:
        Tensor de tokens [batch_size, seq_len + tokens_gerados].
    """
    if seed is not None:
        torch.manual_seed(seed)

    # Conversão de formato de entrada para Tensor 2D [B, L]
    if isinstance(prompt_tokens, list):
        idx = torch.tensor([prompt_tokens], dtype=torch.long)
    elif isinstance(prompt_tokens, torch.Tensor):
        if prompt_tokens.dim() == 1:
            idx = prompt_tokens.unsqueeze(0)
        else:
            idx = prompt_tokens.clone()
    else:
        raise TypeError(f"prompt_tokens deve ser Tensor ou List[int], recebido: {type(prompt_tokens)}")

    device = next(model.parameters()).device
    idx = idx.to(device)

    context_length = getattr(model.config, "context_length", idx.size(1))

    model_was_training = model.training
    model.eval()

    finished = torch.zeros(idx.size(0), dtype=torch.bool, device=device)

    with torch.no_grad():
        for _ in range(max_new_tokens):
            # Se o contexto acumulado exceder context_length, trunca mantendo os últimos tokens
            idx_cond = idx if idx.size(1) <= context_length else idx[:, -context_length:]

            # Passagem para frente
            logits = model(idx_cond)
            # Logits correspondentes ao último passo temporal [B, vocab_size]
            next_token_logits = logits[:, -1, :]

            # Decisão: Amostragem gulosa (greedy) ou estocástica
            if greedy or temperature <= 0.0:
                next_token = torch.argmax(next_token_logits, dim=-1, keepdim=True)
            else:
                # Aplicação de temperatura
                scaled_logits = next_token_logits / temperature

                # Filtragem Top-K
                if top_k is not None and top_k > 0:
                    k = min(top_k, scaled_logits.size(-1))
                    val, _ = torch.topk(scaled_logits, k)
                    # Limiar é o menor valor entre os top k
                    cutoff = val[:, [-1]]
                    scaled_logits = scaled_logits.masked_fill(scaled_logits < cutoff, float("-inf"))

                probs = F.softmax(scaled_logits, dim=-1)
                next_token = torch.multinomial(probs, num_samples=1)

            # Concatena o próximo token gerado
            idx = torch.cat((idx, next_token), dim=1)

            # Verificação de token EOS para parada antecipada
            if eos_token_id is not None:
                is_eos = (next_token.squeeze(-1) == eos_token_id)
                finished = finished | is_eos
                if finished.all():
                    break

    if model_was_training:
        model.train()

    return idx
