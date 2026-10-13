# Frente 09 — Avaliação e integração final

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Implementar avaliação comparável e geração registrada; auditar ponta a ponta e fechar relatório do MVP sem confundir funcionamento com evidência científica.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0, interfaces de modelo/treino/dataset estáveis; pode construir métricas/fixtures na onda 3. Resultados reais dependem de G2/G3/G4; integração final e G6 somente após G5. G6 inclui GH e release histórica; dados Senado/versões posteriores já são escopo inicial.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Releases/splits/tokenizer/tokens, config/ambiente/checkpoints/métricas de runs 07/08, prompts fixos aprovados e byte_nll_v1 de VALIDACAO; relatórios 01–08 e 10, coverage_segments/GH.

**Saídas:** CLI evaluate/generate, métricas ponderadas/token loss/PPL identificada/byte NLL, resultados por família/estrato, gerações versionadas, relatório final com cobertura/qualidade/curvas/retomada/limites; checklist de integração e falhas para os proprietários.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/evaluation/, tests/evaluation/, docs/reports/09.md. Resumos de integração neste relatório; mudanças de docs normativos/README pertencem ao coordenador.

**Interfaces:** python -m legislm.evaluation.cli evaluate --run-id RUN_ID --split validation e generate --run-id RUN_ID --prompts configs/evaluation/prompts.json; usar GPT/logits/checkpoint e reader de 05, sem segundo modelo/tokenizer/trainer. byte_nll_v1 usa mesmos bytes/segmentos em todos candidatos.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Implementar eval/no_grad com soma NLL/alvos válidos, EOS e texto separados, sem média não ponderada de batches; métricas/curvas da trajetória ativa com denominadores/versões, excluindo eventos abandoned e identificando segment_id/rollback.
2. Implementar byte_nll_v1: lista/text hashes comuns, K congelado por train/capacidade mínima, segmentos UTF-8 não sobrepostos, BOS prefixo, pontuar todos tokens de texto sem EOS/PAD e dividir por bytes exatos. Falhar se truncamento ou round-trip desigual.
3. Criar geração via modelo 06 com prompts fixos e parâmetros/seed/checkpoint identificados; salvar resultados no RUN_ROOT persistente. Não ajustar prompts pelo teste.
4. Auditar cobertura fonte×coleção×casa×ano×tipo e consumo do sampler; distinguir release parcial/histórica e modelo smoke. G6 só com GH; reporte generalização por classe/época/casa, sem usar ausência de justificativa como erro universal.
5. Auditar integridade/cobertura/anti-vazamento/IDs e consumos, sem rerodar checks já aprovados quando nada mudou; registrar indisponíveis/falhas reais.
6. Após G5, ler artefatos de treino curto e retomada em nova sessão, comparar continuidade/curvas/ambientes e completar relatório G6. Encaminhar defeitos à camada proprietária por coordenação; não corrigi-los em arquivos alheios.
7. Distinguir MVP funcional de experimentos posteriores; propor desenho de tokenizer/escala/composição/representações com famílias, budgets e labels independentes, sem executá-lo.

## Aceitação e verificações

**Aceitação:** Loss corretamente ponderada, medidas com tokenizer/unidade/protocolo identificados e sem truncamento/contaminação; gerações reprodutíveis por config; persistência/retomada respaldadas por artefatos; relatório final não omite falha bloqueante ou afirma convergência/conhecimento sem evidência.

