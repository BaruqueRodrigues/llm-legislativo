# Validação e avaliação

Versão de protocolo: 2.0.0; revisão: 2026-10-07. Corpus-alvo histórico de Câmara e Senado, todos anos/tipos/versões disponíveis; extração principal PDFKit/Apple Vision no Mac. Os limiares e desenhos numéricos deste documento continuam sendo propostas até aprovação explícita; checks de código, smoke e dados reais já foram executados em escopos distintos. Consulte [STATUS_IMPLEMENTACAO.md](STATUS_IMPLEMENTACAO.md) e os relatórios de frente para os comandos/resultados verificados. A aprovação de gate depende dos critérios objetivos do [plano](PLANO_MESTRE.md), não da mera existência de implementação ou testes.

## 1. Princípios e registros

Verificação proporcional ao risco: contratos, corrupção, contaminação, causalidade e retomada exigem checks; cosmética não exige suíte nova. Fixtures sintéticas não provam cobertura da API nem qualidade do ano. Pequena leitura real não substitui testes de falha. Cada check registra versão de dados/código/config, comando, ambiente, seed quando pertinente, resultado/contagens e URI/hash do relatório. Falha bloqueante não pode ser convertida em warning para liberar o gate.

Thresholds numéricos abaixo são **metas iniciais propostas**, não resultados nem normas oficiais. Congelá-los antes de olhar loss/teste. Se forem inviáveis, revisão motivada do protocolo pelo coordenador, com efeito sobre escopo/inferência; nunca diminuir exigência silenciosamente para passar.

## 2. Identificadores, relações e formatos

| Risco | Verificação necessária | Critério |
|---|---|---|
| Colisão de IDs | PK/FK e namespace por casa/tipo; fixture com mesmo ID numérico nas duas casas | zero colisões/PK duplicadas/FK órfãs; mesmo ID local em namespaces da mesma casa não colide |
| Multiplicação do texto | PL sintético 2 autores×2 temas; documentos compartilhados por 2 PLs | unicidade por logical_unit_id+versão+composição; spans editoriais sem reprodução dupla; um representante por texto equivalente no índice |
| Autoria/tema ausente | metadata_checks distingue vazio, pendente e erro; compara IDs antes/depois de joins | zero exclusões decorrentes só de ausência de metadata |
| Ano enganoso | fixtures com ano da numeração diferente da apresentação, transferência e status posterior | decisão de coorte por política registrada, divergência preservada |
| Relação textual mal usada | cadeia de apensação/versões e citações genéricas sintéticas | fechamento transitivo das ligações aprovadas; citação comum não une tudo |
| Download inválido | HTTP200 HTML, PDF truncado, redirecionamento, timeout, 429 Retry-After, 404 e arquivo zero | nenhum inválido chega como documento verificado; tentativas/estados corretos |
| Captura sobrescrita | mesmo URL com dois hashes, hash igual em URLs distintas, .part abandonado | história e blobs íntegros; estado recuperável; nenhuma promoção prematura |
| Parquet incompatível | fixture R→Parquet→Python e retorno com nulos/acento/IDs/timestamp UTC | esquema e valores estáveis; nenhum ID float/factor implícito |
| Catálogo histórico/tipos | sigla repetida com codTipo distinto, sigla ausente, processo legado/new alias e documento sem processo/data | nenhum excluído automaticamente por filtro PL/2024/metadata ausente |
| Histórico de versões | documento 2026 associado a processo 1995 e reprodução em outra casa/coleção | data documental própria e split global; nenhum vazamento retrospectivo |
| Release parcial | falta arquivo/hash divergente/COMPLETE ausente | consumidor rejeita publicação incompleta |

Injetar falhas em mocks/fixtures, sem sobrecarregar serviços. Smoke real limitado faz uma página/um documento e confere cabeçalho/formato e proveniência. Acesso 403 é limitação registrada, sem contorno. Hash do arquivo e parser corroboram formato; Content-Type e extensão isolados não bastam.

## 3. Cobertura histórica por fonte, coleção, ano e tipo

Há dois denominadores principais: proposições/processos distintos e documentos/unidades arquivísticas distintos; páginas são outro denominador. Mostrar fonte→segmento descoberto→inventário esgotado→objeto digital existente→download válido→texto/OCR→aceito/quarantined→representante→split. Não limitar fluxo a PL inicial/justificativa nem esconder documentos sem data, numeração, autoria, tema ou proposição.

