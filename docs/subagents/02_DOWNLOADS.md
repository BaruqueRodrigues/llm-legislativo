# Frente 02 — Downloads históricos e proveniência

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Capturar toda fila de documentos digitais legislativos das duas casas e coleções, por segmentos/lotes retomáveis, preservando originais, versões e tentativas.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 e segmentos homologados/publicados de 01/10; G1 global acompanha descoberta completa. Lotes podem começar após publicação local verificada; GH exige todos segmentos previstos, não apenas um piloto.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Fila normalizada documents/collection_documents/proposition_documents/coverage_segments de 01/10; URLs alternativas/mapping/termos, configs rede/disco e DATA_ROOT externo.

**Saídas:** Blobs SHA256, fetch_attempts/document_versions/manifests por lote; estados/contagens por segmento para 03/04/GH e histórico de capturas mesmo se bytes compartilhados.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/download/, scripts/download.R, tests/download/, docs/reports/02.md.

**Interfaces:** Rscript scripts/download.R --config configs/data/history.yaml; consumir IDs/URLs de ambas casas sem alterar owners; marker/hashes por lote. Mudança binária na mesma URL gera versão observada, não necessariamente revisão legislativa.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Validar fila/termos/espaço e taxonomias; incluir emendas/pareceres/substitutivos/versões/diários/anais/dossiês disponíveis, sem filtro exclusivo de inicial/2024.
2. Implementar fila idempotente/leases, timeout/backoff/jitter/Retry-After e baixa concorrência por host; guardar toda tentativa, incluindo arquivos indisponíveis e links alternativos oficiais.
3. Download .part com requested/final URL/status/MIME/tamanho; validar magic/parser, rejeitar HTML200/zero/truncado como sucesso e preservar erro.
4. Blob imutável por SHA256, version_id/capturas, reuso de armazenamento com vínculos preservados. Mesmos bytes em Câmara/Senado/anais mantêm múltiplas origens.
5. Homologar lote heterogêneo pequeno e executar toda fila histórica em segmentos configurados, publicando apenas lotes verificados para 03; não interromper permanentemente após piloto.
6. Retentar conforme política e registrar estado final/pendência por candidato; propor URL/relação alternativa ao owner 01/10 via coordenador, sem alterar metadata de terceiro.
7. Reconciliar descobertos→obtidos→falhos/pendentes por casa/coleção/ano/tipo; contribuir GH distinguindo completo disponível de fechado com lacunas.

## Aceitação e verificações

**Aceitação:** Todo arquivo aceito com origem/data/hash/formato; retomada/retries corretos; nenhuma categoria descartada como material posterior; todas capturas e lacunas preservadas; contador de lote não se apresenta como cobertura histórica total.

**Verificações:** HTTP200HTML/redirect/truncado/404/429/5xx/timeout, versões na mesmaURL, mesmo hash nas duas casas, .part abandonado, quotas/retomada/idempotência e contagem por segmento; pequeno smoke real antes da escala.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não extrair/curar/tokenizar, não contornar401/403 ou alterar inventários. Captura histórica configurada é escopo desta frente lançada; downloads em massa não são executados nesta sessão de planejamento. Não inferir classe/papel pela extensão.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/02.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 02 — Downloads históricos e proveniência do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Capturar toda fila de documentos digitais legislativos das duas casas e coleções, por segmentos/lotes retomáveis, preservando originais, versões e tentativas.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0 e segmentos homologados/publicados de 01/10; G1 global acompanha descoberta completa. Lotes podem começar após publicação local verificada; GH exige todos segmentos previstos, não apenas um piloto.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Fila normalizada documents/collection_documents/proposition_documents/coverage_segments de 01/10; URLs alternativas/mapping/termos, configs rede/disco e DATA_ROOT externo.

**Saídas:** Blobs SHA256, fetch_attempts/document_versions/manifests por lote; estados/contagens por segmento para 03/04/GH e histórico de capturas mesmo se bytes compartilhados.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/download/, scripts/download.R, tests/download/, docs/reports/02.md.

**Interfaces:** Rscript scripts/download.R --config configs/data/history.yaml; consumir IDs/URLs de ambas casas sem alterar owners; marker/hashes por lote. Mudança binária na mesma URL gera versão observada, não necessariamente revisão legislativa.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Validar fila/termos/espaço e taxonomias; incluir emendas/pareceres/substitutivos/versões/diários/anais/dossiês disponíveis, sem filtro exclusivo de inicial/2024.
2. Implementar fila idempotente/leases, timeout/backoff/jitter/Retry-After e baixa concorrência por host; guardar toda tentativa, incluindo arquivos indisponíveis e links alternativos oficiais.
3. Download .part com requested/final URL/status/MIME/tamanho; validar magic/parser, rejeitar HTML200/zero/truncado como sucesso e preservar erro.
4. Blob imutável por SHA256, version_id/capturas, reuso de armazenamento com vínculos preservados. Mesmos bytes em Câmara/Senado/anais mantêm múltiplas origens.
5. Homologar lote heterogêneo pequeno e executar toda fila histórica em segmentos configurados, publicando apenas lotes verificados para 03; não interromper permanentemente após piloto.
6. Retentar conforme política e registrar estado final/pendência por candidato; propor URL/relação alternativa ao owner 01/10 via coordenador, sem alterar metadata de terceiro.
7. Reconciliar descobertos→obtidos→falhos/pendentes por casa/coleção/ano/tipo; contribuir GH distinguindo completo disponível de fechado com lacunas.

## Aceitação e verificações

**Aceitação:** Todo arquivo aceito com origem/data/hash/formato; retomada/retries corretos; nenhuma categoria descartada como material posterior; todas capturas e lacunas preservadas; contador de lote não se apresenta como cobertura histórica total.

**Verificações:** HTTP200HTML/redirect/truncado/404/429/5xx/timeout, versões na mesmaURL, mesmo hash nas duas casas, .part abandonado, quotas/retomada/idempotência e contagem por segmento; pequeno smoke real antes da escala.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não extrair/curar/tokenizar, não contornar401/403 ou alterar inventários. Captura histórica configurada é escopo desta frente lançada; downloads em massa não são executados nesta sessão de planejamento. Não inferir classe/papel pela extensão.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/02.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
