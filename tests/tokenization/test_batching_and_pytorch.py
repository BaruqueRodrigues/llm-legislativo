"""
tests/tokenization/test_batching_and_pytorch.py
Testes do pipeline de batching, DataLoader do PyTorch e integração com o modelo Transformer.
"""

import tempfile
import unittest
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel
from legislm.tokenization.bpe import LegislativeBpeTokenizer
from legislm.tokenization.config import TokenizerConfig
from legislm.tokenization.dataset import (
    TokenBatch,
    TokenDataset,
    build_token_dataset,
    make_batch,
)
from legislm.tokenization.reader import CuratedDocument


class TestBatchingAndPyTorch(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.tokenizer = LegislativeBpeTokenizer.create_empty()
        self.config = TokenizerConfig.from_dict({
            "tokenizer_id": "bpe_test_batch",
            "corpus_version": "corpus_v1",
            "split_version": "split_v1",
            "sequence_policy_version": "doc_window_v1",
            "token_dataset_id": "tok_dataset_batch",
            "model": {"type": "BPE", "byte_fallback": True, "vocab_size": 259, "min_frequency": 1},
            "special_tokens": {"PAD": 0, "BOS": 1, "EOS": 2},
            "tokenization": {"lowercase": False, "strip_accents": False, "add_prefix_space": False},
            "dataset": {
                "context_length": 32,
                "dtype": "int32",
                "endianness": "little",
                "shards_dir": "tokens",
            },
        })

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _create_mock_docs(self) -> list[CuratedDocument]:
        texts = [
            "Documento primeiro curto para teste de lote.",
            "Segundo documento um pouco maior com mais palavras e conteúdo legal de teste legislativo.",
            "Terceiro documento médio com termos técnicos e jurídicos.",
        ]
        docs = []
        for i, t in enumerate(texts):
            docs.append(CuratedDocument(
                corpus_item_id=f"doc_{i}",
                text=t,
                text_sha256="abc",
                utf8_bytes=len(t.encode("utf-8")),
                character_count=len(t),
                house="camara",
                normalized_kind="PL",
                version_id=f"v_{i}",
                family_id=f"fam_{i}",
                split="train",
                quality_status="accepted",
                include_in_dataset=True,
                representative_item_id=f"doc_{i}",
            ))
        return docs

    def test_dataloader_and_make_batch(self):
        """Valida que DataLoader empacota janelas em TokenBatch com tipos e formatos estritos."""
        docs = self._create_mock_docs()
        out_dir = self.tmp_path / "dataset"
        L = 32

        build_token_dataset(
            docs_by_split={"train": docs},
            tokenizer=self.tokenizer,
            config=self.config,
            output_dir=out_dir,
            tokenizer_file_sha256="fake_sha",
        )

        dataset = TokenDataset.from_dataset_dir(out_dir, split="train", context_length=L)
        self.assertGreater(len(dataset), 0)

        loader = DataLoader(dataset, batch_size=2, shuffle=False, collate_fn=make_batch)

        batches_seen = 0
        for batch in loader:
            batches_seen += 1
            self.assertIsInstance(batch, TokenBatch)

            # Tipos e dimensões exigidos pelo contrato
            self.assertEqual(batch.input_ids.shape[1], L)
            self.assertEqual(batch.targets.shape[1], L)
            self.assertEqual(batch.attention_mask.shape[1], L)
            self.assertEqual(batch.loss_mask.shape[1], L)

            self.assertEqual(batch.input_ids.dtype, torch.int64)
            self.assertEqual(batch.targets.dtype, torch.int64)
            self.assertEqual(batch.attention_mask.dtype, torch.bool)
            self.assertEqual(batch.loss_mask.dtype, torch.float32)

            self.assertGreater(batch.valid_targets_count, 0)
            self.assertEqual(batch.total_positions, batch.input_ids.shape[0] * L)

            # Acesso estilo dicionário
            self.assertIs(batch["input_ids"], batch.input_ids)
            self.assertIs(batch["targets"], batch.targets)
            self.assertIs(batch["loss_mask"], batch.loss_mask)

            # Transferência de dispositivo
            batch_cpu = batch.to("cpu")
            self.assertEqual(batch_cpu.input_ids.device.type, "cpu")

            # Conversão para o Batch do pacote training
            training_b = batch.to_training_batch()
            self.assertEqual(training_b.loss_mask.dtype, torch.bool)

        self.assertGreater(batches_seen, 0)

    def test_end_to_end_forward_and_backward_with_gpt_model(self):
        """Valida integração ponta a ponta: TokenBatch -> GPTModel -> Loss -> Backward sem NaNs."""
        docs = self._create_mock_docs()
        out_dir = self.tmp_path / "dataset_gpt"
        L = 32
        V = 259

        build_token_dataset(
            docs_by_split={"train": docs},
            tokenizer=self.tokenizer,
            config=self.config,
            output_dir=out_dir,
            tokenizer_file_sha256="fake_sha",
        )

        dataset = TokenDataset.from_dataset_dir(out_dir, split="train", context_length=L)
        loader = DataLoader(dataset, batch_size=2, collate_fn=make_batch)
        first_batch = next(iter(loader))

        # Instancia modelo pequeno para teste educacional
        gpt_cfg = GPTConfig(
            vocab_size=V,
            context_length=L,
            d_model=64,
            n_layers=2,
            n_heads=2,
            dropout=0.0,
            tie_embeddings=True,
        )
        model = GPTModel(gpt_cfg)

        # Forward pass
        logits = model(first_batch.input_ids, attention_mask=first_batch.attention_mask)
        self.assertEqual(logits.shape, (first_batch.input_ids.shape[0], L, V))
        self.assertFalse(torch.isnan(logits).any(), "Logits não podem conter NaN")

        # Cálculo da perda por alvos válidos (ignorando posições -100)
        loss = F.cross_entropy(
            logits.view(-1, V),
            first_batch.targets.view(-1),
            ignore_index=-100,
            reduction="mean",
        )
        self.assertFalse(torch.isnan(loss), "Loss não pode ser NaN")
        self.assertGreater(loss.item(), 0.0)

        # Backward pass
        loss.backward()

        for name, param in model.named_parameters():
            if param.requires_grad and param.grad is not None:
                self.assertFalse(
                    torch.isnan(param.grad).any(),
                    f"Gradiente NaN encontrado no parâmetro {name}",
                )


if __name__ == "__main__":
    unittest.main()
