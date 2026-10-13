# Decisões técnicas — revisão 2.0.0

Data: 2026-10-07. Revisão do usuário: corpus histórico de Câmara e Senado, todos anos/tipos disponíveis e versões posteriores; Mac/PDFKit/Apple Vision. Status das escolhas de implementação abaixo: **propostas para implementação**, exceto fatos explicitamente identificados. Evidências e limites de acesso estão em [fontes e diagnóstico](FONTES_E_DIAGNOSTICO.md); parâmetros são hipóteses ajustáveis, não resultados experimentais. Mudanças passam pelo coordenador e atualizam contratos, configuração e relatório.

## D01 — Fontes múltiplas e descoberta histórica

**Problema:** “todos” não cabe em uma coorte PL/ano ou na listagem padrão da API. **Alternativas:** API apenas; arquivos anuais; inventário reconciliado de API+portal+dossiês+acervos. **Escolha:** fontes oficiais de Câmara e Senado, todos tipos/anos descobertos, com source_collections/legislative_types/coverage_segments e data-corte; preservar códigos/siglas/nomes antigos e casos sem sigla. Datas de apresentação, numeração, publicação/juntada e tramitação permanecem separadas.

**Justificativa:** API não garante todos acessórios/textos. **Evidência:** investigação oficial encontrou DVT no portal da Câmara ausente no detalhe/relacionadas da API; catálogos históricos têm períodos e lacunas próprios. Senado tem processos/documentos/emendas e tipos encerrados. Links e limites em FONTES_E_DIAGNOSTICO. **Rever se:** índices/rotas mudarem ou nova coleção oficial for identificada; incorporar por snapshot/mapping novo, sem apagar registros nem declarar acervo inexistente por resposta vazia.

## D02 — Todos os anos e tipos, homologação em lotes

**Problema:** usuário priorizou base histórica ampla para treinar com PLP/PEC/emendas/pareceres/substitutivos e demais textos. **Alternativas:** manter PL inicial 2024; coletar tudo sem auditoria; coletar acervo-alvo completo após homologação de lotes. **Escolha:** todo acervo legislativo textual recuperável das duas casas até snapshot, sem início universal arbitrário; lotes pequenos são teste operacional, não redução definitiva de escopo. Anais/diários/dossiês/transcrições oficiais são coleções próprias quando disponíveis.

**Justificativa:** atende ao objetivo de composição ampla mantendo retomada/qualidade. **Evidência:** instrução explícita do usuário; exemplos de catálogos oficiais antigos e recentes, sem garantia de digitalização total. **Rever se:** regras de uso, objeto inexistente ou falha comprovada impedirem um item; registrar lacuna em vez de excluir categoria inteira. 2024 deixa de ser candidato a limite do corpus; continua só amostra investigada. GH distingue cobertura histórica do G2 de um lote.

## D03 — Referência do artigo anterior

**Problema:** aproveitar experiência sem transportar seleção penal e ementas. **Alternativas:** RDS no treino; copiar coletores; novos adaptadores oficiais aproveitando padrões/IDs. **Escolha:** usar conhecimentos de CSV/endpoints/IDs e RDS para diagnóstico; inventário novo amplo, inclusive tipos/autorias não presentes no artigo. Trechos de código precisam de condições de incorporação/redistribuição esclarecidas pelo coordenador.

**Justificativa:** RDS inspecionado não contém íntegros nem autores/documentos/versionamento. **Evidência:** leitura e scripts fixados no commit registrado nas fontes. **Rever se:** surgirem originais com proveniência e condições de uso; não misturar automaticamente. Regex/sentimento seguem como rótulos fracos fora do corpus/modelo inicial.

## D04 — R/Python e adaptador Mac

**Problema:** manter ciência de dados em R e usar OCR nativo disponível. **Alternativas:** todo Python; RDS interoperável; R+Swift na camada documental e Parquet para Python. **Escolha:** R coordena inventário/download/curadoria e chama adaptador Swift/PDFKit/Vision do projeto; Parquet tipado+manifesto é fronteira para tokenizer/modelo/treino/avaliação Python. Extração nativa roda no Mac antes do Colab.

