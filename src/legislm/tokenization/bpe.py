"""
src/legislm/tokenization/bpe.py
Implementação e treinamento do Byte-Level BPE Tokenizer educacional para o LLM Legislativo.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import tokenizers
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers

from legislm.tokenization.config import TokenizerConfig


@dataclass
class TokenizerMetrics:
    """Métricas de treinamento, vocabulário e compressão."""

    vocab_size_effective: int
    vocab_size_target: int
    total_training_docs: int
    total_training_bytes: int
    total_training_tokens: int
    compression_bytes_per_token: float
    tokens_per_character: float
    min_doc_tokens: int
    max_doc_tokens: int
    mean_doc_tokens: float
    p50_doc_tokens: float
    p95_doc_tokens: float


class LegislativeBpeTokenizer:
    """Tokenizer BPE Byte-Level do LLM Legislativo.

    Propriedades fundamentais:
    - Alfabeto byte completo de 256 bytes (cobertura total sem caractere desconhecido).
    - Sem normalização destrutiva (mantém caixa alta/baixa, acentuação e quebras de linha).
    - Tokens especiais reservados estritamente: PAD=0, BOS=1, EOS=2.
    - Strings literais de controle no texto (ex: '<pad>', '<bos>') são tokenizadas
      como texto comum e NUNCA produzem os IDs de controle 0, 1 ou 2.
    - Decodificação com round-trip exato garantido.
    """

    SPECIAL_PAD = "<pad>"
    SPECIAL_BOS = "<bos>"
    SPECIAL_EOS = "<eos>"

    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer

    @classmethod
    def create_empty(cls) -> "LegislativeBpeTokenizer":
        """Cria um tokenizer vazio com o alfabeto de 256 bytes e especiais configurados."""
        alphabet = pre_tokenizers.ByteLevel.alphabet()

        # Monta vocabulário base com os 3 especiais e os 256 bytes
        vocab: Dict[str, int] = {
            cls.SPECIAL_PAD: 0,
            cls.SPECIAL_BOS: 1,
            cls.SPECIAL_EOS: 2,
        }
        for i, b in enumerate(alphabet):
            vocab[b] = 3 + i

        bpe_model = models.BPE(vocab=vocab, merges=[], byte_fallback=True)
        tok = Tokenizer(bpe_model)
        tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=True)
        tok.decoder = decoders.ByteLevel()
        return cls(tok)

    def encode(self, text: Union[str, bytes]) -> List[int]:
        """Codifica texto ou bytes em IDs de subpalavras (sem tokens especiais)."""
        if isinstance(text, (bytes, bytearray)):
            text = text.decode("utf-8")
        encoding = self._tokenizer.encode(text, add_special_tokens=False)
        return list(encoding.ids)

    def encode_tokens(self, text: Union[str, bytes]) -> List[str]:
        """Retorna lista de tokens (strings com codificação bytelevel)."""
        if isinstance(text, (bytes, bytearray)):
            text = text.decode("utf-8")
        encoding = self._tokenizer.encode(text, add_special_tokens=False)
        return list(encoding.tokens)

    def encode_sequence(self, text: Union[str, bytes]) -> List[int]:
        """Codifica sequência completa com delimitadores estruturais: [BOS] + text + [EOS]."""
        body_ids = self.encode(text)
        return [1] + body_ids + [2]

    def decode(self, ids: Sequence[int], skip_special_tokens: bool = False) -> str:
        """Decodifica lista de IDs de volta para string."""
        int_ids = [int(i) for i in ids]
        if skip_special_tokens:
            int_ids = [i for i in int_ids if i not in (0, 1, 2)]
        return self._tokenizer.decode(int_ids)

    def decode_to_bytes(self, ids: Sequence[int], skip_special_tokens: bool = False) -> bytes:
        """Decodifica lista de IDs de volta para bytes UTF-8."""
        return self.decode(ids, skip_special_tokens=skip_special_tokens).encode("utf-8")

    def verify_round_trip(self, text: str) -> bool:
        """Verifica se o texto sobrevive ao round-trip exato: text == decode(encode(text))."""
        ids = self.encode(text)
        decoded = self.decode(ids)
        return decoded == text

    def get_vocab_size(self) -> int:
        """Retorna o tamanho do vocabulário efetivo."""
        return self._tokenizer.get_vocab_size()

    def get_vocab(self) -> Dict[str, int]:
        """Retorna o dicionário completo de tokens e seus IDs."""
        return self._tokenizer.get_vocab()

    def token_to_id(self, token: str) -> Optional[int]:
        """Retorna o ID correspondente ao token string."""
        return self._tokenizer.token_to_id(token)

    def id_to_token(self, token_id: int) -> Optional[str]:
        """Retorna a representação textual do token ID."""
        return self._tokenizer.id_to_token(int(token_id))

    def save(self, path: Union[str, Path]) -> None:
        """Salva a definição do tokenizer em arquivo JSON."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._tokenizer.save(str(p))

    @classmethod
    def load(cls, path: Union[str, Path]) -> "LegislativeBpeTokenizer":
        """Carrega o tokenizer a partir de arquivo JSON salvo."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Arquivo do tokenizer não encontrado: {p}")
        tok = Tokenizer.from_file(str(p))
        return cls(tok)


def train_bpe_tokenizer(
    texts: Iterable[str] | Callable[[], Iterable[str]],
    config: TokenizerConfig,
    show_progress: bool = False,
) -> Tuple[LegislativeBpeTokenizer, TokenizerMetrics]:
    """Treina um Tokenizer ByteLevel BPE sobre textos de treinamento."""
    config.validate()

    # Prepara o modelo inicial com o alfabeto completo
    base_tok = Tokenizer(models.BPE(byte_fallback=True))
    base_tok.pre_tokenizer = pre_tokenizers.ByteLevel(
        add_prefix_space=config.tokenization.add_prefix_space,
        use_regex=True,
    )
    base_tok.decoder = decoders.ByteLevel()

    alphabet = pre_tokenizers.ByteLevel.alphabet()
    special_tokens = [
        LegislativeBpeTokenizer.SPECIAL_PAD,
        LegislativeBpeTokenizer.SPECIAL_BOS,
        LegislativeBpeTokenizer.SPECIAL_EOS,
    ]

    trainer = trainers.BpeTrainer(
        vocab_size=config.model.vocab_size,
        min_frequency=config.model.min_frequency,
        special_tokens=special_tokens,
        initial_alphabet=alphabet,
        show_progress=show_progress,
    )

    # Callable providers allow bounded-memory passes over large Parquet releases.
    # One-shot iterators retain the older materialized behavior for API compatibility.
    if callable(texts):
        corpus_factory = texts
    else:
        corpus_list = texts if isinstance(texts, Sequence) else list(texts)
        corpus_factory = lambda: iter(corpus_list)

    base_tok.train_from_iterator(corpus_factory(), trainer=trainer)

    # CRÍTICO: Remover especiais de added_tokens para que strings literais no texto
    # (como '<pad>', '<bos>') sejam tokenizadas como caracteres comuns e NUNCA
    # produzam os IDs de controle de sequência 0, 1 ou 2.
    raw_state = json.loads(base_tok.to_str())
    raw_state["added_tokens"] = []
    cleaned_tok = Tokenizer.from_str(json.dumps(raw_state))

    tokenizer = LegislativeBpeTokenizer(cleaned_tok)

    # Validação do mapeamento de tokens especiais
    if tokenizer.token_to_id(LegislativeBpeTokenizer.SPECIAL_PAD) != 0:
        raise ValueError(
            f"PAD token deve ter ID 0, obtido: {tokenizer.token_to_id(LegislativeBpeTokenizer.SPECIAL_PAD)}"
        )
    if tokenizer.token_to_id(LegislativeBpeTokenizer.SPECIAL_BOS) != 1:
        raise ValueError(
            f"BOS token deve ter ID 1, obtido: {tokenizer.token_to_id(LegislativeBpeTokenizer.SPECIAL_BOS)}"
        )
    if tokenizer.token_to_id(LegislativeBpeTokenizer.SPECIAL_EOS) != 2:
        raise ValueError(
            f"EOS token deve ter ID 2, obtido: {tokenizer.token_to_id(LegislativeBpeTokenizer.SPECIAL_EOS)}"
        )

    # Cálculo de métricas e verificação de round-trip sobre todos os documentos de treino
    total_bytes = 0
    total_chars = 0
    total_tokens = 0
    doc_lengths: List[int] = []

    for doc in corpus_factory():
        doc_bytes = doc.encode("utf-8")
        total_bytes += len(doc_bytes)
        total_chars += len(doc)

        encoded_ids = tokenizer.encode(doc)
        doc_len = len(encoded_ids)
        doc_lengths.append(doc_len)
        total_tokens += doc_len

        # Teste estrito de round-trip
        decoded = tokenizer.decode(encoded_ids)
        if decoded != doc:
            raise ValueError(
                f"Falha de round-trip no documento de treino!\n"
                f"Original: {repr(doc[:100])}\n"
                f"Decodificado: {repr(decoded[:100])}"
            )

        # Prova de que IDs de controle não foram emitidos pelo texto
        if 0 in encoded_ids or 1 in encoded_ids or 2 in encoded_ids:
            raise ValueError("ID de controle especial (0, 1 ou 2) foi emitido a partir de texto comum!")

    doc_lengths.sort()
    n_docs = len(doc_lengths)
    if not n_docs:
        raise ValueError("Corpus de treino está vazio")
    p50_idx = int(0.50 * n_docs)
    p95_idx = min(n_docs - 1, int(0.95 * n_docs))

    metrics = TokenizerMetrics(
        vocab_size_effective=tokenizer.get_vocab_size(),
        vocab_size_target=config.model.vocab_size,
        total_training_docs=n_docs,
        total_training_bytes=total_bytes,
        total_training_tokens=total_tokens,
        compression_bytes_per_token=round(total_bytes / max(1, total_tokens), 4),
        tokens_per_character=round(total_tokens / max(1, total_chars), 4),
        min_doc_tokens=doc_lengths[0] if doc_lengths else 0,
        max_doc_tokens=doc_lengths[-1] if doc_lengths else 0,
        mean_doc_tokens=round(total_tokens / max(1, n_docs), 2),
        p50_doc_tokens=float(doc_lengths[p50_idx]) if doc_lengths else 0.0,
        p95_doc_tokens=float(doc_lengths[p95_idx]) if doc_lengths else 0.0,
    )

    return tokenizer, metrics


def save_tokenizer_bundle(
    tokenizer: LegislativeBpeTokenizer,
    metrics: TokenizerMetrics,
    config: TokenizerConfig,
    output_dir: Union[str, Path],
    training_item_ids_hash: str,
    training_text_hashes_hash: str,
    training_bytes: int,
    seed: int = 42,
) -> Tuple[Path, Path, Path]:
    """Salva os artefatos do tokenizer, o manifesto normativo e o marcador COMPLETE.json."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Salva tokenizer.json
    tok_file = out_dir / "tokenizer.json"
    tokenizer.save(tok_file)
    tok_file_sha = hashlib.sha256(tok_file.read_bytes()).hexdigest()

    # 2. Monta tokenizer_manifest.json em conformidade estrita com o esquema
    manifest_data: Dict[str, Any] = {
        "tokenizer_id": config.tokenizer_id,
        "corpus_version": config.corpus_version,
        "split_version": config.split_version,
        "training_item_ids_hash": training_item_ids_hash,
        "training_text_hashes_hash": training_text_hashes_hash,
        "config_hash": config.compute_config_hash(),
        "library": "tokenizers",
        "library_version": tokenizers.__version__,
        "vocab_size": metrics.vocab_size_effective,
        "special_tokens": config.special_tokens.to_dict(),
        "alphabet_policy": "byte_level_full_256",
        "normalization_policy": "none_preserving",
        "tokenizer_file_sha256": tok_file_sha,
        "seed": seed,
        "training_bytes": training_bytes,
    }

    manifest_file = out_dir / "tokenizer_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    manifest_sha = hashlib.sha256(manifest_file.read_bytes()).hexdigest()

    # 3. Salva COMPLETE.json
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    complete_data = {
        "manifest_file": "tokenizer_manifest.json",
        "manifest_sha256": manifest_sha,
        "published_at_utc": now_utc,
    }
    complete_file = out_dir / "COMPLETE.json"
    with open(complete_file, "w", encoding="utf-8") as f:
        json.dump(complete_data, f, indent=2, ensure_ascii=False)

    return tok_file, manifest_file, complete_file
