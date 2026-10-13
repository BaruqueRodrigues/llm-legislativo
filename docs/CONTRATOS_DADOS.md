# Contratos de dados e interfaces — proposta 2.0.0

Data: 2026-10-07. Documento normativo para a futura implementação, ainda inexistente. Revisão do usuário: Câmara+Senado, todos os anos e categorias disponíveis, versões posteriores elegíveis; PDFKit/Apple Vision no Mac. A restrição anterior a PL inicial de um ano foi substituída. O coordenador aprova e versiona mudanças; nenhum agente altera a interface unilateralmente. Ler também [plano](PLANO_MESTRE.md), [decisões](DECISOES_TECNICAS.md) e [validação](VALIDACAO.md).

## 1. Convenções

Tabelas em Parquet com esquema Arrow explícito. JSON UTF-8 para manifestos/configurações de publicação; YAML para configurações humanas. Sem fatores R exportados, índices pandas, datas locais implícitas ou valores sentinela como `NA` em strings. `S` = string UTF-8; `I32/I64` = inteiros assinados; `F64` = double; `B` = boolean; `D` = date32; `TS` = timestamp em microssegundos UTC. `!` = não nulo; `?` = anulável. Listas são tabelas-filhas, salvo arrays explicitamente definidos em JSON. Identificadores e hashes são strings; nunca converter IDs oficiais a ponto flutuante.

Datas de apresentação sem fuso inequívoco: preservar `presentation_raw`, obter somente a data civil oficial em `presentation_date`; não fabricar UTC. Datas de captura e execução são UTC. Campos textuais desconhecidos são nulos; string vazia só quando a fonte realmente fornece vazio. Campos adicionais exigem incremento de esquema e migração testada R↔Python. JSONs brutos preservam campos oficiais não mapeados.

`house` ∈ `camara`, `senado` identifica o namespace da fonte oficial de obtenção; preservar também `legislative_body` para órgão/casa/fase responsável, inclusive Congresso Nacional em recursos hospedados pelo Senado. Proposição: `camara:prop:<id_oficial>` ou `senado:prop:processo:<id>`; código legado usa `senado:prop:materia:<codigo>` até reconciliação via entity_aliases. Nunca identificar por número/ano isolados. Autor: namespace, tipo e ID oficial; se faltar ID, `house:author:local:<sha256>` de identidade de fonte registrada, sem fundir pessoas pelo nome. Temas: `house:theme:<codigo>`; dicionários entre casas não são equivalentes por hipótese. IDs de coleções/fontes incluem namespace específico; não fundir código de processo com código legado por igualdade numérica. CodTipo/sigla/nome são distintos; várias classificações podem compartilhar sigla.

`document_id`: `house:doc:<source_namespace>:<id_oficial>` quando existir; senão `house:doc:<source_namespace>:url:<sha256(url_identidade)>`. Mesmo ID local em API/legado/arquivo pode identificar entidades distintas; não fundir sem entity_aliases verificado. Normalizar apenas esquema/host e fragmento comprovadamente irrelevante; preservar parâmetros de consulta que identificam inteiro teor. Guardar regra e URL original. Um documento lógico pode ter várias capturas e versões; relações com proposições ficam em ponte. `version_id = document_id + ':v:' + sha256_arquivo`, conservando o hash completo. Mudança binária gera versão observada, mesmo sem mudança textual. Não afirmar que é revisão legislativa sem evidência; `version_kind` distingue essas situações.

## 2. Tabelas de inventário e proveniência

Cada release contém snapshots dessas tabelas; história operacional é append-only. PK e FK são verificadas, não apenas anotadas.

### `source_snapshots` — uma captura de resposta oficial

| Campo | Tipo | Regra |
|---|---|---|
| snapshot_id | S! | PK; UUID ou hash determinístico da captura |
| house, source_kind | S! | API, arquivo anual, catálogo ou página |
| request_url, query_json | S! | URL e parâmetros exatos; `{}` se não houver |
| collected_at | TS! | relógio de captura |
| http_status | I32? | nulo se conexão falhar |
| payload_sha256, raw_path | S? | ambos preenchidos para payload preservado |
| pagination_complete | B! | false até fechar todas páginas/janelas |
| source_schema_version | S? | versão oficial quando informada |
| license_evidence_id | S? | FK `use_evidence` |

### `propositions` — uma linha por proposição no snapshot

| Campo | Tipo | Regra |
|---|---|---|
| proposition_id | S! | PK |
| house, source_id | S! | IDs originais; fonte/namespace registrados |
| type_code, type_source_id | S? | sigla e código oficiais; não filtrar só PL; pelo menos tipo/descrição quando verificável |
| type_label | S! | nome original ou unknown registrado |
| legislative_type_id | S? | FK legislative_types; nulo só se mapping não disponível |
| source_namespace | S! | API, legado, portal ou coleção; chave de aliases |
| number, numbering_year | I32? | valores numéricos quando aplicáveis; nunca identidade universal |
| number_raw, identifier_label | S? | identificação original, inclusive colegiado/numeração composta |
| presentation_date | D? | data de apresentação; não limita data de anexos/versões |
| presentation_raw | S? | valor original e semântica preservada |
| origin_house, legislative_body | S? | origem/órgão responsável quando comprovados; não confundir com host da fonte |
| title, summary | S? | ementa não substitui inteiro teor |
| source_uri | S! | página/API oficial |
| whole_text_url | S? | pista de documento; não prova papel inicial |
| snapshot_id | S! | FK captura de metadados |
| cohort_status | S! | candidate, included, excluded, review |
| cohort_reason | S! | motivo; vazio proibido |

### `authors` e `proposition_authors`

`authors`: `author_id:S!` PK; `house:S!`; `source_id:S?`; `name:S!`; `author_type:S!` (código oficial ou `unknown`); `source_uri:S?`; `snapshot_id:S!` FK. Não limitar a deputados: Executivo, comissões, Senado e autoria coletiva permanecem quando constarem na fonte.

