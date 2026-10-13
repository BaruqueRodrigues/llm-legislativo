"""
tests/model/test_memorization.py
Harness de teste para memorização de fixture sintética fixa (Gate G4).
Demonstra capacidade de sobreajuste/memorização perfeita de 2-4 sequências em CPU,
atingindo Cross-Entropy <= 0.1 e acurácia next-token >= 99% em alvos válidos.
"""

import pytest
import torch
import torch.optim as optim

from legislm.model.config import GPTConfig
from legislm.model.gpt import GPTModel


def test_synthetic_fixture_memorization_cpu():
    """Harness de teste para memorização de fixture sintética com modelo minúsculo em CPU.

    Critérios de aprovação (Gate G4):
    - CE <= 0.1
    - Acurácia next-token >= 99% em alvos válidos (desconsiderando PAD/-100).
    - Execução pura em CPU com dropout=0.0.
    """
    torch.manual_seed(42)

    # 1. Modelo minúsculo e determinístico
    cfg = GPTConfig(
        vocab_size=50,
        context_length=8,
        d_model=64,
        n_layers=2,
        n_heads=2,
        dropout=0.0,
        tie_embeddings=True,
    )
    model = GPTModel(cfg)
    model.train()

    # 2. Fixture sintética fixa de 3 sequências representativas
    # Inclui sequências de diferentes tamanhos úteis com acolchoamento (PAD=0)
    # EOS = 2
    inputs = torch.tensor([
        [10, 11, 12, 13, 14, 2, 0, 0],
        [20, 21, 22, 23, 24, 25, 2, 0],
        [30, 31, 32, 33, 34, 35, 36, 2],
    ], dtype=torch.long)

    # Alvos de próxima predição (-100 onde não há alvo válido ou onde o input era PAD/EOS final)
    targets = torch.tensor([
        [11, 12, 13, 14, 2, -100, -100, -100],
        [21, 22, 23, 24, 25, 2, -100, -100],
        [31, 32, 33, 34, 35, 36, 2, -100],
    ], dtype=torch.long)

    # Máscara de atenção: False nas posições de PAD (0)
    attention_mask = (inputs != cfg.pad_token_id)

    # 3. Otimizador AdamW
    optimizer = optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.0)

    # 4. Loop de treinamento rápido em CPU
    max_steps = 100
    final_loss = float("inf")
    final_acc = 0.0

    for step in range(max_steps):
        optimizer.zero_grad()
        logits, loss = model(inputs, attention_mask=attention_mask, targets=targets)
        loss.backward()
        optimizer.step()

        # Medição de acurácia sobre os alvos válidos (target != -100)
        with torch.no_grad():
            preds = torch.argmax(logits, dim=-1)
            valid_mask = (targets != -100)
            acc = (preds[valid_mask] == targets[valid_mask]).float().mean().item()
            final_loss = loss.item()
            final_acc = acc

        # Critério de parada precoce se já atender os requisitos com margem
        if final_loss <= 0.05 and final_acc >= 0.99:
            break

    # 5. Validação rigorosa dos critérios de aprovação
    assert final_loss <= 0.1, f"Perda Cross-Entropy {final_loss:.4f} excede o teto de 0.1!"
    assert final_acc >= 0.99, f"Acurácia {final_acc * 100:.2f}% inferior à meta de 99%!"

    # 6. Modo de avaliação e conferência exata das predições
    model.eval()
    with torch.no_grad():
        eval_logits, eval_loss = model(inputs, attention_mask=attention_mask, targets=targets)
        eval_preds = torch.argmax(eval_logits, dim=-1)
        valid_mask = (targets != -100)
        eval_acc = (eval_preds[valid_mask] == targets[valid_mask]).float().mean().item()

    assert eval_loss.item() <= 0.1
    assert eval_acc == 1.0, f"Todas as predições válidas devem estar 100% corretas no final, obtido: {eval_acc}"