GH exige mapa source_collections/coverage_segments de Câmara e Senado, todas categorias atuais/legadas descobertas e todos anos/períodos enumeráveis até snapshot. Períodos anteriores a índices de proposições exigem coleções históricas oficiais. A inexistência de arquivo anual ou uma resposta vazia não prova ausência de toda produção naquele ano. Ano corrente é parcial; passado pode ganhar nova digitalização. Relatório distingue corpus recuperado, descrição sem digitalização, link indisponível, query não encerrada, limitação de acesso e erro de extração.

Câmara: reconciliar API/anuais com seções de ficha, relacionadas/tramitações, árvore/dossiê e acervos. Fixture de acessório disponível no portal e ausente API precisa sobreviver no inventário. Coleção/documento sem proposição têm metadata_checks próprios; fases distintas/numeração por colegiado e pontes document_phases mantêm semântica sem multiplicar texto. Taxonomia preserva codTipo+sigla+nome, inclusive sigla repetida/ausente. Arquivo de tramitações é por evento, não por ano original do projeto.

Senado: incluir encerrados e tipos antigos, processos+documentos+emendas/fases e acervos; verificar defaults e limites de datas/formatos/contagens. Não inventar paginação ausente da especificação. Consulta sem filtros recentes/em tramitação não atende GH. IDs novos/legados são aliases verificados, não fundidos por igualdade numérica.

Conferir completude de cada segmento por links/catálogo/paginação/controles oficiais disponíveis e diferenças de conjuntos; expected_count desconhecido permanece nulo. Divergências são classificadas individualmente; >1% inexplicadas é alerta proposto para investigação, e percentual baixo não autoriza omissão. Não anunciar “todos recuperados” com query pendente ou descrição sem arquivo digital. GH pode registrar closed_with_gaps, com todas lacunas e efeitos explícitos; alcance literal complete_discovered depende dos objetos disponíveis realmente recuperados.

Relatórios casa×fonte×coleção×ano/período×tipo mostram contagens de registros/documentos/páginas/bytes aceitos e perdas. Temas/autorias N:M contam IDs distintos, incluindo unknown/not_queried/query_error; soma de categorias pode exceder universo. Não filtrar deputados/tema penal/tipo PL/ano 2024 como requisito. 2022–2024 são somente amostras previamente observadas.

Homologação antes da escala: ambos adaptadores inventariam segmentos representativos de períodos antigos/intermediários/recentes e classes distintas. Pipeline deve reconhecer e preservar emenda, parecer/voto, substitutivo, redação, inicial/justificativa, dossiê/anais/diário quando encontrados. Critério inicial de leitura ≥90% dos objetos digitais amostrados, com falhas explicadas, é meta de homologação; não exclui estrato difícil nem é prova de cobertura histórica.

## 4. Extração Mac, OCR e limpeza

Amostra de homologação proposta: pelo menos 30 documentos aleatórios de cada casa, mais até 20 suplementares por casa para risco/diversidade; se menos disponíveis, censo do segmento. Estratificar ou suplementar por coleção/época/tipo/método (nativo/scan/misto/manuscrito), comprimento e autoria. Definir seed antes da medição. Suplementares não entram em estimativa simples de taxa. Repetir auditoria em novo lote/estrato/motor quando mudança de qualidade justificar, sem exigir leitura humana de todo corpus por regra fixa. Publicar tamanho/intervalo/limite de inferência.

No Mac, texto embutido é lido por PDFKit; somente páginas sem texto útil/corrompido exigem Vision. Consultar supportedRecognitionLanguages para fast/accurate e pt-BR na revision/build usados. Registrar helper source hash, macOS/SDK/compilador, engine/mode/idioma/correção/renderização/tempo por página. Tipo engine=pdfkit é nativo, não OCR; Apple Vision é engine de OCR. Falha de permissões/recursos é erro concreto registrado, não texto vazio aceito.

Benchmark OCR em mesmas páginas/imagens e resolução: comparar Vision fast/accurate e Tesseract somente se disponível. Isolar warmup/compilação/abrir PDF/renderizar/OCR; repetir ao menos 3 rodadas em pequena amostra com ordem controlada, medindo páginas/s, p50/p95, pico de memória e erros. Sem promessa de rapidez antes da execução. Modo accurate do helper de pesquisa também muda resolução/correção; comparação justa fixa essas variáveis ou declara configurações diferentes. No diagnóstico desta sessão houve consulta de idiomas, não benchmark nem instalação de Tesseract.

Comparar original e extração: ordem, artigos, incisos, números, negações, datas, autores e seções de cada categoria; em pareceres/votos, relatório e fundamentação; em emendas/substitutivos, alterações normativas; em diários/anais, ordenação/colunas/tabelas e reprodução de peças. Conteúdo substantivo desconhecido não é removido por falta de heading. A ausência de articulado/justificativa em parecer não é falha. Nomes/assinaturas substantivas preservados.

