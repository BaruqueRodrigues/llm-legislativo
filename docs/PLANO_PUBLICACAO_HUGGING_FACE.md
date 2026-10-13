# Plano de implementação — Câmara: Drive → Hugging Face raw → text em Parquet

Plano iniciado em 10/10/2026. O histórico abaixo preserva as observações incrementais da execução; o estado mais recente da prévia global está registrado a seguir.

## Atualização — release unificada de pretraining publicada (11/10/2026)

- Dataset público: [`BaruqRodrigues/corpus-legislativo-pretraining`](https://huggingface.co/datasets/BaruqRodrigues/corpus-legislativo-pretraining).
- Revisão final verificada: `1349620c8530d73ed9e6f3e910291f2d5dfa1fbd`.
- Inclui a release Parquet unificada Câmara+Senado, manifests/`COMPLETE.json`, tokenizer BPE de 8.192 tokens, card e texto da licença MIT (`SPDX: MIT`). Quarentena e duplicatas estão presentes em tabelas próprias; ficam excluídas do treino pelo contrato do leitor.
- Upload concluído em duas fases: payload primeiro; cada `COMPLETE.json` após verificação remota dos tamanhos e SHA-256. Acesso público anônimo foi confirmado para o card, LICENSE, manifests e marcadores; o manifesto público confirma 931.992 registros e `coverage_status=partial`.
- Total versionado: 12 arquivos. Shards de tokens (aprox. 5,8 GB) e checkpoints não foram enviados.
- Implementação reproduzível: `scripts/publication/publish_integral_pretraining_release.py`; card-fonte: `docs/README_HF_INTEGRAL.md`.

## Estado atual — prévia global de splits (11/10/2026)

A prévia antiga `splits/parts001-014-preview/` foi mantida como snapshot histórico. Para que os novos lotes não ficassem sem atribuição, foi construída e publicada uma divisão conjunta dos 43 TARs em `splits/parts001-043-preview/`, revisão Hugging Face `782a62a77e6a7bed84bcb3b21e4ac75dfd425cb1`.

- Saída reproduzível: `scripts/publication/prepare_text_split_preview_streaming.py`, com staging em SQLite e gravação Parquet por blocos para limitar a memória.
- Cobertura verificada: 43 TARs, 760.766 PDFs e 93.894 registros não PDF; 854.660 atribuições documentais, 284.200 famílias.
- Splits publicados: 604.587 `train`, 68.172 `validation`, 69.102 `test`; 105.237 registros em quarentena e 7.562 duplicatas exatas.
- Política: `group_hash`, seed 42, metas 80/10/10. Relações oficiais de proposições, `codteor`, SHA-256 de origem e texto exato foram consolidados entre os 43 lotes antes da atribuição.
- Validação: checksums locais e LFS remotos conferidos; contagens Parquet iguais ao manifesto; nenhuma família ou hash de texto exato cruza os splits.
- Limite: continua sendo prévia. Deduplicação aproximada/containment, revisão manual/visual e complementos da coleta própria ainda não foram concluídos; não é o split curado final nem um benchmark.

O card principal do dataset agora aponta a configuração `preview` para a divisão 001–043. Os snapshots menores continuam disponíveis para reproduzir estados anteriores.

## 1. Decisões validadas com o usuário

- Conta de destino: `BaruqRodrigues`, conforme [perfil informado](https://huggingface.co/BaruqRodrigues).
- Primeira publicação: somente Câmara dos Deputados.
- Dois repositórios de datasets públicos: `BaruqRodrigues/camara-corpus-raw` e `BaruqRodrigues/camara-corpus-text`.
- Raw: preservar os 43 TARs recebidos e acrescentar documentos válidos da coleta própria quando corrigirem lacunas; conservar a origem de cada representação.
- Entradas dos índices recebidos: pasta local `processo_hiago/`.

Proposta técnica para revisão: raw primeiro; extração e curadoria depois; text publicado em Parquet com train/validation/test por família, nas metas 80/10/10 e seed 42 já configuradas no projeto. OCR, treino do tokenizer e treinamento do modelo não são condições para publicar o raw. Treinamento do modelo fica fora deste plano.

## 2. O que está confirmado e o que ainda precisa de execução

| Evidência | Situação | Consequência para a implementação |
|---|---|---|
| Listagem atual da pasta dos TARs | Conferida nesta tarefa: 43 arquivos, `part001.tar` a `part043.tar`, 334.344.765.440 bytes, aproximadamente 334,34 GB ou 311,38 GiB | Usar como referência inicial; congelar uma listagem de execução antes da transferência |
| Índice de membros | Relatório de 10/10: 856.904 linhas, sendo 856.901 `listado` e 3 `sem_arquivo`; correspondência multiconjunto exata com índice de hashes | Aproveitar o índice; não refazer a descoberta dos membros do zero |
| Offsets dos membros | Relatório: alinhados em 512 bytes e dentro dos tamanhos conhecidos dos respectivos TARs | Validar o índice durante leitura efetiva; limites corretos sozinhos não comprovam bytes corretos |
| Recuperação por faixa e PDF→texto | Relatório: um membro de `part028.tar` recuperado com hash igual; duas páginas extraídas por PDFKit | Método comprovado para um documento; ampliar para piloto estratificado |
| Comparação com coleta própria | Auditoria de 09/10: 182.197 correspondências de hash e 3.772 divergências identificadas como HTML na sobreposição de 185.969 URLs próprias verificadas | Reusar representações iguais; localizar cópias documentais válidas para as divergências |
| Formatos recebidos | Manifesto declara 760.753 linhas HTTP 200 com `.pdf`, 94.054 com `.html` e 2.075 com `.doc` | São classificações do manifesto, não contagens de PDFs fisicamente validados |
| Cobertura legislativa | Coletor recebido usa `urlInteiroTeor` dos CSVs anuais; não demonstra descoberta de todas as versões, coleções ou categorias | Publicar escopo parcial e denominadores explícitos; não chamar de corpus legislativo completo |
| Integridade de todos os TARs e documentos | Ainda não demonstrada por leitura completa nas auditorias consultadas | Executar hashes completos, leitura dos TARs e validação dos formatos por lote |
| Conta HF | Namespace informado pelo usuário; página de perfil indisponível pela ferramenta web | Conferir identidade autenticada, capacidade de escrita e armazenamento na fase inicial |

Fontes locais: [auditoria de TARs](reports/COMPARACAO_HIAGO_TAR_20261010.md), [comparação de conteúdo](reports/COMPARACAO_HIAGO_20261009.md), [contratos](CONTRATOS_DADOS.md), [plano mestre](PLANO_MESTRE.md) e [armazenamento](ARMAZENAMENTO_NUVEM.md). Os resultados históricos acima foram lidos dos relatórios; suas auditorias não foram reexecutadas nesta tarefa.

## 3. De onde vêm os arquivos

### Fonte A — pacotes recebidos

[Pasta dos TARs no Drive](https://drive.google.com/drive/folders/1HjjB6XLrC_7gqquAMU-YHJgMKn997Xue).

Entradas locais:

- `processo_hiago/indice_tar2.csv`: URL, SHA-256 de conteúdo, TAR, membro, offset, tamanho e estado.
- `processo_hiago/indice_sha256.csv`: hashes e tamanhos por ocorrência.
- `processo_hiago/manifesto.csv`: resultado declarado pelo coletor, ano atribuído e caminho de saída.
- `processo_hiago/proposicoes-2026.zip`: CSVs anuais para reconstruir os vínculos de cada URL com todas as proposições.
- `processo_hiago/final.py`: referência do comportamento do coletor; não será executado para repetir a coleta.

Importar esses arquivos como dados de origem e registrar seus hashes. Os nomes dos membros usam hash da URL; eles não são o SHA-256 dos bytes. Nove ocorrências repetidas e os eventos sem arquivo precisam permanecer auditáveis.

### Fonte B — coleta própria do projeto

[Pasta persistente do projeto](https://drive.google.com/drive/folders/1ViNLdnO7pE0aF_0R4h66FoCz7RsMC6Ko), configurada em `configs/storage/drive.json`.

Nesta tarefa foram observadas as pastas `data/packs`, `data/manifests` e `data/state_snapshots`. A enumeração completa de pacotes, recibos e snapshots fica para a implementação. A subpasta `docs_mimi` retornou listagem vazia; os 43 TARs estão na Fonte A.

O formato próprio é `pack_v1`: concatenação de bytes, com localização por offset/tamanho e manifesto; não é TAR. Reusar os recibos e `scripts/cloud_storage.py` para recuperação. Não tentar descompactar `.pack` como arquivo TAR.

O `DATA_ROOT` documentado é `/Users/quemuelbaruque/Documents/produtos/llm_do_zero_DATA`, externo ao checkout. Examinar os inventários e journals locais e, quando necessário, restaurar snapshots identificados do Drive. Fazer o snapshot entre lotes do coletor: `backup-state` não produz snapshot transacional de uma coleta em movimento.

### Regra de composição

1. Preservar TARs recebidos byte a byte, incluindo respostas inválidas identificadas no catálogo, desde que todo conteúdo publicado tenha condição de redistribuição documentada.
2. Compartilhar a representação lógica de blobs com hash igual e conservar todas as ocorrências e vínculos. Os TARs de preservação podem conter repetições físicas; não prometer deduplicação física total sem reempacotá-los.
3. Quando o recebido for HTML de erro e houver documento próprio válido, manter a ocorrência recebida como inválida e relacionar a representação própria apta ao processamento.
4. Quando houver dois documentos válidos com bytes diferentes, preservar ambos como versões observadas até esclarecer a diferença. Não substituir silenciosamente.
5. Publicar complementos próprios em TARs independentes, contendo apenas os blobs selecionados ainda necessários. Produzir catálogo de offsets e hashes. Não copiar toda a coleta própria para o HF só porque uma parte corrige lacunas.
6. Documento sem formato suportado ou com erro fica registrado com motivo. DOC legítimo permanece elegível; HTML só é conteúdo textual se sua natureza documental for comprovada.

## 4. Correções ao rascunho anterior

- Os índices e manifests já existem em `processo_hiago`; aproveitá-los.
- Já há um piloto de acesso por intervalo. Para publicar os TARs será necessário transferir seus bytes completos; para extração piloto ou recuperação pontual podemos buscar apenas membros.
- Não são 856.901 PDFs validados: são registros de membros listados, incluindo formatos e respostas distintos.
- Há uma segunda fonte em `.pack`, importante para corrigir HTMLs e outras lacunas.
- `document_id` identifica documento lógico namespaced; `file_sha256` identifica bytes. A proposta antiga `document_id = hash do conteúdo` conflita com os contratos.
- Parquet já é a interface do projeto para tabelas e texto por página. O trabalho novo inclui exportação pública por split e adaptação para o Hub; não precisamos criar primeiro milhões de `.txt`.
- A existência de CLI, publisher ou `COMPLETE.json` não comprova conformidade com todos os campos do contrato. Incluir validação explícita do esquema de release.
- A etapa raw poderá terminar antes da text. Concluir integridade da publicação não conclui o Gate GH de cobertura histórica.

## 5. Fluxo de implementação e critérios de aceite

| Fase | Trabalho | Entrega verificável | Dependência |
|---|---|---|---|
| P0 — Preparação | Fixar fontes, snapshot de índices, configuração, ambiente e credenciais; aferir disco e capacidade HF | Configuração sem segredos, hashes de entrada, inventário interno e definição do escopo | Plano validado e acesso às contas |
| P1 — Catálogo | Importar índices; reconstruir vínculos N:M; reconciliar fontes e versões; validar PK/FK | Catálogo preliminar em Parquet e lista de complementos necessários | P0 |
| P2 — Piloto raw | Baixar um TAR, auditar bytes e estrutura, recuperar complementos representativos; executar upload e verificação | Pacote auditado, catálogo piloto, recibo remoto e medição de transferência/uso de disco | P1 |
| P3 — Release raw | Processar os 43 TARs sequencialmente e os complementos; publicar catálogos/documentação | Release pública raw com manifestos, hashes, commit fixado e marcador de conclusão | P2 |
| P4 — Extração piloto | Amostra estratificada no Mac; ajustar qualidade e formatos adicionais | Relatório com páginas/s, OCR, memória, erros e revisão visual/textual | P1/P2; pode preceder o fim de P3 para estimar esforço |
| P5 — Extração em lotes | Recuperar bytes verificados, extrair por página, registrar qualidade e checkpoint | Tabelas sharded de extração, páginas, seções e falhas reconciliadas | P4 |
| P6 — Curadoria e splits | Limpeza auditável, dedup escalável, grafo global da release Câmara e divisão por família | Release canônica com zero vazamento entre splits e variantes substantivas preservadas | P5 e inventário de vínculos |
| P7 — Release text | Exportar Parquet por split, publicar, verificar bytes e uso sem autenticação | Dataset text público com train/validation/test, qualidade, proveniência e revisão raw fixada | P3/P6 |

Cada fase deve produzir relatório com comando, configuração/hash, contagens, erros, bytes e pendências. Nenhuma etapa redefine sucesso só porque um arquivo de saída existe.

### P0 — Acesso, ambiente e armazenamento

- Confirmar com autenticação HF que a identidade é `BaruqRodrigues` e que pode criar datasets públicos. Tokens entram por armazenamento local de credenciais ou variável de ambiente; nunca em config, log ou dataset card.
- Conferir plano e espaço disponível para raw + complementos + text + histórico de versões. O volume text e dos complementos ainda não foi medido.
- A documentação consultada mantém armazenamento público gratuito em best-effort e PRO com até 10 TB incluídos. Capacidade da conta deve ser verificada; não assumir disponibilidade garantida para 334 GB. Não contratar plano automaticamente. [Armazenamento HF](https://huggingface.co/docs/hub/storage-limits).
- Usar `DATA_ROOT` externo para dados e staging. Fixar versões compatíveis de R/Arrow, extrator Swift, `huggingface_hub`, `hf_xet` e bibliotecas de exportação após piloto; preservar os locks existentes e acrescentar somente dependências necessárias.
- Começar com um pacote em staging. Dimensionar espaço como maior pacote + complementos do lote + temporários de extração + caches medidos + reserva. Não exigir baixar o acervo inteiro; uma estimativa inicial de 30–50 GiB livres deve ser confirmada no piloto.

### P1 — Catálogo e proveniência

Preservar as tabelas canônicas: `documents`, `proposition_documents`, `document_versions`, `fetch_attempts`, `metadata_checks`, `coverage_segments`, proposições e evidências de uso. Construir tabelas adicionais de publicação, sem redefinir identidades:

| Tabela pública proposta | Unidade e campos principais |
|---|---|
| `archives` | Um pacote: ID namespaced, formato, caminho HF, bytes, SHA-256 integral, contagens por tipo/estado e release |
| `archive_members` | Uma ocorrência em um pacote: ID, pacote, ordinal/caminho, offset dos dados, tamanho, hash esperado e hash observado, MIME detectado, estado e erro |
| `blob_locations` | Um local de um blob: `file_sha256`, pacote/membro/offset/tamanho; várias localizações podem compartilhar o hash |
| `ingest_provenance` | Registro legado e evidência da importação: origem da coleção, hash do índice, linha original, URL, status recebido e verificação efetiva |
| `coverage` | Visão das tabelas canônicas por segmento/ano/categoria, com denominador e data de corte declarados |

Esses esquemas novos precisam ser versionados pelo coordenador com migração R↔Python. `archive_members` não é sinônimo de `documents`: falhas HTTP não viram documentos legislativos aceitos.

Reconstruir proposição→URL a partir de todos os CSVs anuais do ZIP, preservando relações múltiplas. Separar ano da proposição, data do conteúdo e data de captura. Não fabricar data de download antiga a partir da importação ou do upload no Drive.

O contrato atual exige captura para cada versão aceita. Se a coleção legada não tiver horário/evidência suficientes, definir uma política versionada de importação: registrar a verificação presente como evento de adoção, preservar os campos históricos desconhecidos como tais e ligar a evidência recebida. O importador não deve simular requisição oficial bem-sucedida nem alterar silenciosamente a semântica de `fetch_attempts`.

Hashes e tamanhos declarados ficam separados dos verificados. Contagens distinguem linhas, URLs/chaves, proposições, documentos lógicos, versões, blobs únicos, páginas e itens textuais. Cobertura só é calculada com denominador conhecido; valores desconhecidos são nulos.

IDs privados do Drive, caminhos do computador, recibos administrativos e credenciais ficam no estado interno. O catálogo público usa caminhos HF e URLs oficiais sanitizadas. Metadados N:M não multiplicam linhas de texto.

### P2/P3 — Auditoria e transferência raw

Para cada TAR:

1. Fixar ID, tamanho e versão/modificação da fonte; verificar alteração durante aquisição. Baixar para `.part` com autenticação Drive/rclone e retomada quando suportada.
2. Calcular SHA-256 de todos os bytes. Confirmar leitura independente do TAR, headers, tipos de membros, tamanhos e offsets; confrontar com os índices. Não confiar só no sufixo `.tar`.
3. Ler cada membro em fluxo, recalcular hash e detectar mídia por bytes/parser. Limitar memória por membro e registrar PDF ilegível, arquivo vazio, truncamento, DOC ou HTML. Não extrair caminhos arbitrários do TAR: rejeitar traversal, links inesperados e colisões de nomes.
4. Verificar abertura/páginas dos PDFs e classificação dos demais formatos. Validar fisicamente também os complementos próprios no momento da recuperação; recibo antigo não prova presença atual do objeto no Drive.
5. Se houver problema de redistribuição em qualquer membro, o TAR integral correspondente não pode ser publicado como está. Criar derivado documentado e novo hash, conservando o original no Drive. Não atribuir CC0 ao acervo inteiro por hipótese.
6. Enviar pacote concluído com `huggingface_hub`/`hf_xet`; registrar commit e caminhos. Reexecutar upload após interrupção e consultar o remoto após timeout de commit antes de repetir. A solução será compatível com a versão fixada no piloto. [Upload HF](https://huggingface.co/docs/huggingface_hub/guides/upload).
7. Conferir tamanho e hash remoto quando houver SHA-256 de conteúdo documentado; identificador Xet ou ETag genérico não substitui esse hash. Sem hash comparável, reler os bytes remotos completos em streaming e calcular SHA-256. Fazer leitura por usuário não autenticado na revisão publicada.
8. Persistir recibo de verificação. Liberar apenas staging descartável depois da conferência remota, mantendo a fonte Drive; nunca excluir o acervo original como parte desta publicação.

Integridade e validade documental são estados diferentes: um TAR pode ter bytes íntegros e conter HTML de erro. A release raw de preservação precisa dizer isso explicitamente. O catálogo distingue dados aptos à extração, evidência de erro e formato pendente.

No piloto, medir transferência, releitura, parser, cache e concorrência. O caminho padrão usa staging local; não presumir que Drive→HF diretamente, sem arquivo local, forneça a mesma retomada e verificação. Não há OCR no Hugging Face Hub: o Hub recebe artefatos produzidos pelo pipeline.

### P4/P5 — Texto extraído e qualidade

- PDFs: Swift + PDFKit primeiro; Apple Vision somente nas páginas necessárias, no macOS, conforme perfil existente. Não mover esse processamento para Colab/Linux.
- Recuperar bytes pelo catálogo e conferir hash antes da extração. Reusar blobs/extrações iguais de forma auditável; documentos e vínculos continuam distintos quando necessário.
- Piloto proposto: 200–500 documentos estratificados por período disponível, tamanho, tipo, digital/escaneado, nativo/OCR, finais curtos, DOC/HTML legítimos e ocorrências corrigidas. Validar manualmente uma amostra por estrato e todas as classes novas de erro; fixar seleção e seed.
- A auditoria de 10/10 detectou página contendo só o número `2` com status automático de aprovação. Ajustar indicadores para páginas vazias/numeração/rodapé, sem remover conteúdo substantivo de páginas curtas por tamanho apenas.
- Preservar `pages.raw_text` na ordem original e publicar `extraction_runs`, `pages`, `sections`, métricas e revisões. Separar extração bruta da versão limpa em `curated_documents.text`.
- Registrar método/motor/build/config, caracteres, bytes, proporção de caracteres de substituição/imprimíveis, razões de qualidade, tempo e confiança OCR somente quando disponível. Métrica desconhecida fica nula; score automático não representa acurácia humana.
- DOCs exigem adaptador próprio com piloto, versão e validação. Conversão, se necessária, gera derivado com proveniência, preservando bytes originais. Não forçar DOC pelo PDFKit. HTML documental recebe extrator de conteúdo com evidência de natureza legislativa; HTML de erro fica fora do text.
- Persistir lotes de páginas em Parquet e checkpoints. Estimar tempo por páginas nativas/OCR e formatos, não só por número de arquivos. Ajustar tamanho dos lotes pela memória/tempo medidos.

### P6 — Curadoria e prevenção de vazamento

- Limpeza versionada preserva acentos, números, artigos, justificativas, pareceres, votos e versões substantivas. Remoção de assinatura digital/cabeçalho exige evidência e trilha de transformação.
- Deduplicação binária e textual exata primeiro. Para quase duplicatas e containment, gerar candidatos com índice de passagens e MinHash/LSH ou mecanismo equivalente; confirmar candidatos e registrar decisões. Não comparar todos os pares em memória.
- Mudança substantiva, mesmo com alta similaridade, preserva os textos como variantes da mesma família. Menção incidental, tema ou citação da mesma lei não unem processos por si só.
- Construir o grafo global de todos os itens da release Câmara antes dos splits, usando vínculos de proposições, versões, reproduções e aliases comprovados. Não dividir por TAR, ano, página ou lote da extração. A falta de relações suficientes exige revisão/quarentena de candidatos de alto risco.
- Usar `group_hash`, seed 42 e metas 80/10/10 por famílias, conforme `configs/curation/history.yaml`. Publicar proporções reais em famílias, itens e bytes; elas não serão necessariamente idênticas.
- Apenas `quality_status=accepted` e `include_in_dataset=true` entram nos três splits públicos de treino. Quarentena e exclusões ficam em tabelas de auditoria separadas, com motivo; não viram textos vazios.
- Conferir zero famílias entre splits, unicidade dos representantes, ausência de cópia exata entre partições, PK/FK, proveniência e suporte documental para permissões/tipo. Validar que cada split tem material útil e diversidade suficiente antes de publicar a release text estável.
- Adições posteriores, inclusive Senado, podem alterar famílias: recalcular e versionar splits. Não prometer estabilidade de atribuição quando a composição do grafo mudar. Tokenizer futuro usa somente train da release aprovada.

### P7 — Exportação Parquet e publicação text

Manter a release canônica com `curated_documents`, `split_assignments`, vínculos, seções, eventos de limpeza, dedup e revisões. Exportar uma visão de consumo com uma linha por `corpus_item_id` aceito/representante, preservando o esquema Arrow definido para essa visão.

Campos principais: `corpus_item_id`, `document_id`, `version_id`, `extraction_id`, `logical_unit_id`, `family_id`, `house`, `normalized_kind`, datas e estado da evidência, `text`, `text_sha256`, `utf8_bytes`, `character_count`, `quality_status`, versões de limpeza/split e referência de proveniência raw. Métricas de extração ficam em tabelas próprias ou agregados com regra explícita; não criar números sem medição.

Tamanho inicial sugerido por shard: 128–512 MiB comprimidos, ajustado no piloto. Usar compressão Parquet compatível, preferencialmente Zstandard após verificar leitores. Cada shard deve ter hash, número de linhas, bytes e esquema registrados. Não particionar por autor/tema nem criar um arquivo por PDF.

A visão pública por split deriva das tabelas canônicas, não substitui a interface atual do leitor do tokenizer. Publicar metadados N:M em tabelas separadas e validar a equivalência entre a seleção canônica e a visão pública.

## 6. Organização dos dois repositórios

```text
BaruqRodrigues/camara-corpus-raw/
  README.md                     # dataset card PT/EN, configs explícitas
  CITATION.cff
  LICENSES.md
  RELEASE_NOTES.md
  raw/received/part001.tar ... part043.tar
  raw/supplements/<id>.tar
  metadata/archives.parquet
  metadata/archive_members-*.parquet
  metadata/blob_locations-*.parquet
  metadata/documents*.parquet
  metadata/document_versions*.parquet
  metadata/proposition_documents*.parquet
  metadata/ingest_provenance*.parquet
  metadata/coverage*.parquet
  checksums/archives.sha256
  reports/audit.md
  examples/find_and_download_document.py
  publication_manifest.json
  COMPLETE.json

BaruqRodrigues/camara-corpus-text/
  README.md                     # dataset card PT/EN, splits explícitos
  CITATION.cff
  LICENSES.md
  RELEASE_NOTES.md
  data/train/part-*.parquet
  data/validation/part-*.parquet
  data/test/part-*.parquet
  canonical/<corpus_version>/    # release compatível com leitor do projeto
  extraction/pages-*.parquet
  extraction/extraction_runs*.parquet
  extraction/sections-*.parquet
  metadata/<tabelas-de-proveniencia-e-auditoria>.parquet
  reports/quality.md
  reports/splits.md
  publication_manifest.json
  COMPLETE.json
```

No raw, configurar o viewer para catálogos Parquet com configurações separadas por tabela. TARs arbitrários não passam a ser WebDataset pela extensão. No text, a configuração principal aponta explicitamente a `data/train`, `data/validation` e `data/test`, evitando misturar páginas brutas, catálogo e quarentena. [Configuração HF](https://huggingface.co/docs/hub/datasets-manual-configuration).

Modelo proposto de configuração para o text, a gerar após definir os caminhos finais:

```yaml
language: [pt]
configs:
  - config_name: default
    default: true
    data_files:
      - split: train
        path: data/train/*.parquet
      - split: validation
        path: data/validation/*.parquet
      - split: test
        path: data/test/*.parquet
```

As cards precisam informar coleta, escopo, data de corte, métodos, qualidade, cobertura, limitações, licenças/evidências e como recuperar originais. O período 1934–2026 é o horizonte do coletor recebido, não prova de cobertura uniforme; 2026 é parcial. [Dataset cards](https://huggingface.co/docs/hub/datasets-cards).

Usar um manifesto de publicação específico para raw/text e manter o `release_manifest.json` canônico de curadoria. O manifesto text identifica repositório/commit/release/hash do raw; cada item chega aos bytes e à origem oficial. Evitar referência circular: commit HF final fica no recibo de publicação e é fixado por tag após conclusão; não inserir dentro de um arquivo o hash do commit que contém esse próprio arquivo.

Publicar conteúdo e manifesto primeiro, verificar o remoto, publicar `COMPLETE.json` por último com hash do manifesto e fixar revisão/tag. Enquanto houver commits parciais no repositório público, a card indica publicação em andamento. O marker indica integridade/conclusão daquela release, não cobertura histórica integral. A ausência dele impede promover a versão como concluída pelo pipeline.

## 7. Reuso de código e lacunas de implementação

| Componente | Reuso | Ajuste necessário antes da escala |
|---|---|---|
| `scripts/cloud_storage.py` e `R/inventory/common/cloud_storage.R` | Recuperação de `.pack`, hashes e recibos próprios | Adaptar fonte recebida/TAR e localização pública HF mantendo estado operacional separado |
| `R/download/validator.R` e armazenamento por hash | Validação de formatos e blobs canônicos | Importador dos índices legados, reconciliação das fontes e tratamento dos eventos sem bytes |
| `R/extraction/` e helper Swift | Extração nativa, OCR seletivo, páginas e seções | Driver por inventário/`version_id` real, lotes retomáveis e revisão de qualidade |
| `scripts/extract.R` | Referência de orquestração | Hoje descobre `.pdf` por pasta e monta `doc:v1:<nome>`; usar IDs reais e entradas `.bin` verificadas em produção |
| `R/curation/` | Limpeza, representação canônica, famílias e splits | Substituir comparação par a par de shingles por candidatos indexados e limitar memória de texto |
| `scripts/curate.R` | Interfaces de tabelas | Permitir escopo explícito Câmara sem inventário artificial do Senado; selecionar runs/entradas fixados |
| `R/curation/publisher.R` | Parquet e marcador de conclusão | Gerar todos os campos obrigatórios do JSON schema; contagens separadas para inventário e itens efetivamente exportados; validar esquema e imutabilidade |
| `src/legislm/tokenization/reader.py` | Leitura da release canônica | Validar compatibilidade da nova release, sem usar a visão pública para refazer joins N:M |

Helpers operacionais criados para a publicação raw incremental:

- `scripts/publication/verify_tar_index.py`: valida conjunto de membros, nomes seguros, tamanho, offset e SHA-256 por TAR; emite índice CSV e resumo de verificação.
- `scripts/publication/fetch_rclone_range.py`: baixa arquivos Drive em intervalos retomáveis e pode conferir SHA-256 de uma faixa de blob em pack.
- `scripts/publication/build_supplement_catalog.py`: filtra hashes Câmara ausentes dos TARs usando ledgers validados e manifests, e cria catálogo Parquet local.
- `scripts/publication/register_verified_archive.py` e `publish_drive_tars.py`: atualizam a release staged e publicam cada TAR validado, verificando tamanho/SHA-256 anônimos no Hub. O publicador mantém um único TAR seguinte em prefetch enquanto o TAR atual é publicado; com `--text-repo-id`, ele reutiliza o mesmo arquivo local para extrair PDFs e documentos não PDF e publicar os Parquets por arquivo no repositório text. O staging fica limitado ao TAR atual mais um TAR em transferência, com reserva mínima de disco configurável (`--min-free-gib`, padrão 10 GiB). Essa saída por TAR permanece uma extração parcial; divisões globais de treino/validação/teste seguem na etapa de curadoria após consolidar e reconciliar os lotes.
- `scripts/publication/fetch_supplement_blobs.py`: recupera apenas os complementos selecionados por offset, confere hash e prepara o manifesto Parquet público sem caminhos locais internos.

Ainda necessários para tornar o pipeline completo e declarativo:

- `configs/publication/huggingface.yaml`: repo IDs, fontes, revisão, staging, limites, releases e formatos; sem credenciais.
- `schemas/publication/`: schemas dos catálogos e manifesto de publicação; mudanças legadas canônicas versionadas se necessárias.
- `R/publication/`: importação/reconciliação, catálogos e exportação pública por split, preservando a responsabilidade de R por preparação do corpus.
- `tests/publication/`: fixtures pequenas e testes de falhas/retomada/contratos.
- `docs/reports/PUBLICACAO_HF_<release>.md`: evidências sanitizadas da execução.

O coordenador aprova interfaces compartilhadas. Não é necessária abertura de novos chats ou execução de subagentes para cumprir este plano.

Comandos a implementar, com ajuda/config explícitas: `inventory`, `audit`, `build-catalog`, `coverage`, `prepare-release`, `upload`, `verify-release` e `status`. O upload opera por seleção declarada da release e lista permitida de caminhos. Usar `--dry-run` para escritas externas e operações locais de preparação; consultas e verificações devem informar seu custo de leitura.

Estado persistente em SQLite sob `DATA_ROOT/staging/publication`, com eventos append-only. Chave idempotente por etapa, entidade, config e hashes de entrada. Estados de aquisição/auditoria/publicação separados; erro tem classe, tentativas e próxima ação. Pausar só uma entidade quando apropriado e reconciliar o lote ao concluir. Não escrever progresso operacional no histórico público do HF a cada documento.

## 8. Verificações planejadas

Os itens abaixo seguem como requisitos de robustez para o pipeline completo. Os helpers foram compilados, o catálogo de complementos foi construído e o validador foi exercitado contra os dois primeiros TARs reais. O helper de offset recuperou também um membro em posição alta do primeiro TAR com SHA-256 idêntico ao índice.

- TAR truncado, header/offset divergente, extensão enganosa, nomes repetidos, traversal e links inesperados.
- PDF inválido, HTML HTTP 200 de erro, DOC legítimo, zero bytes, hash esperado divergente e ocorrência sem arquivo.
- URL compartilhada por várias proposições, duas versões binárias válidas da mesma URL e hash igual em URLs distintas.
- Complemento próprio substituindo para processamento um HTML recebido, sem apagar o registro original.
- Interrupção no download/upload, timeout após commit efetivo, retomada sem duplicação e fonte alterada durante transferência.
- Prefetch limitado a um TAR, falha de espaço antes do início da transferência, falha raw preservando o TAR para retomada e falha text preservando o TAR após a publicação raw.
- Falha de hash remoto bloqueando conclusão e liberação do staging.
- IDs preservados entre importação, extração e curadoria; campos históricos desconhecidos não preenchidos com valores inventados.
- Mesma família/duplicata atravessando lote ou ano; variantes substantivas conservadas; grafo e splits independentes da ordem de processamento.
- Manifesto incompleto rejeitado, marker com hash errado, contagens reconciliadas e invariantes Arrow/PK/FK.
- Leitura canônica compatível com Python, seleção pública equivalente, leitura dos splits em ambiente limpo e acesso público aos bytes por commit fixado.

Aceite raw: todos os pacotes previstos contabilizados, hashes integrais verificados, catálogo reconciliado, proveniência/condições de publicação documentadas e conferência remota concluída. Falhas documentais permanecem explicitamente quantificadas.

Aceite text: dados aceitos rastreáveis ao raw, texto preservado e limpeza auditável, qualidade revisada por estratos, zero vazamento entre famílias/splits, ausência de representantes exatos repetidos, esquemas/manifestos íntegros e splits úteis documentados. Qualquer lacuna restante é identificada por release parcial, sem afirmar GH completo.

## 9. Esforço, sequência prática e pendências

A implementação começa por P0/P1, depois um TAR completo e complementos representativos em P2. Após validar esse ciclo, escalar raw e executar extração piloto; publicar text quando a curadoria global da release tiver terminado. Extração pode usar membros já disponíveis e não precisa esperar que todos os TARs terminem de subir.

Para 334,34 GB, a fórmula `bytes × 8 / banda efetiva` dá aproximadamente 7,43 horas a 100 Mb/s ou 2,48 horas a 300 Mb/s para uma transferência. São mínimos teóricos. O fluxo completo inclui download Drive→staging, upload, possíveis releituras remotas, auditoria e complementos. Fixar estimativa operacional após medir um pacote; estimar extração separadamente por páginas e proporção de OCR. Não prometer prazo total antes dessas medições.

Pendências para iniciar execução, sem alterar as decisões já validadas:

- Confirmar máquina Mac e espaço/disco de staging disponível; o perfil de SSD citado no rascunho não foi aferido nesta tarefa.
- Confirmar autenticação HF, armazenamento/plano e permissões de escrita; não pedir token pelo chat.
- Documentar condições de redistribuição dos documentos e licença dos metadados/código; ainda não houve conclusão jurídica/licenciamento nesta tarefa.
- Fechar piloto de qualidade e adaptador DOC/HTML legítimo, com metas de aceitação baseadas em medição.
- Validar a sequência e os critérios deste documento com o usuário antes de começar a implementação solicitada em uma etapa posterior.

## 10. Evidência produzida nesta tarefa

Lidos: rascunho anexado, índices de `processo_hiago`, auditorias de 09–10/10, contratos/esquema da release, configurações de armazenamento/extração/curadoria e interfaces relevantes de publicação/leitura.

Consultados: metadados das duas pastas Drive e subpastas identificadas; documentação oficial HF de armazenamento, upload, configuração e cards. O TAR `part001.tar` está em cópia para staging para sua primeira validação física; ainda não foi publicado.

Este plano e o card inicial da camada raw foram preparados no workspace. Os dois repositórios HF públicos foram criados após autenticação da conta e aprovação explícita do usuário. Esta pasta de trabalho não tem `.git`: `git status --short` retornou “not a git repository”, portanto diff Git indisponível. A revisão do resultado usa leitura dos arquivos e evidências das fontes.

## 11. Atualização de execução após aprovação

Em 10/10/2026, o usuário aprovou esta sequência e explicitou a intenção de publicar o projeto científico publicamente.

- A conta-alvo e os dois repositórios foram definidos nas decisões acima.
- O rclone autenticado listou 43 TARs na pasta original (mesmos tamanhos do inventário) e 46 pacotes `.pack`, com 46 manifests na pasta do projeto. Os manifests registram `storage_kind=pack_v1`, `pack_sha256`, tamanho e lista de blobs/offsets. Os 182.596 registros de blobs somam 95.901.491.231 bytes; todos os caminhos de blob observados nos ledgers locais têm localização de Drive, e o snapshot de estado está sendo reconciliado.
- O ambiente tem macOS ARM64, Hugging Face Hub CLI 1.8.0, `hf_xet`, PyArrow e cerca de 114 GiB livres no momento da leitura. O catálogo poderá usar os manifests do Drive sem baixar todos os `.pack`.
- A autenticação Hugging Face foi concluída pelo proprietário; `hf auth whoami` confirmou `BaruqRodrigues`. Os repositórios públicos `BaruqRodrigues/camara-corpus-raw` e `BaruqRodrigues/camara-corpus-text` foram criados. Nenhum token foi colocado no chat.
- A rede do processo inicialmente isolado bloqueou Google OAuth; o acesso de leitura ao Drive funcionou após autorização do ambiente para esse comando.
- O inventário recebido contém 43 TARs, 856.901 linhas `listado` e 848.030 hashes distintos. As partes 001 e 002 passaram validação integral de membros. A parte 003 está sendo baixada em modo retomável; a fila sequencial prossegue até a parte 043.
- A reconciliação do snapshot completo recuperado do Drive encontrou 58 ledgers da coleta da Câmara com 192.220 linhas com hash e 180.623 hashes distintos. Desses, 1.076 hashes validados pela coleta estão ausentes dos TARs recebidos e somam 18.310.373.322 bytes nos manifests de pack; são candidatos a complementos, ainda sujeitos à validação física de bytes e tipo. Foram excluídos da seleção os 1.972 hashes em packs que não aparecem nesses ledgers até que haja proveniência Câmara verificável.
- Os 46 manifests de pack contêm 182.596 registros e 182.595 hashes únicos. A cópia local dos manifests está disponível para fechar a reconciliação; não se deve publicar o conteúdo completo dos packs sem filtrar por proveniência da Câmara.
- O primeiro lote `part001.tar` passou pela verificação integral dos 20.000 membros: nomes, conjunto exato de membros, tamanho, offsets e SHA-256 conferidos contra o índice. O TAR tem 8.207.564.800 bytes e SHA-256 `7f57e92f15ad60004ac52a9e1fd34a11c6196062c5b4241caec55aba9f459e93`.
- O commit público raw `2e53e5e11ec9386c0500177e173c53f7c4ff0f1d` contém o TAR, seu índice CSV por membro, o relatório de validação, o card e `release_manifest.json` com `status=partial`. A API do Hub confirmou acesso sem autenticação, repositório público e tamanho/SHA-256 remotos idênticos aos locais. Link: https://huggingface.co/datasets/BaruqRodrigues/camara-corpus-raw.
- A segunda parte passou a mesma verificação completa e foi confirmada anonimamente no commit `9845bc2f81cbc8e411762afc614d0efbc1daa3ac`, com 20.000 membros, 6.797.271.040 bytes e SHA-256 `da1e04ed9e99f82db1c01c66605f930d5a676da42cc9bbfb81b02252fb474e51`.
- O publicador sequencial está ativo para as partes `part003.tar`–`part043.tar`. Ele usa download Drive em intervalos retomáveis, valida o conjunto de membros/tamanho/offset/SHA-256 contra o índice, publica cada TAR com manifestos em um commit e verifica acesso anônimo, tamanho e SHA-256 remoto antes de limpar a cópia local. Log: `DATA_ROOT/staging/publication/logs/publish_raw_tarballs_20261010.log`.
- Um teste físico de complemento leu um blob a partir do offset publicado no pack e confirmou o SHA-256 esperado (927.634 bytes; digest `e9bc61af46338bb7ffd02b5712bc0a9dd5ffbfbb3ca31c1ccf5b5be6cde4d03a`). A recuperação dos 1.076 candidatos Câmara começou com dois trabalhadores e conferência de hash; os artefatos de staging estão em `/private/tmp/camara-supplement-fetch` porque `DATA_ROOT` é somente leitura para esta sessão. Os 1.972 blobs sem proveniência Câmara continuam excluídos.
- A extração foi iniciada em paralelo com a fila raw. Um piloto estratificado de 12 PDFs de `part001.tar` recuperou e conferiu cada SHA-256; produziu 34 páginas reais (33 nativas e uma OCR), 48.524 caracteres e status `pass` nas 34 páginas. O bundle Parquet passou a validação local em `/private/tmp/llm_do_zero_data/staging/extraction/pilot-verified`, com manifest SHA-256 `7ef752eb924d312dee69cf16db92e1479e7e48b9252bee562b65e0b349212c70`; não foi publicado no Hub. A amostra é pequena e ainda não estima a proporção de digitalizados do corpus.
- A correção em `scripts/extract.R` carrega `R/inventory/common/storage.R` antes de resolver `DATA_ROOT`. A CLI direta repetiu o piloto com sucesso. As falhas de Vision observadas dentro do sandbox foram reproduzidas como restrição desse ambiente; a execução no host macOS reconheceu páginas OCR. A suíte `tests/extraction/test_extraction_suite.R` passou com 81 expectativas e nenhuma falha. O controlador/checkpoint por blocos e a publicação parcial de extração foram implementados depois deste registro inicial; deduplicação por família, splits globais e publicação curada continuam pendentes.
- O repositório text foi criado como público e recebeu uma extração parcial de `part001.tar`; não confundir esse artefato com a futura release curada com famílias e splits.
- A documentação atual do Hub descreve armazenamento público gratuito como *best-effort*, recomenda uso responsável além dos primeiros GB e indica PRO/Team/Enterprise ou grant para volumes substanciais; todos os repositórios contam para a cota da conta. A coleção raw projetada excede 300 GB. O piloto de 7,6 GiB validará a ingestão inicial, mas a capacidade para o volume total depende da cota aplicável à conta; nenhuma compra ou mudança de plano foi feita. Fonte: [limites de armazenamento do Hugging Face Hub](https://huggingface.co/docs/hub/en/storage-limits).

## Execução do primeiro lote

- Escopo executado: `part001.tar` inteiro, fixado à revisão raw `2e53e5e11ec9386c0500177e173c53f7c4ff0f1d`, SHA-256 `7f57e92f15ad60004ac52a9e1fd34a11c6196062c5b4241caec55aba9f459e93`. O TAR contém 20.000 membros: 17.776 PDFs, 2.171 HTMLs e 53 DOCs. Os demais TARs não fizeram parte desta extração.
- Extração PDF em 72 blocos retomáveis: 17.776 execuções, 92.210 páginas e 75.269 seções. Métodos de página: 85.946 nativas, 6.037 OCR e 227 sem texto; 91.983 páginas `pass` e 227 `review`. A tabela opcional `quality_reviews` tem zero linhas porque benchmark/revisão visual não foi executado.
- HTML/DOC: 2.224 linhas em `non_pdf_text.parquet`; 1.074 `fail`, 1.150 `review`; 2.214 marcadas para revisão documental manual e 10 como possível erro/placeholder. Nenhum foi liberado para treino.
- Verificação local: os 72 manifests de bloco e os SHA-256/tamanhos dos Parquets foram conferidos; os totais de linhas correspondem ao manifesto. `COMPLETE.json` identifica explicitamente revisão manual pendente. Ainda não há deduplicação global, splits treino/validação/teste, teste de vazamento ou release pronta para treinamento.
- Publicação HF: `extraction/part001/` e o cartão raiz foram publicados em `BaruqRodrigues/camara-corpus-text`; revisão final `b7e09e8e4f5bea12831ea21d01937e066e0e0887`. Verificação anônima confirmou os 512 arquivos do prefixo, todos os tamanhos locais/remotos, e downloads byte a byte idênticos de `README.md`, `publication_manifest.json`, `COMPLETE.json` e `non_pdf_manifest.json`. O marcador final tem status `published_extraction_complete_manual_review_pending` e confere o SHA-256 `c581fbdf96e1713cb12d81524573c521dad11aa89ef6f95d74802abedd5f0fa3` do manifesto.

## Execução do segundo lote e divisão provisória

- `part002.tar` foi baixado da revisão raw `49f20d60f67713e82db62664849796673b4f3dcc`; SHA-256 `da1e04ed9e99f82db1c01c66605f930d5a676da42cc9bbfb81b02252fb474e51`, 6.797.271.040 bytes, 20.000 membros conferidos. Foram extraídos 17.809 PDFs em 72 blocos e processados 2.191 HTML/DOC, todos mantidos em quarentena para revisão documental.
- Extração publicada em `extraction/part002/`; revisão do commit de upload `263939bd3b367654f0b6fc3dd63ce4dca4cddca3`. Divisão provisória publicada em `splits/parts001-002-preview/`; commit `938189bd1b558356f97997ee9b5541f5ed7562a4`. Card e marcadores `COMPLETE.json` publicados no commit final `a74314ed4f4e4f1e92a5f5a6a894e7a1575fe24f`.
- A divisão foi recalculada em conjunto para os dois TARs, usando relações oficiais de proposições e hashes de origem/texto; atribuição `group_hash`, seed 42, meta 80/10/10. Resultado: 27.535 treino, 3.179 validação, 3.589 teste, 5.273 quarentena e 424 duplicatas textuais exatas. A verificação local confirmou zero famílias ou textos idênticos atravessando splits. SHA-256 do manifesto: `155c773a2aba51ebf95be8dc8f2eb8c2a8222303f4ca0f63fa31ece72055840d`.
- A API anônima confirmou que o repositório é público, o card e os marcadores finais correspondem byte a byte aos arquivos preparados, e 447 arquivos remotos têm tamanho compatível; SHA-256 foi conferido para os 295 objetos LFS. A prévia segue explicitamente marcada como provisória: deduplicação aproximada/containment, revisão humana/visual, complementos da coleta própria e integração dos demais TARs ainda estão pendentes.
- `part003.tar` passou pela verificação integral: 8.734.187.520 bytes, SHA-256 `d35c5776367797bc676da0d2be2ab5d2a28d0c0c6b842f5990ffd79d7ad39fab`, 20.000 membros. Foram processados 17.783 PDFs em 72 blocos e 2.217 HTML/DOC (2.167 HTML, 50 DOC), todos não-PDFs em quarentena.
- Extração `extraction/part003/` publicada no commit `6d6e66a5e8e6f280ee3d58ce68ce7e69af5d9f08`; preview conjunto `splits/parts001-003-preview/` no commit `ca7fa500b150fc9b232fcddf301f4555fa9bce35`; card e marcadores `COMPLETE.json` no commit final `b0dff1bea45c7bcd1f197cf3f93a8d1318bd63e9`.
- A divisão recalculada dos três TARs registra 39.590 treino, 4.733 validação, 6.589 teste, 8.209 quarentena e 879 duplicatas exatas. Verificação local confirmou zero famílias/textos idênticos cruzando splits. SHA-256 do manifesto: `3611fbb8b798bdaea3f565f746d489920d2e7d4a8f5a239f879240485d14ea91`. Verificação anônima confirmou card/marcadores byte a byte e 447 tamanhos remotos (incluindo SHA-256 dos 295 objetos LFS), sem ausências ou divergências.
- `part004.tar` passou pela verificação integral: 8.525.608.960 bytes, SHA-256 `37935e5a3ede308ac3a039dfa62b87493b96b688b44dd1a39e1671d32e0082fb`, 20.000 membros. Foi baixado da revisão raw `bcc3a4bc391b219ef9c3e8af15b5771ec79bcefb`; foram processados 17.702 PDFs em 72 blocos e 2.298 HTML/DOC (2.244 HTML, 54 DOC), todos não-PDFs em quarentena.
- Extração `extraction/part004/` publicada no commit `bcbeb115b840559f433211f378021a8349bf82ba`; preview conjunto `splits/parts001-004-preview/` no commit `e84497e2eeb61dca85715b1ae6c58127db13d1dd`; card e marcadores `COMPLETE.json` no commit final `0a68369a557802b6fb96636c60a9be9209be5ada`.
- Divisão dos quatro TARs: 54.415 treino, 6.368 validação, 6.640 teste, 11.187 quarentena e 1.390 duplicatas exatas. Verificação local encontrou zero famílias ou textos idênticos atravessando splits. SHA-256 do manifesto: `5f555978c53854884d35b9712f227fab90b64ee5c664277ed6a79ca058e370d3`. Para reduzir o custo quadrático do loop do motor R para 80 mil itens, o publicador calcula em R a mesma regra `digest::digest(paste0(family_id, ':', seed), algo='sha256')` uma vez por família; teste comparativo com `assign_splits()` confirmou atribuições e motivos idênticos em 200 itens/100 famílias. A API anônima confirmou card/marcadores byte a byte, 441 tamanhos remotos e SHA-256 dos 291 objetos LFS, sem ausências ou divergências.
- `part005.tar` passou pela verificação integral: 8.194.007.040 bytes, SHA-256 `e31a704f3bba9867ea52049ce89f85cae3f5dc777bbb443e9fc4b0ff888a51a0`, 20.000 membros, revisão raw `3fa4d71e3cd1b96b4dc9b6d33bfee1eca342aa1d`. Foram processados 17.789 PDFs em 72 blocos e 2.211 HTML/DOC (2.164 HTML, 47 DOC), mantidos em quarentena.
- Extração `extraction/part005/` publicada no commit `5e22ed01ba2cf8a9455f0d487d7f58573961eb50`; preview `splits/parts001-005-preview/` no commit `3238b6df22c73b75e2c2aa685ea10b960da145f9`; card e marcadores finais no commit `9a0bcee8957061da292ef0a30ffb32159f4508a6`.
- Divisão atual: 67.824 treino, 7.942 validação, 8.279 teste, 14.111 quarentena e 1.844 duplicatas exatas, em 100.000 itens. Verificação local encontrou zero famílias/textos idênticos cruzando splits. SHA-256 do manifesto: `1bfdd81d663a853f3b81aaed546d28604bbe8c44544d71cea5c7e1bf1faea48c`. Verificação anônima confirmou 447 tamanhos e SHA-256 dos 295 objetos LFS, sem ausências ou divergências; card/marcadores conferidos byte a byte.
- A localização correta dos TARs recebidos foi informada pelo usuário: pasta Drive `1HjjB6XLrC_7gqquAMU-YHJgMKn997Xue`, com os 43 arquivos `part001.tar`–`part043.tar`. O bloqueio de origem do `part006` foi resolvido; a execução abaixo registra a publicação e o processamento.

## Execução do sexto lote e divisão cumulativa

- `part006.tar` foi validado contra `processo_hiago/indice_tar2.csv`: 7.419.607.040 bytes, SHA-256 `528940debb956af2a1186621414062c20d93e3cd228ac46eb54ff4df6210b45c`, 20.000 membros. O TAR foi publicado no raw em `3a1910ccfa08605e7d8f98831bd727f1b0a3e6ad`; tamanho, SHA-256 LFS e manifesto de release foram conferidos publicamente.
- Foram extraídos 17.722 PDFs em 71 blocos retomáveis e processados 2.278 HTML/DOC (2.229 HTML, 49 DOC). Nos registros não PDF, 1.106 receberam `quality_status=fail`, 1.172 `review`; todos ficaram fora do treino, com 2.270 exigindo revisão documental e oito sinalizados como possível erro/placeholder.
- `extraction/part006/` foi publicado no commit `924e5f178faf8827289ce1593d90be748be8f301`. A divisão conjunta `splits/parts001-006-preview/` foi publicada no commit `8719357f60c67eebda5da60c3ce25072f3301803`; card raiz e marcadores finais no commit `0dbdbe0121c7c6714ba1d913f590d6e83f7907a6`.
- A prévia contém 120.000 itens e 71.155 famílias: 82.286 treino, 9.485 validação, 9.859 teste, 16.490 quarentena e 1.880 duplicatas exatas. Verificação local encontrou zero famílias em mais de um split e zero duplicatas sem destino ou atribuídas a split diferente. O manifesto tem SHA-256 `b457f3c48e1d9a4a182e9c2a5e534e562c2ad35cce3c57385d625a259239eb83`; os seis hashes de TAR e as seis revisões raw estão preenchidos.
- Verificação anônima do commit público de texto confirmou 441 arquivos da extração e da divisão por tamanho e hash (LFS SHA-256 ou Git blob SHA-1), e README/marcadores finais byte a byte. O raw, os manifests, as seis árvores de extração e a prévia cumulativa também foram preservados em `llm_do_zero_DATA/staging/` fora do Git.
- Correção registrada em `scripts/publication/prepare_text_split_preview.py`: quando o TAR não está ao lado da extração, o SHA de origem vem do manifesto de extração em vez de ficar nulo.

## Execução do sétimo lote e divisão cumulativa

- `part007.tar` foi retomado da pasta Drive informada pelo usuário e validado contra o índice: 7.866.552.320 bytes, SHA-256 `8c56c8c58103c7275df07b076ca19fafa1dabd6382168891a7bd9c72814d52fb`, 20.000/20.000 membros. Publicação raw verificada na revisão `f180810c5a5d0f17a492d4a5da2ab10c0ab9e74b`.
- Foram extraídos 17.778 PDFs em 72 blocos retomáveis e processados 2.222 HTML/DOC (2.173 HTML, 49 DOC). Nos registros não PDF, 1.069 receberam `quality_status=fail`, 1.153 `review`; nenhum foi incluído no treino, 2.219 exigem revisão documental e três foram sinalizados como possível erro/placeholder.
- `extraction/part007/` foi publicado no commit `91ef4e4137c90362a9b9f6a7380408a1b598867f`. A divisão conjunta `splits/parts001-007-preview/` foi publicada no commit `d3666535303fd017bd709324766995f250c74d5d`; card raiz e marcadores finais no commit `bdedb44a54690231af62194711446e9b47782e0e`.
- A prévia contém 140.000 itens e 80.325 famílias: 96.528 treino, 11.214 validação, 11.514 teste, 18.826 quarentena e 1.918 duplicatas exatas. Verificação local encontrou zero famílias em mais de um split e zero duplicatas sem destino ou atribuídas a split diferente. O manifesto tem SHA-256 `78008b09831fddba0c937f3b6df43c62737146b1a8f729d77e007867c59849f3`; os sete hashes de TAR e as sete revisões raw estão preenchidos.
- Verificação anônima do commit público confirmou 447 arquivos da extração e da divisão por tamanho e hash (LFS SHA-256 ou Git blob SHA-1), e README/marcadores finais byte a byte. O TAR, os manifests, a extração part007 e a prévia cumulativa também foram preservados em `llm_do_zero_DATA/staging/` fora do Git.
- Próxima etapa sequencial: validar e processar `part009.tar`; 35 TARs ainda não foram processados.

## Execução do oitavo lote e divisão cumulativa

- `part008.tar` foi conferido integralmente: 8.417.996.800 bytes, SHA-256 `52c9af40cd1de3d941cad28d7ba70e3a140a5bfc8bfacd2e534e32a209937789`, 20.000/20.000 membros. Publicação raw confirmada na revisão `9ca80d692b89befedde094a97f7ae6b14f751686`.
- Foram extraídos 17.810 PDFs em 72 blocos retomáveis (90.363 páginas, 74.858 seções e zero revisões automáticas de qualidade) com PDFKit e OCR seletivo Apple Vision. Também foram processados 2.190 HTML/DOC (2.145 HTML, 45 DOC); 1.109 ficaram `fail` e 1.081 `review`, todos excluídos do treino. Há 2.185 itens que exigem revisão documental e cinco possíveis erros/placeholders.
- `extraction/part008/` foi publicado em `32acf31ecfdb66e89a3769068e53127cfa2a4ea8`. A divisão `splits/parts001-008-preview/` foi publicada em `2730c12b286f604b177ea83793791ce5d32a80c1`; card e marcadores finais foram atualizados em `0765eafdf603acc105d50c76ee028447f0a03b40`.
- A prévia tem 160.000 itens e 89.179 famílias totais: 110.872 treino, 12.849 validação, 13.164 teste, 21.152 quarentena e 1.963 duplicatas exatas. A checagem local de itens elegíveis confirmou zero famílias ou textos idênticos atravessando splits, zero SHA de TAR ausente e 1.963 duplicatas com destino registrado. Os 10.841 registros de texto vazio estão excluídos do treino. SHA-256 do manifesto: `87faa077ec6770365d404dc9a332b02760c2e40f4a47ff2a7f2381e598ab09ed`; os oito hashes de TAR e revisões raw estão preenchidos.
- A checagem anônima da revisão pública `0765eafd` confirmou tamanho e hash dos 520 arquivos de extração/divisão, além de README e marcadores idênticos aos locais. Extração, prévia cumulativa, card e marcadores foram preservados no DATA_ROOT fora do Git.
- Próxima etapa sequencial: validar, publicar raw e processar `part013.tar`; restam 30 TARs.

## Execução do décimo quarto lote e divisão cumulativa

- `part014.tar` foi validado em 20.000/20.000 membros: 7.309.465.600 bytes, SHA-256 `2f2c9dd9eeaad17639737cdcdee0bdb11fd58c97d326118b8c3c416b5b7aeb90`. O raw foi publicado na revisão `3fd9fea3e4566dc8f0f9b9c0356d98cf507d979e`; a verificação anônima confirmou tamanho, SHA-256 e manifesto com 14 TARs.
- Foram extraídos 17.772 PDFs em 72 blocos, totalizando 84.564 páginas e 72.273 seções, sem linhas em `quality_reviews`. Foram processados 2.228 não PDFs (2.180 HTML e 48 DOC); 1.099 ficaram `fail` e 1.129 `review`, todos fora do treino. Há 2.215 registros para revisão documental e 13 possíveis erros/placeholders.
- `extraction/part014/` foi publicado na revisão `1a32468cb8e409b14d62ce91c363ca0a5f8a01f6`. A prévia `splits/parts001-014-preview/` foi publicada na revisão `a76520dd4b19fbaf668afe96d19d5f376c8f10a3`; card e marcadores finais foram atualizados em `4084784900a8336f7aa5f07d3eaf685d946998e5`.
- A prévia contém 280.000 itens e 134.857 famílias: 191.637 treino, 22.060 validação, 22.292 teste, 39.157 quarentena e 4.854 duplicatas exatas. A checagem local encontrou zero cruzamentos por família e por SHA de texto entre splits. SHA-256 do manifesto: `9ffbe4e3198e3148a23de8aa68ef310d9ed018e88ed4424104dc3f6d371b3f7b`.
- A revisão pública `40847849` foi conferida anonimamente: 520 arquivos de extração/divisão com tamanho e hash corretos; README e marcadores idênticos aos locais. TAR, extração, divisão, card e marcadores foram preservados no DATA_ROOT fora do Git.
- Próxima etapa sequencial: validar, publicar raw e processar `part015.tar`; restam 28 TARs.

## Execução do décimo terceiro lote e divisão cumulativa

- `part013.tar` foi validado em 20.000/20.000 membros: 8.795.463.680 bytes, SHA-256 `c64effb038ca9a5c973008c3cbafc407897323fe116b7d2a93e9ba984ecc7280`. O raw foi publicado na revisão `e4ca17fe43bb40abce330732463918949bcd2e0f`; verificação anônima confirmou tamanho, SHA-256 e manifesto com 13 TARs.
- Foram extraídos 17.724 PDFs em 71 blocos, totalizando 90.088 páginas e 69.526 seções, sem linhas em `quality_reviews`. Foram processados 2.276 não PDFs (2.234 HTML, 41 DOC e 1 TXT); 1.119 ficaram `fail` e 1.157 `review`, todos fora do treino. Há 2.267 registros para revisão documental e nove possíveis erros/placeholders.
- `extraction/part013/` foi publicado na revisão `e4a3d6fc594f50ef1b5cab7a1c7524a2904cd4e9`. A prévia `splits/parts001-013-preview/` foi publicada na revisão `c54572070391f3354beccbfd6423c192423ea629`; card e marcadores finais foram atualizados em `684b5ee82b92ed08a843e35f7c2c06bd5ba1683d`.
- A prévia contém 260.000 itens e 127.901 famílias: 178.300 treino, 20.476 validação, 20.707 teste, 36.149 quarentena e 4.368 duplicatas exatas. A checagem local encontrou zero famílias cruzando os splits elegíveis. SHA-256 do manifesto: `568af7cab838a8ea23fb16385d8b98aac95454832907800e187e7dd71a634dfc`.
- A revisão pública `684b5ee8` foi conferida anonimamente: 513 arquivos de extração/divisão com tamanho e hash corretos; README e marcadores idênticos aos locais. TAR, extração, divisão, card e marcadores foram preservados no DATA_ROOT fora do Git.
- Próxima etapa sequencial: validar, publicar raw e processar `part014.tar`; restam 29 TARs.

## Execução do décimo segundo lote e divisão cumulativa

- `part012.tar` foi validado em 20.000/20.000 membros: 8.145.981.440 bytes, SHA-256 `8bfcfd7e411bf19b309a7aa7c706d83923d911488b93d219ffa1da9e5ae54502`. Publicação raw verificada na revisão `4107060f4b92e2ce3ad4c83e3143ab2609e46dd8`; o manifesto contém doze TARs.
- Foram extraídos 17.722 PDFs em 71 blocos, com 87.404 páginas e 74.019 seções. Foram processados 2.278 HTML/DOC (2.230 HTML, 48 DOC); 1.102 receberam `fail`, 1.176 `review`, todos em quarentena. Há 2.264 exigindo revisão documental e 14 possíveis erros/placeholders.
- `extraction/part012/` foi publicado em `b4b594aa20dd918dcfa4dc48fbad74e5d0e7e96e`. A divisão `splits/parts001-012-preview/` foi publicada em `a6bb9989b7885207f56a06114cffb279e3e1d7d6`; card e marcadores finais em `f174df1702f21f2e20028898fd0080d8a64c9357`.
- A prévia contém 240.000 itens e 120.747 famílias: 164.928 treino, 18.990 validação, 19.152 teste, 33.092 quarentena e 3.838 duplicatas. A verificação local dos itens elegíveis encontrou zero famílias ou textos idênticos cruzando splits; zero SHA de TAR ausente. Os 17.462 textos vazios ficaram excluídos. SHA-256 do manifesto: `be1e929ed40c75f359b599e50666957e4cb0906af963d3d4d0d112fc1ed52a46`.
- A revisão pública `f174df17` teve 513 arquivos conferidos por tamanho e hash; README e marcadores coincidiram byte a byte. A extração, divisão, card e marcadores foram preservados no DATA_ROOT.
- Próxima etapa sequencial: validar, publicar raw e processar `part013.tar`; restam 30 TARs.

## Execução do décimo primeiro lote e divisão cumulativa

- `part011.tar` foi validado em 20.000/20.000 membros: 6.271.047.680 bytes, SHA-256 `493870b2f94e92ccb231c2e6cd3f7f26e21c90bb12729c106dabed5812b546ad`. Publicação raw confirmada na revisão `034da5f2fc3507659e8db506d4ac0d1eca2c1421`; o manifesto registra onze TARs.
- Foram extraídos 17.739 PDFs em 71 blocos, totalizando 73.574 páginas e 67.350 seções. Também foram processados 2.261 HTML/DOC (2.213 HTML, 48 DOC); 1.113 receberam `fail`, 1.148 `review`, todos fora do treino. Há 2.245 itens que exigem revisão documental e 16 possíveis erros/placeholders.
- `extraction/part011/` foi publicado em `0104f7772e1569d223415bb56b0fb317ab53c898`. A prévia `splits/parts001-011-preview/` foi publicada em `4e5309a5457b898993ca106ddeddd4ebcbd85050`; card e marcadores finais em `2c1d1c1a728dccfb940a9cdd67080c0bc5f9ce51`.
- A prévia contém 220.000 itens e 113.340 famílias: 151.455 treino, 17.531 validação, 17.603 teste, 30.053 quarentena e 3.358 duplicatas exatas. A checagem local encontrou zero cruzamentos de famílias/textos entre os itens elegíveis e zero SHA de TAR ausente. Os 15.773 textos vazios foram excluídos. SHA-256 do manifesto: `fd2da482eecbe647f3aa774af46d570c9bd5ee44a42f8ffc936f3733edd7c6c2`.
- A revisão pública `2c1d1c1a` teve tamanho e hash dos 513 arquivos de extração/divisão conferidos anonimamente; card e marcadores bateram byte a byte. Os artefatos foram preservados no DATA_ROOT fora do Git.
- Próxima etapa sequencial: validar, publicar raw e processar `part012.tar`; restam 31 TARs.

## Execução do décimo lote e divisão cumulativa

- `part010.tar` foi validado em 20.000/20.000 membros: 7.645.388.800 bytes, SHA-256 `8b3a17d1015a312d8e71042ed18b19654cf0393540b3617c7520df86680b4033`. O raw foi publicado e verificado na revisão `1cc932f8b932ebadd95fc1f2e1487e9713713d32`; o manifesto público contém dez TARs.
- Foram extraídos 17.729 PDFs em 71 blocos, totalizando 90.816 páginas e 79.392 seções. Foram processados 2.271 HTML/DOC (2.222 HTML, 49 DOC); 1.086 ficaram `fail`, 1.185 `review`, todos fora do treino. Há 2.261 itens que requerem revisão documental e dez possíveis erros/placeholders.
- `extraction/part010/` foi publicado em `30c098465ea732eaf2350c776eade7ed6444fc87`. A prévia `splits/parts001-010-preview/` foi publicada em `53e2f94c1f5d4065c187ec66b10f48224535f70f`; card e marcadores finais em `f0893b4493d4710069f34f9cfca7020411df60c5`.
- A prévia contém 200.000 itens e 105.624 famílias: 137.879 treino, 15.962 validação, 16.238 teste, 27.041 quarentena e 2.880 duplicatas exatas. A checagem local confirmou zero cruzamentos de família/texto entre os splits elegíveis, zero SHA de TAR ausente e 2.880 duplicatas com destino. Os 14.090 textos vazios foram excluídos. SHA-256 do manifesto: `8dd000290a731d09541fddde5b11d0ad3494945f8185a6b0938df3a3ab9ff085`.
- A checagem anônima da revisão `f0893b44` confirmou tamanho e hash dos 513 arquivos de extração/divisão, além de card e marcadores idênticos aos locais. A extração, divisão, card e marcadores foram preservados no DATA_ROOT externo ao Git.
- Para retomar a parte010 foi instalado o rclone CLI via Homebrew, usando a configuração Drive local que já existia. O download foi retomado do parcial de 3,5 GB, verificado contra o índice e transferido ao repositório raw sem erro.
- Próxima etapa sequencial: validar, publicar raw e processar `part011.tar`; restam 33 TARs.

## Execução do nono lote e divisão cumulativa

- `part009.tar` foi conferido em 20.000/20.000 membros: 8.878.131.200 bytes, SHA-256 `55eb38175f03a014a8d9660bb0fa2d78ceb8aaff662b68a9b46968f05871d234`. O manifesto raw público inclui o arquivo e foi conferido byte a byte na revisão `3e7b6e67baac57aefc57e3c4225cc13a2091710a`.
- Foram extraídos 17.824 PDFs em 72 blocos retomáveis, totalizando 93.593 páginas e 72.469 seções. Também foram processados 2.176 HTML/DOC (2.131 HTML, 45 DOC); 1.065 ficaram `fail`, 1.111 `review`, todos fora do treino, com 2.168 exigindo revisão documental e oito possíveis erros/placeholders.
- `extraction/part009/` foi publicado em `4a45864c0b8d2041f6173e79c0ff9b7b9b52e283`. A prévia `splits/parts001-009-preview/` foi publicada em `9b6ee2e7bc9e2d95e7ec8d9870cce70e573b99d9`; card e marcadores finais em `64506419fd16a4e7f5a70d50b50d2ecd178c05a3`.
- A prévia tem 180.000 itens e 97.599 famílias: 116.780 treino, 22.080 validação, 14.682 teste, 24.049 quarentena e 2.409 duplicatas exatas. A checagem local dos textos elegíveis confirmou zero cruzamentos de famílias ou hashes de texto entre splits, zero origem TAR ausente e 2.409 duplicatas com destino. Os 12.461 textos vazios foram excluídos. SHA-256 do manifesto: `901441e469a1383829348afed8a6e6ab38b5662572bb2a792e2aa63a33601990`; os nove hashes e revisões raw estão preenchidos.
- A checagem anônima da revisão `64506419` confirmou tamanho e hash dos 520 arquivos de extração/divisão e README/marcadores idênticos. A extração, divisão, card e marcadores foram copiados ao DATA_ROOT fora do Git.
- Durante a retomada, o volume temporário ficou sem espaço; foram removidas somente cópias dos TARs 006–008 que já estavam preservadas no DATA_ROOT. O part009 retomou do checkpoint após o bloco 32 e terminou sem reprocessar os blocos completos.
- Próxima etapa sequencial: validar, publicar raw e processar `part010.tar`; restam 34 TARs.
