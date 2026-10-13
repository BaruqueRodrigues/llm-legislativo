# Auditoria da implementação e plano de continuidade por subagentes

**Data da auditoria:** 2026-10-07  
**Escopo:** estado encontrado no checkout, código, documentação, manifests disponíveis, configuração de armazenamento e verificações executadas nesta revisão.

## Conclusão da auditoria

O repositório já tem uma implementação substancial: coletores incrementais, downloads com hashes, extração macOS, curadoria, BPE, Transformer, treino, persistência Colab e avaliação. As suítes Python passam. O modelo também tem evidência suficiente para o gate de CPU G4.

O projeto ainda não tem o corpus histórico nem uma execução científica completa. A auditoria identificou caminhos de saída no checkout e falhas OCR escaneadas; essas falhas de infraestrutura foram corrigidas e revalidadas depois. Os manifests disponíveis continuam sendo probes/pilotos, as coletas históricas não foram concluídas e esta cópia não tem metadado Git. O plano abaixo continua o que já existe, sem pedir aos agentes que recriem módulos prontos.

## Evidências verificadas na auditoria inicial

Os bullets desta seção registram o estado de entrada em 2026-10-07. A seção “Revalidação e decisão de fluxo” no fim registra o estado posterior às correções.

- **Python:** .venv/bin/python -m pytest -q passou com **137 testes** na auditoria inicial.
- **R:** as suítes de contratos comuns, inventário da Câmara, inventário do Senado, downloads e curadoria passaram. A suíte tests/extraction falhou: pelo menos dez asserções dos casos escaneado/misto receberam method=none, engine=none e texto vazio. Uma execução direta do helper em tests/extraction/fixtures/scanned_image.pdf confirmou texto OCR vazio. performVisionOCR converte erros de Vision em resultado vazio, sem preservar o erro que explicaria a falha. Os testes de download também emitem avisos porque mdls não consegue ler metadados dos PDFs neste ambiente; Arrow emite avisos de acesso a sysctl bloqueado.
- **Git:** git rev-parse falhou porque esta pasta não contém .git. Não foi possível verificar diff, commits ou arquivos rastreados.
- **Armazenamento:** .gitignore exclui data/, staging/ e runs/, mas isso não protege o checkout de gravações e não é possível verificar rastreamento sem Git. configs/data/history.yaml usa data_root: "data". O publicador de extração tem fallback para repo_root/data/staging/extraction; o de curadoria também grava em repo_root/data/staging/curation. scripts/curate.R busca inventários e extrações em caminhos repo_root/data/..., e o treino usa runs relativo ao projeto.
- **Artefatos no checkout:** existem aproximadamente 3,2 MB em data/ e 3,8 MB em staging/; não os removi nem movi.
- **Artefatos externos:** /Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA tem cerca de 45 MB e 713 arquivos. O piloto da Câmara preserva 22 PDFs verificados, 127 páginas extraídas por PDFKit e 22 itens curados. Todos os 22 têm kind=unknown, não há revisão humana, e os splits são 21 train, zero validation e um test.
- **Senado:** há um manifest antigo de uma consulta all_years/status:S com 10.780 processos, enquanto status:N falhou com HTTP 400 e Anais/Diários continuam pendentes. Outros manifests de 2024 listam 4.943 processos. Esses resultados não demonstram que todos os anos, fases ou documentos foram enumerados. Os cinco downloads de amostra do Senado foram recusados como HTML de verificação; não se deve contornar essa proteção.
- **Tokenizer:** há um BPE piloto treinado nos 21 itens train da Câmara (177.107 bytes; vocabulário efetivo 5.053; 39.331 tokens de corpo). Round-trip e separação dos shards do piloto estão testados; isso não libera G3 para o corpus histórico.
- **Gates:** G0 tem os contratos/esquemas/fixtures, mas sua regra de isolamento de dados falha nos defaults atuais. G1 é parcial. G2 só tem homologação limitada da Câmara. GH está pendente. G3 é piloto. G4 está aprovado para as provas CPU. G5 não foi comprovado em Colab/Drive real; o preflight local não encontrou CUDA nem Drive. G6 não tem avaliação ou geração de checkpoint treinado no corpus.
- **Relatórios:** os cabeçalhos de docs/reports/03.md e 04.md declaram G2/GH aprovados; 05.md, 06.md e 07.md usam linguagem de aprovação ampla. Isso conflita com os próprios denominadores e limitações dos manifests e com docs/STATUS_IMPLEMENTACAO.md. O status geral deve prevalecer até cada relatório ser atualizado com evidência do gate correspondente.
- **Binários locais:** R/extraction/native/macos/bin/ contém executáveis Mach-O arm64 e o código de compilação cria cache em R/extraction/native/macos/.cache. São artefatos dependentes da plataforma dentro da árvore de código; devem ser gerados em cache externo e excluídos do baseline versionado.

