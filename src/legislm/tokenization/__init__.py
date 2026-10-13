"""
src/legislm/tokenization/__init__.py
Pacote de Tokenização BPE Byte-Level e Datasets de Tokens do LLM Legislativo.
"""

from legislm.tokenization.bpe import (
    LegislativeBpeTokenizer,
    TokenizerMetrics,
    save_tokenizer_bundle,
    train_bpe_tokenizer,
)
from legislm.tokenization.config import (
    BPEModelConfig,
    DatasetConfig,
    SpecialTokensConfig,
    TokenizationParamsConfig,
    TokenizerConfig,
)
from legislm.tokenization.dataset import (
    TokenBatch,
    TokenDataset,
    WindowInfo,
    build_token_dataset,
    make_batch,
)
from legislm.tokenization.reader import (
    CorpusSplitSummary,
    CuratedDocument,
    CuratedReleaseReader,
)

__all__ = [
    "TokenizerConfig",
    "BPEModelConfig",
    "SpecialTokensConfig",
    "TokenizationParamsConfig",
    "DatasetConfig",
    "CuratedDocument",
    "CorpusSplitSummary",
    "CuratedReleaseReader",
    "LegislativeBpeTokenizer",
    "TokenizerMetrics",
    "train_bpe_tokenizer",
    "save_tokenizer_bundle",
    "WindowInfo",
    "TokenBatch",
    "TokenDataset",
    "make_batch",
    "build_token_dataset",
]
