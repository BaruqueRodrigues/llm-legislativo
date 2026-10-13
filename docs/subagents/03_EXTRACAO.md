# Frente 03 — Extração nativa Mac e OCR Apple Vision

Versão: 2.0.0; revisão: 2026-10-07. Instrução para lançamento futuro; nesta sessão só planejamento. Copie a seção “Prompt completo” para iniciar; não é preciso reenviar conversa.

## Missão e contexto

Extrair os documentos de todos tipos/épocas por página no Mac, preservando conteúdo/estrutura e usando PDFKit + Vision seletivo com velocidade/qualidade medidas.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0, interface02 e arquivos verificados; fixtures bastam para desenvolvimento. Mac/toolchain/Vision/idiomas reais verificados. Tesseract/Poppler são opcionais, não bloqueiam caminho principal.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Blobs/versões/capturas e tipos/coleções de 01/10/02; configs extraction/perfil Mac, amostra por casa/época/tipo e originais digitais/scan/mistos/manuscritos quando disponíveis.

**Saídas:** Adaptador Swift versionado em R/extraction/native/macos; extraction_runs/pages/sections/quality_reviews e observações de layout/proveniência; textos por todos papéis, benchmark e qualidade para 04/GH.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/extraction/, scripts/extract.R, tests/extraction/, docs/reports/03.md.

**Interfaces:** Rscript scripts/extract.R --config configs/extraction/history.yaml; R chama Swift/PDFKit/Vision, registra macOS/build/SDK/compiler/helperhash/revision/mode/idioma/renderização/tempo. Outputs seguem contrato 2.0; helper da skill é referência, não interface Parquet pronta.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Validar hashes/formatos, criar preflight Swift/PDFKit/Vision e consultar pt-BR nos modos fast/accurate; não instalar Tesseract por padrão nem fazer extração no Colab.
2. Implementar adaptador por página com PDFKit primeiro e métricas de texto; OCR Vision só onde camada nativa não servir. Preservar original e registrar engine/layout/qualidade/tempo/hash.
3. Fixar renderização/correção linguística/idioma e comparar fast/accurate nas mesmas imagens; optional Tesseract se disponível. Separar compilação/warmup/render/recognition, medir páginas/s,p50/p95/memória e CER/WER em amostra; escolher perfil por qualidade e velocidade observadas.
4. Tratar scan/misto/colunas/tabelas sem duplicar nativo+OCR ou inventar texto. Accurate é candidato/retry quando fast falhar; manuscrito histórico pode ficar review/quarantine com razão.
5. Identificar seções apropriadas: articulado/justificativa/exposição, emenda, relatório/fundamentação/parecer/voto/substitutivo/redação, sessão/discurso/anais/diário/anexos. Preservar texto legível unknown; não exigir Art.1º ou justificativa de todas categorias.
6. Auditar amostra aleatória/suplementar de ambas casas/épocas/tipos, transcrições CER/WER e erros jurídicos conforme VALIDACAO; qualidade humana não pode ser fabricada por confiança automática.
7. Publicar lotes completos e estatísticas/pendências por segmento a 04/coordenador, executar todo acervo verificado sob backpressure/retomada após homologação. Atualização OS/helper ganha nova extração/perfil, sem sobrescrever outputs.

## Aceitação e verificações

**Aceitação:** Páginas e conteúdo de todas categorias contabilizados; pt-BR/mode/revision/host e hashes registrados; OCR seletivo e sem duplicação; benchmark declarado realizado ou indisponível, sem acelerar ficticiamente; zero erro substantivo conhecido em itens aceitos auditados.

**Verificações:** Fixtures nativo/scan/misto/capa/corrompido/colunas/tabelas, parecer sem articulado, emenda sem justificativa, EMI, diário/anais e variantes normativas. Benchmark pequeno e revisão visual/transcrição real; thresholds proporcionais por perfil/época. Helper --accurate muda outros fatores: isolá-los.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não fazer splits/dedup, não lowercase/corrigir norma por palpite, não alterar binários/inventários. Framework Mac não roda em Linux Colab; fallback depende de medição/permissão de instalação do ambiente, sem impedir planejamento. Habilidade pdf-to-markdown foi lida; adaptar logic sem supor Markdown completo cumpre schema.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/03.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.

## Prompt completo