## Estado dos gates após esta revisão

| Gate | Estado comprovado | Trabalho que falta |
|---|---|---|
| G0 — Fundação | Esquemas, configuração e testes comuns existem; isolamento de armazenamento incompleto | Tornar o DATA_ROOT externo obrigatório nos caminhos de produção e remover fallback para diretórios do checkout |
| G1 — Inventário | Adaptadores e probes oficiais existem, sem censo histórico aprovado | Enumerar fontes, períodos, classes, documentos, fases e filas pendentes das duas casas |
| G2 — Release curada | 22 documentos reais da Câmara em piloto limitado | Resolver cobertura documental das duas casas e produzir release representativa com classificação e qualidade auditáveis |
| GH — Fechamento histórico | Manifests parciais e filas retomáveis | Reconciliar todas as coleções/segmentos e fechar pendências como concluídas ou lacunas documentadas |
| G3 — Tokens | Tokenizer/shards de piloto e testes | Treinar de novo apenas no split train da release histórica; produzir shards train/validation/test |
| G4 — CPU/modelo | Aprovado: testes de modelo/treino e suíte Python completa passam | Reabrir somente se mudanças no modelo ou no loop quebrarem as provas |
| G5 — GPU/persistência | Código e testes locais existem | Executar no Colab com Drive real e comprovar retomada em sessão nova |
| G6 — Avaliação | CLI e métricas implementadas | Avaliar checkpoint histórico real, produzir métricas e geração reproduzíveis |

## Plano de execução para a equipe de agentes

Os prompts existentes em docs/subagents/ continuam sendo a base de escopo e ownership. As tarefas abaixo são complementos orientados pelas lacunas desta auditoria. O coordenador deve enviar a cada agente o prompt completo da sua frente junto com a tarefa de continuidade, respeitar a matriz de AGENTS.md e integrar as entregas antes de liberar as dependências seguintes.

### Onda 0 — Coordenador: preparar a cópia e fechar o bloqueio de armazenamento

1. Preservar o estado completo atual. Por instrução do usuário, não executar comandos Git nem criar metadados Git até o término da implementação. Manter artefatos de dados fora do checkout e documentar o estado sem alegar rastreabilidade de Git; auditar baseline somente após a conclusão funcional.
2. Corrigir a resolução de dados de forma centralizada. Em produção, todos os CLIs devem exigir DATA_ROOT absoluto fora do checkout. Configuração de teste pode usar diretório temporário; modo de amostra deve ser explicitamente sintético. Remover fallbacks dos publicadores e entradas que leem repo_root/data; cobrir inventário, download, extração, curadoria, tokenizer, treino, avaliação e checkpoints.
3. Fazer a suíte de extração ser executável de fonte. Compilar Swift para cache fora da árvore de código e registrar hashes de fonte/binário no manifesto. Não incluir executável arm64 no código versionado.
4. Atualizar docs/STATUS_IMPLEMENTACAO.md e alinhar cabeçalhos/conclusões dos relatórios 02–09 com os gates comprovados. Conservar resultados anteriores como histórico identificado, sem mantê-los como aprovação atual.
5. Só liberar a coleta histórica depois de um teste que demonstre que nenhum caminho padrão grava no checkout. Preservar os artefatos existentes; qualquer migração deve verificar SHA-256 antes e depois.

