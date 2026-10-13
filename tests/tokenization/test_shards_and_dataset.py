"""
tests/tokenization/test_shards_and_dataset.py
Testes da geração de shards .npy, índice Parquet, derivação de janelas e manifesto de dataset.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch

from legislm.tokenization.bpe import LegislativeBpeTokenizer
from legislm.tokenization.config import TokenizerConfig
from legislm.tokenization.dataset import (
    TokenDataset,
    build_token_dataset,
)
from legislm.tokenization.reader import CuratedDocument


class TestShardsAndDataset(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.tokenizer = LegislativeBpeTokenizer.create_empty()
        self.config = TokenizerConfig.from_dict({
            "tokenizer_id": "bpe_test_shards",
            "corpus_version": "corpus_v1",
            "split_version": "split_v1",
            "sequence_policy_version": "doc_window_v1",
            "token_dataset_id": "tok_dataset_test",
            "model": {"type": "BPE", "byte_fallback": True, "vocab_size": 259, "min_frequency": 1},
            "special_tokens": {"PAD": 0, "BOS": 1, "EOS": 2},
            "tokenization": {"lowercase": False, "strip_accents": False, "add_prefix_space": False},
            "dataset": {
                "context_length": 32,
                "dtype": "int32",
                "endianness": "little",
                "shards_dir": "tokens",
                "max_shard_tokens": 1000,
            },
        })

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _create_mock_docs(self, split: str = "train", count: int = 3) -> list[CuratedDocument]:
        docs = []
        for i in range(count):
            text = f"PROJETO DE LEI {i}\nArt. 1º Disposição inicial do teste {i}.\n" + ("Conteúdo longo " * (10 + i * 15))
            text_bytes = text.encode("utf-8")
            h = hashlib.sha256(text_bytes).hexdigest()
            doc = CuratedDocument(
                corpus_item_id=f"camara:doc:pl_{2024}_{i:03d}",
                text=text,
                text_sha256=h,
                utf8_bytes=len(text_bytes),
                character_count=len(text),
                house="camara",
                normalized_kind="PL",
                version_id=f"v_{i}",
                family_id=f"fam_{i}",
                split=split,
                quality_status="accepted",
                include_in_dataset=True,
                representative_item_id=f"camara:doc:pl_{2024}_{i:03d}",
            )
            docs.append(doc)
        return docs

    def test_build_shards_npy_format_and_disjoint_intervals(self):
        """Valida que shards .npy são int32 little-endian e intervalos no índice são disjuntos."""
        docs = self._create_mock_docs("train", count=3)
        out_dir = self.tmp_path / "dataset"

        idx_f, man_f, comp_f = build_token_dataset(
            docs_by_split={"train": docs},
            tokenizer=self.tokenizer,
            config=self.config,
            output_dir=out_dir,
            tokenizer_file_sha256="fake_sha",
        )

        self.assertTrue(idx_f.exists())
        self.assertTrue(man_f.exists())
        self.assertTrue(comp_f.exists())

        # Valida token_index.parquet
        index_tbl = pq.read_table(idx_f)
        self.assertEqual(index_tbl.num_rows, 3)
        expected_cols = {"corpus_item_id", "split", "shard_path", "offset", "length", "text_sha256", "utf8_bytes"}
        self.assertEqual(set(index_tbl.column_names), expected_cols)

        # Checa disjunção e delimitadores BOS/EOS no shard
        offsets = index_tbl["offset"].to_pylist()
        lengths = index_tbl["length"].to_pylist()
        shard_paths = index_tbl["shard_path"].to_pylist()

        for i in range(len(offsets)):
            shard_file = out_dir / shard_paths[i]
            self.assertTrue(shard_file.exists())

            # Lê array diretamente do .npy
            arr = np.load(shard_file)
            self.assertEqual(arr.dtype, np.dtype("<i4"), "Shard deve ser int32 little-endian (<i4)")

            off = offsets[i]
            length = lengths[i]
            seq = arr[off : off + length]

            self.assertEqual(seq[0], 1, "Início da sequência no shard deve ser BOS=1")
            self.assertEqual(seq[-1], 2, "Final da sequência no shard deve ser EOS=2")

            # Verifica que o próximo item (se no mesmo shard) começa exatamente no final do atual
            if i + 1 < len(offsets) and shard_paths[i] == shard_paths[i + 1]:
                self.assertEqual(off + length, offsets[i + 1], "Intervalos de documentos contíguos devem ser disjuntos")

    def test_window_derivation_zero_target_duplication(self):
        """Valida que derivação de janelas particiona alvos com zero duplicação e soma exata."""
        docs = self._create_mock_docs("train", count=1)
        out_dir = self.tmp_path / "dataset_win"
        L = 32

        build_token_dataset(
            docs_by_split={"train": docs},
            tokenizer=self.tokenizer,
            config=self.config,
            output_dir=out_dir,
            tokenizer_file_sha256="fake_sha",
        )

        dataset = TokenDataset.from_dataset_dir(out_dir, split="train", context_length=L)
        self.assertGreater(len(dataset), 1, "Documento longo deve produzir múltiplas janelas")

        # Recupera sequência completa do documento
        raw_seq = [1] + self.tokenizer.encode(docs[0].text) + [2]
        N = len(raw_seq)
        expected_total_targets = N - 1

        all_predicted_targets = []
        for w_idx in range(len(dataset)):
            sample = dataset[w_idx]
            input_ids = sample["input_ids"]
            targets = sample["targets"]
            attn_mask = sample["attention_mask"]
            loss_mask = sample["loss_mask"]

            self.assertEqual(input_ids.shape, (L,))
            self.assertEqual(targets.shape, (L,))
            self.assertEqual(attn_mask.shape, (L,))
            self.assertEqual(loss_mask.shape, (L,))
            self.assertEqual(loss_mask.dtype, torch.float32)

            # Alvos válidos desta janela (onde loss_mask == 1.0)
            valid_mask = (targets != -100)
            self.assertTrue(torch.equal(valid_mask, loss_mask == 1.0))
            self.assertTrue(torch.equal(valid_mask, attn_mask))

            valid_tgt_tokens = targets[valid_mask].tolist()
            all_predicted_targets.extend(valid_tgt_tokens)

            # Posições de padding devem ter input_ids=0 e targets=-100
            pad_mask = ~valid_mask
            if pad_mask.any():
                self.assertTrue((input_ids[pad_mask] == 0).all())
                self.assertTrue((targets[pad_mask] == -100).all())
                self.assertTrue((loss_mask[pad_mask] == 0.0).all())

            # Teste de transição entre janelas consecutivas:
            # A última posição prevista na janela k vira o primeiro input da janela k+1
            if w_idx + 1 < len(dataset):
                next_sample = dataset[w_idx + 1]
                last_target_token = valid_tgt_tokens[-1]
                first_next_input = next_sample["input_ids"][0].item()
                self.assertEqual(
                    last_target_token,
                    first_next_input,
                    "A última posição prevista em uma janela deve virar o primeiro input da próxima!",
                )

        # Prova formal de completude e ausência de duplicação:
        # A lista de todos os alvos previstos nas janelas deve ser IDÊNTICA a raw_seq[1:]
        self.assertEqual(len(all_predicted_targets), expected_total_targets)
        self.assertEqual(all_predicted_targets, raw_seq[1:])

    def test_token_dataset_manifest_schema_compliance(self):
        """Valida que token_dataset_manifest.json atende estritamente ao esquema JSON normativo."""
        docs = self._create_mock_docs("train", count=2)
        out_dir = self.tmp_path / "dataset_manifest"

        _, man_f, comp_f = build_token_dataset(
            docs_by_split={"train": docs},
            tokenizer=self.tokenizer,
            config=self.config,
            output_dir=out_dir,
            tokenizer_file_sha256="dummy_tok_hash",
        )

        schema_file = Path("schemas/manifests/token_dataset_manifest.schema.json")
        self.assertTrue(schema_file.exists())
        with open(schema_file, "r", encoding="utf-8") as f:
            schema_data = json.load(f)

        with open(man_f, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        required_keys = schema_data.get("required", [])
        for k in required_keys:
            self.assertIn(k, manifest_data, f"Campo obrigatório '{k}' ausente no manifesto")

        self.assertEqual(manifest_data["token_dataset_id"], self.config.token_dataset_id)
        self.assertEqual(manifest_data["dtype"], "int32")
        self.assertEqual(manifest_data["endianness"], "little")
        self.assertEqual(manifest_data["context_length"], self.config.dataset.context_length)
        self.assertIn("train", manifest_data["counts"])

        # Valida COMPLETE.json
        with open(comp_f, "r", encoding="utf-8") as f:
            comp_data = json.load(f)
        self.assertEqual(comp_data["manifest_file"], "token_dataset_manifest.json")
        self.assertEqual(comp_data["manifest_sha256"], hashlib.sha256(man_f.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
