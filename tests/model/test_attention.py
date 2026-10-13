"""
tests/model/test_attention.py
Testes do mecanismo de CausalMultiHeadAttention:
- Exemplo calculável passo a passo com pesos conhecidos.
- Prova de causalidade (pesos estritamente zero para tokens futuros).
- Mascaramento de chaves PAD.
- Ausência de NaN em queries PAD descartadas (frente e gradientes).
- Demonstração de que EOS sozinho não impede atenção cruzada sem máscara explícita.
"""

import math
import pytest
import torch
import torch.nn.functional as F

from legislm.model.attention import CausalMultiHeadAttention
from legislm.model.config import GPTConfig


def test_attention_calculable_example():
    """Teste com pesos fixos e cálculo analítico manual comparado ao forward."""
    # Configuração determinística: d_model=4, n_heads=1, context_length=3, dropout=0
    cfg = GPTConfig(
        vocab_size=10,
        context_length=3,
        d_model=4,
        n_layers=1,
        n_heads=1,
        dropout=0.0,
        bias=False,
    )
    attn = CausalMultiHeadAttention(cfg)
    attn.eval()

    # Forçamos pesos identidade para q, k, v, out
    with torch.no_grad():
        attn.q_proj.weight.copy_(torch.eye(4))
        attn.k_proj.weight.copy_(torch.eye(4))
        attn.v_proj.weight.copy_(torch.eye(4))
        attn.out_proj.weight.copy_(torch.eye(4))

    # Entrada conhecida [1, 3, 4]
    x = torch.tensor([
        [
            [1.0, 0.0, 0.0, 0.0],  # pos 0
            [0.0, 2.0, 0.0, 0.0],  # pos 1
            [1.0, 1.0, 0.0, 0.0],  # pos 2
        ]
    ])

    out, weights = attn(x, return_attn_weights=True)

    # Cálculo manual:
    # d_head = 4, scale = 1 / sqrt(4) = 0.5
    # q0 = [1, 0, 0, 0], k0 = [1, 0, 0, 0] -> dot(q0, k0) = 1.0 -> score = 0.5
    # Causal pos 0: só atende pos 0 -> softmax([0.5]) = [1.0, 0.0, 0.0]
    assert torch.allclose(weights[0, 0, 0], torch.tensor([1.0, 0.0, 0.0]), atol=1e-5)
    assert torch.allclose(out[0, 0], x[0, 0], atol=1e-5)

    # Para pos 1:
    # q1 = [0, 2, 0, 0]
    # k0 = [1, 0, 0, 0] -> dot = 0 -> score0 = 0.0
    # k1 = [0, 2, 0, 0] -> dot = 4 -> score1 = 4 * 0.5 = 2.0
    # k2 mascarado (-inf)
    # softmax([0.0, 2.0]) = [exp(0)/(exp(0)+exp(2)), exp(2)/(exp(0)+exp(2))]
    p0 = math.exp(0.0) / (math.exp(0.0) + math.exp(2.0))
    p1 = math.exp(2.0) / (math.exp(0.0) + math.exp(2.0))
    expected_pos1 = torch.tensor([p0, p1, 0.0])
    assert torch.allclose(weights[0, 0, 1], expected_pos1, atol=1e-5)

    expected_out_pos1 = p0 * x[0, 0] + p1 * x[0, 1]
    assert torch.allclose(out[0, 1], expected_out_pos1, atol=1e-5)


def test_causal_mask_enforcement():
    """Verifica que posições futuras recebem peso de atenção estritamente 0.0."""
    cfg = GPTConfig(vocab_size=10, context_length=8, d_model=16, n_heads=2, dropout=0.0)
    attn = CausalMultiHeadAttention(cfg)
    attn.eval()

    x = torch.randn(2, 6, 16)
    _, weights = attn(x, return_attn_weights=True)
    # weights: [B, n_heads, L, L]
    B, heads, L, _ = weights.shape

    for i in range(L):
        for j in range(i + 1, L):
            # Para todo j > i, peso deve ser estritamente zero
            future_weights = weights[:, :, i, j]
            assert torch.all(future_weights == 0.0), f"Vazamento causal detectado em query={i}, key={j}"


def test_pad_keys_and_discarded_pad_queries_no_nan():
    """Testa que chaves PAD não são atendidas e que queries PAD descartadas não geram NaN."""
    cfg = GPTConfig(vocab_size=10, context_length=8, d_model=16, n_heads=2, dropout=0.0)
    attn = CausalMultiHeadAttention(cfg)
    attn.eval()

    # Lote com 2 sequências:
    # seq 0: comprimento 3 válido, posições 3, 4, 5 são PAD
    # seq 1: comprimento 5 válido, posição 5 é PAD
    x = torch.randn(2, 6, 16, requires_grad=True)
    mask = torch.tensor([
        [True, True, True, False, False, False],
        [True, True, True, True, True, False],
    ])

    out, weights = attn(x, attention_mask=mask, return_attn_weights=True)

    # 1. Sem NaN na saída
    assert not torch.isnan(out).any(), "Saída do attention contém NaN!"
    assert not torch.isnan(weights).any(), "Pesos de atenção contêm NaN!"

    # 2. Chaves PAD devem ter peso 0.0 para todas as queries
    # Para seq 0, chaves 3, 4, 5 são PAD
    assert torch.all(weights[0, :, :, 3:] == 0.0), "Chave PAD recebeu peso diferente de zero!"
    # Para seq 1, chave 5 é PAD
    assert torch.all(weights[1, :, :, 5] == 0.0), "Chave PAD recebeu peso diferente de zero!"

    # 3. Queries PAD descartadas (posições 3, 4, 5 da seq 0):
    # Devem ter pesos 0.0 e saída de atenção 0.0
    assert torch.all(weights[0, :, 3:, :] == 0.0), "Query PAD descartada não tem pesos zerados!"
    assert torch.all(out[0, 3:, :] == 0.0), "Saída de query PAD descartada não é zero!"

    # 4. Verificação de gradientes sem NaN
    loss = out.sum()
    loss.backward()
    assert x.grad is not None
    assert not torch.isnan(x.grad).any(), "Gradiente de entrada contém NaN após backward com PAD!"


def test_eos_alone_does_not_prevent_cross_attention():
    """Demonstra que EOS como token simples não impede atenção entre documentos sem máscara."""
    cfg = GPTConfig(vocab_size=10, context_length=8, d_model=16, n_heads=2, dropout=0.0)
    attn = CausalMultiHeadAttention(cfg)
    attn.eval()

    # Suponha tokens [t0, t1, EOS, t3, t4]
    # Sem attention_mask dividindo segmentos, t3 DEVE atender a t0, t1 e EOS
    x = torch.randn(1, 5, 16)
    _, weights = attn(x, attention_mask=None, return_attn_weights=True)

    # Query na posição 3 (após EOS) atende posições 0, 1 (antes de EOS)?
    weights_before_eos = weights[0, :, 3, :2]
    # Em atenção causal padrão, esses pesos são não-nulos!
    assert (weights_before_eos > 0.0).any(), (
        "Demonstração: atenção causal padrão atende tokens antes de EOS. "
        "Isso comprova a premissa de que EOS sozinho não isola documentos sem política de máscara/janela."
    )