`proposition_authors`: PK composta (`proposition_id:S!`, `author_id:S!`, `role:S!`); ambas FKs; `is_proponent:B?`; `signature_order:I32?`; `snapshot_id:S!` FK. Papel ausente vira `unspecified`; ordem não se inventa. A autoria textual e a autoria catalogada podem divergir e devem ser auditadas.

### `document_authors` — autoria própria do documento

PK (`document_id:S!`, `author_id:S!`, `role:S!`), FKs; `signature_order:I32?`; `source_uri:S!`; `snapshot_id:S!` FK. Papel pode ser author, rapporteur, signatory, issuing_body, unspecified, com código original preservado na captura. Autor de parecer/documento não é automaticamente autor da proposição nem só deputado; manter autoria documental e órgão quando fornecidos. Ausência de vínculo com proposição não impede esta ponte.

### `themes` e `proposition_themes`

`themes`: `theme_id:S!` PK; `house:S!`; `source_id:S!`; `name:S!`; `snapshot_id:S!` FK.

`proposition_themes`: PK (`proposition_id:S!`, `theme_id:S!`), FKs; `relevance:S?`; `snapshot_id:S!` FK. Ausência de tema não exclui um PL nem significa tema inexistente.

### `metadata_checks` — completude explícita por entidade

PK (`entity_kind:S!`, `entity_id:S!`, `endpoint_kind:S!`); entity_kind ∈ proposition, document, collection, phase; entity_id referencia respectivamente propositions, documents, source_collections ou process_phases por validador obrigatório. `status:S!` (pending, success_nonempty, success_empty, retryable_error, terminal_error); `snapshot_id:S?` FK; `last_checked_at:TS?`; `reason:S?`. Documento sem proposição e coleção também têm estado de autoria/tipo/relações. Endpoint não aplicável é declarado na política da entidade; vazio difere de não consultado/erro.

### `relations` — arestas dirigidas com evidência

`relation_id:S!` PK; `source_proposition_id:S!` FK; `target_proposition_id:S!` FK; `relation_type:S!` (código oficial e mapeamento documentado); `snapshot_id:S!` FK; `source_uri:S!`; `grouping_policy:S!` (bind, do_not_bind, review). Alvos fora da coorte são nós de inventário mínimos, com status excluded, não documentos de treino. Não agrupar todos os textos que simplesmente citam a mesma lei. Ligações mention e citações de PLs em diários/anais não são bind por si só; compartilhar volume/blob sem compartilhar unidade/texto não é aresta bind automática.

### `process_phases` e `document_phases`

`process_phases`: `phase_id:S!` PK; `process_proposition_id:S!` FK propositions/processo canônico; `house:S!`; `source_namespace:S!`; `source_phase_id:S?`; `phase_kind:S!` (initiating, reviewing, amendments, substitute, other, unknown); `legislative_body:S?`; `committee_source_id:S?`; `number_raw:S?`; `type_code:S?`; `numbering_year:I32?`; `date_start:D?`; `date_end:D?`; `source_uri:S!`; `snapshot_id:S!` FK. ID oficial é usado com namespace; sem ele, phase_id é hash de processo + identidade de fase da fonte registrada, sem deduzir fase apenas por data/sigla. Não criar fases fictícias para preencher campo.

`document_phases`: PK (`document_id:S!`, `phase_id:S!`), FKs; `role:S!`; `evidence:S!`; `snapshot_id:S!` FK. Fases distintas do mesmo processo permanecem entidades distintas; aliases legados apontam a processo ou fase conforme equivalência verificada, jamais colapsam fases por conveniência. Família textual considera continuidade documentada entre fases; fase/órgão não multiplica texto. Autoria documental continua em document_authors.

### `documents` e `proposition_documents`

`documents`: `document_id:S!` PK; `house:S!`; `source_document_id:S?`; `source_namespace:S!`; `identity_url:S!`; `document_type:S!` (original ou unknown); `document_type_source_id:S?`; `legislative_type_id:S?` FK; `legislative_body:S?`; `normalized_kind:S!` (initial, amendment, opinion, report, substitute, final_text, justification, session_record, speech, diary, annals, annex, other_legislative, unknown); `publication_date:D?`; `date_range_start:D?`; `date_range_end:D?`; `date_status:S!` (verified, inferred, unknown); `source_uri:S!`; `snapshot_id:S!` FK. Inferência é sinalizada e não tratada como data factual. Documento pode existir sem proposição identificada, especialmente em arquivos/anais/diários.

`proposition_documents`: PK (`proposition_id:S!`, `document_id:S!`), FKs; `document_role:S!` (initial, justification, exposition_of_motives, initial_with_justification, amendment, opinion, report, vote, substitute, final_text, associated, reproduction, mention, unknown); `role_status:S!` (verified, proposed, unknown); `role_evidence:S?`; `document_date:D?`; `source_order:I32?`; `snapshot_id:S!` FK. Papel verified exige evidência; emendas, pareceres, substitutivos e associados textuais legislativos são candidatos ao corpus. Menção isolada não é relação de continuidade nem prova de autoria/vinculação substantiva. Um PDF pode incluir articulado e justificativa: não o copiar como dois textos completos.

### `document_versions` — representação binária observada

| Campo | Tipo | Regra |
|---|---|---|
| version_id, document_id | S! | PK e FK |
| file_sha256, raw_path | S! | conteúdo endereçado por hash; pode compartilhar blob |
| file_size_bytes | I64! | > 0 |
| detected_media_type | S! | assinatura/parser; não extensão |
| page_count | I32? | > 0 para PDF válido |
| version_kind | S! | observed_capture, legislative_revision, repackaging |
| source_version_label | S? | somente valor da fonte |
| source_content_date, availability_date | D? | datas próprias da versão/conteúdo, quando comprovadas |
| version_date_status | S! | verified, inferred, unknown; captura não vira data histórica |
| predecessor_version_id | S? | FK se relação comprovada, não só cronologia |
| first_capture_id | S! | FK `fetch_attempts` de sucesso |
| integrity_status | S! | verified, quarantined |

