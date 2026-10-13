"""
src/legislm/training/config.py
Configuração de treinamento do LLM legislativo, com validação e hashes imutáveis.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import yaml

from legislm.model.config import GPTConfig


def canonical_json_hash(obj: Any) -> str:
    """Calcula hash SHA-256 determinístico via serialização JSON canônica (chaves ordenadas)."""
    canonical_str = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


@dataclass
class ModelArchitectureConfig:
    vocab_size: int = 8192
    context_length: int = 512
    d_model: int = 384
    n_layers: int = 6
    n_heads: int = 6
    dropout: float = 0.1
    tie_embeddings: bool = True
    layer_norm_eps: float = 1e-5

    def to_gpt_config(self) -> GPTConfig:
        return GPTConfig(
            vocab_size=self.vocab_size,
            context_length=self.context_length,
            d_model=self.d_model,
            n_layers=self.n_layers,
            n_heads=self.n_heads,
            dropout=self.dropout,
            tie_embeddings=self.tie_embeddings,
            layer_norm_eps=self.layer_norm_eps,
        )


@dataclass
class TrainingHyperparameters:
    seed: int = 42
    precision: str = "fp32"  # "fp32", "bf16", "fp16"
    micro_batch_size: int = 2
    grad_accum_steps: int = 4
    max_steps: int = 200
    max_tokens: Optional[int] = None
    max_seconds: Optional[float] = None
    budget_counter: str = "successful_update_tokens"  # "successful_update_tokens" ou "consumed_tokens"
    learning_rate: float = 0.0005
    min_learning_rate: float = 0.00005
    warmup_steps: int = 20
    weight_decay: float = 0.01
    grad_clip_norm: float = 1.0
    evaluation_interval: int = 25
    checkpoint_interval_steps: int = 50
    checkpoint_interval_seconds: float = 300.0


@dataclass
class PersistenceConfig:
    backend: str = "local"  # "local", "drive", etc.
    runs_dir: str = "runs"
    checkpoints_to_keep: int = 2
    drive_root: Optional[str] = None


@dataclass
class TrainingConfig:
    run_id: str
    corpus_version: str
    split_version: str
    tokenizer_id: str
    token_dataset_id: str
    sequence_policy_version: str
    model: ModelArchitectureConfig = field(default_factory=ModelArchitectureConfig)
    training: TrainingHyperparameters = field(default_factory=TrainingHyperparameters)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    device: str = "cpu"
    raw_config_sha256: Optional[str] = None

    def validate(self) -> None:
        """Validações estritas de contratos normativos e integridade numérica."""
        if not self.run_id or not isinstance(self.run_id, str):
            raise ValueError("run_id deve ser uma string não vazia")
        if not self.corpus_version or not isinstance(self.corpus_version, str):
            raise ValueError("corpus_version deve ser uma string não vazia")
        if not self.split_version or not isinstance(self.split_version, str):
            raise ValueError("split_version deve ser uma string não vazia")
        if not self.tokenizer_id or not isinstance(self.tokenizer_id, str):
            raise ValueError("tokenizer_id deve ser uma string não vazia")
        if not self.token_dataset_id or not isinstance(self.token_dataset_id, str):
            raise ValueError("token_dataset_id deve ser uma string não vazia")

        # Modelo
        self.model.to_gpt_config()  # Executa validações de GPTConfig

        # Hiperparâmetros
        if self.training.precision not in ("fp32", "bf16", "fp16"):
            raise ValueError(f"precision inválida: {self.training.precision}. Opções: 'fp32', 'bf16', 'fp16'")
        if self.training.budget_counter not in ("successful_update_tokens", "consumed_tokens"):
            raise ValueError(
                f"budget_counter inválido: {self.training.budget_counter}. "
                "Opções: 'successful_update_tokens', 'consumed_tokens'"
            )
        if self.training.micro_batch_size <= 0:
            raise ValueError("micro_batch_size deve ser positivo")
        if self.training.grad_accum_steps <= 0:
            raise ValueError("grad_accum_steps deve ser positivo")
        if self.training.max_steps <= 0:
            raise ValueError("max_steps deve ser positivo")
        if self.training.learning_rate <= 0:
            raise ValueError("learning_rate deve ser positivo")
        if self.training.min_learning_rate < 0:
            raise ValueError("min_learning_rate não pode ser negativo")
        if self.training.min_learning_rate > self.training.learning_rate:
            raise ValueError("min_learning_rate não pode ser maior que learning_rate")
        if self.training.warmup_steps < 0:
            raise ValueError("warmup_steps não pode ser negativo")
        if self.training.weight_decay < 0:
            raise ValueError("weight_decay não pode ser negativo")
        if self.training.grad_clip_norm <= 0:
            raise ValueError("grad_clip_norm deve ser positivo")
        if self.persistence.checkpoints_to_keep < 2:
            raise ValueError("checkpoints_to_keep deve ser >= 2 para garantir recuperação segura")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "corpus_version": self.corpus_version,
            "split_version": self.split_version,
            "tokenizer_id": self.tokenizer_id,
            "token_dataset_id": self.token_dataset_id,
            "sequence_policy_version": self.sequence_policy_version,
            "model": asdict(self.model),
            "training": asdict(self.training),
            "persistence": asdict(self.persistence),
            "device": self.device,
        }

    def compute_hashes(self) -> Tuple[str, str, str]:
        """Calcula a tríade de hashes imutáveis:
        1. config_file_sha256 (do arquivo ou representação canônica completa)
        2. scientific_config_hash (parâmetros de corpus, arquitetura, plano de treino/orçamento)
        3. execution_config_hash (ambiente, microbatch/acumulação, precisão, paths de persistência)
        """
        # 1. config_file_sha256
        if self.raw_config_sha256:
            cfg_sha256 = self.raw_config_sha256
        else:
            cfg_sha256 = canonical_json_hash(self.to_dict())

        # 2. scientific_config
        scientific_dict = {
            "corpus_version": self.corpus_version,
            "split_version": self.split_version,
            "tokenizer_id": self.tokenizer_id,
            "token_dataset_id": self.token_dataset_id,
            "sequence_policy_version": self.sequence_policy_version,
            "model": asdict(self.model),
            "seed": self.training.seed,
            "learning_rate": self.training.learning_rate,
            "min_learning_rate": self.training.min_learning_rate,
            "warmup_steps": self.training.warmup_steps,
            "weight_decay": self.training.weight_decay,
            "grad_clip_norm": self.training.grad_clip_norm,
            "budget_counter": self.training.budget_counter,
            "max_steps": self.training.max_steps,
            "max_tokens": self.training.max_tokens,
        }
        scientific_hash = canonical_json_hash(scientific_dict)

        # 3. execution_config
        execution_dict = {
            "run_id": self.run_id,
            "device": self.device,
            "precision": self.training.precision,
            "micro_batch_size": self.training.micro_batch_size,
            "grad_accum_steps": self.training.grad_accum_steps,
            "evaluation_interval": self.training.evaluation_interval,
            "checkpoint_interval_steps": self.training.checkpoint_interval_steps,
            "checkpoint_interval_seconds": self.training.checkpoint_interval_seconds,
            "persistence": asdict(self.persistence),
        }
        execution_hash = canonical_json_hash(execution_dict)

        return cfg_sha256, scientific_hash, execution_hash

    @classmethod
    def from_dict(cls, data: Dict[str, Any], raw_sha256: Optional[str] = None) -> TrainingConfig:
        d = copy.deepcopy(data)
        model_data = d.get("model", {})
        training_data = d.get("training", {})
        persistence_data = d.get("persistence", {})

        model_cfg = ModelArchitectureConfig(**model_data)
        training_cfg = TrainingHyperparameters(**training_data)
        persistence_cfg = PersistenceConfig(**persistence_data)

        cfg = cls(
            run_id=d.get("run_id", "pilot_run"),
            corpus_version=d.get("corpus_version", "corpus_v1"),
            split_version=d.get("split_version", "split_v1"),
            tokenizer_id=d.get("tokenizer_id", "bpe_byte_v1_8k"),
            token_dataset_id=d.get("token_dataset_id", "tok_dataset_v1"),
            sequence_policy_version=d.get("sequence_policy_version", "doc_window_v1"),
            model=model_cfg,
            training=training_cfg,
            persistence=persistence_cfg,
            device=d.get("device", "cpu"),
            raw_config_sha256=raw_sha256,
        )
        cfg.validate()
        return cfg

    @classmethod
    def from_yaml(cls, path_or_yaml: Union[str, Path]) -> TrainingConfig:
        p = Path(path_or_yaml)
        if p.exists() and p.is_file():
            raw_bytes = p.read_bytes()
            raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            content = raw_bytes.decode("utf-8")
        else:
            raw_sha256 = hashlib.sha256(str(path_or_yaml).encode("utf-8")).hexdigest()
            content = str(path_or_yaml)

        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            raise ValueError(f"Conteúdo de configuração inválido (esperado dict, obtido {type(data)})")

        return cls.from_dict(data, raw_sha256=raw_sha256)