Métricas por página: tamanho, U+FFFD, proporção imprimível, caracteres/área, imagem e confiança/bbox quando o motor permitir; ausentes são nulos, não inventados. Alertas propostos <50 caracteres em página de conteúdo, >1% U+FFFD ou imprimível<95% levam à revisão, não exclusão automática de capa/assinatura. PDFKit também pode errar ordem/colunas, portanto nativo é auditado.

Obter transcrição humana de trechos críticos em pelo menos 10 páginas OCR por perfil/estrato auditado, ou todas se menos; CER/WER sem normalização que apague erro de número/negação. Meta proposta CER≤2% e zero erro substantivo conhecido nos itens aceitos auditados. Se fast falhar, avaliar accurate/segmentação/renderização e ampliar amostra; textos antigos/manuscritos podem permanecer quarantined com causa. Confiança do motor não substitui revisão. Tesseract é fallback/comparador, sem uso obrigatório se Vision atender critérios.

Limpeza mantém caso, acentos, numeração e estrutura, com diff/logs/hashes. Não “corrigir” norma/OCR por linguagem adivinhada, nem cortar texto citado substantivo. Remover artefatos de digitalização apenas por regra/evidência; nova versão de macOS/helper/regra exige extraction_id e auditoria novos. Outputs publicados permitem treinar em Colab sem rerodar OCR Mac.

Gate de extração por lote: todas páginas/artefatos contabilizados, perfis e regras aprovados, amostra auditada, nenhuma falha conhecida em item aceito, perdas por estrato publicadas. GH depende também de todos segmentos processados/estados reconciliados; passar um lote não certifica o histórico.

## 5. Deduplicação, famílias e contaminação

Fixtures: duplicação exata; mesma lei com boilerplate mas conteúdo diferente; versão que troca instituído/revogado; valor distinto; negação adicionada; documento compartilhado; cadeia transitiva A–B–C; componente entre anos/casas, texto reproduzido em dossiê/diário e documento 2026 de processo 1995; mudança de URL sem texto diferente; famílias atravessando ambos cortes temporais.

Conferir que hashes exatos não cruzam splits e componentes familiares globais entre anos/casas/coleções têm um split. Mention em diário/citação genérica não pode unir todas proposições mencionadas. Data desconhecida é permitida no group_hash, mas purgada na avaliação temporal. Verificar candidatos próximos entre conjuntos mesmo após a formação inicial; revisar pares de alta similaridade que escaparam. Incluir fixture de peça de uma página reproduzida em diário de 100p: Jaccard global baixo não pode ocultar containment. Validar construção de IDs/spans/unidades editoriais e intervalos de conteúdo distintos do container; quando a unidade não tiver data própria, fallback conservador à faixa do container fica registrado. Validar spans/unidades editoriais e que volume integral mais seus segmentos não entram duplicados no dataset; unidades distintas no mesmo arquivo não se unem apenas pelo container. Auditar ao menos 20 pares próximos e todos os componentes anormalmente grandes/ambiguidades, ou todos se menores. Zero exclusão de mudança substantiva conhecida; zero duplicata exata elegível atravessando splits; zero família aprovada dividida. Candidatos de alto risco não resolvidos ficam quarantine antes de tokenizer.

Publicar componentes, regras/limiares, representatives e decisões; não apenas porcentagem global. Split preserva os mesmos IDs até nova versão. Temporal_purged tem check específico: nenhum membro de família cruzando corte em train/validation/test e nenhuma data futura em treino; perdas e população final aparecem no relatório. Se proporções/alocação forem revistas, gerar split_version nova antes de treinar vocabulário.

## 6. Tokenizer e dataset

Provar procedência do treino por hashes dos IDs/textos elegíveis train e lista efetivamente consumida. Teste negativo: tentativa de adicionar item validation/test deve falhar no builder. Fixture exclusiva de held-out fornece texto sentinel para evidência complementar; a prova é lista/hash, não ausência de substring em vocabulário. Ordem/seed e amostragem, se houver, ficam gravadas.

Round-trip **exato dos bytes UTF-8 curados** nos itens de smoke e fixtures de português, espaços/quebras, símbolos jurídicos, tabs, emoji e grafias iguais a especiais. Nenhum UNK no esquema byte-level completo; PAD/BOS/EOS com IDs fixados, nunca reconhecidos como controle no texto ordinário. Vocab real e hash do tokenizer conferem com embedding; ids fora de faixa falham cedo.

