# Frente 10 — Inventário histórico do Senado

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Descobrir todos tipos/anos/processos/documentos e coleções históricas disponíveis no Senado, incluindo encerrados, fases, emendas e versões posteriores.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 com contrato 2.0/interface common preparados. Pode trabalhar em paralelo a 01 em diretórios/snapshots próprios. Coleta produtiva de arquivos não é responsabilidade desta frente.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** OpenAPI atual /dadosabertos/processo e documentação oficial pesquisa/catálogo/unificação/anais/diários; configs all_available/snapshot_cutoff e fixtures comuns.

**Saídas:** source_collections/legislative_types/coverage_segments/aliases Senado; processos normalizados como propositions, process_phases/document_phases, documentos/emendas/autorias/assuntos/collection_documents/relações e snapshots; fila histórica e relatório de lacunas/controles para 02/G1/GH.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/inventory/senado/, scripts/inventory_senado.R, tests/inventory/senado/, docs/reports/10.md.

**Interfaces:** CLI futura Rscript scripts/inventory_senado.R --config configs/data/history.yaml; mesmos Parquet/semântica de 01. IDs processo e codigoMateria legado usam namespaces distintos/aliases verificados; fase/órgão/numeração original preservados. Não inventar page/limit sem suporte documentado. Agregador common é do coordenador.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Reler OpenAPI/termos/deprecações e registrar snapshots; descobrir coleções/intervalos em pesquisa/índices oficiais, sem primeiro ano universal nem supor cobertura API desde início dos Anais.
2. Consultar /processo/siglas, classes, documento/tipos e tipos-conteudo, incluindo tipos encerrados e nomenclaturas legadas, com mapping original-normalizado explícito.
3. Inventariar atuais+encerrados por ano/data/períodos explicitamente definidos; validar comportamento S/N e formatos/limites. Default tramitando/recentes não satisfaz histórico; verificar completude/contagens e subdividir filtros sem inventar paginação.
4. Para cada processo percorrer TODOS documentos e emendas/subemendas/fases relacionadas; complementar listagem documental por períodos e reconciliar. Documentos não ficam limitados ao ano inicial do processo.
5. Preservar idProcesso/codigoMateria/colegiado/fase/antecessoras/sucessoras, publicando process_phases e document_phases conforme contrato; aliases distinguem fase de processo, autoria documental e relações Câmara↔Senado com evidência. Não fundir só pelo número/ano ou string da sigla.
6. Inventariar Anais/Diários e demais acervos legislativos oficiais disponíveis por edição/volume/objeto; descrição sem arquivo é lacuna. Fazer amostra limitada de homologação temporal/tipológica com ferramentas existentes.
7. Publicar segmentos/filas/snapshots e relatório casa×fonte×coleção×ano×tipo, explicar consultas vazias/limitações; entregar parte Senado de G1/GH ao coordenador e 02.

## Aceitação e verificações

**Aceitação:** Encerrados/legados/documentos posteriores incluídos, defaults/intervalos controlados, identidades/fases/aliases rastreáveis, todos segmentos descobertos com estado e lacunas; nenhum ano inicial/contagem/completude presumida. Sem colisão ou escrita nos arquivos01/common.

**Verificações:** Mocks de default recente/tramitando, S/N, datas máximas, 429/503/deprecações, documento posterior à apresentação, emenda/subemenda/fase e ID processo vs legado. Pequeno smoke oficial de formatos/contagens/coleções; Parquet e FKs da publicação.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não editar01/agregador comum nem baixar acervo integral nesta missão de inventário; amostra limitada é permitida. Não depender de rotas deprecated sem validar substitutos, não contornar controles, não alegar /processo completo desde 1826 por faixa dos Anais.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/10.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 10 — Inventário histórico do Senado do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Descobrir todos tipos/anos/processos/documentos e coleções históricas disponíveis no Senado, incluindo encerrados, fases, emendas e versões posteriores.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 com contrato 2.0/interface common preparados. Pode trabalhar em paralelo a 01 em diretórios/snapshots próprios. Coleta produtiva de arquivos não é responsabilidade desta frente.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** OpenAPI atual /dadosabertos/processo e documentação oficial pesquisa/catálogo/unificação/anais/diários; configs all_available/snapshot_cutoff e fixtures comuns.

**Saídas:** source_collections/legislative_types/coverage_segments/aliases Senado; processos normalizados como propositions, process_phases/document_phases, documentos/emendas/autorias/assuntos/collection_documents/relações e snapshots; fila histórica e relatório de lacunas/controles para 02/G1/GH.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/inventory/senado/, scripts/inventory_senado.R, tests/inventory/senado/, docs/reports/10.md.

**Interfaces:** CLI futura Rscript scripts/inventory_senado.R --config configs/data/history.yaml; mesmos Parquet/semântica de 01. IDs processo e codigoMateria legado usam namespaces distintos/aliases verificados; fase/órgão/numeração original preservados. Não inventar page/limit sem suporte documentado. Agregador common é do coordenador.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Reler OpenAPI/termos/deprecações e registrar snapshots; descobrir coleções/intervalos em pesquisa/índices oficiais, sem primeiro ano universal nem supor cobertura API desde início dos Anais.
2. Consultar /processo/siglas, classes, documento/tipos e tipos-conteudo, incluindo tipos encerrados e nomenclaturas legadas, com mapping original-normalizado explícito.
3. Inventariar atuais+encerrados por ano/data/períodos explicitamente definidos; validar comportamento S/N e formatos/limites. Default tramitando/recentes não satisfaz histórico; verificar completude/contagens e subdividir filtros sem inventar paginação.
4. Para cada processo percorrer TODOS documentos e emendas/subemendas/fases relacionadas; complementar listagem documental por períodos e reconciliar. Documentos não ficam limitados ao ano inicial do processo.
5. Preservar idProcesso/codigoMateria/colegiado/fase/antecessoras/sucessoras, publicando process_phases e document_phases conforme contrato; aliases distinguem fase de processo, autoria documental e relações Câmara↔Senado com evidência. Não fundir só pelo número/ano ou string da sigla.
6. Inventariar Anais/Diários e demais acervos legislativos oficiais disponíveis por edição/volume/objeto; descrição sem arquivo é lacuna. Fazer amostra limitada de homologação temporal/tipológica com ferramentas existentes.
7. Publicar segmentos/filas/snapshots e relatório casa×fonte×coleção×ano×tipo, explicar consultas vazias/limitações; entregar parte Senado de G1/GH ao coordenador e 02.

## Aceitação e verificações

**Aceitação:** Encerrados/legados/documentos posteriores incluídos, defaults/intervalos controlados, identidades/fases/aliases rastreáveis, todos segmentos descobertos com estado e lacunas; nenhum ano inicial/contagem/completude presumida. Sem colisão ou escrita nos arquivos01/common.

**Verificações:** Mocks de default recente/tramitando, S/N, datas máximas, 429/503/deprecações, documento posterior à apresentação, emenda/subemenda/fase e ID processo vs legado. Pequeno smoke oficial de formatos/contagens/coleções; Parquet e FKs da publicação.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não editar01/agregador comum nem baixar acervo integral nesta missão de inventário; amostra limitada é permitida. Não depender de rotas deprecated sem validar substitutos, não contornar controles, não alegar /processo completo desde 1826 por faixa dos Anais.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/10.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
