# Plano mestre — corpus legislativo histórico e LLM do zero

Versão de planejamento: **2.0.0**; revisão em 2026-10-07. Esta revisão incorpora a orientação do usuário: **Câmara e Senado, todos os anos disponíveis e todos os tipos de documentos legislativos textuais**, incluindo PL, PLP, PEC, emendas, pareceres, substitutivos e versões posteriores no corpus de treino. OCR nativo do Mac foi confirmado: PDFKit + Apple Vision. A antiga restrição a PLs iniciais de 2024 foi substituída.

Esta entrega continua sendo planejamento. Pipeline, configurações executáveis, notebooks e treinos não foram implementados. Houve apenas investigação e diagnóstico local de capacidades do Vision; não coleta histórica massiva, commit, push ou PR.

## 1. Prioridade e população

A primeira prioridade é **obter, rastrear e organizar a base documental histórica completa que as fontes oficiais disponibilizam**, antes de limitar experimentos de treinamento. “Todos os anos” significa descobrir o intervalo efetivamente disponível por casa/fonte/tipo, sem impor 1989, 2001 ou 2024 como ano inicial universal. Registrar anos vazios, lacunas, acervos não digitalizados, links quebrados e limites de cada fonte; não prometer documentos que não estão disponíveis online.

Universo de coleta: proposições/processos e documentos legislativos oficiais publicados nas fontes da Câmara e do Senado até a data-corte do snapshot. Todos temas e autorias. Descobrir a taxonomia oficial: PL, PLP e PEC são exemplos, não um filtro exclusivo. Incluir textos iniciais, justificativas/exposições de motivos, emendas/subemendas, relatórios, pareceres/votos, substitutivos, redações e versões posteriores, além das demais categorias legislativas textuais encontradas. Mapear nomes legados e fases entre casas sem inventar equivalência. Anexos textuais vinculados também são inventariados, com regras próprias de uso/qualidade. Arquivo Histórico, dossiês, Anais/Diários/Constituintes e transcrições legislativas oficiais digitalmente disponíveis integram a descoberta; fontes/códigos/volumes são preservados mesmo sem proposição identificada.

Datas de apresentação, numeração, juntada/publicação do documento, tramitação e coleta são dimensões distintas. Como o alvo agora inclui todas as fases, **a data de apresentação de um projeto não limita a data dos documentos associados**. Documento de 2026 de processo de 1995 integra o inventário até o snapshot; não fingir que seu conteúdo já existia em 1995. Ano corrente é parcial e explicitamente marcado. Documentos sem data permanecem rastreados e podem entrar no corpus agrupado se origem/qualidade forem suficientes; avaliação temporal os trata separadamente.

Todo documento textual legislativo recuperável é candidato à curadoria e treino, preservando tipo, papel e versão. Curadoria ainda exige formato válido, texto útil, proveniência e regras de uso: indisponível/corrupto/ambíguo não vira texto fabricado. Duplicatas exatas são representadas uma vez no dataset, com todos os vínculos preservados; versões substantivas permanecem. “Tudo no treino” abrange todas categorias, com validation/test reservados por família para avaliação sem vazamento.

## 2. Homologação, coleta completa e treinamento

A amostra de homologação valida adaptadores, downloads e OCR em lotes pequenos e heterogêneos; **não é o limite temporal ou tipológico do corpus**. Selecionar ambas casas, períodos antigos/intermediários/recentes, classes distintas, documentos digitais/escaneados/mistos e versões relacionadas. Os PDFs de 2022–2024 já inspecionados são referências de pesquisa, não uma decisão de excluir outros anos/tipos.

Após homologação, processar todos os segmentos descobertos em filas retomáveis por casa/fonte/período/tipo. Publicar releases incrementais imutáveis para auditoria. Uma release parcial declara exatamente seus segmentos; nunca recebe rótulo de corpus histórico completo. Fechamento da coleta-alvo exige que todos os segmentos previstos tenham consulta encerrada e todos os candidatos tenham estado final ou pendência explicitada; “fechado com lacunas” difere de “todos arquivos disponíveis recuperados”.

