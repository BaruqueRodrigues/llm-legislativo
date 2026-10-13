# Fontes, investigação e diagnóstico

Revisão de planejamento: **2.0.0**. Consulta: **2026-10-07**, fuso do pesquisador America/Maceio. Este registro separa **V** (verificado em fonte/consulta), **P** (proposta) e **A** (aberto). URLs online podem mudar: a implementação deverá guardar snapshots e hashes. Esta sessão fez inspeção e amostras pequenas, sem coleta anual completa nem treinamento.

## 1. Workspace e investigação

**V:** `/Users/quemuelbaruque/Documents/produtos/llm_do_zero` estava vazio, sem `.git`, README, código ou AGENTS.md local/ancestral nos caminhos conferidos. Aplicam-se as instruções AGENTS.md fornecidas na conversa. Não foi inicializado Git. Jev foi descoberto, mas TYPESAFE_API_KEY não estava no ambiente; não houve chamada nem recomendação atribuída ao serviço.

Três subagentes de pesquisa investigaram Câmara, repositório anterior e Colab/Senado. Não foram lançados agentes de implementação. As amostras ficaram em diretório temporário; a entrega no workspace consiste somente em Markdown.

## 2. Repositório anterior — estado efetivamente inspecionado

**V:** branch main, HEAD `0e321aab85387efaf7b050bfd091db183959dc94`, commit em 2024-07-21 14:08:25 UTC. A árvore tem seis arquivos: `.Rhistory`, `classificacao.R`, `get_data_2024.R`, `propo_sentimentos.rds`, `proposicoes_legislativas.Rproj`, `script_get_data.R`. Sem README/licença/lockfile/PDFs. Data de atualização do repositório não prova atualização de código. Fontes: [commit](https://github.com/BaruqueRodrigues/punitivismo_legisladores/commit/0e321aab85387efaf7b050bfd091db183959dc94), [árvore](https://api.github.com/repos/BaruqueRodrigues/punitivismo_legisladores/git/trees/5f1dfbf71995beebf3fecd1c4d58ef888223bfbc?recursive=1), [metadados/licença](https://api.github.com/repos/BaruqueRodrigues/punitivismo_legisladores). Consulta 2026-10-07.

| Arquivo e evidência | Diagnóstico e consequência |
|---|---|
| [get_data_2024.R](https://github.com/BaruqueRodrigues/punitivismo_legisladores/blob/0e321aab85387efaf7b050bfd091db183959dc94/get_data_2024.R), linhas 4/24/44, 61–88, 95–110 | Solicita 1989–2023; filtra penal/processual e exige pelo menos um deputado. Não restringe a PL nem comprova autoria exclusivamente parlamentar. Baixa urlInteiroTeor como `.pdf`, sem extração. Reutilizar conhecimento dos arquivos anuais/IDs, refazer seleção e proveniência. |
| [script_get_data.R](https://github.com/BaruqueRodrigues/punitivismo_legisladores/blob/0e321aab85387efaf7b050bfd091db183959dc94/script_get_data.R), linhas 9/26–29/39 | XML legado para PL, solicita 1989–2022. Não prova cobertura; arquivo de saída na raiz difere da entrada esperada pela classificação. Priorizar API moderna, preservar legado só como referência. |
| [classificacao.R](https://github.com/BaruqueRodrigues/punitivismo_legisladores/blob/0e321aab85387efaf7b050bfd091db183959dc94/classificacao.R), linhas 39–103/120–156 | Regex e sentimento de ementas, com lowercase e concatenação inadequada. Não fornecer texto de treino nem rótulo ouro. Não integrar essa análise ao MVP. |

**V:** chamada isolada `glimpse()` em get_data_2024.R:68 falhou por argumento ausente no R disponível. Diretórios iniciais não são criados recursivamente. Os downloads não validam formato/hash nem têm manifesto/retomada. Em uma URL do RDS, [codteor=15703](https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=15703), GET limitado devolveu HTTP 200 e 1.204 bytes de HTML, sem assinatura PDF. Esse caso não estima taxa anual de falhas.

**Limite:** não executamos os coletores nem reproduzimos sentimento; não há versões de pacotes preservadas e sentimentr/lexiconPT não estavam instalados no ambiente de inspeção. `algorithm='vader'` no script não comprova uso de VADER: [fonte oficial atual de sentimentr](https://raw.githubusercontent.com/trinker/sentimentr/master/R/sentiment.R) tem `...` ignorado e não esse parâmetro explícito. Consulta 2026-10-07.

### RDS lido, sem suposição de inteiro teor

**V:** [propo_sentimentos.rds no commit](https://github.com/BaruqueRodrigues/punitivismo_legisladores/blob/0e321aab85387efaf7b050bfd091db183959dc94/propo_sentimentos.rds) foi baixado isoladamente com limite de 11 MB e lido por readRDS, R 4.4.3. Tamanho 9.947.228 bytes; SHA-256 `50f900415678d72dac4451ee29642a7ef785e9c777a9a62601bc99a8bd641347`; hash Git `e 18b599dfef831c377a35d65d112a37e6fb21e62` confere com blob remoto. Serialização v2/XDR.

6.390 linhas × 37 campos, IDs únicos, anos 1989–2023, todos tema 43. PL=6.038; outros tipos INC=59, PDC=25, PDL=28, PEC=93, PFC=1, PLP=26, PLV=2, PRC=6, RCP=7, RIC=105. Ementa detalhada falta em 3.848 e URL integral em 76. Há metadados, ementas e rótulos lexicais; **não há textos integrais, justificativas separadas, páginas, autores ou proveniência documental**. Anos presentes não certificam completude. **P:** referência histórica para auditoria, sem importar como corpus de treino.

## 3. Câmara — documentação e semântica

Fontes oficiais consultadas em 2026-10-07: [OpenAPI](https://dadosabertos.camara.leg.br/api/v2/api-docs), versão declarada 0.4.344, 18/08/2026; [catálogo/arquivos](https://dadosabertos.camara.leg.br/swagger/api.html); [uso de dados abertos](https://dadosabertos.camara.leg.br/howtouse/sobre-dados-abertos.html).

| Necessidade | Fonte e significado verificados | Limite |
|---|---|---|
| Inventário | `/proposicoes`, filtros dataApresentacaoInicio/Fim; `dataInicio/Fim` tratam tramitação | ano/numeração não bastam; padrão pode limitar aos últimos 30 dias |
| Metadados | `/proposicoes/{id}`; ementa, URIs, data e urlInteiroTeor | texto/justificativa nulos nas quatro amostras |
| Autores | `/proposicoes/{id}/autores`, arquivo anual proposicoesAutores | conservar tipos, ordemAssinatura e proponente; não só primeiro deputado |
| Temas | `/proposicoes/{id}/temas`, arquivo anual proposicoesTemas | ausência e falha de consulta devem diferir |
| Inteiro teor/inicial | urlInteiroTeor e URL em `/tramitacoes` de apresentação | cotejar papel/conteúdo quando divergem |
| Associados/relações | `/relacionadas`, `/tramitacoes`, uriPropPrincipal/Anterior/Posterior | não há sequência editorial completa de versões garantida |

**V:** paginação documentada: pagina≥1, padrão 15, máximo 100, links de navegação. Consulta por intervalo anual de apresentação deu HTTP 400 (máximo observado de três meses); trimestrais funcionaram. Proposta: janelas trimestrais fechadas sem sobreposição; seguir links next e deduplicar IDs; subdividir se limite mudar.

**V:** [ano=2024, cinco registros](https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=PL&ano=2024&itens=5&ordem=ASC&ordenarPor=id) retornou apresentações em 2004/2007/2011/2013/2015. ID 253500 hoje é PL 2597/2024, apresentação 13/05/2004. Também houve PL 4031/2021 apresentado em 03/01/2023. **P:** definir coorte pela data registrada na Câmara e auditar origem/renumeração; não inferir ano original de todo o processo.

### Amostras 2022–2024 — evidência da investigação inicial

**V:** primeiras e últimas páginas (itens=1) de quatro trimestres por ano indicaram 2.531 PLs em 2022, 5.488 em 2023, 4.496 em 2024. São **indicações de paginação**, sem baixar páginas intermediárias, sem fechar contagem de IDs únicos nem corpus utilizável. Consultas do primeiro trimestre: [2022](https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=PL&dataApresentacaoInicio=2022-01-01&dataApresentacaoFim=2022-03-31&itens=1&ordem=ASC&ordenarPor=id), [2023](https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=PL&dataApresentacaoInicio=2023-01-01&dataApresentacaoFim=2023-03-31&itens=1&ordem=ASC&ordenarPor=id), [2024](https://dadosabertos.camara.leg.br/api/v2/proposicoes?siglaTipo=PL&dataApresentacaoInicio=2024-01-01&dataApresentacaoFim=2024-03-31&itens=1&ordem=ASC&ordenarPor=id). Outros trimestres: 01/04–30/06, 01/07–30/09, 01/10–31/12.

**V:** HEAD200 nos nove CSVs de proposições/autores/temas de 2022–2024; Last-Modified indicado 07/10/2026. Não foram baixados arquivos anuais. Para 2024: [proposições](https://dadosabertos.camara.leg.br/arquivos/proposicoes/csv/proposicoes-2024.csv), [autores](https://dadosabertos.camara.leg.br/arquivos/proposicoesAutores/csv/proposicoesAutores-2024.csv), [temas](https://dadosabertos.camara.leg.br/arquivos/proposicoesTemas/csv/proposicoesTemas-2024.csv). HEAD não valida conteúdo nem completude.

| Amostra oficial | Evidência documental |
|---|---|
| PL 799/2022, deputado, trabalho | [detalhe](https://dadosabertos.camara.leg.br/api/v2/proposicoes/2319130), [PDF](https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=2154796): 2 páginas com artigos e JUSTIFICAÇÃO |
| PL 1574/2023, deputado, saúde/trabalho | [detalhe](https://dadosabertos.camara.leg.br/api/v2/proposicoes/2354733), [PDF](https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=2254320): 3 páginas com artigos e JUSTIFICATIVA |
| PL 2/2024, Executivo, economia/finanças/indústria | [detalhe](https://dadosabertos.camara.leg.br/api/v2/proposicoes/2416804), [PDF](https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=2382927): 5 páginas, artigos 1–3 e exposição de motivos EMI 00179/2023 MF MDIC 4–5 |
| PL 2634/2024, deputado, administração/meio ambiente/transportes | [detalhe](https://dadosabertos.camara.leg.br/api/v2/proposicoes/2444049), [PDF](https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=2444018): 5 páginas, artigos 1–2 e JUSTIFICATIVA 3–5 |

**V:** quatro PDFs com texto nativo; nos dois de 2024, dez páginas lidas por PDFKit sem OCR. É evidência de disponibilidade/qualidade local, não taxa anual. As ementas amostrais de 2024 também abrangem aborto legal, aprendizes, deficiência, cigarros, assistência veterinária, Caatinga e incêndio: diversidade exploratória, sem representatividade demonstrada.

**V/A:** PL799/2022: URL no detalhe termina codteor=2154796, apresentação seq1 aponta 2154797; ambos PDF via HEAD, mas só primeiro lido. Diferença de versão/conteúdo permanece aberta. Nos três outros casos, URL integral coincide com apresentação seq1. [Relacionadas do PL2/2024](https://dadosabertos.camara.leg.br/api/v2/proposicoes/2416804/relacionadas) retornaram 46 registros incluindo material posterior. **P:** não baixar/treinar indiscriminadamente todas relacionadas.

### Uso e acessos

**V:** [termo oficial da Câmara](https://www2.camara.leg.br/termo-de-uso-e-politica-de-privacidade), itens 7 e 29, autoriza reprodução com indicação institucional e autoria quando houver; declara informações do portal de domínio público. Há regras específicas para textos/notícias/estudos. Não identificamos licença CC nominal deste corpus. A [Lei 9.610/1998, art. 8º IV](https://www.planalto.gov.br/ccivil_03/leis/l9610.htm) trata textos de atos oficiais; não assumir extensão a anexos de terceiros. Consulta 2026-10-07.

**Limitação:** ferramenta web recebeu 429 e outra falha ao abrir PDFs; consultas HTTP diretas limitadas conseguiram os mesmos arquivos, com espera/sem carga em massa. Não foi identificada taxa oficial da Câmara; concorrência inicial baixa é proposta. A ausência de resposta não prova ausência de documento.

## 4. Senado — fonte inicial no escopo 2.0.0

Fontes oficiais consultadas em 2026-10-07: [OpenAPI](https://legis.senado.leg.br/dadosabertos/v3/api-docs), versão declarada 4.1.3.99; [catálogo legislativo](https://www12.senado.leg.br/dados-abertos/conjuntos?grupo=projetos-e-materias&portal=Legislativo); [unificação e fases](https://www25.senado.leg.br/web/atividade/simplificou/impacto-nos-dados-abertos).

**V:** recurso atual `/dadosabertos/processo`; detalhe `/processo/{id}` com autoria/assuntos/relações; documentos `/processo/documento`; emendas `/processo/emenda`; vocabulários `/processo/assuntos`, `/processo/classes`, `/processo/tipos-autor`. Rotas legadas `/materia` relacionadas estão depreciadas. Monitorar Deprecation/Sunset/Link. API pública; acima de 10 req/s pode gerar 429; demanda alta, 503.

**V:** lista sem filtros contém atualmente em tramitação; filtros próprios dataInicioApresentacao/dataFimApresentacao são necessários à coorte. CSVs do catálogo podem ser só dos processos em tramitação. **A:** validar diferenças texto/schema, inclusive codAssuntoEspecifico vs descrição codigoAssuntoEspecifico, no inventário histórico. **P:** mapear fases iniciadora/revisora e antecessoras/sucessoras, sem duplicá-las como proposições independentes nem equiparar temas entre casas.

**V:** [portal Dados Abertos](https://www12.senado.leg.br/dados-abertos) apresenta livre utilização; [política de uso](https://www12.senado.leg.br/institucional/documentos/politica-de-uso-do-portal-do-senado-federal) requer fonte e não prejudicar acesso. Não encontramos licença CC nominal. Não houve coleta de textos do Senado nesta sessão.

## 5. Colab e Google AI Pro

Fontes oficiais consultadas em 2026-10-07: [benefício AI Pro em inglês](https://support.google.com/googleone/answer/14534406?hl=en), [ajuda pt-BR](https://support.google.com/googleone/answer/14534406?hl=pt-BR), [elegibilidade](https://support.google.com/googleone/answer/16476811?hl=en), [planos Brasil](https://one.google.com/intl/pt-BR_br/about/google-ai-plans/), [FAQ Colab](https://research.google.com/colaboratory/faq.html).

**V:** ajuda inglesa anuncia 200 CCUs para AI Pro, com condições de idade/gestor/conta paga; pt-BR não lista Colab. A divergência não prova ausência no Brasil. Brasil consta na elegibilidade, para conta pessoal. Página brasileira anuncia 5 TB compartilhados em Drive/Gmail/Fotos, mas saldo e plano reais não foram inspecionados. **A:** verificar conta do usuário em Settings → Subscription; não acessamos sua assinatura.

**V:** FAQ diz unidades mensais para planos AI elegíveis, mesma conta e possibilidade de soma com Colab Pro/Pro+. Recursos variam, VMs são temporárias, GPU/VRAM/tempo não são garantidos. Recomenda reduzir pequenos I/Os no Drive e staging local. **P:** usar conta existente, conferir saldo e escolher configuração por benchmark; não pressupor Colab Pro+ ou duração fixa de sessão.

## 6. Referências de implementação e ciência

Todas consultadas em 2026-10-07; versões de instalação só serão resolvidas/testadas na implementação.

| Referência primária | Aplicação e limite |
|---|---|
| [Manning, livro](https://www.manning.com/books/build-a-large-language-model-from-scratch), [repositório do autor](https://github.com/rasbt/LLMs-from-scratch) | percurso didático dados→atenção→GPT→pretraining; fixar commit/licença antes de copiar código |
| [Arrow/Parquet Python](https://arrow.apache.org/docs/python/parquet.html) | tabelas interoperáveis e esquema explícito de datas/timestamps |
| [Poppler](https://poppler.freedesktop.org/), [qualidade Tesseract](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html) | extração nativa/OCR condicionado à página; escolhas ainda requerem benchmark |
| [Tokenizers modelos](https://huggingface.co/docs/tokenizers/api/models), [pre-tokenizers](https://huggingface.co/docs/tokenizers/api/pre-tokenizers), [trainers](https://huggingface.co/docs/tokenizers/api/trainers), [decoders](https://huggingface.co/docs/tokenizers/api/decoders) | BPE/ByteLevel/especiais/round-trip; uso não envolve Trainer |
| [PyTorch checkpoints](https://docs.pytorch.org/tutorials/beginner/saving_loading_models.html), [reprodução](https://docs.pytorch.org/docs/2.14/notes/randomness.html), [AMP](https://docs.pytorch.org/docs/2.14/amp.html), [receita AMP](https://docs.pytorch.org/tutorials/recipes/recipes/amp_recipe.html) | estados para retomada, controle RNG e limites de reprodução entre versões/dispositivos |
| [Lee et al., ACL 2022](https://aclanthology.org/2022.acl-long.577/) | evidência para dedup/controle de vazamento; não transfere automaticamente limiares para o domínio |

## 7. O que ainda não foi medido

**A:** inventário histórico completo por casa/fonte/coleção/tipo/ano e diferenças entre API/portais/acervos; distribuição de temas e tipos de autor; percentuais de inicial/justificativa disponível, OCR e erros; duplicações/famílias; bytes e tokens curados; tamanho útil de cada split; GPU/VRAM, throughput e tempo de staging/checkpoint; saldo CCU real, consumo/custo e frequência de interrupção. Resolução e responsáveis constam dos gates do [plano](PLANO_MESTRE.md). Nenhum desses valores foi preenchido como resultado de treinamento.


## 8. Ampliação autorizada e investigação histórica

**V:** usuário confirmou todos anos disponíveis e OCR nativo Mac/Apple Vision, incluindo Senado, PLP/PEC/emendas/pareceres/substitutivos/versões posteriores no treino. Proposta anterior PL inicial 2024 está substituída. **P:** descobrir acervo oficial digital disponível sem primeiro ano universal, inventariando também descrição sem arquivo como lacuna; homologação pequena não limita coleta final.

### Câmara — cadastro, coleções e lacunas

**V:** catálogo [Dados Abertos](https://dadosabertos.camara.leg.br/swagger/api.html) enumerou proposições/autores em 1934,1935,1945–2026; temas 1945–2026; tramitações 1935,1945–2026. Cadastro 1934–1945 é parcial;1946–2000 cobre tipos que podem virar normas;2001+ é declaração sobre registros tramitados, não garantia de todos íntegros. Prefixo limitado de [CSV1934](https://dadosabertos.camara.leg.br/arquivos/proposicoes/csv/proposicoes-1934.csv) mostrou registro com link; PDF não foi lido. Prefixo de [tramitações 2026](https://dadosabertos.camara.leg.br/arquivos/proposicoesTramitacoes/csv/proposicoesTramitacoes-2026.csv) mostrou eventos de projetos 1988/2000, confirmando eixo temporal distinto. Consulta 2026-10-07.

**V:** [taxonomia REST](https://dadosabertos.camara.leg.br/api/v2/referencias/proposicoes/siglaTipo) retornou 544 registros,181 siglas não vazias distintas e 13 registros sem sigla; siglas podem ter múltiplos codTipo. Não são544 tipos de textos disponíveis. **P:** preservar código/sigla/nome e mapear famílias depois, sem whitelist PL. Consulta 2026-10-07.

**V:** [histórico pareceres/substitutivos/votos PL2/2024](https://www.camara.leg.br/proposicoesWeb/prop_pareceres_substitutivos_votos?idProposicao=2416804) mostra declarações de voto; [ficha DVT1](https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2422083) tem vínculo e íntegra. O [detalhe API](https://dadosabertos.camara.leg.br/api/v2/proposicoes/2422083) deu404 e o ID não apareceu nas46 relacionadas. Evidência de lacuna local API↔portal, não estimativa de taxa geral. **P:** incluir reconciliação de seções/árvore/dossiê, além de API/anuais. Consulta 2026-10-07.

**V:** [FAQ Arquivo Histórico](https://www2.camara.leg.br/a-camara/documentos-e-pesquisa/arquivo/servicos/veja-as-perguntas-frequentes) distingue descrição/objeto digital e informa acervo anterior aos índices de proposições, inclusive itens anteriores a 1823; nem tudo está online. [Boletins/Diários/Anais](https://www2.camara.leg.br/a-camara/documentos-e-pesquisa/diariosdacamara) descreve séries históricas/constituintes; [pesquisa por publicações](https://imagem.camara.leg.br/diarios.asp) oferece coleções/data. [Discursos/notas](https://www2.camara.leg.br/atividade-legislativa/discursos-e-notas-taquigraficas/pesquisa/como-pesquisar) é outra coleção textual legislativa. **P:** registrar por fonte/coleção/período, sem inferir digitalização contínua ou primeiro ano universal. Algumas leituras de publicações deram503/429; não houve coleta de volumes. Consulta 2026-10-07.

### Senado — histórico, encerrados e documentos

**V:** [pesquisa oficial](https://www25.senado.leg.br/web/atividade/materias) inclui encerrados e tipos históricos, além de documentos anexados. [OpenAPI](https://legis.senado.leg.br/dadosabertos/v3/api-docs) confirma processo/siglas, classes, documento/tipos e tipos-conteudo; documentos/emendas por idProcesso. Default de documentos é recente (seis meses), de emendas um ano, e processos sem filtro só em tramitação. Não há page/limit documentado em processo. Limites/formatos e S/N precisam smoke; não inventar parâmetros. Payloads de alguns vocabulários não ficaram acessíveis na ferramenta web; interfaces confirmadas por schema. Consulta 2026-10-07.

**V:** [Anais](https://www25.senado.leg.br/web/atividade/anais) descrevem1826–2013 e consolidação nos Diários a partir2014. Essa faixa não comprova API de processos desde 1826. [Catálogo](https://www12.senado.leg.br/dados-abertos/conjuntos?grupo=projetos-e-materias&portal=Legislativo) inclui arquivos só em tramitação. **A:** primeiro ano/contagens/cobertura de cada coleção/tipo; **P:** complementar inventário processo→todos documentos com catálogos/publicações oficiais e registrar lacunas. Consulta 2026-10-07.

## 9. Mac OCR — verificação local e referências

Habilidade aplicada: [pdf-to-markdown](</Users/quemuelbaruque/.agents/skills/pdf-to-markdown/SKILL.md>), helper e Swift inspecionados, sem alterar arquivos da skill. **V:** usa PDFKit para texto embutido e Vision para OCR; modo padrão fast, accurate muda modo/correção/renderização. Markdown simplificado não contém todo contrato de páginas/proveniência/layout. **P:** adaptador versionado do projeto com os campos necessários, invocado por R.

**V:** diagnóstico temporário Swift compilou e executou neste Mac: macOS26.6.2, arm64, VNRecognizeTextRequest revision 3; pt-BR apareceu em supportedRecognitionLanguages tanto fast quanto accurate. Tesseract e pdftotext não foram encontrados no PATH. Não houve instalação de motores, OCR de corpus nem benchmark de rapidez/CER; suporte a idiomas não prova qualidade/velocidade. Artefatos de diagnóstico ficaram fora do repositório.

Fontes oficiais Apple consultadas2026-10-07: [Reconhecer texto em imagens](https://developer.apple.com/documentation/vision/recognizing-text-in-images?changes=_1&language=objc), [VNRecognizeTextRequest](https://developer.apple.com/documentation/vision/vnrecognizetextrequest), [idiomas suportados](https://developer.apple.com/documentation/vision/vnrecognizetextrequest/supportedrecognitionlanguages%28%29?changes=_3), [PDFPage.string](https://developer.apple.com/documentation/pdfkit/pdfpage/string). A documentação distingue reconhecimento fast/accurate e suporte por configuração/revision. Algumas páginas JS e links Markdown deram erro na ferramenta; snippets oficiais e diagnóstico local forneceram alternativa concreta.

**P:** PDFKit primeiro; Vision fast pt-BR auditado e accurate quando necessário; comparar mesmas imagens/renderização/idioma/correção e medir páginas/s,p50/p95/memória/CER/WER. Tesseract é fallback/comparador opcional. Extração Mac precede treino Colab; publicar textos/versionamento preserva reprodução mesmo se macOS mudar. Nenhuma aceleração relativa foi quantificada nesta sessão.