**Justificativa:** combina experiência do pesquisador e capacidade local, com camada de treino independente. **Evidência:** skill pdf-to-markdown/helper inspecionados, frameworks Apple e diagnóstico runtime; Arrow suporta contrato interoperável. **Rever se:** escalabilidade/portabilidade medida exigir outro motor; manter schema/proveniência e corpus publicado, sem reescrever treino para ler PDF.

## D05 — Todas as fases documentais elegíveis

**Problema:** seleção exclusiva de articulado+justificativa excluiria o escopo novo. **Alternativas:** inicial apenas; juntar tudo no mesmo texto por processo; uma unidade por documento/versão, com papéis e conteúdo preservados. **Escolha:** textos iniciais, justificativas, emendas/subemendas, pareceres/votos/relatórios, substitutivos, redações/versões e demais textos legislativos, além de unidades arquivísticas/diários/anais disponíveis. Preservar tipo/papel original e mapping, seções/ordem e vínculo com processo quando houver; documentos sem processo continuam possíveis.

**Justificativa:** conteúdo das fases posteriores é objeto de aprendizado solicitado. **Evidência:** APIs/portais têm classes heterogêneas; usuário mudou escopo. **Rever se:** conteúdo for ilegível/corrupto/sem origem ou condição de uso conhecida, por decisão de item. Parecer não precisa ter “Art.1º” ou justificativa; documento sem data não é excluído automaticamente de group_hash. Não fundir várias versões nem cortar citações jurídicas substantivas só por repetição.

## D06 — PDFKit e Apple Vision como caminho principal

**Problema:** extração/OCR deve usar ambiente Mac com rapidez e precisão verificável. **Alternativas:** Tesseract como baseline obrigatório; OCR de tudo; PDFKit primeiro + Vision seletivo. **Escolha:** texto embutido por PDFKit; páginas sem texto útil/corrompido via Vision fast pt-BR quando suportado e auditado, accurate para páginas/estratos que precisem. Consultar idiomas/revision/build, guardar renderização e usesLanguageCorrection. Tesseract/Poppler são fallback/comparadores opcionais de portabilidade.

**Justificativa:** escolha do usuário e stack disponível localmente; evita OCR desnecessário. **Evidência:** diagnóstico neste Mac compilou consulta Vision e confirmou pt-BR em fast/accurate revision 3; tesseract/pdftotext não encontrados no PATH. O helper da skill usa esses frameworks, mas não entrega sozinho todo contrato. **Rever se:** benchmark de páginas antigas/manuscritas/mistas revelar erros, custo ou idioma incompatível. Comparar mesmas imagens, resoluções, correção linguística, CER/WER, páginas/s, p50/p95 e memória. Sem alegar que é mais rápido que Tesseract antes de medir; comparação não realizada nesta revisão.

## D07 — Proveniência, armazenamento e Git

**Problema:** arquivos podem mudar na mesma URL, falhar parcialmente ou multiplicar nas junções. **Alternativas:** pastas por PL e sobrescrita; blobs imutáveis por hash + tabelas relacionais. **Escolha:** IDs com namespace, documento lógico separado de versão binária, capturas append-only e blobs SHA-256; Parquet/JSON para contratos. Autoria/tema/relacionamentos são pontes; um item de treino aparece uma vez. DATA_ROOT externo; código, locks e manifestos leves no Git futuro.

**Justificativa:** rastreabilidade, reprocessamento e economia sem perder história. **Evidência:** resposta HTML em URL aparentemente PDF no artigo e joins N:M nos scripts. **Rever se:** escala tornar arquivos pequenos impraticáveis; agrupar em shards/archives sem perder hashes/índice. Drive precisa marcador de conclusão e releitura, sem supor atomicidade de rename remoto.

## D08 — Uso e redistribuição

**Problema:** conteúdo oficial e anexos de terceiros podem ter regras diferentes. **Alternativas:** supor CC0; impedir todo uso; classificação por evidência e escopo. **Escolha:** registrar termos oficiais/data/atribuição; distinguir metadados, textos legislativos oficiais e anexos; internal research e release redistribuível têm elegibilidade própria. Não atribuir licença nominal sem evidência. Código anterior sem licença exige decisão explícita do titular antes de incorporar trecho substancial.