### `fetch_attempts` — toda tentativa, inclusive erro

`capture_id:S!` PK; `document_id:S!` FK; `requested_url:S!`; `final_url:S?`; `started_at:TS!`; `finished_at:TS?`; `attempt_no:I32!`; `http_status:I32?`; `declared_media_type:S?`; `declared_size_bytes:I64?`; `received_size_bytes:I64?`; `file_sha256:S?`; `version_id:S?` FK; `status:S!`; `error_code:S?`; `error_message:S?`; `next_retry_at:TS?`. Não registrar credenciais. Resposta HTML de erro a uma URL `.pdf` nunca vira PDF válido.

### `use_evidence` — termos e sua aplicabilidade

`evidence_id:S!` PK; `source_uri:S!`; `accessed_at:TS!`; `snapshot_id:S?`; `applies_to:S!` (metadata, official_legislative_text, third_party_attachment, code); `permission_status:S!` (allowed, restricted, unresolved); `attribution_rule:S?`; `redistribution_rule:S?`; `review_note:S!`. Acesso aberto e ausência de licença no GitHub não equivalem a autorização irrestrita. Release interna pode ter itens unresolved separados; release redistribuível não pode incluí-los.

### Registro de fontes, taxonomias e cobertura histórica

`source_collections`: `collection_id:S!` PK; `house:S!`; `source_namespace:S!`; `name:S!`; `collection_kind:S!` (api, annual_files, dossier, archive, diary, annals, transcripts, other_legislative); `catalog_uri:S!`; `snapshot_id:S!` FK; `inventory_unit:S!` (proposition, process, document, volume, issue, archival_unit); `digital_availability_note:S!`. Descrição arquivística sem arquivo digital é registro, não texto recuperado.

`legislative_types`: `legislative_type_id:S!` PK; `house:S!`; `source_namespace:S!`; `type_source_id:S?`; `type_code:S?`; `type_label:S!`; `entity_kind:S!` (proposition, process, document, content, collection); `normalized_family:S!`; `mapping_status:S!` (verified, proposed, unknown); `snapshot_id:S!` FK. Chave não é sigla isolada; incluir codTipo/namespace ou hash da identidade de catálogo quando sem código. Todas entradas descobertas são inventariadas antes de seleção, inclusive tipos legados e sem sigla.

`coverage_segments`: `segment_id:S!` PK; `collection_id:S!` FK; `house:S!`; `legislative_type_id:S?` FK; `year:I32?`; `period_start:D?`; `period_end:D?`; `date_axis:S!` (presentation, numbering, publication, attachment, event, catalog_period, undated); `snapshot_cutoff_utc:TS!`; `query_json:S!`; `inventory_status:S!` (pending, running, exhausted, error, not_digitized); `coverage_status:S!` (pending, partial, empty_verified, closed_with_gaps, complete_discovered); `expected_count:I64?`; `discovered_count:I64!`; `retrieved_count:I64!`; `accepted_count:I64!`; `count_unit:S!`; `exhaustion_evidence:S?`; `gap_reason:S?`; `snapshot_id:S!` FK. Contagens não misturam processos/documentos/páginas; cada denominador e intervalo são explícitos. Ano nulo admite undated. Uma resposta vazia não define o primeiro ano nem encerra descoberta retrospectiva. Atualizações históricas ganham novo snapshot.

`collection_documents`: PK (`collection_id:S!`, `document_id:S!`), FKs; `source_catalog_id:S?`; `reference_code:S?`; `volume_label:S?`; `issue_label:S?`; `source_order:I32?`; `snapshot_id:S!` FK. Permite volumes/diários/dossiês/objetos arquivísticos sem proposição conhecida. Não converter volume que menciona muitos PLs em um vínculo bind com todos eles.

`entity_aliases`: `alias_id:S!` PK; `entity_kind:S!`; `alias_namespace:S!`; `alias_source_id:S!`; `canonical_entity_id:S!`; `evidence_uri:S!`; `snapshot_id:S!` FK; `status:S!` (verified, review). Unicidade (entity_kind, alias_namespace, alias_source_id). IDs de Senado processo/materia e Câmara portal/API podem apontar à mesma entidade apenas com evidência. Indisponibilidade de um ID na API não apaga sua ficha/arquivo disponível no portal.

Inventário deve percorrer API, arquivos/índices, documentos por processo, seções do portal, dossiês e acervos históricos disponíveis. Não whitelist de PL/ano único; não restringir documentos ao ano de apresentação de seu processo. Anais/diários/transcrições legislativas oficiais entram como coleções textuais com tipo próprio; descrições sem objeto digital ficam como lacunas. Fechamento GH é por todos segmentos descobertos reconciliados, não por ter concluído um lote ou obter uma porcentagem alta sem denominador.

## 3. Extração e curadoria

### `extraction_runs`, `pages` e `sections`

`extraction_runs`: `extraction_id:S!` PK; `version_id:S!` FK; `extraction_config_hash:S!`; `tool_versions_json:S!`; `host_os_build:S!`; `helper_source_sha256:S!`; `started_at:TS!`; `status:S!`; `error_code:S?`. Reexecução com outro extrator ganha novo ID.

`pages`: PK (`extraction_id:S!`, `page_index:I32!`), FK; índice começa em 1. `method:S!` (native, ocr, hybrid, none); `engine:S!` (pdfkit, apple_vision, poppler, tesseract, html, txt, other, none); `engine_revision:S?`; `recognition_level:S?` (fast, accurate); `recognition_languages_json:S?`; `uses_language_correction:B?`; `render_width:I32?`; `render_height:I32?`; `elapsed_ms:F64?`; `raw_text:S?`; `raw_text_sha256:S?`; `character_count:I64!`; `replacement_char_ratio:F64?`; `printable_ratio:F64?`; `image_area_ratio:F64?`; `ocr_confidence:F64?`; `layout_path:S?`; `layout_sha256:S?`; `quality_status:S!` (pass, review, fail); `quality_reasons_json:S!`. Métricas não disponíveis são nulas. Confiança OCR só vem do motor, com regra de agregação declarada, sem substituir auditoria humana nem ser comparada diretamente entre motores. Layout/bbox/confiança por bloco, quando coletados, ficam no artefato referenciado. HTML/TXT: uma página lógica explicitamente marcada no manifesto; não fingir páginas físicas.

