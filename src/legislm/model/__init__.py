"""
src/legislm/model/__init__.py
Módulo do Transformer Decoder educacional explícito do LLM legislativo.
"""

from legislm.model.attention import CausalMultiHeadAttention
from legislm.model.block import TransformerBlock
from legislm.model.config import GPTConfig
from legislm.model.generation import generate
from legislm.model.gpt import GPTModel
from legislm.model.mlp import FeedForward
from legislm.model.params import ParameterReport, count_parameters

__all__ = [
    "GPTConfig",
    "GPTModel",
    "CausalMultiHeadAttention",
    "FeedForward",
    "TransformerBlock",
    "generate",
    "count_parameters",
    "ParameterReport",
]