**Critério de saída:** configuração e testes comprovam DATA_ROOT externo em todos os estágios; relatórios mostram status coerente; binário/helper é gerado de fonte fora do checkout. Baseline Git fica explicitamente adiado até o usuário liberar trabalho com Git.

### Onda 1 — Agentes 01 e 10: terminar os inventários oficiais

Trabalhar em paralelo nos diretórios exclusivos já definidos em AGENTS.md. O Agente 01 completa a descoberta Câmara por segmento histórico, tipo, portal, arquivos anuais, dossiês e documentos acessórios; retoma as tarefas de enriquecimento pendentes e classifica a proveniência de cada link. O Agente 10 executa o plano anual Senado correspondente, inclui processos encerrados, fases e filhos de cada processo e enumera Anais e Diários por volume/edição/ano, sem presumir continuidade.

Para cada coleção e segmento, registrar filtro real, intervalo coberto, unidade contada, consulta/snapshot, totais observados, cursor/paginação, falhas, pendências e evidência de exaustão. Substituir ou marcar manifests antigos all_years como superseded quando o desenho atual requer consultas anuais. Resposta vazia não encerra a descoberta histórica. Não declarar G1/GH com base em um ano, um endpoint ou um catálogo de tipos.

**Critério de saída:** inventário retomável de ambas as casas; todas as classes e coleções identificadas; nenhuma consulta incompleta marcada como cobertura concluída; relatório deixa explícito o que foi enumerado e o que não tem rota oficial disponível.

### Onda 2 — Agentes 02 e 03: downloads e extração com documentos reais

O Agente 02 consome as filas reconciliadas progressivamente e valida cada payload por conteúdo, tipo, hash e tamanho. Amplia a captura a todos os documentos elegíveis, não somente o texto inicial. Para o bloqueio do Senado, pesquisar somente rotas oficiais documentadas ou conjuntos oficiais publicados. Não automatizar nem contornar a página de verificação; registrar os IDs/URLs e o bloqueio como lacuna se não houver rota suportada.

O Agente 03 corrige primeiro a falha atual: nos fixtures escaneados, Apple Vision retorna texto vazio e a falha interna é silenciosamente convertida em página “blank”. Expor o erro, distinguir página em branco de página escaneada sem reconhecimento, verificar renderização/idioma/revisão do Vision e corrigir testes escaneados e mistos. Depois processar PDFs reais baixados, aplicar OCR seletivo por página e publicar métricas de qualidade. Medir fast/accurate em amostra real representativa; não afirmar que Apple Vision é mais rápido que Tesseract sem comparação medida.

**Critério de saída:** nenhum HTML aceito como PDF; blobs são relidos e conferidos por hash; extração funciona para digital, escaneado, misto e corrompido; baixa qualidade gera revisão/lacuna explícita, não texto vazio classificado como aprovado.

### Onda 3 — Agente 04: release histórica curada

Integrar originais e extrações das duas casas. Classificar tipo/versão com evidência de origem, preservar versões substantivas, separar unidades textuais de diários/anais, executar deduplicação global e montar famílias antes dos splits. Exigir revisão de qualidade conforme contrato. A release pode ser parcial enquanto fontes oficiais estiverem bloqueadas, desde que declare as casas, tipos, segmentos, hashes e lacunas e não seja apresentada como corpus completo.

**Critério de saída:** FKs e hashes íntegros; cada item tem proveniência; famílias não vazam entre splits; duplicatas exatas têm representante único; itens com conteúdo elegível nos três splits ou explicação baseada em volume para qualquer split vazio; manifest declara cobertura real.

### Onda 4 — Agente 05; Agente 06 somente se houver regressão

O Agente 05 deve reexecutar tokenizer e shards na release curada escolhida após G2/GH, sempre aprendendo merges exclusivamente em train e produzindo manifestos ligados por hash à release e aos textos de treino. Deve incluir train, validation e test sem treinar tokenizer nas duas últimas partições. A implementação atual passa testes, mas seus artefatos são piloto.