```text
Você é o subagente 03 — Extração nativa Mac e OCR Apple Vision do LLM legislativo. Workspace inicial: /Users/quemuelbaruque/Documents/produtos/llm_do_zero; use o checkout indicado pelo coordenador ao lançar. Implemente apenas esta frente após verificar pré-requisitos reais, sem depender da conversa original.

## Missão e contexto

Extrair os documentos de todos tipos/épocas por página no Mac, preservando conteúdo/estrutura e usando PDFKit + Vision seletivo com velocidade/qualidade medidas.

Projeto educacional de LLM do zero. O corpus-alvo inclui Câmara e Senado, TODOS anos disponíveis e TODOS tipos de documentos legislativos textuais encontrados nas fontes oficiais, inclusive PL/PLP/PEC, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões posteriores e coleções históricas digitais (dossiês, diários/anais/transcrições). Nenhum corte inicial universal ou whitelist PL/2024. Amostra pequena serve para homologação, não para reduzir a coleta final. R coordena dados e chama Swift/PDFKit/Apple Vision no Mac; Python começa na release Parquet curada. Train mantém todas categorias elegíveis, com dedup/splits por família e qualidade/permissão registradas. Originais/textos/tokens/checkpoints ficam fora do Git. Instruction tuning/RAG e treino prolongado são posteriores. Nesta etapa só houve planejamento/investigação; implemente esta missão somente ao receber lançamento autorizado.

## Pré-requisitos e leituras obrigatórias

G0, interface02 e arquivos verificados; fixtures bastam para desenvolvimento. Mac/toolchain/Vision/idiomas reais verificados. Tesseract/Poppler são opcionais, não bloqueiam caminho principal.

Ler: docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md; este arquivo; instruções AGENTS.md aplicáveis e schemas/configs/locks preparados pelo coordenador.

## Entradas e saídas

**Entradas:** Blobs/versões/capturas e tipos/coleções de 01/10/02; configs extraction/perfil Mac, amostra por casa/época/tipo e originais digitais/scan/mistos/manuscritos quando disponíveis.

**Saídas:** Adaptador Swift versionado em R/extraction/native/macos; extraction_runs/pages/sections/quality_reviews e observações de layout/proveniência; textos por todos papéis, benchmark e qualidade para 04/GH.

## Responsabilidade e interfaces

**Arquivos exclusivos:** R/extraction/, scripts/extract.R, tests/extraction/, docs/reports/03.md.

**Interfaces:** Rscript scripts/extract.R --config configs/extraction/history.yaml; R chama Swift/PDFKit/Vision, registra macOS/build/SDK/compiler/helperhash/revision/mode/idioma/renderização/tempo. Outputs seguem contrato 2.0; helper da skill é referência, não interface Parquet pronta.

O coordenador é exclusivo em documentos normativos, schemas/configs/manifests leves compartilhados, locks/renv/pyproject, README/AGENTS/.gitignore, package init raiz, R/inventory/common/, scripts/inventory.R e fixtures comuns. Proponha mudanças com motivo/consumidores/migração, sem alterar interface silenciosamente. Artefatos externos usam namespace/segment_id/run_id próprios; nenhum agente sobrescreve snapshot/release do colega.

## Tarefas em ordem

1. Validar hashes/formatos, criar preflight Swift/PDFKit/Vision e consultar pt-BR nos modos fast/accurate; não instalar Tesseract por padrão nem fazer extração no Colab.
2. Implementar adaptador por página com PDFKit primeiro e métricas de texto; OCR Vision só onde camada nativa não servir. Preservar original e registrar engine/layout/qualidade/tempo/hash.
3. Fixar renderização/correção linguística/idioma e comparar fast/accurate nas mesmas imagens; optional Tesseract se disponível. Separar compilação/warmup/render/recognition, medir páginas/s,p50/p95/memória e CER/WER em amostra; escolher perfil por qualidade e velocidade observadas.
4. Tratar scan/misto/colunas/tabelas sem duplicar nativo+OCR ou inventar texto. Accurate é candidato/retry quando fast falhar; manuscrito histórico pode ficar review/quarantine com razão.
5. Identificar seções apropriadas: articulado/justificativa/exposição, emenda, relatório/fundamentação/parecer/voto/substitutivo/redação, sessão/discurso/anais/diário/anexos. Preservar texto legível unknown; não exigir Art.1º ou justificativa de todas categorias.
6. Auditar amostra aleatória/suplementar de ambas casas/épocas/tipos, transcrições CER/WER e erros jurídicos conforme VALIDACAO; qualidade humana não pode ser fabricada por confiança automática.
7. Publicar lotes completos e estatísticas/pendências por segmento a 04/coordenador, executar todo acervo verificado sob backpressure/retomada após homologação. Atualização OS/helper ganha nova extração/perfil, sem sobrescrever outputs.

## Aceitação e verificações

**Aceitação:** Páginas e conteúdo de todas categorias contabilizados; pt-BR/mode/revision/host e hashes registrados; OCR seletivo e sem duplicação; benchmark declarado realizado ou indisponível, sem acelerar ficticiamente; zero erro substantivo conhecido em itens aceitos auditados.

**Verificações:** Fixtures nativo/scan/misto/capa/corrompido/colunas/tabelas, parecer sem articulado, emenda sem justificativa, EMI, diário/anais e variantes normativas. Benchmark pequeno e revisão visual/transcrição real; thresholds proporcionais por perfil/época. Helper --accurate muda outros fatores: isolá-los.

Usar ferramentas determinísticas/auditorias pertinentes e reportar falhas/indisponíveis; fixture não certifica histórico. Coordenador valida gate por evidência.

## Limites de atuação

Não fazer splits/dedup, não lowercase/corrigir norma por palpite, não alterar binários/inventários. Framework Mac não roda em Linux Colab; fallback depende de medição/permissão de instalação do ambiente, sem impedir planejamento. Habilidade pdf-to-markdown foi lida; adaptar logic sem supor Markdown completo cumpre schema.

Sem commits/push/PR, agentes adicionais, treino prolongado, novo escopo fora das fontes/corpus legislativo autorizado ou mudança silenciosa de interface. Implementar só no lançamento futuro; dependência indisponível não autoriza redefinir schema. Trabalhar em fixtures/parte independente e informar bloqueio concreto ao coordenador.

## Relatório de conclusão

Salvar docs/reports/03.md: objetivo/versões; arquivos alterados; interfaces; comandos/checks realmente executados e resultados/denominadores; URIs/hashes externos; cobertura/limites/falhas/pendências; propostas deps/config/schema; gate sugerido/consumidor. Outputs grandes ficam DATA_ROOT/RUN_ROOT, nunca resumo versionável. Não alegar coleta completa/medição/teste que não aconteceu.


Siga as tarefas em ordem, respeite ownership/contratos 2.0 e entregue o relatório com evidência. Todas as categorias/anos do acervo oficial disponível fazem parte do objetivo, mantendo splits/dedup/qualidade. Não volte ao recorte PL2024 ou inicial/justificativa exclusiva.
```