Primeira entrega de dados: inventário histórico das duas casas, taxonomias, fila documental e cobertura; originais e textos processados; relatório de qualidade/cobertura; corpus histórico versionado e splits por famílias. Depois: tokenizer somente em train, GPT explícito, checks CPU, benchmark e treino curto Colab com retomada Drive. O smoke pode usar uma sub-release representativa identificada, mas **não conclui a coleta completa nem substitui o treino sobre a release histórica**. O treino principal terá orçamento e cobertura definidos depois de medir tokens/VRAM/throughput, sem previsão inventada de horas/custo.

Fora desta entrega de implementação inicial: instruction tuning, RAG, pesos prontos, Trainer, otimizações avançadas e conclusões científicas de superioridade. Senado e versões posteriores já estão dentro da camada de dados inicial. Áudio/vídeo/imagem sem texto oficial ou OCR utilizável ficam preservados/inventariados, sem fabricar transcrição ou texto para o modelo.

## 3. Diagnóstico e decisões

[FONTES_E_DIAGNOSTICO.md](FONTES_E_DIAGNOSTICO.md) registra evidências, links, consultas e limites; [DECISOES_TECNICAS.md](DECISOES_TECNICAS.md) distingue fatos/propostas. Repositório anterior inspecionado no commit `0e321aab85387efaf7b050bfd091db183959dc94`: seis arquivos, sem README/licença/locks/PDFs. RDS lido: ementas/metadados do recorte penal, sem inteiro teor extraído. Ele não é o corpus histórico solicitado.

Reutilizar conhecimento de URLs anuais/CSV e IDs, adaptando para todas categorias/autorias e duas casas. Recoletar proveniência e documentos. Não transportar filtros penais, primeiro deputado, lowercase, sentimento ou regex como regra do corpus/rótulo ouro. Código anterior sem licença exige esclarecer condições de incorporação/redistribuição; clientes novos de APIs oficiais não dependem dessa cópia.

## 4. Arquitetura e fronteira

```mermaid
flowchart LR
  C[Inventário histórico Câmara] --> I[Inventário documental normalizado]
  S[Inventário histórico Senado] --> I
  I --> D[Downloads e versões por hash]
  D --> E[Mac: PDFKit e OCR Apple Vision por página]
  E --> Q[Curadoria R: tipos, qualidade, dedup, famílias e splits]
  Q --> R[Release Parquet e manifesto]
  R --> T[Tokenizer Python exclusivo de train]
  T --> M[GPT explícito PyTorch]
  M --> F[Treino, avaliação e checkpoints]
  H[Colab: benchmark e Drive] --> F
```

R coordena inventário/coleta/curadoria e o adaptador Swift de extração; PDFKit lê texto embutido, Apple Vision reconhece páginas com imagem/texto insuficiente. Modos fast/accurate e português são verificados na máquina. Tesseract/Poppler são alternativas de portabilidade/comparação, não pré-requisito do caminho Mac. Python começa no corpus curado, sem joins N:M de autores/temas para criar sequências. Colab recebe shards e manifestos; não executa Apple Vision.

Manter proposições/processos, documentos, versões, autores, temas e relações separados. Documento pode ter vários vínculos ou nenhum processo identificado; nunca duplicar texto por vinculação. O tipo não é reduzido a initial: versões posteriores, emendas e pareceres têm identidades/papéis próprios. Conteúdo substantivo é preservado integralmente na ordem documental, com seções conhecidas e trechos unknown mantidos quando legíveis; justificativa não é exigência de um parecer/emenda.

Contratos: [CONTRATOS_DADOS.md](CONTRATOS_DADOS.md). Checks: [VALIDACAO.md](VALIDACAO.md). Sessões: [COLAB.md](COLAB.md). Alterações de interface passam pelo coordenador antes dos consumidores.