`sections`: `section_id:S!` PK; `extraction_id:S!` FK; `ordinal:I32!`; `section_type:S!` (initial_text, justification, exposition_of_motives, amendment_text, report, opinion, vote, substitute_text, final_text, session_record, speech, annex, signatures, unknown); `page_start:I32!`; `page_end:I32!`; `start_char:I64?`; `end_char:I64?`; `detection_method:S!`; `confidence:F64?`; `review_status:S!`; `text:S!`. Offsets são intervalos [início,fim), em code points Unicode no texto de páginas concatenado por `\n\f\n`, com índice base zero. O texto final de treino não precisa conter form feed. Exposition_of_motives preserva tipo/head original e satisfaz a finalidade de justificativa quando sua vinculação ao articulado for comprovada. Não excluir justificativa por heading ausente; encaminhar incerteza à revisão.

### `curated_documents` — fronteira de entrada para Python

| Campo | Tipo | Regra |
|---|---|---|
| corpus_item_id | S! | PK; SHA256 de JSON canônico com versão, extração, logical_unit_id, spans, composição e limpeza |
| primary_proposition_id | S? | FK quando identificada; documentos de coleção podem não ter proposição |
| document_id, house, normalized_kind | S! | FK e atributos para cobertura por casa/tipo |
| content_date | D? | data pontual quando comprovada; não usar apresentação inicial por conveniência |
| content_date_start, content_date_end | D? | intervalo da unidade; usar conservadoramente faixa do container quando não houver mais precisão |
| temporal_date_evidence | S? | origem/regra e indicação de fallback ao intervalo do container |
| temporal_date_status | S! | verified, inferred, unknown |
| version_id, extraction_id | S! | FKs; nunca ementa disfarçada de inteiro teor |
| composition_id | S! | regra de composição/ordem e segmentação editorial, sem conteúdo substantivo descartado |
| logical_unit_id | S! | unidade legislativa/editorial; construção determinística abaixo |
| source_span_start, source_span_end | I64? | intervalos code points na extração; exigidos ao segmentar volume composto |
| text | S! | todo conteúdo substantivo legível da unidade documental, em ordem; UTF-8; não limitado a articulado/justificativa |
| text_sha256 | S! | hash dos bytes UTF-8 EXATOS de `text` |
| comparison_sha256 | S! | hash auxiliar; não usado para reconstrução |
| utf8_bytes, character_count | I64! | contagens de text; ambas > 0 |
| cleaning_version | S! | política identificada |
| presentation_date | D? | copiada quando conhecida; falta não exclui corpus group_hash |
| quality_status | S! | accepted ou quarantined |
| eligibility_reason | S! | decisão auditável |
| exact_cluster_id, family_id | S! | grupos exato e anti-contaminação |
| near_cluster_id | S? | grupo de candidatos próximos; não remove automaticamente |
| representative_item_id | S! | FK para representante; self se único |
| include_in_dataset | B! | somente representante elegível em qualquer split; não atribui treino |
| permission_status | S! | condição de uso; detalhes em use_evidence |

Identidade de unidade: documento simples usa logical_unit_id=document_id; peça/editorial com identidade oficial própria usa ID namespaced e vínculo ao container. Sem ID próprio, usar document_id + ':unit:' + SHA256 do source_locator canônico (código de referência/edição/posição original/páginas/ordem do elemento, preservados). Se locator não for estável entre versões, fallback explicitamente version-scoped inclui version_id; equivalência entre versões só por evidência/aliases, não pelo título. Definir a política e guardar source_locator no artefato de composição. corpus_item_id inclui logical_unit_id + source_span_start/end (ou lista ordenada de spans no manifesto de composição) para impedir colisão entre segmentos da mesma extração/regra. Spans são da extração referenciada e não de texto já limpo; offsets e transformações têm trilha.

`corpus_item_propositions`: PK (`corpus_item_id:S!`, `proposition_id:S!`), FKs; `link_type:S!` (document_for, reproduction, mention, unknown); `grouping_policy:S!` (bind, do_not_bind, review); `evidence:S!`. Mention não une famílias automaticamente. Uma unidade textual compartilhada por duas proposições continua sendo um corpus item; volume composto pode ter várias unidades independentes. `curated_document_sections`: PK (`corpus_item_id:S!`, `section_id:S!`), FKs; `output_order:I32!`; `included:B!`; `reason:S!`. Um item pode reunir seções de uma extração; unidades editoriais independentes de volume/dossiê podem ser itens distintos com spans e política versionada. Conteúdo aceito aparece uma vez na composição do arquivo: não treinar volume inteiro e seus segmentos juntos. Segmentar não autoriza apagar texto substantivo; resíduos legíveis ficam em unidade própria. justificativa separada em outro arquivo permanece item próprio da mesma família. Composição entre arquivos fica para nova versão de contrato.

`dedup_pairs`: PK (`left_item_id:S!`, `right_item_id:S!`); FKs; esquerda lexicograficamente menor; `method:S!`; `similarity:F64?`; `decision:S!` (exact, equivalent, substantive_variant, unrelated, review); `evidence:S!`; `policy_version:S!`. Registros substantive_variant ficam preservados e relacionados no mesmo split. Não apagar originais.

`cleaning_events`: `event_id:S!` PK; `corpus_item_id:S!` FK; `rule_id:S!`; `before_sha256:S!`; `after_sha256:S!`; `affected_spans_json:S!`; `reason:S!`. Antes/depois correspondem a artefatos intermediários preservados ou reconstruíveis. Remoção de cabeçalhos, rodapés e assinatura digital exige regra por posição/repetição e amostra visual; nomes/subscrições substantivas não se confundem com selo digital.

