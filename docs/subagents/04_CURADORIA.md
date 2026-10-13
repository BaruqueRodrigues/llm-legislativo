# Frente 04 — Curadoria histórica, deduplicação e splits

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Consolidar todos tipos/anos/casas/coleções em releases auditadas e deduplicadas, com famílias globais e splits anteriores ao tokenizer.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 e lotes reais 01/10→02→03 aprovados, mapa de cobertura/permissões/auditoria; releases incrementais G2 possíveis, GH requer todo acervo descoberto/estados reconciliados.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Proposições/processos/aliases/autorias/temas/collections/coverage/relações/documentos/versões/páginas/seções/revisões de ambas casas; limpeza/dedup/splits aprovados e DATA_ROOT.

**Saídas:** curated_documents/bridges/cleaning_events/dedup_pairs/splits/release_manifest/COMPLETE; cobertura histórica e qualidade por casa/fonte/coleção/ano/tipo; release parcial ou histórica claramente identificada paraG2/GH/05.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/curation/, scripts/curate.R, tests/curation/, docs/reports/04.md.

**Interfaces:** Rscript scripts/curate.R --config configs/curation/history.yaml; fronteira Parquet2.0 R→Python. Documento sem processo/data pode ser aceito em group_hash com origem/texto verificados; inicial+justificativa não é critério obrigatório para emenda/parecer/etc.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Reconciliar universo histórico e cadeia fonte→documento→captura→versão→página→texto; classificar elegibilidade por origem/qualidade/uso de documento, sem filtro tipo/ano inicial. Completude de justificativa é métrica específica de inicial, não exclusão das demais peças.
2. Limpeza mínima com hashes/logs/diffs; preservar conteúdo substantivo, títulos/seções/citações normativas e desconhecidos legíveis, caso/acentos/números/negações.
3. Dedup binária/exata textual e candidatos próximos com diff/revisão; preservar variantes substantivas e todas origens. Peça em dossiê/diário/outra casa não vira repetição invisível: usar índice de passagens/containment, não apenas Jaccard global. Segmentar volume composto em unidades editoriais com logical_unit_id/spans/intervalo de data e composição versionada; não incluir volume integral mais os mesmos segmentos, nem unir unidades independentes só por container.
4. Grafo global entre anos/casas/coleções por aliases/versões/continuidade/fases/duplicações; mention/citação genérica não liga todos processos. Auditar componentes grandes antes dos splits.
5. Group_hash por família/seed metas 80/10/10; datas nulas preservadas nesse corpus, temporal_purged usa datas próprias do documento/versão e intervalos, sem texto 2026 em treino 1995. Famílias novas exigem recalcular splits antes da próxima release/tokenizer.
6. Auditar cobertura/qualidade/dedup/contaminação por estrato e publicar bytes/famílias/tipos por split; manifesto identifica parcial/closed_with_gaps/complete_discovered e pendências, sem confundir um lote com GH.
7. Publicar release imutável/COMPLETE e entregar ao coordenador para G2/GH; todos itens representantes elegíveis seguem para 05, com categorias/versões preservadas.

## Aceitação e verificações

**Aceitação:** Zero PK/FK inválida/dup exata elegível/família dividida; nenhuma exclusão automática por tipo/ano/data/autoria/ausência de justificativa inaplicável. Proveniência/hashes/permissões/auditoria, cobertura e versão explícitas; GH com relatório de todo acervo descoberto.

