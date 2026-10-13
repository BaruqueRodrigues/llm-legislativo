# Frente 01 — Inventário histórico da Câmara

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Descobrir e inventariar todos tipos/anos/coleções legislativas digitais da Câmara, reconciliando API, arquivos, portal, dossiês e acervos históricos.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 com schema 2.0/identidades/taxonomias/cobertura e interface common preparados. Independente de 10 Senado, modelo e coletores produtivos; amostra de homologação usa ferramentas disponíveis e temporário.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Documentação oficial APIv2, catálogo anual, fichas/seções/árvore/dossiês e índices de Arquivo Histórico/diários/anais/transcrições; configs de descoberta all_available, snapshot_cutoff e fixtures comuns.

**Saídas:** source_collections, legislative_types, coverage_segments e entity_aliases Câmara; snapshots/proposições/autores/document_authors/temas/relações/documentos/collection_documents; diferenças API↔portal↔catálogos e fila completa com cobertura/lacunas. Publicação por segmento para 02 e coordenador/G1/GH.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/inventory/camara/, scripts/inventory_camara.R, tests/inventory/camara/, docs/reports/01.md.

**Interfaces:** CLI futura Rscript scripts/inventory_camara.R --config configs/data/history.yaml; Parquet/schemas comuns. Source namespace e codTipo/sigla/nome são preservados; sem whitelist. Agregação scripts/inventory.R é do coordenador, não do 01. Portal-only ID sobrevive mesmo se API retornar404.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Guardar documentação/termos e snapshot; descobrir fontes/coleções digitais e anos/períodos enumerados, sem primeiro ano universal nem parar na primeira lacuna.
2. Enumerar referência de tipos, preservando codTipo+sigla+nome/agrupamentos/legados; não reduzir 544 registros do catálogo a suposta contagem de textos ou siglas únicas.
3. Implementar inventário de registros por estratégias explícitas apropriadas à fonte e paginação, cobrindo catálogo anual/períodos, casos undated/ano 0 e todas classes; apresentação/numeração/tramitação/publicação ficam separadas.
4. Percorrer detalhe/autores/temas/relacionadas/tramitações e seções oficiais de ficha/árvore/avulsos/emendas/pareceres/substitutivos/votos/redações/dossiês. Reconciliação inclui peça disponível no portal e ausente API.
5. Inventariar objetos digitais em coleções históricas oficiais por volume/edição/código de referência; descrição sem arquivo é lacuna, não documento baixado. Não inferir identidade de proposição a partir de menção incidental.
6. Fazer pequena amostra temporária de homologação por épocas/tipos/métodos, sem depender da implementação02/03; usar PDFKit/Vision para leitura quando necessário, registrando limites e não estimando OCR anual sem amostra.
7. Publicar segmentos completos/contagens/estados para 02/coordenador, classificar diferenças e cobrir todos segmentos descobertos até snapshot; entregar parte Câmara de G1/GH sem afirmar cobertura Senado.

## Aceitação e verificações

**Aceitação:** Catálogos/segmentos/tipos preservados, nenhuma exclusão PL/2024/autor/tema/data faltante; estados/paginação e diferenças auditados; todos candidatos com origem/papel/mapping/cobertura; DVT portal-only e arquivos antigos preservados. G1/GH global depende também de 10 e integração.

