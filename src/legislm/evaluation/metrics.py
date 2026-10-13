"""
src/legislm/evaluation/metrics.py
Métrica comparável independente de vocabulário byte_nll_v1 e utilitários de texto.
"""

from __future__ import annotations

import math
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

import torch
import torch.nn as nn
import torch.nn.functional as F

from legislm.tokenization.bpe import LegislativeBpeTokenizer


def count_words(text: str) -> int:
    """Conta palavras em texto legislativo utilizando separação padrão por whitespace."""
    if not text:
        return 0
    return len(text.strip().split())


def split_text_into_utf8_segments(text: str, max_bytes: int) -> List[bytes]:
    """Segmenta deterministicamente um texto em trechos contíguos de no máximo max_bytes.

    Regras normativas (docs/VALIDACAO.md Seção 9):
    1. O corte deve ocorrer estritamente no último limite de code point UTF-8 válido.
    2. Não altera, normaliza, remove nem adiciona nenhum byte ou espaço.
    3. Garante que b"".join(segments) == text.encode("utf-8") com preservação exata.
    4. Cada segmento resultante é uma sequência UTF-8 decodificável válida.
    """
    if max_bytes < 1:
        raise ValueError(f"max_bytes deve ser >= 1, recebido: {max_bytes}")

    raw_bytes = text.encode("utf-8")
    total_len = len(raw_bytes)
    if total_len == 0:
        return []

    if total_len <= max_bytes:
        return [raw_bytes]

    segments: List[bytes] = []
    start = 0

    while start < total_len:
        end = min(start + max_bytes, total_len)
        if end < total_len:
            # Recua 'end' para evitar cortar no meio de um code point UTF-8 multibyte
            # Em UTF-8, bytes de continuação estão na faixa 0x80 a 0xBF (10xxxxxx)
            while end > start:
                try:
                    raw_bytes[start:end].decode("utf-8")
                    break
                except UnicodeDecodeError:
                    end -= 1

            if end == start:
                raise ValueError(
                    f"Impossível segmentar UTF-8 válido na posição {start} com max_bytes={max_bytes}"
                )

        seg = raw_bytes[start:end]
        segments.append(seg)
        start = end

    # Validação de integridade do particionamento
    reconstructed = b"".join(segments)
    if reconstructed != raw_bytes:
        raise ValueError("Falha de integridade: a junção dos segmentos difere dos bytes originais")

    return segments


@dataclass
class ByteNllResult:
    """Resultado consolidado da métrica comparável independente de vocabulário byte_nll_v1."""

    protocol_version: str = "byte_nll_v1"
    k_bytes: int = 512
    nats_per_byte: float = 0.0
    bits_per_byte: float = 0.0
    total_nll: float = 0.0
    total_bytes: int = 0
    total_tokens: int = 0
    total_documents: int = 0
    total_segments: int = 0
    compression_bytes_per_token: float = 0.0
    tokens_per_byte: float = 0.0
    item_list_sha256: str = ""
    text_hashes_sha256: str = ""
    context_length: int = 0
    document_metrics: List[Dict[str, Any]] = field(default_factory=list)
    strata_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "k_bytes": self.k_bytes,
            "nats_per_byte": self.nats_per_byte,
            "bits_per_byte": self.bits_per_byte,
            "total_nll": self.total_nll,
            "total_bytes": self.total_bytes,
            "total_tokens": self.total_tokens,
            "total_documents": self.total_documents,
            "total_segments": self.total_segments,
            "compression_bytes_per_token": self.compression_bytes_per_token,
            "tokens_per_byte": self.tokens_per_byte,
            "item_list_sha256": self.item_list_sha256,
            "text_hashes_sha256": self.text_hashes_sha256,
            "context_length": self.context_length,
            "strata_metrics": self.strata_metrics,
            "documents_count": len(self.document_metrics),
        }