**Verificações:** NLL manual em fixture, EOS/PAD exclusões, ponderação bytes e UTF-8/code points, mesmos segmentos com tokenizers sintéticos de granularidades distintas, contexto insuficiente falha, invariância de eval dropout off. Auditoria cruzada de manifests/reports e verificação de checkpoint/artefatos remotos já produzida.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não usar PPL bruta entre tokenizers como ranking, não abrir teste para tuning exploratório, não tratar regex do artigo como ouro, não editar fontes/modelo/loop/Drive/contratos. Não lançar agentes extras ou experimentos científicos adicionais automaticamente.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/09.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 09 — Avaliação e integração final do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Implementar avaliação comparável e geração registrada; auditar ponta a ponta e fechar relatório do MVP sem confundir funcionamento com evidência científica.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0, interfaces de modelo/treino/dataset estáveis; pode construir métricas/fixtures na onda 3. Resultados reais dependem de G2/G3/G4; integração final e G6 somente após G5. G6 inclui GH e release histórica; dados Senado/versões posteriores já são escopo inicial.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Releases/splits/tokenizer/tokens, config/ambiente/checkpoints/métricas de runs 07/08, prompts fixos aprovados e byte_nll_v1 de VALIDACAO; relatórios 01–08 e 10, coverage_segments/GH.

**Saídas:** CLI evaluate/generate, métricas ponderadas/token loss/PPL identificada/byte NLL, resultados por família/estrato, gerações versionadas, relatório final com cobertura/qualidade/curvas/retomada/limites; checklist de integração e falhas para os proprietários.

## Responsabilidade e interfaces

**Arquivos exclusivos:** src/legislm/evaluation/, tests/evaluation/, docs/reports/09.md. Resumos de integração neste relatório; mudanças de docs normativos/README pertencem ao coordenador.

**Interfaces:** python -m legislm.evaluation.cli evaluate --run-id RUN_ID --split validation e generate --run-id RUN_ID --prompts configs/evaluation/prompts.json; usar GPT/logits/checkpoint e reader de 05, sem segundo modelo/tokenizer/trainer. byte_nll_v1 usa mesmos bytes/segmentos em todos candidatos.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Implementar eval/no_grad com soma NLL/alvos válidos, EOS e texto separados, sem média não ponderada de batches; métricas/curvas da trajetória ativa com denominadores/versões, excluindo eventos abandoned e identificando segment_id/rollback.
2. Implementar byte_nll_v1: lista/text hashes comuns, K congelado por train/capacidade mínima, segmentos UTF-8 não sobrepostos, BOS prefixo, pontuar todos tokens de texto sem EOS/PAD e dividir por bytes exatos. Falhar se truncamento ou round-trip desigual.
3. Criar geração via modelo 06 com prompts fixos e parâmetros/seed/checkpoint identificados; salvar resultados no RUN_ROOT persistente. Não ajustar prompts pelo teste.
4. Auditar cobertura fonte×coleção×casa×ano×tipo e consumo do sampler; distinguir release parcial/histórica e modelo smoke. G6 só com GH; reporte generalização por classe/época/casa, sem usar ausência de justificativa como erro universal.
5. Auditar integridade/cobertura/anti-vazamento/IDs e consumos, sem rerodar checks já aprovados quando nada mudou; registrar indisponíveis/falhas reais.
6. Após G5, ler artefatos de treino curto e retomada em nova sessão, comparar continuidade/curvas/ambientes e completar relatório G6. Encaminhar defeitos à camada proprietária por coordenação; não corrigi-los em arquivos alheios.
7. Distinguir MVP funcional de experimentos posteriores; propor desenho de tokenizer/escala/composição/representações com famílias, budgets e labels independentes, sem executá-lo.

## Aceitação e verificações

**Aceitação:** Loss corretamente ponderada, medidas com tokenizer/unidade/protocolo identificados e sem truncamento/contaminação; gerações reprodutíveis por config; persistência/retomada respaldadas por artefatos; relatório final não omite falha bloqueante ou afirma convergência/conhecimento sem evidência.

**Verificações:** NLL manual em fixture, EOS/PAD exclusões, ponderação bytes e UTF-8/code points, mesmos segmentos com tokenizers sintéticos de granularidades distintas, contexto insuficiente falha, invariância de eval dropout off. Auditoria cruzada de manifests/reports e verificação de checkpoint/artefatos remotos já produzida.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não usar PPL bruta entre tokenizers como ranking, não abrir teste para tuning exploratório, não tratar regex do artigo como ouro, não editar fontes/modelo/loop/Drive/contratos. Não lançar agentes extras ou experimentos científicos adicionais automaticamente.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/09.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
