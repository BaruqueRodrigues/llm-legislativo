# Sistema Multi-Agente: LLM Legislativo Brasileiro

Este repositório implementa um pipeline completo, determinístico e reproduzível para coleta, preservação, extração, curadoria, tokenização, modelagem e treinamento de um modelo de linguagem do zero (LLM educacional em PyTorch) treinado sobre o corpus legislativo oficial da Câmara dos Deputados e do Senado Federal.

## 1. Princípios e Regras Gerais de Atuação

1. **Propriedade Estrita de Arquivos (Exclusive Ownership)**:
   - Nenhum subagente edita arquivos fora do seu escopo exclusivo.
   - O Coordenador é o único responsável pelos arquivos normativos, esquemas, configurações compartilhadas, manifests, locks, fixtures comuns e scripts agregadores.
   - Conflitos de interface ou necessidades de alteração em esquemas compartilhados devem ser propostos ao Coordenador com motivação, impacto nos consumidores e plano de migração.

2. **Integridade de Dados e Contratos**:
   - Respeito irrestrito a [docs/CONTRATOS_DADOS.md](docs/CONTRATOS_DADOS.md) e [docs/PLANO_MESTRE.md](docs/PLANO_MESTRE.md).
   - Identificadores determinísticos com namespace (`house:entity:...`).
   - Não converter IDs numéricos oficiais em ponto flutuante.
   - Não descartar categorias legislativas: proposições (PL, PLP, PEC, PDC, etc.), emendas, pareceres, substitutivos, votos, redações finais, diários e anais são elegíveis.
   - Lacunas e erros devem ser registrados explicitamente em `metadata_checks`, `coverage_segments` e `fetch_attempts`. Uma resposta vazia de API ou ausência de arquivo anual não é prova de que não houve produção legislativa.
   - Textos substantivos de versões e pareceres são integralmente preservados na ordem documental original.

3. **Arquitetura de Isolamento**:
   - Dados brutos, PDFs, blobs, extrações intermediárias, shards de tokens e checkpoints de modelos residem em `DATA_ROOT/` externo ao Git.
   - No Git ficam apenas código-fonte, configurações, locks e manifestos leves sanitizados.

4. **Separação de Plataformas**:
   - Extração nativa de PDFs e OCR seletivo por Apple Vision rodam exclusivamente no macOS usando Swift + PDFKit/Vision.
   - Treinamento em PyTorch e persistência em Google Drive rodam em ambiente Linux/Colab.
   - O ambiente Colab não executa ferramentas exclusivas do Mac.

---

## 2. Matriz de Propriedade de Arquivos (Ownership)

| Agente / Frente | Arquivos Exclusivos | Responsabilidade Principal |
|---|---|---|
| **Coordenador** | `README.md`, `AGENTS.md`, `.gitignore`, `pyproject.toml`, `requirements-*.lock`, `renv.lock`, `src/legislm/__init__.py`, `schemas/`, `configs/`, `R/inventory/common/`, `scripts/inventory.R`, `tests/fixtures/common/`, `tests/test_common_contracts.*` | Governança técnica, esquemas Arrow/JSON, configurações, fixtures de integração, locks e coordenação dos gates |
| **01 Câmara** | `R/inventory/camara/`, `scripts/inventory_camara.R`, `tests/inventory/camara/`, `docs/reports/01.md` | Descoberta, taxonomia e inventário histórico da Câmara (API v2, arquivos, portal, dossiês) |
| **10 Senado** | `R/inventory/senado/`, `scripts/inventory_senado.R`, `tests/inventory/senado/`, `docs/reports/10.md` | Descoberta, processos, fases, documentos, emendas e inventário histórico do Senado |
| **02 Downloads** | `R/download/`, `scripts/download.R`, `tests/download/`, `docs/reports/02.md` | Captura idempotente de originais por SHA-256, controle de tentativas e versionamento binário |
| **03 Extração** | `R/extraction/`, `scripts/extract.R`, `tests/extraction/`, `docs/reports/03.md` | Adaptador Swift Mac (PDFKit + Apple Vision), extração por página, seções e medição de qualidade |
| **04 Curadoria** | `R/curation/`, `scripts/curate.R`, `tests/curation/`, `docs/reports/04.md` | Limpeza, deduplicação exata/quase-duplicatas, detecção de containment, grafo global de famílias, splits e release Parquet |
| **05 Tokenizer** | `src/legislm/tokenization/`, `tests/tokenization/`, `docs/reports/05.md` | BPE byte-level treinado estritamente no split train, shards `.npy`, índice de janelas sem contaminação |
| **06 Modelo** | `src/legislm/model/`, `tests/model/`, `docs/reports/06.md` | Implementação PyTorch explícita de Transformer Decoder (estilo GPT educacional), sem HF Trainer nem pesos externos |
| **07 Treinamento** | `src/legislm/training/`, `tests/training/`, `docs/reports/07.md` | Loop de treinamento com AdamW, scheduler com warmup/decay, benchmark de VRAM/throughput, checkpoints recuperáveis |
| **08 Colab** | `src/legislm/colab/`, `notebooks/piloto_colab.ipynb`, `tests/colab/`, `docs/reports/08.md` | Preflight de hardware/saldo, staging em disco local, persistência verificada e retomada em nova sessão |
| **09 Avaliação** | `src/legislm/evaluation/`, `tests/evaluation/`, `docs/reports/09.md` | Avaliação rigorosa (NLL por byte comum, perplexidade identificada), geração controlada e relatório consolidado |

---

## 3. Portões de Qualidade (Gates)

O fluxo de trabalho avança sequencialmente por ondas de maturidade:

1. **Gate G0 (Fundação)**: Contratos, esquemas Arrow/JSON, configurações, fixtures canônicas (SYN001–SYN006), utilitários comuns em R e estrutura do pacote Python estabelecidos pelo Coordenador.
2. **Gate G1 (Inventário)**: Ambas as casas com todas as taxonomias e segmentos históricos descobertos e mapeados (01 e 10), sem cortes arbitrários de ano ou tipo.
3. **Gate G2 (Release Curada)**: Amostra ou lote processado com proveniência, integridade referencial 100%, zero vazamento entre splits por família, tipos e versões preservados (02, 03 e 04).
4. **Gate GH (Fechamento Histórico)**: Todos os segmentos históricos descobertos reconciliados com estados explícitos (completo, parcial, indisponível, pendente) com relatório e denominação clara.
5. **Gate G3 (Tokens)**: Tokenizer treinado exclusivamente em treino curado, round-trip exato verificado, janelas e máscaras de alvos geradas (05).
6. **Gate G4 (CPU/Modelo)**: Transformer explícito validado em CPU: invariância causal, tratamento de padding, teste de gradientes e memorização de lote sintético (06 e 07).
7. **Gate G5 (GPU/Persistência)**: Benchmark de GPU e persistência com validação de recuperação após sessão efêmera no Colab/Drive (07 e 08).
8. **Gate G6 (Entrega e Avaliação Final)**: Avaliação completa, geração registrada, integração ponta a ponta e relatório consolidado (09).

---

## 4. Instruções para Subagentes

Ao receber sua missão:
1. Leia seus arquivos de entrada obrigatórios indicados no prompt.
2. Não altere arquivos fora do seu escopo exclusivo.
3. Não presuma dados: use medições, logs reais e relatórios detalhados.
4. Salve seu relatório final em `docs/reports/<ID>.md` documentando comandos, evidências e resultados.