## 5. Organização e ownership futuros

```text
README.md, AGENTS.md, .gitignore, pyproject.toml, requirements-*.lock, renv.lock
schemas/, configs/, manifests/
R/inventory/{camara,senado,common}/
scripts/{inventory_camara,inventory_senado,inventory,download,extract,curate}.R
R/{download,extraction,curation}/
R/extraction/native/macos/             # adaptador Swift versionado
src/legislm/{tokenization,model,training,colab,evaluation}/
notebooks/piloto_colab.ipynb
tests/{inventory/camara,inventory/senado,download,extraction,curation,
       tokenization,model,training,colab,evaluation,fixtures/common}/
docs/
```

Árvore proposta; nesta sessão existem somente Markdown. DATA_ROOT externo contém originais, respostas, textos, Parquet de corpus, tokens, checkpoints e relatórios grandes. Git futuro contém código/config/locks e manifestos leves sanitizados; nenhuma massa documental/tokens/checkpoints no histórico.

| Frente / instrução | Arquivos exclusivos futuros | Entrega |
|---|---|---|
| 01 [Câmara](subagents/01_INVENTARIO.md) | R/inventory/camara/, scripts/inventory_camara.R, tests/inventory/camara/, docs/reports/01.md | taxonomia, anos/segmentos e inventário histórico Câmara |
| 10 [Senado](subagents/10_SENADO.md) | R/inventory/senado/, scripts/inventory_senado.R, tests/inventory/senado/, docs/reports/10.md | processos/fases/documentos/emendas e cobertura histórica Senado |
| 02 [Downloads](subagents/02_DOWNLOADS.md) | R/download/, scripts/download.R, tests/download/, docs/reports/02.md | originais/capturas/versões de ambas casas |
| 03 [Extração Mac](subagents/03_EXTRACAO.md) | R/extraction/, scripts/extract.R, tests/extraction/, docs/reports/03.md | Swift/PDFKit/Vision, páginas/seções/qualidade |
| 04 [Curadoria](subagents/04_CURADORIA.md) | R/curation/, scripts/curate.R, tests/curation/, docs/reports/04.md | releases históricas/splits/cobertura |
| 05 [Tokenizer](subagents/05_TOKENIZER.md) | src/legislm/tokenization/, tests/tokenization/, docs/reports/05.md | tokenizer/tokens/batch |
| 06 [Modelo](subagents/06_MODELO.md) | src/legislm/model/, tests/model/, docs/reports/06.md | GPT/checks CPU |
| 07 [Treino](subagents/07_TREINAMENTO.md) | src/legislm/training/, tests/training/, docs/reports/07.md | loop/benchmark/checkpoints |
| 08 [Colab](subagents/08_COLAB.md) | src/legislm/colab/, notebooks/piloto_colab.ipynb, tests/colab/, docs/reports/08.md | staging/persistência/notebook |
| 09 [Avaliação](subagents/09_AVALIACAO.md) | src/legislm/evaluation/, tests/evaluation/, docs/reports/09.md | métricas estratificadas/byte NLL/integração |
| Coordenador | docs normativos, schemas/configs/manifests leves, README/AGENTS/.gitignore/pyproject/locks/renv, package init raiz, R/inventory/common/, scripts/inventory.R, fixtures comuns/CI | contratos e integração normalizada das duas casas |

A frente 10 é adicionada porque APIs/taxonomias/fases e história do Senado são trabalho independente suficiente; evita um único agente implementar dois adaptadores heterogêneos e permite pesquisa/coleta de metadados simultânea. Não há sobreposição com o diretório de 01. Coordenador é dono da interface/agregador comum, dependências e configs. Agentes usam staging/partições próprios; nenhum escreve no snapshot/release do colega.

## 6. Gates e ondas