O Agente 06 não precisa reimplementar o modelo: as provas CPU passam. Só abrir uma tarefa de correção para 06 se a integração da nova release expuser incompatibilidade ou se uma regressão reabrir G4.

**Critério de saída:** round-trip exato; tokenizer e shards reproduzíveis; nenhuma entrada validation/test/quarantine usada no treino do vocabulário; janelas/máscaras e hashes validados.

### Onda 5 — Agentes 07 e 08: treino histórico e persistência

O Agente 07 integra o token dataset histórico, mede tamanho de modelo, memória e alvos processados, e prepara configuração de treino principal sem confundir o smoke de 200 steps com treino do corpus. A auditoria de continuidade encontrou que `training train` ainda cria dataset sintético automaticamente; corrigir a CLI para exigir o token dataset externo em treinos normais e exigir uma opção explícita de smoke sintético. O carregador deve consumir os shards de train/validation produzidos pela Frente 05 e validar contexto/manifests antes do treino. O Agente 08 executa preflight e staging no runtime Colab autorizado, compara o mesmo payload em disco local/Drive quando aplicável, grava checkpoint e então inicia uma sessão nova restaurando somente do Drive. A conta concreta e a GPU disponível devem ser verificadas naquele runtime.

**Critério de saída:** G5 exige checkpoint COMPLETE verificado no Drive e retomada em sessão diferente com configuração, RNG, sampler e contadores restaurados. Se o runtime ou acesso à conta não estiver disponível, documentar o bloqueio concreto; não simular G5 com testes em diretório temporário.

### Onda 6 — Agente 09 e coordenador: avaliação final

Depois de G3/G5 e da release definida, avaliar checkpoints reais em validation e test com a métrica byte_nll_v1, registrar tokenizer, K, textos/hashes, split e ambiente, e produzir gerações com os prompts fixos. Reconciliar eventos/segmentos de treino e excluir ramos abandonados das curvas ativas. O coordenador atualiza o status dos gates e integra o relatório final.

**Critério de saída:** G6 só é concluído com GH, release/tokenizer identificados, checkpoint histórico treinado e retomável, métricas e geração verificáveis, além das limitações de cobertura declaradas.

## Prompt de coordenação para copiar e enviar ao agente de codificação

~~~text
Você é o coordenador técnico desta implementação. Leia AGENTS.md, docs/PLANO_MESTRE.md, docs/CONTRATOS_DADOS.md, docs/DECISOES_TECNICAS.md, docs/VALIDACAO.md, docs/COLAB.md, docs/FONTES_E_DIAGNOSTICO.md, docs/STATUS_IMPLEMENTACAO.md e docs/AUDITORIA_E_PLANO_DE_IMPLEMENTACAO.md. Leia também o prompt completo da frente antes de delegar para cada subagente.

O repositório já contém módulos funcionais e suítes de teste. Continue a implementação existente; não reescreva módulos que já passam. Siga a auditoria e o plano de continuidade, a propriedade exclusiva de arquivos em AGENTS.md e os contratos de dados. Você pode criar subagentes e deve delegar por ondas, após resolver a exigência de DATA_ROOT externo. O usuário determinou que não haja trabalho com Git até terminar a implementação; não execute Git nem inicialize metadados antes disso.

Ordem:
1. Coordenador: preserve o estado atual, não use Git até terminar a implementação, torne DATA_ROOT absoluto e externo obrigatório em todas as etapas, remova caminhos padrão para dentro do checkout, mova geração/cache do helper Swift para fora do código e alinhe relatórios/status com evidência atual.
2. Agentes 01 e 10 em paralelo: complete inventários históricos retomáveis Câmara/Senado, coleções, tipos, documentos, fases e filas; reconcilie manifests antigos e não marque lacunas como ausência.
3. Agentes 02 e 03: faça downloads oficiais validados e extração real progressiva. O download do Senado atualmente recebe HTML de verificação; use só rota oficial documentada, sem contornar a proteção. A suíte de OCR atualmente falha nos fixtures escaneados: exponha o erro de Vision, corrija o reconhecimento e prove digital, escaneado, misto e corrompido antes de ampliar.
4. Agente 04: integre as duas casas, preserve versões e unidades, faça deduplicação/famílias/splits e publique release com cobertura explicitamente declarada.
5. Agente 05: reexecute tokenizer e shards somente sobre a release, treinando BPE exclusivamente em train. Não refaça Agente 06, salvo regressão.
6. Agentes 07 e 08: treine a partir do corpus real após os gates anteriores; valide checkpoint no Drive e retomada em sessão Colab nova.
7. Agente 09 e coordenador: execute avaliação byte_nll_v1 e geração em checkpoint real; atualize status e relatório final.