def compute_byte_nll_v1(
    model: nn.Module,
    tokenizer: LegislativeBpeTokenizer,
    documents: Sequence[Any],
    k_bytes: Optional[int] = None,
    device: Optional[Union[torch.device, str]] = None,
) -> ByteNllResult:
    """Calcula a métrica comparável universal byte_nll_v1 conforme docs/VALIDACAO.md Seção 9.

    Protocolo normativo:
    1. Lista comum de itens com round-trip verificado e preservação estrita de UTF-8.
    2. Segmentação em trechos não sobrepostos de no máximo K bytes, sem quebra de code points.
    3. Prefixar com [BOS] e predizer TODOS os tokens de texto a partir de [BOS].
    4. Excluir estritamente [EOS] e [PAD] do numerador e do denominador.
    5. Dividir o somatório da perda em nats pelo total de bytes UTF-8 dos segmentos.
    6. Falhar explicitamente se o segmento tokenizado exceder o context_length do modelo (sem truncamento silencioso).

    Args:
        model: Modelo GPT em modo eval com atributo config.context_length e config.vocab_size.
        tokenizer: Tokenizer LegislativeBpeTokenizer treinado e congelado.
        documents: Coleção de documentos (CuratedDocument ou objetos com .text e .corpus_item_id).
        k_bytes: Tamanho máximo de cada segmento em bytes UTF-8.
        device: Dispositivo de execução (CPU, CUDA, MPS).

    Returns:
        ByteNllResult com métricas nats/byte, bits/byte e estatísticas estratificadas.
    """
    if device is None:
        try:
            device = next(model.parameters()).device
        except StopIteration:
            device = torch.device("cpu")
    else:
        device = torch.device(device)

    model_was_training = model.training
    model.eval()

    context_length = getattr(model.config, "context_length", 512)
    vocab_size = getattr(model.config, "vocab_size", tokenizer.get_vocab_size())

    # byte_nll_v1 congela K com dados de treino e a menor capacidade dos
    # candidatos. Para um único modelo, usa o ponto inicial normativo.
    max_k = context_length - 1
    if max_k < 1:
        raise ValueError(f"context_length={context_length} não comporta BOS e texto")
    if k_bytes is None:
        k_bytes = min(512, max_k)
    if not isinstance(k_bytes, int) or isinstance(k_bytes, bool):
        raise ValueError("k_bytes deve ser um inteiro congelado antes da avaliação")
    if k_bytes < 1 or k_bytes > max_k:
        raise ValueError(
            f"k_bytes={k_bytes} deve estar entre 1 e context_length-1 ({max_k}); "
            "K deve ser congelado usando train e a menor capacidade dos candidatos"
        )

    total_nll = 0.0
    total_bytes = 0
    total_tokens = 0
    total_segments = 0
    doc_metrics_list: List[Dict[str, Any]] = []
    scored_items: List[Dict[str, str]] = []
    seen_item_ids: set[str] = set()

    # Estratos (casa, tipo documental, ano)
    strata: Dict[str, Dict[str, Dict[str, float]]] = {
        "house": {},
        "document_type": {},
        "year": {},
    }

    with torch.no_grad():
        for doc in documents:
            # Extração de campos do documento
            if hasattr(doc, "text"):
                text = doc.text
                item_id = getattr(doc, "corpus_item_id", "unknown")
                meta = getattr(doc, "metadata", {}) or {}
                house = getattr(doc, "house", meta.get("house", "unknown"))
                doc_type = getattr(doc, "normalized_kind", meta.get("normalized_kind", "unknown"))
                content_date = getattr(doc, "content_date", meta.get("content_date", None))
                year = str(content_date)[:4] if content_date else str(meta.get("year", "unknown"))
            elif isinstance(doc, dict):
                text = doc.get("text", "")
                item_id = doc.get("corpus_item_id", "unknown")
                meta = doc.get("metadata", {}) or {}
                house = doc.get("house", meta.get("house", "unknown"))
                doc_type = doc.get("normalized_kind", meta.get("normalized_kind", "unknown"))
                content_date = doc.get("content_date", meta.get("content_date", None))
                year = str(content_date)[:4] if content_date else str(meta.get("year", "unknown"))
            else:
                raise TypeError(f"Formato de documento não suportado: {type(doc)}")

            if not text:
                continue

            if str(item_id) in seen_item_ids:
                raise ValueError(f"Lista byte_nll_v1 contém corpus_item_id duplicado: {item_id}")
            seen_item_ids.add(str(item_id))

            # 1. Verificação rigorosa de round-trip exato antes de pontuar
            if not tokenizer.verify_round_trip(text):
                raise ValueError(
                    f"Violação de integridade: texto do documento '{item_id}' falhou no round-trip exato do tokenizer"
                )
            # O conjunto comparável é identificado por ID e hash do texto exato.
            text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            scored_items.append({"corpus_item_id": str(item_id), "text_sha256": text_sha256})

            # 2. Segmentação determinística em trechos de no máximo k_bytes
            segments = split_text_into_utf8_segments(text, max_bytes=k_bytes)
            doc_nll = 0.0
            doc_bytes = 0
            doc_tokens = 0
            doc_segments_count = len(segments)

            for seg_idx, seg_bytes in enumerate(segments):
                seg_text = seg_bytes.decode("utf-8")
                body_ids = tokenizer.encode(seg_text)
                M = len(body_ids)
                if any(token_id in (0, 1, 2) for token_id in body_ids):
                    raise ValueError(
                        f"Tokenizer emitiu token especial em texto comum do item '{item_id}'"
                    )
                if M == 0:
                    continue

                # 3. Falha explícita se tokenização ultrapassar context_length
                if M > context_length:
                    raise ValueError(
                        f"Segmento {seg_idx} do documento '{item_id}' possui {M} tokens, "
                        f"excedendo context_length={context_length}. Truncamento proibido pela Seção 9 de docs/VALIDACAO.md!"
                    )

                # 4. Sequência com BOS como prefixo: input=[BOS, t_1, ..., t_{M-1}], target=[t_1, ..., t_M]
                # Posição 0: input=BOS, target=t_1
                # Posição 1: input=t_1, target=t_2
                # ...
                # Posição M-1: input=t_{M-1}, target=t_M
                bos_id = tokenizer.token_to_id(LegislativeBpeTokenizer.SPECIAL_BOS)
                if bos_id is None:
                    raise ValueError("Tokenizer não define token BOS")
                input_seq = [bos_id] + body_ids[:-1]
                target_seq = body_ids

                input_tensor = torch.tensor([input_seq], dtype=torch.long, device=device)
                target_tensor = torch.tensor([target_seq], dtype=torch.long, device=device)

                logits = model(input_tensor)  # [1, M, vocab_size]

                # Perda somada não-reduzida sobre todos os tokens de texto (sem EOS e sem PAD)
                ce_loss = F.cross_entropy(
                    logits.view(-1, vocab_size),
                    target_tensor.view(-1),
                    reduction="sum",
                ).item()

                seg_byte_len = len(seg_bytes)
                doc_nll += ce_loss
                doc_tokens += M
                doc_bytes += seg_byte_len

            # Consolidação do documento
            total_nll += doc_nll
            total_bytes += doc_bytes
            total_tokens += doc_tokens
            total_segments += doc_segments_count

            doc_nats_per_byte = doc_nll / doc_bytes if doc_bytes > 0 else 0.0
            doc_metrics_list.append({
                "corpus_item_id": item_id,
                "house": house,
                "document_type": doc_type,
                "year": year,
                "bytes": doc_bytes,
                "tokens": doc_tokens,
                "segments": doc_segments_count,
                "nll": doc_nll,
                "nats_per_byte": doc_nats_per_byte,
                "bits_per_byte": doc_nats_per_byte / math.log(2) if doc_nats_per_byte > 0 else 0.0,
            })

            # Atualização de estratos
            for strata_name, val in [("house", house), ("document_type", doc_type), ("year", year)]:
                if val not in strata[strata_name]:
                    strata[strata_name][val] = {"nll": 0.0, "bytes": 0, "tokens": 0, "docs": 0}
                strata[strata_name][val]["nll"] += doc_nll
                strata[strata_name][val]["bytes"] += doc_bytes
                strata[strata_name][val]["tokens"] += doc_tokens
                strata[strata_name][val]["docs"] += 1

    if model_was_training:
        model.train()

    # Cálculo final ponderado
    nats_per_byte = total_nll / total_bytes if total_bytes > 0 else 0.0
    bits_per_byte = nats_per_byte / math.log(2) if total_bytes > 0 else 0.0
    comp_bytes_per_tok = total_bytes / total_tokens if total_tokens > 0 else 0.0
    tok_per_byte = total_tokens / total_bytes if total_bytes > 0 else 0.0

    # Compilação dos estratos
    compiled_strata: Dict[str, Dict[str, Any]] = {}
    for strata_name, strata_dict in strata.items():
        compiled_strata[strata_name] = {}
        for k, v in strata_dict.items():
            s_bytes = v["bytes"]
            s_nll = v["nll"]
            s_nats = s_nll / s_bytes if s_bytes > 0 else 0.0
            compiled_strata[strata_name][k] = {
                "documents": v["docs"],
                "bytes": s_bytes,
                "tokens": v["tokens"],
                "nll": s_nll,
                "nats_per_byte": s_nats,
                "bits_per_byte": s_nats / math.log(2) if s_bytes > 0 else 0.0,
            }

    return ByteNllResult(
        protocol_version="byte_nll_v1",
        k_bytes=k_bytes,
        nats_per_byte=nats_per_byte,
        bits_per_byte=bits_per_byte,
        total_nll=total_nll,
        total_bytes=total_bytes,
        total_tokens=total_tokens,
        total_documents=len(doc_metrics_list),
        total_segments=total_segments,
        compression_bytes_per_token=comp_bytes_per_tok,
        tokens_per_byte=tok_per_byte,
        item_list_sha256=hashlib.sha256(
            json.dumps(sorted(scored_items, key=lambda item: item["corpus_item_id"]),
                       ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        text_hashes_sha256=hashlib.sha256(
            json.dumps(sorted(item["text_sha256"] for item in scored_items),
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        context_length=context_length,
        document_metrics=doc_metrics_list,
        strata_metrics=compiled_strata,
    )