`quality_reviews`: `review_id:S!` PK; `extraction_id:S!` FK; `corpus_item_id:S?` FK; `page_index:I32?`; `reviewer:S!`; `sample_seed:I64!`; `stratum:S!`; `result:S!`; `cer:F64?`; `wer:F64?`; `reviewed_at:TS!`; `notes:S!`. Não colocar transcrições extensas no Git.

### `split_assignments`

PK (`split_version:S!`, `corpus_item_id:S!`); FK; `family_id:S!`; `split:S!` (train, validation, test, quarantine); `policy:S!` (group_hash, temporal_purged); `assignment_reason:S!`; `seed:I64!`; `temporal_cut_train:D?`; `temporal_cut_validation:D?`. O family_id tem exatamente um split por versão. A release pode conter itens excluídos para auditoria; só items accepted + include_in_dataset entram nos tokens.

## 4. Cardinalidades e integridade

- Proposição↔autor N:M; proposição↔tema N:M; proposição↔documento N:M; documento→versão 1:N; versão→extração 1:N; extração→página/seção 1:N.
- Cada item curado aponta a uma versão; uma versão composta pode ter N unidades/itens com spans e composição validados; item↔seção N:M; item↔proposição N:M; item→split 1:1 em uma split_version; família→split 1:1. Elegibilidade é por documento: parecer/emenda/substitutivo/diário não precisa conter articulado e justificativa juntos. Textos iniciais têm completude de seções auditada, mas falta de justificativa no processo não exclui automaticamente outros documentos válidos. Não preencher conteúdo ausente. Tipos e versões substantivas solicitados ficam elegíveis; quarantine só por falha concreta registrada, não por ano, autoria ou categoria.
- Autor/tema nunca são joins do dataset de treino. O dataset seleciona diretamente corpus_item_id distintos e seus representantes. Relatórios N:M usam contagem de proposições distintas ou peso fracionário declarado, não somam textos multiplicados.
- PKs únicas e não nulas; FKs válidas; hashes SHA-256 com 64 hexadecimais; caminhos relativos ao DATA_ROOT, sem `..`; tamanhos recalculados; intervalos e ordem de seções coerentes; razões de exclusão não vazias.
- Todo texto chega ao binário e captura; todo binário aceito chega a URL e horário. Mesmo hash em muitas URLs preserva todas as capturas. Estados terminal_error não silenciam faltantes no denominador de cobertura.
- Um PL sem URL, autoria ou tema continua no inventário. Nenhum placeholder vazio é texto de treino. Data desconhecida fica sinalizada e permite group_hash quando origem/texto/tipo legislativo forem verificáveis; é excluída de avaliação temporal estrita. Tipo/papel incerto requer revisão específica; não exigir papel inicial para categorias posteriores. Extração insuficiente continua quarantined.
- Release de treino: zero representantes exatos repetidos, zero famílias cruzando splits, zero PK/FK inválidas, todos os itens com proveniência e permissões registradas. O total aceito + quarentena + não disponível deve reconciliar os denominadores explicitamente definidos.

## 5. Estados, retomada e arquivos

Não usar um único campo `processed` para todo o pipeline. Manifesto de estágio registra `stage`, `entity_id`, `config_hash`, `input_hashes`, `status`, `attempt_no`, `started_at`, `finished_at`, `error_code`, `next_retry_at` e `output_hashes`; estados: pending → running → succeeded, retryable_error ou terminal_error; saída ambígua → quarantined. Um running abandonado volta a pending somente após lease expirar e conferir artefatos; succeeded só após validação e publicação. Chave idempotente por (stage, entity_id, config_hash, input_hashes). Logs append-only podem ser JSONL; snapshots em Parquet. Não inferir sucesso pela existência de um arquivo parcial.

Proposta de política inicial: duas conexões por host, timeout conexão 10 s/leitura 120 s, até 5 tentativas totais com backoff exponencial e jitter, respeitando Retry-After. 429/5xx/timeout são retentáveis; 404/410 ficam terminais após revisão de URL; 401/403 exigem registrar limitação, sem contornar controle. Parâmetros ajustáveis e sujeitos às regras oficiais. Escrever `.part` no disco local, verificar formato/parser/tamanho/hash e então promover. Não prometer transação atômica em Drive montado.

```text
DATA_ROOT/                         # externo ao Git
  sources/<house>/<snapshot_id>/   # respostas e termos brutos
  raw/sha256/<hh>/<hash>.bin        # bytes originais imutáveis
  staging/<stage>/<run_id>/        # parciais e leases
  extracted/<extraction_id>/       # páginas e extrações brutas
  curated/<corpus_version>/        # tabelas + release manifest
  tokenizers/<tokenizer_id>/       # tokenizer.json + manifesto
  tokens/<token_dataset_id>/       # arrays + índice + manifesto
  runs/<run_id>/                   # config, eventos, métricas, resultados
  reports/<release_or_run_id>/     # auditorias completas
```

Código/configurações/manifestos leves sem conteúdo documental podem ficar no Git. Dados integrais, RDS, Parquet de corpus, PDFs, textos, tokens e checkpoints nunca ficam no histórico. `.gitignore` e um DATA_ROOT externo serão criados pelo coordenador na onda 0. Manifestos públicos não devem copiar dados pessoais desnecessários nem URLs com credenciais. Git é histórico de código; corpus tem histórico próprio.

### Perfil de extração nativa Mac

Perfil proposto `mac_native_v1`: PDFKit primeiro; Vision fast com pt-BR se suportado por revision/build local, e accurate para páginas/estratos que não atendam qualidade ou estejam fora do suporte. Ambos modos são candidatos ao benchmark. Pré-verificar supportedRecognitionLanguages para cada modo, guardar OS/build/SDK/compilador/helper SHA-256/request revision e hashes de saída. PDFKit e OCR são métodos distintos; não passar documento digital inteiro pelo OCR por padrão.