Janelas: validar deslocamento target=input do próximo token, primeira previsão de texto após BOS, EOS uma vez por item, padding -100/loss_mask e ausência de atenção entre documentos. Documento curto, comprimento exatamente L/L+1 e múltiplas janelas garantem cada alvo real uma vez por passagem, sem perda do último token. Reconstituir cada item a partir de shard/index e comparar tokens/text hash. Publicar alvos válidos, percentuais de padding, tokens/byte e distribuição de comprimentos por split; estadísticas held-out são de avaliação, não de treino do tokenizer.

## 7. Modelo educacional

Checks CPU obrigatórios e pequenos, sem necessidade de corpus completo:

- Formato input int64[B,L] → logits[B,L,V]; d divisível por cabeças, L≤contexto, IDs válidos e máscaras compatíveis. Config inválida gera mensagem concreta.
- Causalidade: com eval/dropout=0, alterar tokens futuros j>i não muda logits até i dentro da tolerância numérica declarada. Comparar atenção em fixture minúscula com cálculo matricial de referência e triangular inferior.
- Padding: mesma sequência curta sozinha e com PAD à direita mantém logits/loss nas posições válidas; targets ignorados não alteram CE. Sem NaN em queries totalmente PAD; batch sem alvos é rejeitado ou pulado explicitamente.
- Gradientes finitos e não nulos nos componentes esperados; passo de otimizador altera pesos; tying realmente compartilha parâmetro e contagem única. Uso de PAD não depende de embedding permanecer zero.
- Geração: modo eval/no_grad, contexto respeitado, seed/sampling registrados; EOS encerra geração segundo política. Não confundir fluência curta com conhecimento factual.

Memorização de lote pequeno: fixture sintética fixa de 2–4 sequências, modelo minúsculo, dropout=0, LR/seed registrados, até 500 updates CPU com early stop. Meta proposta: CE≤0,1 e acurácia next-token≥99% em alvos válidos, sem vazamento de gradiente no teste. Se não alcançar, investigar causalidade/alvos/otimizador antes de escalar. Isso é diagnóstico de capacidade e mecânica, não avaliação científica. Tempo não é prometido; registrar teto/resultado real.

## 8. Loss, checkpoints e persistência

Loss validation é soma NLL / soma de alvos válidos no conjunto fixo, nunca média não ponderada de batches. Desativar dropout, usar eval/no_grad, não alterar otimizador. Registrar baseline de modelo inicial, curvas por updates/tokens/bytes e frequências de avaliação. Smoke exige perdas finitas e treino do lote fixo decrescente; não exige que cada ponto validation caia. Divergência sustentada, NaNs, colapso ou gap extremo dispara investigação. Um treino curto pode não demonstrar melhora de generalização; relatar isso sem declarar sucesso científico.

Retomada CPU: fixture N+M updates sem interrupção versus N → save/load → M, mesmo ambiente determinístico, dropout/RNG e sampler ativos. Comparar próximo batch, global_step, LR, tokens, parâmetros e estado do otimizador; tolerância definida, igualdade exata quando operações permitirem. Avaliação antes/depois do save deve coincidir. Testar overflow AMP/mocks de update descartado, fronteira de acumulação, checkpoint truncado e latest apontando incompleto. Caso overflow → checkpoint → retomada compara tokens_seen/tokens_for_successful_updates/budget_counter/scaler e próximo batch; clipping deve ocorrer após unscale. Mudanças BF16↔FP16 são testadas como transição identificada, sem promessa de trajetória igual. Scheduler não pode avançar em update descartado.

GPU/Drive: save local → cópia/releitura/hash → COMPLETE → nova sessão ou disco local descartado → download/load → pelo menos um update/avaliação. Testar recuperação de cópia anterior quando última incompleta, e retenção que preserve duas versões completas/best. Verificar métricas/config/tokenizer/manifestos/generações persistentes além dos pesos. Fixture de rollback mantém ramo abandonado separado por segment_id e prova que curva ativa não mistura steps repetidos; resolver não pode escolher checkpoint de outra run. No próprio ambiente, medir diferença de uma continuação curta; em GPU/stack diferente não exigir identidade bit a bit, documentar alteração e tolerância.

## 9. Protocolo de medidas e comparação

Perplexidade `exp(NLL média por alvo)` só é comparável diretamente com mesmo tokenizer, corpus, política de limites/contexto e alvos incluídos. Publicar loss token com EOS e loss só de texto separadas, denominadores e unidade. Vocabulários diferentes alteram granularidade e parâmetros; não ranquear tokenizers pela menor perplexidade bruta.

