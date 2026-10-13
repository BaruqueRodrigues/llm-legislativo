"""
tests/training/test_sampler_and_coverage.py
Testes do sampler determinístico, rastreamento estratificado e inclusão sem filtros.
"""

import unittest

from legislm.training.data import (
    DeterministicSampler,
    DocumentItem,
    StratifiedTracker,
    TokenDataset,
)


class TestSamplerAndCoverage(unittest.TestCase):
    def setUp(self):
        # Cria conjunto deliberadamente heterogêneo de documentos legislativos
        self.docs = [
            DocumentItem("camara:doc:PL_2020_01", [1, 10, 11, 2], {"house": "camara", "normalized_kind": "PL", "year": "2020", "version_id": "v1"}),
            DocumentItem("camara:doc:emenda_2021_02", [1, 12, 13, 2], {"house": "camara", "normalized_kind": "emenda", "year": "2021", "version_id": "v1"}),
            DocumentItem("camara:doc:parecer_2022_03", [1, 14, 15, 2], {"house": "camara", "normalized_kind": "parecer", "year": "2022", "version_id": "v2"}),
            DocumentItem("senado:doc:substitutivo_2023_04", [1, 16, 17, 2], {"house": "senado", "normalized_kind": "substitutivo", "year": "2023", "version_id": "v1"}),
            DocumentItem("senado:doc:diario_2024_05", [1, 18, 19, 2], {"house": "senado", "normalized_kind": "diario", "year": "2024", "version_id": "v1"}),
        ]
        self.dataset = TokenDataset(self.docs, context_length=16)

    def test_no_filter_and_full_inclusion(self):
        """Verifica que nenhum filtro restringe documentos a apenas PL ou versões iniciais."""
        total_windows = len(self.dataset)
        self.assertEqual(total_windows, 5, "Todas as categorias documentais devem ser incluídas no dataset")

        sampler = DeterministicSampler(num_items=total_windows, seed=42)
        tracker = StratifiedTracker(total_eligible_items=total_windows)

        # Amostra um ciclo completo
        sampled_indices = []
        for _ in range(total_windows):
            idx, new_cycle = sampler.next_index()
            sampled_indices.append(idx)
            _, _, _, _, item_id, _, meta = self.dataset.get_window(idx)
            tracker.register_item(item_id, meta)

        # Todos os índices devem estar presentes na permutação
        self.assertEqual(set(sampled_indices), set(range(total_windows)))

        # Verifica se o rastreador registrou estratos de ambas as casas e todos os tipos
        summary = tracker.summary()
        self.assertEqual(summary["total_eligible_items"], 5)
        self.assertEqual(summary["unique_items_seen"], 5)
        self.assertEqual(summary["coverage_percentage"], 100.0)
        self.assertTrue(summary["is_full_coverage"])

        # Presença de casas
        self.assertIn("camara", summary["strata_counts"]["house"])
        self.assertIn("senado", summary["strata_counts"]["house"])

        # Presença de tipos documentais além de PL
        kinds = summary["strata_counts"]["document_type"]
        self.assertIn("PL", kinds)
        self.assertIn("emenda", kinds)
        self.assertIn("parecer", kinds)
        self.assertIn("substitutivo", kinds)
        self.assertIn("diario", kinds)

    def test_distinguish_smoke_budget_from_historical_coverage(self):
        """Verifica que um orçamento curto (smoke) não afirma falsamente ter coberto o corpus."""
        total_items = 100
        sampler = DeterministicSampler(num_items=total_items, seed=42)
        tracker = StratifiedTracker(total_eligible_items=total_items)

        # Simula smoke curto de 10 passos
        for _ in range(10):
            idx, _ = sampler.next_index()
            tracker.register_item(f"item_{idx}", {"house": "camara", "normalized_kind": "PL"})

        summary = tracker.summary()
        self.assertEqual(summary["total_items_consumed"], 10)
        self.assertEqual(summary["unique_items_seen"], 10)
        self.assertEqual(summary["coverage_percentage"], 10.0)
        self.assertFalse(summary["is_full_coverage"], "Smoke parcial não pode alegar cobertura completa")

    def test_sampler_reproducibility_and_resumption(self):
        """Testa que salvar e restaurar o estado do sampler reproduz a sequência exata."""
        sampler1 = DeterministicSampler(num_items=20, seed=123)
        # Consome 7 itens
        for _ in range(7):
            sampler1.next_index()

        state = sampler1.state_dict()

        # Continua sampler1 por mais 10 passos
        seq1 = [sampler1.next_index()[0] for _ in range(10)]

        # Cria sampler2, restaura o estado e gera 10 passos
        sampler2 = DeterministicSampler(num_items=20, seed=999)  # seed diferente antes da restauração
        sampler2.load_state_dict(state)
        seq2 = [sampler2.next_index()[0] for _ in range(10)]

        self.assertEqual(seq1, seq2, "A sequência após restauração do cursor deve ser perfeitamente idêntica")


if __name__ == "__main__":
    unittest.main()