Benchmark de fast/accurate/Tesseract, quando disponível, usa as mesmas imagens/páginas, renderização/resolução e protocolo de transcrição, registra correção de idioma e separa warmup/compilação da execução. Medir páginas/s, latência p50/p95, memória e CER/WER/erros jurídicos; não afirmar aceleração não medida. O helper de pesquisa altera resolução e correção junto com --accurate; seus defaults não isolam efeito do modo. Markdown do helper não fornece toda proveniência, bbox/confiança ou tratamento de tabelas exigidos do adaptador do projeto. Saída textual preservada é o artefato reprodutível; reexecutar Vision após upgrade macOS pode mudar resultado e requer extraction_id novo.

## 6. Limpeza, deduplicação e splits

Limpeza preserva maiúsculas/minúsculas, acentos, números, artigos, parágrafos, incisos, alíneas, ementa documental e justificativa. Uniformizar quebras CRLF→LF e remover artefatos comprovados; eventual NFC é transformação versionada, com hash anterior e posterior e auditoria. Não corrigir OCR por linguagem adivinhada nem remover hifens jurídicos. Comparação para dedup pode colapsar espaços em cópia auxiliar; jamais alterar text por esse motivo.

Dedup: (1) hash binário para compartilhar armazenamento; (2) hash de texto exato; (3) candidatos por shingles/MinHash/LSH e índice de passagens para detectar containment/reprodução de peça curta em dossiê/diário longo; (4) confirmação por similaridade/diff/evidência da unidade. Jaccard global isolado não detecta necessariamente inclusão de texto curto em volume grande. Conservação dos textos substantivos e seleção de representantes devem distinguir reprodução verdadeira de citação normativa genérica. Sugestão inicial: shingles de 5 palavras, Jaccard ≥ 0,90 como candidato, não licença para excluir. Negações, valores, datas, artigos ou destinatários alterados são diferenças substantivas mesmo com similaridade alta. Equivalência exige revisão e motivo; representante pela melhor qualidade, completude e depois menor corpus_item_id. Boilerplate isolado não basta para agrupar proposições independentes.

Construir grafo GLOBAL ANTES do split, entre anos/casas/coleções, ligando itens da mesma unidade legislativa/proposição/processo/fase vinculada, versões da mesma unidade, duplicações/reproduções e relações que impliquem continuidade textual; relações genéricas ficam fora. Ligação próxima confirmada como versão substantiva une família, mas não remove item. Candidatos não resolvidos em alto risco ficam em quarentena. Aplicar fechamento transitivo e auditar componentes gigantes para evitar junções por tema ou citações genéricas. Nós externos ajudam detectar relações, sem ampliar corpus automaticamente.

Corpus histórico de ambas casas: group_hash determinístico por family_id + seed, metas propostas 80/10/10 em famílias. Ordenar famílias e usar hash uniforme em intervalos [0,0,8), [0,8,0,9), [0,9,1); proporções reais em documentos e bytes podem diferir e são publicadas. family_id = hash dos IDs de membros ordenados; nova composição requer nova split_version. Se validação ou teste ficarem pequenos ou sem diversidade, rever por política de alocação em grupos ANTES do tokenizer, sem examinar loss de teste. Não estratificar por autor/tema como se categorias fossem exclusivas.

Experimentos temporais futuros: cortes por data verificada do conteúdo/versão (`content_date`/`availability_date`, ou intervalo da unidade em diários/anais) e `temporal_purged`. A data de apresentação só substitui data textual se a fonte comprovar que o item é o texto inicial disponível naquele instante; numeração/tramitação/captura não a substituem. Extensão temporal da família usa todos itens/versões com datas conhecidas, inclusive reproduções/vínculos entre casas; datas de nós de inventário são evidência auxiliar, não fabricação de data do texto. Documento de 2026 em processo de 1995 não entra no treino anterior a 2026. Famílias cujo intervalo cruza qualquer corte ficam inteiramente quarantine nesse protocolo; datas desconhecidas/inferidas não verificadas também. Publicar contagens, bytes e estratos purgados; a medida estima generalização em famílias elegíveis novas, não toda produção futura. Alternativa mover toda família para split mais tardio retira material antigo do treino e mistura datas no teste, só como sensibilidade identificada. Nunca mover conteúdo futuro para treino. Recalcular splits ao acrescentar anos/fontes/relações e não reutilizar tokenizer quando textos de seu treino migrarem a held-out.

## 7. Release e fronteira R→Python

R é responsável por inventário, downloads, orquestração de extração/OCR e curadoria/auditoria. No Mac, adaptador Swift versionado usa PDFKit para texto embutido e Apple Vision para OCR seletivo; R o chama e registra versões/build/idioma/mode/renderização. Poppler/Tesseract são alternativas opcionais em outra plataforma ou comparação, não dependências obrigatórias do caminho nativo. O helper da habilidade pdf-to-markdown foi inspecionado como referência de pesquisa, sem supor que seu Markdown já satisfaça os contratos. Python começa pelo corpus curado publicado, sem refazer joins de autores/temas. Importações ad hoc de RDS não são interface.

`release_manifest.json` exige: schema_version, corpus_version, created_at_utc, cohort_definition, source_snapshot_ids, snapshot_cutoff_utc, history_scope (all_available), houses, source_collection_ids, coverage_segment_ids, coverage_status (partial, closed_with_gaps, complete_discovered), document_type_mapping_version, selection_policy, extraction_config_hash, cleaning_version, dedup_policy_version, split_version, seed, code_revision (commit futuro ou hash do bundle enquanto não houver Git), permission_summary, counts por etapa/split, utf8_bytes por split, e files[] com path, table_name, row_count, size_bytes, sha256, Arrow schema. corpus_version identifica publicação imutável; nunca sobrescrever em local existente. Release parcial declara house/source/collection/type/year/períodos e pendências; amostra de homologação não se apresenta como corpus histórico completo. Todas as categorias e versões aprovadas permanecem elegíveis para treino, respeitados splits/dedup/qualidade/permissões. Disponibilizar uma pequena cópia sanitizada do manifesto no repositório, com URI externa do payload.