**Justificativa:** tornar condições rastreáveis sem bloquear planejamento. **Evidência:** políticas oficiais e Lei 9.610/1998, art. 8º IV, quanto a atos oficiais, conforme fonte oficial citada; isso não torna todos os anexos atos oficiais. **Rever se:** termo mudar, documento misturar obras de terceiros ou finalidade de publicação mudar. Dúvidas afetam esses itens, não suspendem criação de contratos ou inventário.

## D09 — Limpeza e deduplicação

**Problema:** ruído editorial e duplicações distorcem distribuição; pequenas revisões podem alterar norma. **Alternativas:** lowercase/regex agressiva; nenhuma limpeza; transformações mínimas com histórico. **Escolha:** preservar caso e estrutura; limpar artefatos provados e versionar cada regra. Dedup binária, exata textual e candidatos próximos com diff/revisão; diferenças substantivas permanecem. Nunca usar alta similaridade como exclusão automática de versão legislativa.

**Justificativa:** leis têm negações, valores e incisos sensíveis. **Evidência:** artigo de Lee et al. apoia controlar duplicações; sem transferir limiares de corpus web ao legislativo. **Rever se:** falsos positivos/negativos na amostra excederem critérios; calibrar em treino/fixtures auditadas e publicar política. Excluir sem evidência é defeito bloqueante.

## D10 — Famílias globais e datas documentais

**Problema:** versões entre anos/casas e textos reproduzidos em diários/dossiês contaminam avaliação. **Alternativas:** split por ano/casa/linha; por processo; componentes globais com evidência. **Escolha:** formar famílias sobre todo snapshot das duas casas antes do split/tokenizer; group_hash 80/10/10 inicialmente, proporções reais publicadas. Temporal_purged opcional usa data própria do conteúdo/versão, intervalo de coleções e relações; famílias cruzando corte ou data incerta são purgadas da avaliação temporal.

**Justificativa:** documento 2026 de projeto 1995 não pode ser retrospectivamente treinado como texto 1995. **Evidência:** arquivos de tramitação atuais sobre projetos antigos e fases/versões oficiais. **Rever se:** componentes enormes por citações genéricas, poucas famílias ou mapping indevido; revisar arestas bind, jamais quebrar família aprovada para atingir proporção. Mention em diário não une automaticamente todos projetos; peça reproduzida demanda detecção de containment por passagens, não só Jaccard global. Unidades editoriais independentes de volume composto usam spans e regra versionada, sem treino duplicado volume+segmentos. Release incremental nova pode unir componentes: recalcular split global e inputs do tokenizer.

## D11 — Tokenizer

**Problema:** português jurídico exige cobertura sem normalização destrutiva e permite estudar segmentação. **Alternativas:** tokenizer pronto GPT-2; BPE byte-level novo; Unigram/SentencePiece; caractere/byte puro. **Escolha:** BPE byte-level próprio, treino exclusivo em split train, vocabulários candidatos 8.192/16.384 com especiais incluídos; caso/acento/whitespace preservados; ByteLevel sem espaço artificial e decoder compatível. Byte puro serve como baseline futuro ou fixture; Unigram é experimento posterior.

**Justificativa:** implementação especializada pode tratar merges sem esconder Transformer; bytes garantem caminho para caracteres observados quando alfabeto completo é corretamente configurado. **Evidência:** documentação oficial Tokenizers. **Rever se:** tokenização de artigos/incisos, compressão, tempo ou round-trip falhar; investigar configuração antes de aumentar vocabulário. A grafia de BOS/EOS no texto não pode produzir IDs de controle. Medir tokens/byte, tokens/caractere, distribuição de comprimentos, vocabulário efetivo e raridade no treino; não presumir tamanho ótimo.

## D12 — Sequências e limites documentais

**Problema:** packing ingênuo permite atenção entre proposições e distorce alvos. **Alternativas:** concatenação com EOS; packing com máscara de blocos; uma janela de um documento por amostra. **Escolha:** uma janela/documento, BOS/EOS uma vez por item e PAD à direita, targets -100 sem alvo, máscara causal + padding; janelas com uma posição compartilhada e targets sem repetição por passagem, conforme contrato.

