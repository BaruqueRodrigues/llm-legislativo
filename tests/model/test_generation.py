"""
tests/model/test_generation.py
Testes do utilitário de geração autorregressiva:
- Amostragem gulosa (greedy) determinística.
- Amostragem com temperatura e semente reproduzível.
- Filtragem Top-K.
- Parada antecipada em token EOS.
- Truncamento de contexto longo (context cropping).
"""

import pytest
import torch

from legislm.model.config import GPTConfig
from legislm.model.generation import generate
from legislm.model.gpt import GPTModel


def test_greedy_generation_is_deterministic():
    """Geração com greedy=True deve ser estritamente determinística a cada execução."""
    cfg = GPTConfig(vocab_size=30, context_length=16, d_model=32, n_layers=2, n_heads=2)
    model = GPTModel(cfg)

    prompt = [1, 5, 10]
    out1 = generate(model, prompt, max_new_tokens=6, greedy=True)
    out2 = generate(model, prompt, max_new_tokens=6, greedy=True)

    assert torch.equal(out1, out2)
    assert out1.shape == (1, 9)
    # Prefixo original preservado
    assert out1[0, :3].tolist() == prompt


def test_generation_seed_reproducibility():
    """Amostragem com temperatura deve produzir sequências idênticas para a mesma semente."""
    cfg = GPTConfig(vocab_size=30, context_length=16, d_model=32, n_layers=2, n_heads=2)
    model = GPTModel(cfg)

    prompt = [1, 2, 3]
    out1 = generate(model, prompt, max_new_tokens=5, temperature=0.8, seed=42)
    out2 = generate(model, prompt, max_new_tokens=5, temperature=0.8, seed=42)
    out_diff = generate(model, prompt, max_new_tokens=5, temperature=0.8, seed=999)

    assert torch.equal(out1, out2), "Mesma semente gerou saídas diferentes!"
    # Sementes diferentes devem com alta probabilidade gerar saídas diferentes
    assert not torch.equal(out1, out_diff), "Sementes distintas geraram exatamente os mesmos tokens"


def test_top_k_1_equals_greedy():
    """Top-K com k=1 deve ser matematicamente equivalente à amostragem gulosa (greedy)."""
    cfg = GPTConfig(vocab_size=40, context_length=16, d_model=32, n_layers=2, n_heads=2)
    model = GPTModel(cfg)

    prompt = [1, 4, 7]
    out_top1 = generate(model, prompt, max_new_tokens=5, top_k=1, temperature=1.0, seed=123)
    out_greedy = generate(model, prompt, max_new_tokens=5, greedy=True)

    assert torch.equal(out_top1, out_greedy), "top_k=1 divergiu de greedy=True!"


def test_early_stopping_on_eos():
    """Geração deve parar imediatamente quando o token EOS for gerado."""
    cfg = GPTConfig(vocab_size=20, context_length=16, d_model=16, n_layers=1, n_heads=2, eos_token_id=2)
    model = GPTModel(cfg)

    # Forçamos o modelo a prever sempre EOS (id 2) na saída
    with torch.no_grad():
        model.lm_head.weight.zero_()
        # Faz a linha 2 ter logit altíssimo
        model.lm_head.weight[2, :] = 100.0

    prompt = [1, 5]
    # Pedimos 10 tokens novos, mas como o primeiro gerado será 2 (EOS), deve parar com comprimento 3
    out = generate(model, prompt, max_new_tokens=10, eos_token_id=2, greedy=True)

    assert out.shape == (1, 3), f"Deveria ter parado no EOS! Shape obtido: {out.shape}"
    assert out[0, 2].item() == 2, "Último token deveria ser EOS (2)"


def test_context_cropping_on_long_prompt():
    """Se o prompt for mais longo que context_length, o modelo trunca o início sem erro."""
    context_length = 8
    cfg = GPTConfig(vocab_size=20, context_length=context_length, d_model=16, n_layers=1, n_heads=2)
    model = GPTModel(cfg)

    # Prompt com 12 tokens (maior que context_length=8)
    long_prompt = list(range(12))
    out = generate(model, long_prompt, max_new_tokens=3, greedy=True)

    # O tensor resultante deve ter 12 + 3 = 15 tokens
    assert out.shape == (1, 15)