**Verificações:** Mocks de paginação/retries/vazio e lacunas de catálogo, sigla duplicada codTipo distinto/ausente, registro só no portal com 404 na API, evento 2026 sobre projeto 1988, documento sem data/número/processo e coleções históricas. Smoke pequeno oficial; esquema/FKs/contagens e reconciliação por fonte/coleção/ano/tipo.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não implementar download/extração em escala/curadoria/modelo ou adapter Senado/common. Inspeção amostral autorizada para homologação, outputs temporários. Nenhuma promessa de íntegros físicos não digitalizados; não omitir ano/tipo difícil para passar gate.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/01.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 01 — Inventário histórico da Câmara do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Descobrir e inventariar todos tipos/anos/coleções legislativas digitais da Câmara, reconciliando API, arquivos, portal, dossiês e acervos históricos.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 com schema 2.0/identidades/taxonomias/cobertura e interface common preparados. Independente de 10 Senado, modelo e coletores produtivos; amostra de homologação usa ferramentas disponíveis e temporário.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Documentação oficial APIv2, catálogo anual, fichas/seções/árvore/dossiês e índices de Arquivo Histórico/diários/anais/transcrições; configs de descoberta all_available, snapshot_cutoff e fixtures comuns.

**Saídas:** source_collections, legislative_types, coverage_segments e entity_aliases Câmara; snapshots/proposições/autores/document_authors/temas/relações/documentos/collection_documents; diferenças API↔portal↔catálogos e fila completa com cobertura/lacunas. Publicação por segmento para 02 e coordenador/G1/GH.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/inventory/camara/, scripts/inventory_camara.R, tests/inventory/camara/, docs/reports/01.md.

**Interfaces:** CLI futura Rscript scripts/inventory_camara.R --config configs/data/history.yaml; Parquet/schemas comuns. Source namespace e codTipo/sigla/nome são preservados; sem whitelist. Agregação scripts/inventory.R é do coordenador, não do 01. Portal-only ID sobrevive mesmo se API retornar404.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Guardar documentação/termos e snapshot; descobrir fontes/coleções digitais e anos/períodos enumerados, sem primeiro ano universal nem parar na primeira lacuna.
2. Enumerar referência de tipos, preservando codTipo+sigla+nome/agrupamentos/legados; não reduzir 544 registros do catálogo a suposta contagem de textos ou siglas únicas.
3. Implementar inventário de registros por estratégias explícitas apropriadas à fonte e paginação, cobrindo catálogo anual/períodos, casos undated/ano 0 e todas classes; apresentação/numeração/tramitação/publicação ficam separadas.
4. Percorrer detalhe/autores/temas/relacionadas/tramitações e seções oficiais de ficha/árvore/avulsos/emendas/pareceres/substitutivos/votos/redações/dossiês. Reconciliação inclui peça disponível no portal e ausente API.
5. Inventariar objetos digitais em coleções históricas oficiais por volume/edição/código de referência; descrição sem arquivo é lacuna, não documento baixado. Não inferir identidade de proposição a partir de menção incidental.
6. Fazer pequena amostra temporária de homologação por épocas/tipos/métodos, sem depender da implementação02/03; usar PDFKit/Vision para leitura quando necessário, registrando limites e não estimando OCR anual sem amostra.
7. Publicar segmentos completos/contagens/estados para 02/coordenador, classificar diferenças e cobrir todos segmentos descobertos até snapshot; entregar parte Câmara de G1/GH sem afirmar cobertura Senado.

## Aceitação e verificações

**Aceitação:** Catálogos/segmentos/tipos preservados, nenhuma exclusão PL/2024/autor/tema/data faltante; estados/paginação e diferenças auditados; todos candidatos com origem/papel/mapping/cobertura; DVT portal-only e arquivos antigos preservados. G1/GH global depende também de 10 e integração.

**Verificações:** Mocks de paginação/retries/vazio e lacunas de catálogo, sigla duplicada codTipo distinto/ausente, registro só no portal com 404 na API, evento 2026 sobre projeto 1988, documento sem data/número/processo e coleções históricas. Smoke pequeno oficial; esquema/FKs/contagens e reconciliação por fonte/coleção/ano/tipo.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não implementar download/extração em escala/curadoria/modelo ou adapter Senado/common. Inspeção amostral autorizada para homologação, outputs temporários. Nenhuma promessa de íntegros físicos não digitalizados; não omitir ano/tipo difícil para passar gate.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/01.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