Inicie apenas subagentes das dependências imediatas, respeite os arquivos exclusivos e integre cada entrega antes de abrir a onda seguinte. Envie a cada agente o prompt integral em docs/subagents/<ID> correspondente e complemente com a tarefa de continuidade acima. Alterações em schemas, configs, locks, fixtures comuns, README, AGENTS.md, agregador ou manifestos compartilhados são somente do coordenador. Se um contrato compartilhado precisar mudar, proponha a mudança, explique consumidores e migração, e aguarde a integração do coordenador.

Critérios obrigatórios:
- Nunca grave documentos, snapshots, Parquet, shards, checkpoints, runs ou caches dentro do checkout em execução de produção.
- Não confunda teste aprovado com cobertura histórica. O piloto atual da Câmara tem 22 itens, todos com kind unknown, zero validation e zero reviews humanos. Os artefatos antigos do Senado incluem consulta all_years/S de 10.780 processos, N com erro HTTP 400 e Anais/Diários pendentes; não declare isso como inventário histórico completo.
- Não declare GH/G6 concluídos enquanto houver segmentos pendentes ou sem estado/evidência explícita, nem G5 com mocks locais.
- Registre comandos, hashes, contagens, origem, estados, limitações e resultados reais em docs/reports/<ID>.md e docs/STATUS_IMPLEMENTACAO.md.
- Execute as verificações relevantes nos gates. A suíte Python passou 141 testes após as correções atuais; as suítes R integradas de contratos, inventário, downloads, curadoria e extração passaram na revalidação desta rodada. Reexecute após novas alterações e informe qualquer falha sem ocultá-la.
- Não contorne bloqueios do Senado nem invente cobertura, velocidade, custo, saldo ou tempo de treino. Se uma etapa exigir acesso institucional, conta autenticada ou rota oficial indisponível, continue o trabalho independente e registre precisamente a dependência.

Ao terminar, entregue os arquivos modificados, os agentes e gates concluídos, os testes realmente executados, a cobertura de dados verificada e todo o trabalho ainda bloqueado ou pendente. Não chame o projeto de concluído antes de atender os critérios G0–G6 e GH.
~~~


## Revalidação e decisão de fluxo (2026-10-07)

- `.venv/bin/python -m pytest -q`: **141 passed**.
- Suítes R executadas na rodada: contratos comuns; todos os testes `tests/inventory/camara`; inventário Senado; todos os testes de download e curadoria; extração Apple Vision. O comando terminou com exit code 0 e cada arquivo exibiu `DONE`, sem falhas. Após a última correção do helper e do publicador, a mesma lista de suítes foi repetida com o mesmo resultado.
- A correção do helper Swift agora compila e usa binários/módulos em cache sob DATA_ROOT. As páginas sem texto do Vision deixam de ser classificadas como aprovação em branco.
- A CLI de extração valida diretórios de entrada/saída em DATA_ROOT; a CLI Câmara aplica a mesma validação em `--output-dir`. O manifesto de extração resolve o caminho real relativo a DATA_ROOT mesmo para saída customizada. O helper comum rejeita caminho explícito no checkout ou raiz diferente da DATA_ROOT. A CLI normal de treino exige shards em DATA_ROOT; dataset sintético só é aceito pela opção explícita `--synthetic-smoke`.
- O usuário determinou que não haverá trabalho com Git até a implementação terminar. Portanto, estabelecer baseline Git foi removido da sequência imediata e fica para depois; nenhuma operação Git foi executada nesta continuidade.