**Justificativa:** primeira versão auditável, mesmo com maior padding e perda de contexto em janelas longas. **Evidência:** invariante verificável em fixtures; não há throughput medido. **Rever se:** padding/baixa ocupação comprometer benchmark; packing exige novo sequence_policy_version, máscara de blocos e provas contra contaminação. EOS alone não bloqueia atenção cruzada.

## D13 — GPT educacional

**Problema:** aprender cada componente e manter treino possível no hardware disponível. **Alternativas:** pesos prontos/Trainer; nn.Transformer abstrato; decoder explícito inspirado no livro. **Escolha:** embeddings de tokens e posições aprendidas, atenção multihead causal Q/K/V explícita, pre-LayerNorm, residual, MLP GELU com expansão 4d, dropout configurável, projeção final com tying configurável (proposta inicial true). Sem pesos pré-treinados nem Hugging Face Trainer. FP32/CPU verifica mecanismo; GPU e AMP vêm depois.

**Justificativa:** código transparente e alinhado ao percurso dos capítulos 2–5. **Evidência:** livro/repositório oficial; arquitetura escolhida é adaptação, não cópia de um preset 124M. **Rever se:** experimentos justificarem RoPE, RMSNorm, SDPA, flash, compile, checkpoint de ativações ou tying diferente; cada otimização precisa equivalência numérica/testes e benchmark próprios.

Candidatos de benchmark, **não configuração final**: n_layers=6, d=384 ou 512, n_heads=6 ou 8 respectivamente; L=256 ou 512; V=8.192 ou 16.384. Contagem aproximada com tying: Vd + Ld + n_layers·12d² + termos lineares de bias/norm. Exemplos aproximados com L=512: (V=8.192,d=384) ~14,0M; (16.384,384) ~17,1M; (16.384,512) ~27,6M. A implementação contará parâmetros únicos exatamente, registrando biases, normas e tying. Smoke model pode ser muito menor; o alvo GPU permanece 10–30M condicionado a corpus/hardware, sem escalar só para cumprir faixa.

## D14 — Treinamento, orçamento e checkpoints

**Problema:** sessões interrompíveis e experimentos com rastreabilidade. **Alternativas:** loop no notebook; Trainer; módulos com CLI e checkpoint completo. **Escolha:** loop PyTorch explícito, AdamW, scheduler warmup+decay com orçamento de updates definido na config, clipping configurável e loss por alvo válido. Acumulação usa soma de CE dividida pelo total de alvos válidos de todo o update, não média das médias de microbatches de comprimentos diferentes. Pesos/estados base FP32 com autocast na GPU; FP16 usa GradScaler, unscale antes de clipping e scheduler só em update aplicado; BF16 somente com suporte; CPU FP32. Contadores consumidos e de updates válidos são persistidos com budget_counter explícito; mudanças de precisão ficam em segmento novo conforme contrato.

**Justificativa:** evitar perda de estado e diferenças invisíveis em batching. **Evidência:** documentação PyTorch de checkpoints e precisão. **Rever se:** divergência numérica, OOM, custo de I/O ou memória dos estados inviabilizar candidatos. Checkpoint apenas em limite de update, com sampler e RNG; não prometemos recuperar trabalho desde o último checkpoint persistido. Acumulação aumenta batch efetivo, mas não faz pesos/otimizador ou uma sequência individual caberem na VRAM. Reduzir microbatch/contexto/modelo ou aplicar otimizações verificadas atende esse problema.

Orçamento inicial será um trecho curto com limite de tempo/tokens/steps configurado após benchmark e release identificada. Para treino principal, todos os itens train de todas casas/anos/tipos entram na lista do sampler, com consumo real por estrato; smoke não afirma que percorreu todo histórico. Taxa real = alvos válidos/segundo em updates completos; estimar T = alvos planejados / taxa + avaliação + persistência + staging, com intervalo medido e margem. Registrar épocas efetivas, bytes únicos, repetições e tokens consumidos. Nenhum número de tokens, horas ou custo do corpus está pré-fixado. Final científico pode variar orçamento em tokens e bytes; comparações devem dizer qual recurso foi controlado.

