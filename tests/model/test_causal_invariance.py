"""
tests/model/test_causal_invariance.py
Provas matemáticas e numéricas de invariância causal e invariância a PAD à direita.
"""

import pytest
import torch

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel


def test_causal_invariance_future_tokens():
    """Prova que alterar tokens futuros NÃO altera logits de posições passadas ou presentes."""
    torch.manual_seed(42)
    cfg = GPTConfig(
        vocab_size=100,
        context_length=32,
        d_model=64,
        n_layers=3,
        n_heads=4,
        dropout=0.0,
    )
    model = GPTModel(cfg)
    model.eval()

    seq_len = 16
    cutoff = 7  # prefixo de 0 a 7 (comprimento 8)

    # Sequência original
    seq1 = torch.randint(3, 100, (2, seq_len))

    # Sequência modificada: prefixo [0..cutoff] idêntico, mas futuro totalmente alterado
    seq2 = seq1.clone()
    seq2[:, cutoff + 1 :] = torch.randint(3, 100, (2, seq_len - cutoff - 1))

    # Certifica que o futuro realmente difere
    assert not torch.equal(seq1[:, cutoff + 1 :], seq2[:, cutoff + 1 :])

    with torch.no_grad():
        logits1 = model(seq1)
        logits2 = model(seq2)

    # Logits no prefixo até cutoff DEVEM ser exatamente iguais
    prefix_logits1 = logits1[:, : cutoff + 1, :]
    prefix_logits2 = logits2[:, : cutoff + 1, :]

    diff = (prefix_logits1 - prefix_logits2).abs().max().item()
    assert torch.allclose(prefix_logits1, prefix_logits2, atol=1e-5), (
        f"Violação de causalidade! Logits do prefixo diferem por {diff}"
    )

    # Logits após cutoff DEVEM diferir (já que os tokens futuros mudaram)
    future_diff = (logits1[:, cutoff + 1 :, :] - logits2[:, cutoff + 1 :, :]).abs().max().item()
    assert future_diff > 1e-3, "Logits futuros deveriam ser diferentes"


def test_right_pad_invariance():
    """Prova que adicionar tokens PAD à direita com máscara NÃO altera os logits dos tokens válidos."""
    torch.manual_seed(42)
    cfg = GPTConfig(
        vocab_size=100,
        context_length=32,
        d_model=64,
        n_layers=3,
        n_heads=4,
        dropout=0.0,
        pad_token_id=0,
    )
    model = GPTModel(cfg)
    model.eval()

    valid_len = 8
    pad_len = 6
    total_len = valid_len + pad_len

    # Sequência não-acolchoada [1, valid_len]
    seq_unpadded = torch.randint(3, 100, (1, valid_len))

    # Sequência com acolchoamento à direita [1, total_len]
    pad_tokens = torch.full((1, pad_len), cfg.pad_token_id, dtype=torch.long)
    seq_padded = torch.cat([seq_unpadded, pad_tokens], dim=1)

    # Máscara de atenção: True para válidos, False para PAD
    mask_padded = torch.cat([
        torch.ones((1, valid_len), dtype=torch.bool),
        torch.zeros((1, pad_len), dtype=torch.bool),
    ], dim=1)

    with torch.no_grad():
        logits_unpadded = model(seq_unpadded)
        logits_padded = model(seq_padded, attention_mask=mask_padded)

    # Logits dos tokens válidos na versão com PAD à direita devem ser iguais aos da versão sem PAD
    valid_logits_from_padded = logits_padded[:, :valid_len, :]

    diff = (logits_unpadded - valid_logits_from_padded).abs().max().item()
    assert torch.allclose(logits_unpadded, valid_logits_from_padded, atol=1e-5), (
        f"Invariância a PAD à direita violada! Diferença máxima: {diff}"
    )


def test_pad_invariance_in_batched_setting():
    """Prova que sequências de comprimentos diferentes em um mesmo lote não contaminam os logits das sequências mais curtas."""
    torch.manual_seed(123)
    cfg = GPTConfig(
        vocab_size=100,
        context_length=16,
        d_model=32,
        n_layers=2,
        n_heads=2,
        dropout=0.0,
        pad_token_id=0,
    )
    model = GPTModel(cfg)
    model.eval()

    # Seq A tem comprimento 4, Seq B tem comprimento 8
    seq_a_clean = torch.tensor([[10, 20, 30, 40]])
    seq_b_clean = torch.tensor([[50, 60, 70, 80, 90, 15, 25, 35]])

    # Lote unificado de comprimento 8
    pad_a = torch.zeros((1, 4), dtype=torch.long)
    seq_a_padded = torch.cat([seq_a_clean, pad_a], dim=1)

    batch_inputs = torch.cat([seq_a_padded, seq_b_clean], dim=0)
    batch_mask = torch.tensor([
        [True, True, True, True, False, False, False, False],
        [True, True, True, True, True, True, True, True],
    ])

    with torch.no_grad():
        # Execução individual limpa
        logits_a_clean = model(seq_a_clean)
        logits_b_clean = model(seq_b_clean)

        # Execução em lote com máscara de padding
        batch_logits = model(batch_inputs, attention_mask=batch_mask)

    # Compara Seq A no lote com Seq A limpa
    assert torch.allclose(batch_logits[0, :4, :], logits_a_clean[0], atol=1e-5), (
        "Seq A no lote sofreu interferência do acolchoamento ou de outra amostra!"
    )

    # Compara Seq B no lote com Seq B limpa
    assert torch.allclose(batch_logits[1], logits_b_clean[0], atol=1e-5), (
        "Seq B no lote sofreu interferência!"
    )