Implementação e homologação já começaram. O estado dos gates deve ser lido em [STATUS_IMPLEMENTACAO.md](STATUS_IMPLEMENTACAO.md), atualizado pelo coordenador com evidências de artefatos e comandos. Relatórios de frente são entregas dos owners e não substituem a validação dos critérios objetivos abaixo. Lotes incrementais podem ser liberados conforme contratos, mas cobertura total exige gate histórico próprio; não chamar smoke de conclusão do objetivo de dados.

| Gate | Critério objetivo |
|---|---|
| G0 — fundação | contrato 2.0.0, adapters/interfaces comuns, schemas/configs, fixtures e ownership preparados |
| G1 — inventário | ambas casas com taxonomias e segmentos de todos anos descobertos; paginação/encerrados/fases auditados; lacunas e limites registrados; fila de todos tipos, sem restrição PL/2024 |
| G2 — release curada | lote/release declarado, proveniência/qualidade/permissões, zero PK/FK inválida/duplicata elegível/família dividida; tipos e versões preservados |
| GH — cobertura histórica | todos segmentos descobertos e candidatos reconciliados com estados; relatório por casa/ano/tipo distingue completo, parcial, indisponível e pendente; release histórica identificada |
| G3 — tokens | tokenizer só train; corpus/splits congelados e shards/round-trip/alvos corretos; volume medido |
| G4 — CPU | decoder/loop/máscaras/lote pequeno/save-load/sampler/RNG aprovados |
| G5 — GPU/persistência | hardware e throughput/memória/I/O medidos; checkpoint Drive retomado em nova sessão |
| G6 — entrega | GH + release histórica/tokenizer/treino curto identificados + G5 + métricas/geração/limites; smoke de sub-release fica explicitamente parcial |

**Onda 0:** coordenador prepara G0. Primeiro lançamento de dados: **01 Câmara + 10 Senado em paralelo**. 06 pode trabalhar em fixtures como terceira frente independente, se houver capacidade; prioridade é destravar dados. Nenhum agente dependente muda schema por conta própria.

**Onda 1:** 01/10 descobrem e inventariam histórico, tipos, documentos e relações de cada fonte, incluindo encerrados e acervos legados disponíveis. Podem publicar segmentos completos progressivamente. Integração confere IDs/semântica e G1; amostra de homologação é feita com ferramentas existentes, sem depender da implementação 02/03.

**Onda 2:** 02 + 03 processam lotes publicados; 03 começa em fixtures e amostra de ambas casas antes da escala. 07 pode concluir G4 com modelo 06/batches sintéticos. Após homologação, fila segue até todos segmentos do acervo-alvo, com concorrência e retomada; nenhuma regra exclui categorias do usuário. Máximo três frentes além do coordenador.

**Onda 3:** 04 consolida lotes reais, qualidade/dedup/famílias e releases; 08 prepara persistência com checkpoint de 07 e 09 implementa métricas em fixtures. GH mede fechamento histórico separado do progresso de um lote. Relações novas podem juntar famílias antes separadas: release final precisa recomputar grafo/splits sobre todo o snapshot, não apenas dentro de cada ano/casa.

**Onda 4:** 05 recebe release curada congelada (G2); versão-alvo de treino histórico exige GH. Pode fazer smoke anterior em sub-release declarada, sem reutilizar tokenizer de subconjunto como se tivesse sido treinado no corpus todo. Nova release/split exige revalidar inputs e, quando treino muda, treinar novo tokenizer identificado.

**Onda 5:** coordenador/07/08: preflight→benchmark→config medida→trecho curto→Drive→nova sessão→retomada (G5); 09 fecha G6 somente com GH e artefatos da release histórica. Budget de smoke pode limitar a parte consumida, com mapa de cobertura e sem alegar que todos documentos foram vistos. Treino principal sobre todos itens train terá passes/budget/cobertura planejados pelas medições posteriores.