### NLL por byte — protocolo comum `byte_nll_v1`

1. Congelar uma **lista comum** de itens e text_sha256, mesma limpeza, mesmo split de avaliação, sem itens duplicados. O text UTF-8 exato é a unidade; dividir avaliação por tipos de seção/estrato quando necessário.
2. Escolher K em bytes usando apenas train e a menor capacidade de contexto dos modelos comparados. Para BPE byte-level, K≤L_min−1 garante margem de BOS com o limite de um token por byte, que ainda deve ser verificado. Ponto de partida proposto K=min(512,L_min−1). Outros tokenizers precisam prova do limite ou novo protocolo. K e política são congelados ANTES do teste.
3. Segmentar deterministicamente cada texto em trechos não sobrepostos de no máximo K bytes, cortando no último limite de code point UTF-8 válido; não normalizar nem inserir/remover espaço. Cada byte original é contado exatamente uma vez. Segmentos respeitam limites documentais; contexto é resetado entre segmentos, igual para todos.
4. Para cada segmento, tokenizar reversivelmente sem reconhecimento de grafias de especiais, inserir somente BOS como prefixo. Predizer **todos** tokens de texto incluindo o primeiro; sem EOS/PAD/markers artificiais no numerador. Atenção causal; modelo eval, dropout off; mesmo segmento físico de texto em cada modelo, sem truncamento. Se tokenização ultrapassar L de algum candidato, falhar e revisar protocolo pelo treino, não truncar held-out silenciosamente.
5. Somar NLL natural sobre tokens de texto em todos os segmentos: `nats_per_byte = sum(-log p(token | BOS, tokens anteriores no segmento)) / sum(bytes UTF-8 dos segmentos)`. `bits_per_byte = nats_per_byte / log(2)`. Pesos por bytes, sem média simples de ratios dos documentos. Controles são contexto, jamais denominador de bytes ou NLL pontuada.
6. Relatar K, contagem de documentos/segmentos/bytes/tokens por modelo, nats e bits/byte, contexto e hashes. O reset limita contexto e pode elevar loss; resultado desse protocolo não equivale à loss do treino com janelas de contexto próprias.

A medida padroniza unidade e texto avaliado; não elimina diferenças de segmentação/contexto interno, modelo ou orçamento. É NLL do caminho de tokenização determinístico, não uma prova de ranking universal de probabilidades sobre toda string. Comparar também compressão tokens/byte e custo/throughput. Se corpus/splits mudarem, rodar um conjunto comum congelado ou declarar avaliações não comparáveis.

### Desenho científico posterior ao MVP

Separar tokenizer, escala e composição em ablações controladas; mesmo corpus/splits/protocolo, orçamento de recursos definido e múltiplas seeds (meta posterior ≥3, sujeita à viabilidade medida). Vocabulário muda embedding; reportar parâmetros totais e do Transformer e controlar o que for pertinente à hipótese. Tokens iguais entre tokenizers podem expor quantidades diferentes de texto: relatar bytes únicos/consumidos, passes e compute. Comparar orçamento em bytes/passes e, em análise separada, compute/tempo, sem misturar conclusões.

Test é usado após decisões/protocolo congelados; avaliação exploratória usa validation. Bootstrap/intervalos por **família** (unidade independente), não por token. Para representações legislativas, planejar sondas com rótulos independentes, splits por família e baseline lexical/aleatório; nomes de autores e headings podem ser atalhos. Dicionário penal/sentimento do artigo é rótulo fraco e não mede aprendizado jurídico sozinho. Esses experimentos científicos, instruction tuning e RAG ficam após entrega funcional; Senado, todos anos e versões posteriores já integram a obtenção inicial de dados.

## 10. Evidência mínima por gate

G0: contratos/ownership/configs coerentes e fixtures comuns. G1: inventário reconciliado das duas casas, tipos e segmentos históricos descobertos. GH: cobertura histórica fechada/limitações explícitas, distinta de G2 de um lote. G2: release curada com auditoria, permissões e split sem vazamento. G3: tokenizer/tokens identificados e round-trip/alvos verificados. G4: modelo/loop/checkpoint passam CPU. G5: benchmark estável, persistência e retomada em nova sessão demonstradas. G6: GH mais release histórica e treino curto/métricas/geração/retomada identificados; smoke em sub-release é progresso parcial, nunca conclusão de todos dados. Não liberar gate baseado em parecer de outro modelo quando ferramenta determinística ou artefato auditável puder responder.
