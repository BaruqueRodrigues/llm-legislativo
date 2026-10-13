"""
tests/model/test_config.py
Testes unitários para validação de configurações arquiteturais do modelo.
"""

from pathlib import Path
import pytest

from legislm.model.config import GPTConfig

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_default_config_valid():
    """Valida que a configuração padrão é válida."""
    cfg = GPTConfig()
    assert cfg.vocab_size == 8192
    assert cfg.context_length == 512
    assert cfg.d_model == 384
    assert cfg.n_layers == 6
    assert cfg.n_heads == 6
    assert cfg.head_dim == 64
    assert cfg.tie_embeddings is True


def test_d_model_divisible_by_heads_validation():
    """Verifica que d_model % n_heads != 0 levanta ValueError explicativo."""
    with pytest.raises(ValueError, match="estritamente divisível"):
        GPTConfig(d_model=385, n_heads=6)

    with pytest.raises(ValueError, match="estritamente divisível"):
        GPTConfig(d_model=100, n_heads=3)


def test_invalid_parameters_raise_value_errors():
    """Verifica que parâmetros fora de limites levantam ValueError."""
    with pytest.raises(ValueError, match="vocab_size"):
        GPTConfig(vocab_size=0)

    with pytest.raises(ValueError, match="context_length"):
        GPTConfig(context_length=-1)

    with pytest.raises(ValueError, match="d_model"):
        GPTConfig(d_model=0)

    with pytest.raises(ValueError, match="n_layers"):
        GPTConfig(n_layers=0)

    with pytest.raises(ValueError, match="n_heads"):
        GPTConfig(n_heads=0)

    with pytest.raises(ValueError, match="dropout"):
        GPTConfig(dropout=1.0)

    with pytest.raises(ValueError, match="dropout"):
        GPTConfig(dropout=-0.1)

    with pytest.raises(ValueError, match="layer_norm_eps"):
        GPTConfig(layer_norm_eps=0.0)

    with pytest.raises(ValueError, match="pad_token_id"):
        GPTConfig(vocab_size=10, pad_token_id=10)

    with pytest.raises(ValueError, match="bos_token_id"):
        GPTConfig(vocab_size=10, bos_token_id=-1)

    with pytest.raises(ValueError, match="eos_token_id"):
        GPTConfig(vocab_size=10, eos_token_id=15)


def test_load_pilot_yaml():
    """Valida carregamento direto de configs/training/pilot.yaml."""
    pilot_path = REPO_ROOT / "configs" / "training" / "pilot.yaml"
    assert pilot_path.exists(), f"Arquivo {pilot_path} não encontrado"

    cfg = GPTConfig.from_yaml(pilot_path)
    assert cfg.vocab_size == 8192
    assert cfg.context_length == 512
    assert cfg.d_model == 384
    assert cfg.n_layers == 6
    assert cfg.n_heads == 6
    assert cfg.dropout == 0.1
    assert cfg.tie_embeddings is True
    assert cfg.head_dim == 64


def test_to_dict_and_from_dict_roundtrip():
    """Valida round-trip de conversão para/de dicionário."""
    cfg = GPTConfig(vocab_size=1000, context_length=128, d_model=128, n_heads=4, n_layers=2)
    d = cfg.to_dict()
    assert isinstance(d, dict)
    reloaded = GPTConfig.from_dict(d)
    assert cfg == reloaded