Revisões: G0 interfaces; G1 história/taxonomia; 02→03 arquivos; 03→04 qualidade; G2/GH corpus e cobertura; G3 tokens; G4 estado; G5 persistência; G6 relatório. Alterações quebram somente tarefas dependentes até contrato coordenado. Owners aplicam suas correções; integração/eval não editam módulos alheios.

## 7. Caminho local → Colab

1. Descobrir acervo das duas casas e mapear todos tipos/anos, datas e lacunas. Não usar a listagem padrão recente/em tramitação como inventário histórico.
2. Homologar documentos de várias classes/épocas e processar acervo em filas retomáveis, com bytes originais/versionamento/hash.
3. No Mac, extrair nativo por PDFKit e aplicar Vision somente a páginas necessárias, fast/accurate/idioma registrados e auditados. Publicar corpus com papéis e versões preservados.
4. Consolidar dedup/famílias entre anos/casas antes de split/tokenizer; medir cobertura, qualidade, bytes/tokens e composição. Congelar release histórica e tokenizer train.
5. CPU valida decoder e retomada; Colab verifica conta/hardware, recebe dados já processados, mede staging e treino e escolhe modelo (candidato 10–30M, sujeito às medições).
6. Treino curto/restauração demonstram mecânica. Treino principal usa release histórica e amostragem com cobertura de todos itens train; logs dizem quanto de cada casa/ano/tipo foi consumido. Checkpoints completos mantêm configuração, sampler, scheduler e RNG. [COLAB.md](COLAB.md) detalha início/retomada.

## 8. Riscos e pendências

| Questão | Resolução |
|---|---|
| “Todos” sem primeiro ano universal | 01/10 descobrem segmentos/limites por fonte/tipo; coordenador congela snapshot e GH |
| Acervo antigo sem texto/link/data | inventariar lacuna/estado, buscar alternativa oficial, jamais inventar documento; data ausente não exclui automaticamente corpus agrupado |
| Tipos/fases legados e entre casas | 01/10 preservam código original e mapping; aliases com evidência; 04 evita duplicação/vazamento |
| Reprodução de peça em diário/dossiê maior | 04 detecta containment por passagens, segmenta unidades editoriais com spans e preserva todo texto; container/mention não unem todas famílias nem entram duplicados volume+segmentos |
| Parecer com texto citado/versões muito parecidas | 04 mantém diferenças substantivas e família; não reduzir tudo à versão inicial ou remover citação normativa automaticamente |
| Vision fast vs accurate/qualidade | 03 consulta suporte português por revision/macOS, mede páginas/s/CER/WER e audita; Tesseract é fallback comparável se disponível |
| Tempo de coleta e volume total | 02/03 medem por lote, publish logs/cobertura; dimensionar disco/quotas sem inventar horas |
| Token budget/composição desequilibrada | 05/07/09 medem tokens e consumo por classe/ano/casa; default sem excluir tipos, ablações futuras identificadas |
| GPU/saldo/Drive/retomada | 08 verifica condições reais; Colab não faz OCR Mac; migrar treino somente por viabilidade medida |

## 9. Execução autossuficiente e ciência posterior

Cada instrução em docs/subagents contém prompt completo, inputs/outputs/ownership/ordem/gates/checks/relatório, sem depender da conversa. Relatório leve informa versões/arquivos/comandos/checks reais, denominadores, hashes/URIs, limitações, mudanças propostas e próximo consumidor. Metas de qualidade/performance são propostas, não resultados.

Depois da entrega: comparar tokenizer, escala e composição, controlando corpus/splits/budget/seed/parametrização e usando loss por byte além de PPL identificada. Estudos temporais precisam datas documentais e famílias entre anos/casas; sondas de representações usam rótulos independentes/baselines. Ampliar acervo conhecido é manutenção versionada do mesmo objetivo histórico, não um motivo para abandonar tipos solicitados. Instruction tuning/RAG permanecem posteriores.