## D15 — Colab e persistência

**Problema:** benefício de assinatura não define GPU nem janela contínua. **Alternativas:** Colab + Drive; Colab lendo Drive sempre; GPU dedicada. **Escolha:** Colab como primeira bancada, confirmação do benefício/saldo na conta, preflight a cada sessão, dados/shards copiados para disco local, checkpoints/manifestos/config/métricas em Drive com verificação. Medir leitura direta vs staging no mesmo shard; preferir menor tempo total e menos falhas.

**Justificativa:** sessões efêmeras exigem recuperar estado externamente. **Evidência:** FAQ oficial e ajuda AI Pro, com divergência de idiomas registrada em [COLAB.md](COLAB.md). **Rever se:** nenhum candidato couber, staging+checkpoints >20% do tempo útil, retomada falhar, disponibilidade impedir concluir orçamento dentro do calendário definido pelo pesquisador ou saldo/custo observado for incompatível. Medir ao menos duas sessões independentes para decisão de migrar; falha de integridade já bloqueia treino prolongado. Outro ambiente será decisão posterior, sem contratação nesta etapa.

## D16 — Avaliação e medidas comuns

**Problema:** perplexidade muda com vocabulário/segmentação e geração isolada não demonstra representações legislativas. **Alternativas:** perplexidade apenas; loss por byte; tarefas externas. **Escolha:** loss/perplexidade por tokenizer identificado + protocolo byte comum descrito em [VALIDACAO.md](VALIDACAO.md), curvas, cobertura/qualidade e prompts fixos sem ajuste pelo teste. A entrega distingue corpus histórico coberto (GH) e funcionamento do modelo; smoke em sub-release não conclui objetivo histórico nem superioridade científica.

**Justificativa:** comparar distribuição sobre o mesmo texto e orçamento explicitado; tokens têm unidades diferentes. **Evidência:** definição operacional de NLL e documentação de tokenização; avaliação de representações ainda não realizada. **Rever se:** tokenizer não fizer round-trip, contexto truncar segmentos comuns ou corpus curado mudar. Comparações científicas posteriores exigem desenho fatorial/ablação controlando corpus, splits, orçamento, sementes e confusões de parâmetros do embedding; sondas de representação precisam rótulos independentes e baseline, nunca regex do artigo tratada como ouro.

## D17 — Senado integrado desde a obtenção inicial

**Problema:** Senado não é mais expansão opcional e possui APIs/fases/legados distintos. **Alternativas:** adiar Senado; tratar como Câmara; adaptador independente normalizado. **Escolha:** frente 10 exclusiva em R/inventory/senado, em paralelo à Câmara 01; fonte atual processo, documentos/emendas e vocabulários, catálogo/pesquisa/anais/diários oficiais como controles históricos. Preservar idProcesso, codigoMateria legado, colegiado/fase e aliases com evidência.

**Justificativa:** trabalho independente e diferenças reais de semântica/paginação. **Evidência:** OpenAPI atual documenta defaults recentes/em tramitação e deprecações; não promete ano inicial universal. **Rever se:** rotas forem descontinuadas ou cobertura faltar; validar substitutos e alternativas oficiais. Não inventar page/limit onde não documentados, nem supor consulta sem filtros encerra histórico. Contratos/agregador comum são exclusivos do coordenador.


## D18 — Publicações históricas e completude verificável

**Problema:** Arquivos/diários/anais podem anteceder índices de proposições e repetir peças individuais. **Alternativas:** ignorar; tratar todo acervo físico como digital; registrar coleções/unidades e disponibilidade. **Escolha:** incorporar coleções legislativas textuais oficiais digitalmente disponíveis, guardar códigos de referência/volumes/edições e proveniência; descrição sem imagem permanece registro de lacuna. Documento pode ter primary_proposition_id nulo. Cobertura por fonte×coleção×ano×tipo e mapa de arquivos disponíveis/obtidos/aceitos. **Justificativa:** objetivo todos anos, sem fabricar cobertura online. **Evidência:** catálogos oficiais das duas casas, detalhes em FONTES. **Rever se:** surgir nova digitalização/coleção/mapping; release nova e rechecagem global de dedup/splits.
