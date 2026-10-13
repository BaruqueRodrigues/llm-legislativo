"""
src/legislm/training/__init__.py
Módulo de treinamento, benchmark, otimização e checkpoints do LLM legislativo.
"""

from legislm.training.benchmark import run_benchmark
from legislm.training.checkpoint import (
    load_checkpoint,
    restore_training_state,
    save_checkpoint,
    validate_checkpoint_manifest,
)
from legislm.training.config import (
    ModelArchitectureConfig,
    PersistenceConfig,
    TrainingConfig,
    TrainingHyperparameters,
)
from legislm.training.data import (
    Batch,
    DeterministicSampler,
    DocumentItem,
    StratifiedTracker,
    TokenDataset,
    create_synthetic_dataset,
)
from legislm.training.engine import Trainer
from legislm.training.optimizer import CosineAnnealingWarmupScheduler, configure_optimizer
from legislm.training.persistence import (
    LocalPersistenceBackend,
    PersistenceBackend,
    get_persistence_backend,
)
from legislm.training.precision import PrecisionManager, StepExecutionTracker

__all__ = [
    "TrainingConfig",
    "TrainingHyperparameters",
    "ModelArchitectureConfig",
    "PersistenceConfig",
    "configure_optimizer",
    "CosineAnnealingWarmupScheduler",
    "Batch",
    "DocumentItem",
    "DeterministicSampler",
    "StratifiedTracker",
    "TokenDataset",
    "create_synthetic_dataset",
    "PrecisionManager",
    "StepExecutionTracker",
    "save_checkpoint",
    "load_checkpoint",
    "restore_training_state",
    "validate_checkpoint_manifest",
    "PersistenceBackend",
    "LocalPersistenceBackend",
    "get_persistence_backend",
    "Trainer",
    "run_benchmark",
]