Publicação: gerar tabelas e manifesto em staging; validar invariantes e hashes; publicar marcador `COMPLETE.json` por último contendo hash do manifesto. Leitor só aceita manifesto completo e arquivos validados. Essa convenção detecta publicação incompleta mesmo sem atomicidade do armazenamento remoto.

Leitor Python recebe DATA_ROOT e corpus_version; confere marcador/esquema/hash; carrega curated_documents + split_assignments da mesma versão; seleciona accepted, include_in_dataset e split específico; confere unicidade antes de extrair text. Arquivos de autoria/tema servem apenas a análises estratificadas por IDs, nunca à criação das sequências.

## 8. Tokenizer, tokens e batches

Proposta inicial: BPE em bytes via biblioteca Tokenizers, sem normalizer destrutivo, alfabeto ByteLevel completo, decoder correspondente e sem prefixo de espaço artificial. Vocabulário candidato 8.192/16.384 INCLUINDO especiais, decisão após medir somente treino. IDs reservados PAD=0, BOS=1, EOS=2; confirmar e gravar no manifesto, falhar se biblioteca produzir outro mapeamento. Sem UNK no caminho byte-level completo. Conteúdo que coincide com a grafia de especiais deve ser codificado como texto comum; IDs de controle só são inseridos pela construção de sequências. Verificar essa configuração em vez de confiar no default da biblioteca.

`tokenizer_manifest.json`: tokenizer_id, corpus_version, split_version, training_item_ids_hash, training_text_hashes_hash, config_hash, library/version, vocab_size efetivo, special_tokens, alphabet_policy, normalization_policy, tokenizer_file_sha256, seed/order, training_bytes. Nenhum texto de validation/test participa de merges, vocabulário, escolha por estatísticas desses conjuntos ou amostra de treino do tokenizer. Validação serve para decisões de experimento posteriores explicitamente identificadas; teste fica reservado.

Um registro por item elegível: `[BOS] + encode(text) + [EOS]`. Sem concatenar documentos na primeira versão. Separadores de seção são quebras/títulos preservados em text; não inventar conteúdo legal. Janelas longas: para comprimento L, inícios s em range(0, len(ids)-1, L); n_pairs=min(L, len(ids)-1-s), input=ids[s:s+n_pairs], target=ids[s+1:s+n_pairs+1]. Input/target têm o mesmo comprimento antes do padding; não emitir janela sem alvo nem usar EOS final como input sem próximo token. Cada target real do documento aparece exatamente uma vez por passagem. A última posição prevista em uma janela vira primeiro input da próxima; posição de embedding reinicia por janela. Contexto anterior além desse token é perdido, limitação publicada. Não inserir BOS a cada janela do treino sem mudar a política.

Padding só à direita: input PAD; target -100 nas posições sem alvo; `loss_mask` boolean; `attention_mask` indica inputs válidos. Nunca treinar sobre PAD nem tratar -100 como token. Atenção causal permite j≤i e chaves válidas; evitar softmax de linha inteira mascarada para queries PAD, cujas saídas são descartadas. Cada janela pertence a um único documento, impedindo atenção entre documentos. Embedding PAD compartilhado com saída, se houver tying, não pode ser presumido imune a gradiente do softmax; não depender de peso zero de PAD para mascaramento.

Arrays de tokens: `.npy` int32 little-endian, 1-D por shard, sem pickle; índices Parquet. `token_index`: corpus_item_id:S!, split:S!, shard_path:S!, offset:I64!, length:I64!, text_sha256:S!, utf8_bytes:I64!. Intervalos [offset,offset+length) válidos, disjuntos, BOS/EOS presentes. Arrays do disco viram torch.int64 em batch. IDs ∈ [0,vocab_size); shards separados por split. Não armazenar todas janelas duplicadas: derivar índice determinístico, com `sequence_policy_version` e L no manifesto. token_dataset_id muda com tokenizer, corpus, split ou política.

`token_dataset_manifest.json` exige token_dataset_id, corpus_version, split_version, tokenizer_id e hash, sequence_policy_version, context_length, special_tokens, dtype/endian, counts por split (items/body_tokens/valid_targets/bytes), índice e files com path/size_bytes/sha256. Tokenizer e dataset de tokens também publicam COMPLETE com manifest_sha256 por último; leitores verificam todos arquivos. tokenizer_id/token_dataset_id identificam versões imutáveis da configuração e inputs, e não podem ser reaproveitados para conteúdo diferente.

Batch comum: input_ids int64[B,L], targets int64[B,L], attention_mask bool[B,L], loss_mask bool[B,L], item_ids/lista e window_offsets. Modelo devolve logits float[B,L,V]. Loss = soma CE em alvos válidos / quantidade de alvos válidos; PAD não participa. Contagem de throughput reporta alvos válidos e também posições processadas para explicitar padding.

## 9. Contrato de execução e checkpoint

Config resolvida exige corpus_version, split_version, tokenizer_id, token_dataset_id, sequence_policy_version, model (V,L,d,n_layers,n_heads,dropout,tie_embeddings), optimizer, scheduler, seed, precision, micro_batch_size, grad_accum_steps, max_steps/max_tokens, budget_counter (successful_update_tokens por padrão; consumed_tokens se explicitamente escolhido), evaluation_interval, checkpoint_interval_steps/seconds, DATA_ROOT/RUN_ROOT e código/ambiente identificados. CLI planejada falha cedo se versões ou dimensões não coincidirem; nenhum fallback silencioso.

