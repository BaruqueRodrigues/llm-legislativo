from pathlib import Path

import pytest

from legislm.model.config import GPTConfig


@pytest.mark.parametrize("yaml_text", ["", "null", "[]", "value"])
def test_from_yaml_rejects_non_mapping_root(tmp_path: Path, yaml_text: str) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ValueError, match="mapeamento YAML"):
        GPTConfig.from_yaml(config_path)


@pytest.mark.parametrize("model_value", ["null", "[]", "value"])
def test_from_yaml_rejects_non_mapping_model_section(tmp_path: Path, model_value: str) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"model: {model_value}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="seção 'model'"):
        GPTConfig.from_yaml(config_path)


def test_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="mapeamento YAML"):
        GPTConfig.from_dict([])  # type: ignore[arg-type]