**Verificações:** 2×2 joins, crosshouse/crossyear aliases/versões, peça reproduzida, negação/valor, diário menciona muitos PLs sem bind, documento 2026 / processo 1995, sem data/sem processo, candidatos próximos e componentes gigantes; schemas/hashes/COMPLETE e contagens/cobertura.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não treinar tokenizer, mudar outputs01/10/02/03 ou ajustar split pela loss/teste. Não excluir material posterior para cumprir contrato antigo. Arquivos/configs/compartilhados são do coordenador; versões novas após mudança de graph/corpus.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/04.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 04 — Curadoria histórica, deduplicação e splits do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Consolidar todos tipos/anos/casas/coleções em releases auditadas e deduplicadas, com famílias globais e splits anteriores ao tokenizer.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 e lotes reais 01/10→02→03 aprovados, mapa de cobertura/permissões/auditoria; releases incrementais G2 possíveis, GH requer todo acervo descoberto/estados reconciliados.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Proposições/processos/aliases/autorias/temas/collections/coverage/relações/documentos/versões/páginas/seções/revisões de ambas casas; limpeza/dedup/splits aprovados e DATA_ROOT.

**Saídas:** curated_documents/bridges/cleaning_events/dedup_pairs/splits/release_manifest/COMPLETE; cobertura histórica e qualidade por casa/fonte/coleção/ano/tipo; release parcial ou histórica claramente identificada paraG2/GH/05.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/curation/, scripts/curate.R, tests/curation/, docs/reports/04.md.

**Interfaces:** Rscript scripts/curate.R --config configs/curation/history.yaml; fronteira Parquet2.0 R→Python. Documento sem processo/data pode ser aceito em group_hash com origem/texto verificados; inicial+justificativa não é critério obrigatório para emenda/parecer/etc.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Reconciliar universo histórico e cadeia fonte→documento→captura→versão→página→texto; classificar elegibilidade por origem/qualidade/uso de documento, sem filtro tipo/ano inicial. Completude de justificativa é métrica específica de inicial, não exclusão das demais peças.
2. Limpeza mínima com hashes/logs/diffs; preservar conteúdo substantivo, títulos/seções/citações normativas e desconhecidos legíveis, caso/acentos/números/negações.
3. Dedup binária/exata textual e candidatos próximos com diff/revisão; preservar variantes substantivas e todas origens. Peça em dossiê/diário/outra casa não vira repetição invisível: usar índice de passagens/containment, não apenas Jaccard global. Segmentar volume composto em unidades editoriais com logical_unit_id/spans/intervalo de data e composição versionada; não incluir volume integral mais os mesmos segmentos, nem unir unidades independentes só por container.
4. Grafo global entre anos/casas/coleções por aliases/versões/continuidade/fases/duplicações; mention/citação genérica não liga todos processos. Auditar componentes grandes antes dos splits.
5. Group_hash por família/seed metas 80/10/10; datas nulas preservadas nesse corpus, temporal_purged usa datas próprias do documento/versão e intervalos, sem texto 2026 em treino 1995. Famílias novas exigem recalcular splits antes da próxima release/tokenizer.
6. Auditar cobertura/qualidade/dedup/contaminação por estrato e publicar bytes/famílias/tipos por split; manifesto identifica parcial/closed_with_gaps/complete_discovered e pendências, sem confundir um lote com GH.
7. Publicar release imutável/COMPLETE e entregar ao coordenador para G2/GH; todos itens representantes elegíveis seguem para 05, com categorias/versões preservadas.

## Aceitação e verificações

**Aceitação:** Zero PK/FK inválida/dup exata elegível/família dividida; nenhuma exclusão automática por tipo/ano/data/autoria/ausência de justificativa inaplicável. Proveniência/hashes/permissões/auditoria, cobertura e versão explícitas; GH com relatório de todo acervo descoberto.

**Verificações:** 2×2 joins, crosshouse/crossyear aliases/versões, peça reproduzida, negação/valor, diário menciona muitos PLs sem bind, documento 2026 / processo 1995, sem data/sem processo, candidatos próximos e componentes gigantes; schemas/hashes/COMPLETE e contagens/cobertura.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não treinar tokenizer, mudar outputs01/10/02/03 ou ajustar split pela loss/teste. Não excluir material posterior para cumprir contrato antigo. Arquivos/configs/compartilhados são do coordenador; versões novas após mudança de graph/corpus.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/04.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
