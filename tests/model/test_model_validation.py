"""
tests/model/test_model_validation.py
Testes de validação de entradas, dimensões e máscaras no GPTModel.
"""

import pytest
import torch

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel


def test_sequence_length_exceeding_context_length_raises():
    """Valida que sequência maior que context_length levanta ValueError explícito."""
    cfg = GPTConfig(vocab_size=100, context_length=16, d_model=32, n_layers=1, n_heads=2)
    model = GPTModel(cfg)

    too_long = torch.randint(0, 100, (1, 17))
    with pytest.raises(ValueError, match="excede o context_length"):
        model(too_long)


def test_token_ids_out_of_vocab_raises():
    """Valida que IDs fora do vocabulário [0, vocab_size - 1] levantam ValueError."""
    cfg = GPTConfig(vocab_size=100, context_length=16, d_model=32, n_layers=1, n_heads=2)
    model = GPTModel(cfg)

    # Token ID negativo
    neg_id = torch.tensor([[10, -1, 50]])
    with pytest.raises(ValueError, match="fora do vocabulário"):
        model(neg_id)

    # Token ID maior ou igual ao vocab_size
    large_id = torch.tensor([[10, 100, 50]])
    with pytest.raises(ValueError, match="fora do vocabulário"):
        model(large_id)


def test_mismatched_target_and_mask_shapes_raise():
    """Valida que formatos incompatíveis de attention_mask, targets ou loss_mask levantam ValueError."""
    cfg = GPTConfig(vocab_size=100, context_length=16, d_model=32, n_layers=1, n_heads=2)
    model = GPTModel(cfg)

    inputs = torch.randint(0, 100, (2, 8))

    # Target com shape incorreto
    bad_targets = torch.randint(0, 100, (2, 7))
    with pytest.raises(ValueError, match="targets deve ter formato"):
        model(inputs, targets=bad_targets)

    # Attention mask com shape incorreto
    bad_mask = torch.ones((2, 9), dtype=torch.bool)
    with pytest.raises(ValueError, match="attention_mask deve ter formato"):
        model(inputs, attention_mask=bad_mask)

    # Loss mask com shape incorreto
    bad_loss_mask = torch.ones((2, 9), dtype=torch.bool)
    with pytest.raises(ValueError, match="loss_mask deve ter formato"):
        model(inputs, targets=inputs, loss_mask=bad_loss_mask)


def test_loss_mask_ignores_masked_positions():
    """Verifica que loss_mask converte posições mascaradas para ignoradas (-100)."""
    cfg = GPTConfig(vocab_size=20, context_length=8, d_model=16, n_layers=1, n_heads=2, dropout=0.0)
    model = GPTModel(cfg)
    model.eval()

    inputs = torch.randint(0, 20, (1, 4))
    targets = torch.tensor([[5, 10, 15, 18]])
    # Apenas posições 0 e 1 são válidas para perda
    loss_mask = torch.tensor([[True, True, False, False]])

    _, loss_with_mask = model(inputs, targets=targets, loss_mask=loss_mask)

    # Deve calcular a perda apenas sobre as duas primeiras posições
    targets_manual = torch.tensor([[5, 10, -100, -100]])
    _, loss_manual = model(inputs, targets=targets_manual)

    assert torch.allclose(loss_with_mask, loss_manual, atol=1e-6)


def test_all_ignored_targets_yields_zero_loss():
    """Se todos os alvos forem -100, a perda deve retornar tensor(0.0) finito sem erro."""
    cfg = GPTConfig(vocab_size=20, context_length=8, d_model=16, n_layers=1, n_heads=2)
    model = GPTModel(cfg)

    inputs = torch.randint(0, 20, (1, 4))
    targets = torch.full((1, 4), -100, dtype=torch.long)

    logits, loss = model(inputs, targets=targets)
    assert loss.item() == 0.0
    assert not torch.isnan(loss)
