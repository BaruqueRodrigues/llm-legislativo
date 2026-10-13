"""
tests/model/test_gradients_and_tying.py
Testes de tying de embeddings, contagem exata de parâmetros únicos, fluxo de gradientes e passo de otimizador.
"""

import pytest
import torch
import torch.optim as optim

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel
from legislm.model.params import count_parameters


def test_weight_tying_identity_and_untied_mode():
    """Verifica que tie_embeddings=True compartilha exatamente o mesmo tensor e tie_embeddings=False aloca pesos separados."""
    cfg_tied = GPTConfig(vocab_size=200, context_length=16, d_model=32, n_layers=2, n_heads=2, tie_embeddings=True)
    model_tied = GPTModel(cfg_tied)
    # Mesma identidade de objeto em memória
    assert model_tied.lm_head.weight is model_tied.tok_emb.weight

    cfg_untied = GPTConfig(vocab_size=200, context_length=16, d_model=32, n_layers=2, n_heads=2, tie_embeddings=False)
    model_untied = GPTModel(cfg_untied)
    assert model_untied.lm_head.weight is not model_untied.tok_emb.weight

    # Diferença exata na contagem de parâmetros únicos = vocab_size * d_model
    report_tied = count_parameters(model_tied)
    report_untied = count_parameters(model_untied)
    diff = report_untied.total_unique_params - report_tied.total_unique_params
    assert diff == cfg_tied.vocab_size * cfg_tied.d_model


def test_exact_parameter_count_formula():
    """Valida a fórmula teórica exata de contagem de parâmetros únicos contra o modelo."""
    V = 500
    L = 64
    d = 64
    n_layers = 3
    n_heads = 4

    cfg = GPTConfig(
        vocab_size=V,
        context_length=L,
        d_model=d,
        n_layers=n_layers,
        n_heads=n_heads,
        dropout=0.1,
        tie_embeddings=True,
        bias=True,
    )
    model = GPTModel(cfg)
    report = count_parameters(model)

    # Cálculo teórico manual:
    # 1. tok_emb: V * d
    tok_emb_params = V * d
    # 2. pos_emb: L * d
    pos_emb_params = L * d
    # 3. Bloco por camada:
    #    - ln_1: 2 * d (peso e bias)
    #    - q_proj, k_proj, v_proj, out_proj: 4 * (d*d + d)
    #    - ln_2: 2 * d (peso e bias)
    #    - fc1: (d * 4d) + 4d
    #    - fc2: (4d * d) + d
    per_block = (2 * d) + (4 * (d * d + d)) + (2 * d) + (4 * d * d + 4 * d) + (4 * d * d + d)
    all_blocks = n_layers * per_block
    # 4. ln_f: 2 * d
    ln_f_params = 2 * d
    # 5. lm_head: 0 (tied com tok_emb)
    lm_head_params = 0

    expected_total = tok_emb_params + pos_emb_params + all_blocks + ln_f_params + lm_head_params

    assert report.total_unique_params == expected_total, (
        f"Contagem diverge! Esperado {expected_total}, obtido {report.total_unique_params}"
    )
    assert report.trainable_unique_params == expected_total
    assert report.tie_embeddings_active is True
    assert report.tied_params_count == V * d


def test_gradients_flow_and_optimizer_step():
    """Testa que gradientes fluem por todos os parâmetros treináveis e que o otimizador atualiza os pesos."""
    torch.manual_seed(42)
    cfg = GPTConfig(
        vocab_size=50,
        context_length=16,
        d_model=32,
        n_layers=2,
        n_heads=2,
        dropout=0.0,
        tie_embeddings=True,
    )
    model = GPTModel(cfg)
    model.train()

    optimizer = optim.AdamW(model.parameters(), lr=1e-3)

    # Entradas e alvos sintéticos
    inputs = torch.randint(0, 50, (2, 8))
    targets = torch.randint(0, 50, (2, 8))

    # Cópia dos parâmetros iniciais
    initial_params = {name: p.clone().detach() for name, p in model.named_parameters()}

    optimizer.zero_grad()
    logits, loss = model(inputs, targets=targets)
    assert not torch.isnan(loss), "Perda é NaN!"
    assert loss.item() > 0.0

    loss.backward()

    # 1. Verifica que todo parâmetro treinável recebeu gradiente finito e não-nulo
    for name, p in model.named_parameters():
        assert p.grad is not None, f"Parâmetro {name} não recebeu gradiente!"
        assert not torch.isnan(p.grad).any(), f"Gradiente de {name} contém NaN!"
        assert not torch.isinf(p.grad).any(), f"Gradiente de {name} contém Inf!"

    # 2. Executa passo de otimizador
    optimizer.step()

    # 3. Verifica que os pesos realmente foram atualizados
    updated_count = 0
    for name, p in model.named_parameters():
        diff = (p - initial_params[name]).abs().max().item()
        if diff > 0.0:
            updated_count += 1

    assert updated_count == len(initial_params), "Nem todos os parâmetros foram atualizados no step!"
