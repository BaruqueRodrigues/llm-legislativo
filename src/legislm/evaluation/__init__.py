"""
src/legislm/evaluation/__init__.py
Módulo de avaliação rigorosa, métricas comparáveis (byte_nll_v1) e geração controlada do LLM Legislativo.
"""

from legislm.evaluation.evaluator import EvaluationMetrics, StrictEvaluator
from legislm.evaluation.generator import ControlledGenerator, GenerationResult
from legislm.evaluation.metrics import (
    ByteNllResult,
    compute_byte_nll_v1,
    count_words,
    split_text_into_utf8_segments,
)

__all__ = [
    "ByteNllResult",
    "ControlledGenerator",
    "EvaluationMetrics",
    "GenerationResult",
    "StrictEvaluator",
    "compute_byte_nll_v1",
    "count_words",
    "split_text_into_utf8_segments",
]
