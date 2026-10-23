---
title: LLM Legislativo API
emoji: 🏛️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# LLM Legislativo — API de inferência

Serviço FastAPI que carrega o modelo `BaruqRodrigues/llm-legislativo` do Hugging
Face Hub e expõe geração de texto legislativo em português.

Este `README.md` é obrigatório para publicação como Hugging Face Space (SDK
Docker): o bloco de metadados acima (`sdk: docker`, `app_port: 7860`) é lido
pela plataforma.

## Endpoints

- `GET /health` — estado do serviço e dispositivo (cpu/cuda).
- `POST /generate` — gera texto a partir de um prompt.

```bash
curl -X POST https://SEU-SPACE.hf.space/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "PROJETO DE LEI Nº , DE 2026\n\nDispõe sobre", "max_new_tokens": 64}'
```

## Variáveis de ambiente

| Variável | Descrição | Default |
|---|---|---|
| `MODEL_REPO` | Repo do modelo no Hub | `BaruqRodrigues/llm-legislativo` |
| `API_TOKEN` | Se definido, exige `Authorization: Bearer <token>` | vazio |
| `ALLOW_ORIGINS` | Origens de CORS separadas por vírgula | `*` |
| `MAX_NEW_TOKENS_CAP` | Teto de tokens gerados por requisição | `256` |

## Aviso

Artefato educacional e de pesquisa. As gerações **não** são orientação jurídica
nem fonte factual; o modelo pode inventar normas e atribuir conteúdo incorreto
a leis.