Separar `scientific_config_hash` (corpus/split/tokenizer/tokens, arquitetura/L/V, sequência, otimizador e plano scheduler/orçamento) de `execution_config_hash` (paths/dispositivo/microbatch/acumulação/precisão e opções numéricas do segmento). Persistir ambos, a config integral e revisão de código. Retomada exige identidade científica; paths/device podem mudar após validação. Microbatch/acumulação/precisão só mudam com transição explícita registrada e comparação limitada, preservando plano scheduler/orçamento; não alegar trajetória idêntica. Mudanças científicas são nova run; mudança de código exige revisão identificada e decisão de nova run ou migração justificada pelo coordenador, nunca atualização silenciosa.

Checkpoint schema_version=1: model_state, optimizer_state, scheduler_state, amp_scaler_state quando usado, global_step de updates efetivamente aplicados, tokens_seen de alvos processados, tokens_for_successful_updates, budget_counter, segment_id, epoch, sampler permutation/seed/cursor e próximo batch, RNG Python/NumPy/Torch CPU/todas GPUs, config resolvida, config_file_sha256, scientific_config_hash e execution_config_hash, IDs/hashes de corpus/tokenizer/tokens/código, precision e hardware, best_validation_metric e contadores de early stopping, event_sequence. Guardar na fronteira de tentativa de update concluída (aplicada ou descartada por overflow), após atualização do scaler/contadores e zero_grad; não salvamos acumulação parcial. Primeiro loader num_workers=0 evita cursor ambíguo por prefetch; ampliar workers exige contrato de retomada adicional.

Arquivo `.pt` confiável do próprio projeto, com tensores e tipos básicos; RNG NumPy convertido em estrutura compatível com carga restrita, ou companion JSON validado. Não depender de unpickle irrestrito de objeto externo. Restaurar modelo/otimizador/scheduler/scaler antes do RNG final; conferir próximo batch e scheduler. Se AMP descartar update por overflow, registrar evento; scheduler/global_step avançam só se houve update. tokens_seen inclui consumo, distinguir `tokens_for_successful_updates` para orçamento científico. max_tokens usa o contador indicado em budget_counter, persistido e idêntico na retomada; max_steps usa global_step de updates aplicados. Overflow não consome orçamento de successful_update_tokens, mas consumo real/tempo continuam registrados, com teto de sessão independente para impedir repetição indefinida.

Manifesto de checkpoint: run_id, checkpoint_id, schema_version, global_step, tokens_seen, files com tamanho/hash, config_file_sha256, scientific_config_hash, execution_config_hash, tokens_for_successful_updates, budget_counter, segment_id e IDs. Salvar localmente, copiar como candidato persistente, reler e verificar, publicar `COMPLETE.json` por último; índice `latest.json` aponta apenas checkpoint completo. Manter duas versões completas antes de eliminar alguma. Mudança de arquitetura/tokenizer/corpus é nova run; mudança de hardware ou microbatch na retomada cria segmento registrado, sujeito às regras do [Colab](COLAB.md).

### Isolamento da persistência e trajetória de métricas

`persistent_run_root` identifica exclusivamente `runs/<run_id>`, nunca a raiz de todos os runs. Publicador/resolver rejeitam run_id ou hashes científicos incompatíveis. `COMPLETE.json` de checkpoint contém run_id, checkpoint_id e manifest_sha256; `latest.json` contém esses mesmos campos e caminho relativo do manifesto. Resolver valida ponteiro, marker, manifesto e files; fallback busca apenas checkpoints completos compatíveis do mesmo run. Um único writer publica por run; testes usam run_ids próprios.

Métricas/eventos têm event_id=`run_id:segment_id:sequence_in_segment`, checkpoint_parent_id, global_step, tokens_seen, timestamp_utc e tipo. Nova sessão cria segment_id novo. Em rollback, trajectory_manifest registra checkpoint de retorno e segmento predecessor; prefixo até o checkpoint permanece válido e métricas posteriores daquele ramo ficam abandoned, sem apagar evidência. A análise usa só a trajetória ativa e não agrega steps repetidos de ramos descartados. Event_sequence no checkpoint permite identificar o prefixo confirmado; não é ID global único sem segmento. Exports e curvas sempre identificam trajetória/segmento; mesma regra vale para gerações/avaliações feitas depois do ponto recuperado.

## 10. Exemplo sintético mínimo — não são dados reais

```json
{"proposition_id":"camara:prop:SYN001","house":"camara","source_id":"SYN001","type_code":"PL","number":1,"numbering_year":2023,"presentation_date":"2023-03-15","presentation_raw":"2023-03-15","origin_house":null,"title":null,"summary":"Ementa sintética.","source_uri":"https://example.invalid/proposicoes/SYN001","whole_text_url":null,"snapshot_id":"SYN-SNAPSHOT-1","cohort_status":"included","cohort_reason":"fixture sintética","type_source_id":null,"type_label":"Projeto de lei sintético","legislative_type_id":null,"source_namespace":"fixture","number_raw":"1","identifier_label":"PL 1/2023 (sintético)","legislative_body":"Câmara dos Deputados"}
```

SYN001 tem dois autores e dois temas; as pontes têm duas linhas cada. Há apenas um documento lógico, uma versão observada, duas páginas (articulado e justificativa) e um corpus item. O produto cartesiano autores×temas teria quatro linhas; o índice de treino deve continuar com uma. Exemplo de text: `PROJETO DE LEI\nArt. 1º Fica instituído o programa exemplo.\n\nJUSTIFICAÇÃO\nEsta é uma justificativa sintética.` Hashes nas fixtures devem ser calculados sobre os bytes, nunca preenchidos com placeholders numa release válida.

SYN002 é idêntico ao item SYN001: dois itens auditáveis, um representante elegível, mesma família e split. SYN003 altera “instituído” para “revogado”: diferença substantiva; preserva item e, se versão relacionada, permanece na mesma família. SYN004 tem PDF inválido: continua no inventário, sem versão validada nem texto de treino. SYN005 e SYN006 são versões antes/depois de um corte temporal: ambas quarantine em temporal_purged.
