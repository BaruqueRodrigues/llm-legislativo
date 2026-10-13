# tests/inventory/senado/test_senado_inventory.R
# Testes formais e rigorosos para a Frente 10 (Inventário Histórico do Senado)
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0) e docs/subagents/10_SENADO.md

suppressPackageStartupMessages({
  library(testthat)
  library(arrow)
  library(dplyr)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))
source(file.path(repo_root, "R", "inventory", "senado", "client.R"))
source(file.path(repo_root, "R", "inventory", "senado", "taxonomies.R"))
source(file.path(repo_root, "R", "inventory", "senado", "collections.R"))
source(file.path(repo_root, "R", "inventory", "senado", "inventory_engine.R"))
source(file.path(repo_root, "R", "inventory", "senado", "publisher.R"))

# ==============================================================================
# TESTE 1: Mocks de comportamento S/N e default tramitando vs encerrados
# ==============================================================================
test_that("SEN-01: Default tramitando omitido retorna apenas tramitando=Sim; filtro N descobre encerrados", {
  client <- create_senado_client(offline_mode = TRUE)

  # Mock de bare /processo (default do Senado retorna apenas processos tramitando)
  client$register_mock(
    path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=S",
    response_data = list(
      list(
        id = 1001,
        codigoMateria = 2001,
        sigla = "PL",
        identificacao = "PL 1/2024",
        ementa = "Projeto em tramitação ativa",
        dataApresentacao = "2024-01-10",
        tramitando = "Sim",
        objetivo = "Iniciadora",
        tipoDocumento = "Projeto de Lei",
        autoria = "Senador Teste A"
      )
    )
  )

  # Mock de processos encerrados (tramitando = N)
  client$register_mock(
    path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=N",
    response_data = list(
      list(
        id = 1002,
        codigoMateria = 2002,
        sigla = "PL",
        identificacao = "PL 2/2024",
        ementa = "Projeto encerrado e arquivado",
        dataApresentacao = "2024-02-15",
        tramitando = "Não",
        objetivo = "Iniciadora",
        tipoDocumento = "Projeto de Lei",
        autoria = "Senadora Teste B"
      )
    )
  )

  # Mocks dos detalhes e documentos vazios para focar na descoberta
  client$register_mock(path_pattern = "processo/100[12]", response_data = list(id = 1001))
  client$register_mock(path_pattern = "processo/documento\\?idProcesso=100[12]", response_data = list())
  client$register_mock(path_pattern = "processo/emenda\\?idProcesso=100[12]", response_data = list())

  # Executar engine com ambos os filtros (S e N)
  res <- inventory_senado_processes(
    client = client,
    years = c(2024),
    siglas = c("PL"),
    tramitando_filter = c("S", "N"),
    fetch_child_entities = TRUE,
    max_processes_per_run = 10
  )

  expect_equal(nrow(res$propositions), 2)
  expect_true("senado:prop:processo:1001" %in% res$propositions$proposition_id)
  expect_true("senado:prop:processo:1002" %in% res$propositions$proposition_id)

  # Verificar que o processo encerrado não foi descartado
  p_encerrado <- res$propositions %>% filter(source_id == "1002")
  expect_equal(nrow(p_encerrado), 1)
  expect_equal(p_encerrado$cohort_status, "candidate")
})

# ==============================================================================
# TESTE 2: Mapeamento taxonômico e transição histórica PLS/PLC -> PL (2018/2019)
# ==============================================================================
test_that("SEN-02: Transição histórica de siglas preserva taxonomia sem perda de acervo anterior a 2019", {
  client <- create_senado_client(offline_mode = TRUE)

  # Mock de siglas oficiais
  client$register_mock(
    path_pattern = "processo/siglas",
    response_data = list(
      list(sigla = "PL", descricao = "Projeto de Lei", dataInicio = "1900-01-01", dataFim = NULL),
      list(sigla = "PLS", descricao = "Projeto de Lei do Senado", dataInicio = "1900-01-01", dataFim = "2018-12-31"),
      list(sigla = "PLC", descricao = "Projeto de Lei da Câmara", dataInicio = "1900-01-01", dataFim = "2018-12-31"),
      list(sigla = "PEC", descricao = "Proposta de Emenda à Constituição", dataInicio = "1900-01-01", dataFim = NULL)
    )
  )
  client$register_mock(path_pattern = "processo/documento/tipos$", response_data = list())
  client$register_mock(path_pattern = "processo/documento/tipos-conteudo$", response_data = list())

  tax <- discover_senado_taxonomies(client)

  # Verificar que PL, PLS e PLC são da mesma família normalizada 'initial_bill'
  fam_pl <- (tax %>% filter(type_code == "PL"))$normalized_family
  fam_pls <- (tax %>% filter(type_code == "PLS"))$normalized_family
  fam_plc <- (tax %>% filter(type_code == "PLC"))$normalized_family
  fam_pec <- (tax %>% filter(type_code == "PEC"))$normalized_family

  expect_equal(fam_pl, "initial_bill")
  expect_equal(fam_pls, "initial_bill")
  expect_equal(fam_plc, "initial_bill")
  expect_equal(fam_pec, "constitutional_amendment")

  # Mock de consulta histórica de PLS em 2018
  client$register_mock(
    path_pattern = "processo\\?ano=2018&sigla=PLS&tramitando=S",
    response_data = list(
      list(
        id = 201801,
        codigoMateria = 301801,
        sigla = "PLS",
        identificacao = "PLS 100/2018",
        ementa = "Projeto histórico de 2018",
        dataApresentacao = "2018-05-10",
        tramitando = "Sim",
        objetivo = "Iniciadora",
        tipoDocumento = "Projeto de Lei do Senado",
        autoria = "Senador Histórico"
      )
    )
  )
  client$register_mock(path_pattern = "processo\\?ano=2018&sigla=PLS&tramitando=N", response_data = list())
  client$register_mock(path_pattern = "processo/201801", response_data = list(id = 201801))
  client$register_mock(path_pattern = "processo/documento\\?idProcesso=201801", response_data = list())
  client$register_mock(path_pattern = "processo/emenda\\?idProcesso=201801", response_data = list())

  res_hist <- inventory_senado_processes(
    client = client,
    years = c(2018),
    siglas = c("PLS"),
    tramitando_filter = c("S", "N"),
    fetch_child_entities = TRUE
  )

  expect_equal(nrow(res_hist$propositions), 1)
  expect_equal(res_hist$propositions$type_code, "PLS")
  expect_equal(res_hist$propositions$numbering_year, 2018)
})

# ==============================================================================
# TESTE 3: Documentos posteriores à apresentação e múltiplos anos
# ==============================================================================
test_that("SEN-03: Documentos não ficam restritos ao ano de apresentação do processo (anos posteriores)", {
  client <- create_senado_client(offline_mode = TRUE)

  client$register_mock(
    path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=S",
    response_data = list(
      list(
        id = 3001,
        sigla = "PL",
        identificacao = "PL 50/2024",
        ementa = "Projeto apresentado em 2024",
        dataApresentacao = "2024-01-15",
        tramitando = "Sim",
        objetivo = "Iniciadora",
        autoria = "Senador Relator"
      )
    )
  )
  client$register_mock(path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=N", response_data = list())
  client$register_mock(path_pattern = "processo/3001", response_data = list(id = 3001))

  # Retornar 3 documentos: o inicial de 2024, um parecer de 2025 e um relatório de 2026!
  client$register_mock(
    path_pattern = "processo/documento\\?idProcesso=3001",
    response_data = list(
      list(
        id = 5001,
        siglaTipo = "PROJETO_LEI_ORDINARIA",
        descricaoTipo = "Projeto de Lei Ordinária",
        dataRecebimento = "2024-01-15",
        urlDocumento = "https://legis.senado.gov.br/sdleg-getter/documento?dm=5001"
      ),
      list(
        id = 5002,
        siglaTipo = "PARECER",
        descricaoTipo = "Parecer da Comissão",
        dataRecebimento = "2025-06-20", # ANO POSTERIOR!
        urlDocumento = "https://legis.senado.gov.br/sdleg-getter/documento?dm=5002"
      ),
      list(
        id = 5003,
        siglaTipo = "RELATORIO",
        descricaoTipo = "Relatório Legislativo",
        dataRecebimento = "2026-03-10", # DOIS ANOS DEPOIS!
        urlDocumento = "https://legis.senado.gov.br/sdleg-getter/documento?dm=5003"
      )
    )
  )
  client$register_mock(path_pattern = "processo/emenda\\?idProcesso=3001", response_data = list())

  res <- inventory_senado_processes(
    client = client,
    years = c(2024),
    siglas = c("PL"),
    tramitando_filter = c("S"),
    fetch_child_entities = TRUE
  )

  expect_equal(nrow(res$documents), 3)

  # Verificar datas dos documentos
  doc_2024 <- res$documents %>% filter(source_document_id == "5001")
  doc_2025 <- res$documents %>% filter(source_document_id == "5002")
  doc_2026 <- res$documents %>% filter(source_document_id == "5003")

  expect_equal(as.character(doc_2024$publication_date), "2024-01-15")
  expect_equal(as.character(doc_2025$publication_date), "2025-06-20")
  expect_equal(as.character(doc_2026$publication_date), "2026-03-10")

  # Verificar papéis normativos em proposition_documents
  pd_2024 <- res$proposition_documents %>% filter(document_id == "senado:doc:processo:5001")
  pd_2025 <- res$proposition_documents %>% filter(document_id == "senado:doc:processo:5002")
  pd_2026 <- res$proposition_documents %>% filter(document_id == "senado:doc:processo:5003")

  expect_equal(pd_2024$document_role, "initial")
  expect_equal(pd_2025$document_role, "opinion")
  expect_equal(pd_2026$document_role, "report")
})

# ==============================================================================
# TESTE 4: Emendas, subemendas e vínculo com fases
# ==============================================================================
test_that("SEN-04: Emendas e fases são registradas e vinculadas em document_phases", {
  client <- create_senado_client(offline_mode = TRUE)

  client$register_mock(
    path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=S",
    response_data = list(
      list(
        id = 4001,
        sigla = "PL",
        identificacao = "PL 99/2024",
        dataApresentacao = "2024-03-01",
        tramitando = "Sim",
        objetivo = "Iniciadora"
      )
    )
  )
  client$register_mock(path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=N", response_data = list())
  client$register_mock(path_pattern = "processo/4001", response_data = list(id = 4001))
  client$register_mock(path_pattern = "processo/documento\\?idProcesso=4001", response_data = list())

  # Emenda na comissão
  client$register_mock(
    path_pattern = "processo/emenda\\?idProcesso=4001",
    response_data = list(
      list(
        id = 9001,
        idDocumentoEmenda = 9002,
        idProcesso = 4001,
        identificacao = "EMENDA 1 - PL 99/2024",
        tipo = "EMENDA_PARCIAL",
        autoria = "Senador Emendador",
        dataApresentacao = "2024-04-10",
        siglaColegiado = "CCJ"
      )
    )
  )

  res <- inventory_senado_processes(
    client = client,
    years = c(2024),
    siglas = c("PL"),
    tramitando_filter = c("S"),
    fetch_child_entities = TRUE
  )

  # Verificar presença da emenda em documents
  expect_equal(nrow(res$documents), 1)
  expect_equal(res$documents$normalized_kind, "amendment")

  # Verificar presença em document_phases
  expect_equal(nrow(res$document_phases), 1)
  expect_equal(res$document_phases$role, "amendment")
  expect_equal(res$document_phases$phase_id, res$process_phases$phase_id[1])
})

# ==============================================================================
# TESTE 5: Identificadores determinísticos, aliases MATE legado e vínculo CD
# ==============================================================================
test_that("SEN-05: Identificadores com namespace evitam colisao e preservam aliases MATE e CD", {
  client <- create_senado_client(offline_mode = TRUE)

  client$register_mock(
    path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=N",
    response_data = list(
      list(
        id = 8617321,
        codigoMateria = 161961, # MATE legado
        sigla = "PL",
        identificacao = "PL 182/2024",
        ementa = "SBCE",
        dataApresentacao = "2024-02-06",
        tramitando = "Não",
        objetivo = "Revisora"
      )
    )
  )
  client$register_mock(path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=S", response_data = list())

  # Detalhe informando identificacaoProcessoInicial da Câmara (PL 2148/2015)
  client$register_mock(
    path_pattern = "processo/8617321",
    response_data = list(
      id = 8617321,
      identificacaoProcessoInicial = "PL 2148/2015",
      processosRelacionados = list(
        list(idOutroProcesso = 999999, tipoRelacao = "REFERENCIA")
      )
    )
  )
  client$register_mock(path_pattern = "processo/documento\\?idProcesso=8617321", response_data = list())
  client$register_mock(path_pattern = "processo/emenda\\?idProcesso=8617321", response_data = list())

  res <- inventory_senado_processes(
    client = client,
    years = c(2024),
    siglas = c("PL"),
    tramitando_filter = c("N"),
    fetch_child_entities = TRUE
  )

  prop <- res$propositions[1, ]
  expect_equal(prop$proposition_id, "senado:prop:processo:8617321")
  expect_equal(prop$origin_house, "CD") # Objetivo Revisora -> Origem Câmara

  # Aliases
  aliases <- res$entity_aliases
  expect_equal(nrow(aliases), 2)

  alias_mate <- aliases %>% filter(alias_namespace == "senado_materia")
  expect_equal(nrow(alias_mate), 1)
  expect_equal(alias_mate$alias_source_id, "161961")
  expect_equal(alias_mate$canonical_entity_id, "senado:prop:processo:8617321")

  alias_cd <- aliases %>% filter(alias_namespace == "camara_prop_label")
  expect_equal(nrow(alias_cd), 1)
  expect_equal(alias_cd$alias_source_id, "PL 2148/2015")
  expect_equal(alias_cd$canonical_entity_id, "senado:prop:processo:8617321")

  # Relações
  expect_equal(nrow(res$relations), 1)
  expect_equal(res$relations$target_proposition_id, "senado:prop:processo:999999")
  expect_equal(res$relations$grouping_policy, "do_not_bind")
})

# ==============================================================================
# TESTE 6: Resiliência HTTP (Status 429, 503 e Deprecation headers)
# ==============================================================================
test_that("SEN-06: Cliente HTTP captura headers de deprecation e trata retentativas", {
  client <- create_senado_client(offline_mode = TRUE)

  # Mock com header de Deprecation
  client$register_mock(
    path_pattern = "materia/legada",
    response_data = list(msg = "rota antiga"),
    status_code = 200,
    headers = list(deprecation = "@1735689600", sunset = "Wed, 31 Dec 2025 23:59:59 GMT")
  )

  res <- client$request("/materia/legada")
  expect_equal(res$http_status, 200)
  expect_equal(res$headers$deprecation, "@1735689600")

  # Snapshot gravado
  snaps <- client$get_snapshots_df()
  expect_equal(nrow(snaps), 1)
  expect_equal(snaps$house, "senado")
  expect_equal(snaps$http_status, 200)
})

# ==============================================================================
# TESTE 7: Conformidade estrita aos esquemas Arrow e publicação Parquet com COMPLETE.json
# ==============================================================================
test_that("SEN-07: Publicação Parquet atômica valida FKs, integridade e gera COMPLETE.json", {
  tmp_dir <- file.path(tempdir(), paste0("senado_pub_test_", as.numeric(Sys.time())))
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)

  client <- create_senado_client(offline_mode = TRUE)
  client$register_mock(path_pattern = "processo/siglas", response_data = list(
    list(sigla = "PL", descricao = "Projeto de Lei", dataInicio = "1900-01-01", dataFim = NULL)
  ))
  client$register_mock(path_pattern = "processo/documento/tipos", response_data = list())
  client$register_mock(path_pattern = "processo/documento/tipos-conteudo", response_data = list())

  tax <- discover_senado_taxonomies(client)
  snap_id <- client$snapshots_log[[1]]$snapshot_id
  cols <- register_senado_collections(snap_id)
  evid <- build_senado_use_evidence(snap_id)
  segs <- build_senado_coverage_segments(cols, snap_id)

  # Dados mínimos de processo válidos
  client$register_mock(
    path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=S",
    response_data = list(
      list(
        id = 7001,
        sigla = "PL",
        identificacao = "PL 10/2024",
        dataApresentacao = "2024-01-01",
        tramitando = "Sim",
        objetivo = "Iniciadora",
        autoria = "Senador Publicador"
      )
    )
  )
  client$register_mock(path_pattern = "processo\\?ano=2024&sigla=PL&tramitando=N", response_data = list())
  client$register_mock(path_pattern = "processo/7001", response_data = list(id = 7001))
  client$register_mock(
    path_pattern = "processo/documento\\?idProcesso=7001",
    response_data = list(
      list(
        id = 8001,
        siglaTipo = "PROJETO_LEI_ORDINARIA",
        descricaoTipo = "Projeto de Lei Ordinária",
        dataRecebimento = "2024-01-01",
        urlDocumento = "https://legis.senado.gov.br/sdleg-getter/documento?dm=8001"
      )
    )
  )
  client$register_mock(path_pattern = "processo/emenda\\?idProcesso=7001", response_data = list())

  eng_out <- inventory_senado_processes(
    client = client,
    years = c(2024),
    siglas = c("PL"),
    tramitando_filter = c("S"),
    fetch_child_entities = TRUE
  )

  all_tables <- list(
    source_snapshots = client$get_snapshots_df(),
    source_collections = cols,
    use_evidence = evid,
    legislative_types = tax,
    coverage_segments = segs,
    propositions = eng_out$propositions,
    process_phases = eng_out$process_phases,
    documents = eng_out$documents,
    proposition_documents = eng_out$proposition_documents,
    document_phases = eng_out$document_phases,
    authors = eng_out$authors,
    proposition_authors = eng_out$proposition_authors,
    document_authors = eng_out$document_authors,
    relations = eng_out$relations,
    entity_aliases = eng_out$entity_aliases,
    metadata_checks = eng_out$metadata_checks
  )

  # Publicar
  pub_res <- publish_senado_inventory(
    tables = all_tables,
    target_dir = tmp_dir,
    run_id = "test_run_01"
  )

  expect_true(file.exists(pub_res$manifest_path))
  expect_true(file.exists(pub_res$complete_path))

  # Ler Parquets e conferir esquemas Arrow normativos
  p_props <- read_parquet(file.path(pub_res$output_dir, "propositions.parquet"))
  expect_equal(nrow(p_props), 1)
  expect_equal(p_props$proposition_id[1], "senado:prop:processo:7001")

  p_docs <- read_parquet(file.path(pub_res$output_dir, "documents.parquet"))
  expect_equal(nrow(p_docs), 1)
  expect_equal(p_docs$document_id[1], "senado:doc:processo:8001")

  p_phases <- read_parquet(file.path(pub_res$output_dir, "process_phases.parquet"))
  expect_equal(nrow(p_phases), 1)

  # Verificar COMPLETE.json
  complete_data <- fromJSON(readLines(pub_res$complete_path, warn = FALSE))
  expect_equal(complete_data$manifest_file, "manifest.json")
  expect_true(nchar(complete_data$manifest_sha256) == 64)

  unlink(tmp_dir, recursive = TRUE)
})

# ==============================================================================
# TESTE 8: Acervos históricos (Anais 1826–2013, Diários 2014+, gap pré-1946)
# ==============================================================================
test_that("SEN-08: Acervos de Anais e Diários possuem reconciliação e justificativa explícita de lacunas", {
  snap_id <- hash_string("snap_test_collections")
  cols <- register_senado_collections(snap_id)
  segs <- build_senado_coverage_segments(cols, snap_id)

  expect_equal(nrow(cols), 4)
  expect_true("senado:collection:arquivo:anais" %in% cols$collection_id)
  expect_true("senado:collection:publicacoes:diarios" %in% cols$collection_id)

  # Nenhuma ausência ou contagem de volumes é inferida a partir de intervalo
  # descritivo. Os status permanecem pendentes até a enumeração efetiva.
  api_segments <- segs %>% filter(collection_id == "senado:collection:api:processo")
  expect_equal(nrow(api_segments), 0)

  anais <- segs %>% filter(collection_id == "senado:collection:arquivo:anais")
  expect_equal(nrow(anais), 1)
  expect_equal(anais$count_unit, "volume")
  expect_equal(anais$inventory_status, "pending")
  expect_equal(anais$discovered_count, 0)
  expect_false(is.na(anais$gap_reason))

  diaries <- segs %>% filter(collection_id == "senado:collection:publicacoes:diarios")
  expect_equal(nrow(diaries), 1)
  expect_equal(diaries$count_unit, "issue")
  expect_equal(diaries$inventory_status, "pending")
  expect_equal(diaries$coverage_status, "pending")
})

test_that("SEN-09: A consulta histórica cria segmentos anuais sem whitelist de tipos", {
  client <- create_senado_client(offline_mode = TRUE)
  client$register_mock("processo\\?ano=2024&tramitando=S", list(
    list(id = "s-1", sigla = "PEC", identificacao = "PEC 1/2024", dataApresentacao = "2024-03-01"),
    list(id = "s-2", sigla = "PLS", identificacao = "PLS 2/2024", dataApresentacao = "2024-03-02")
  ))
  client$register_mock("processo\\?ano=2024&tramitando=N", list(
    list(id = "n-1", sigla = "PLC", identificacao = "PLC 3/2024", dataApresentacao = "2024-04-01"),
    list(id = "n-2", sigla = "PL", identificacao = "PL 4/2024", dataApresentacao = "2024-04-02")
  ))

  res <- inventory_senado_processes(client, years = 2024, fetch_child_entities = FALSE)
  expect_equal(nrow(res$propositions), 4)
  expect_setequal(res$propositions$type_code, c("PEC", "PLS", "PLC", "PL"))
  expect_equal(nrow(res$coverage_segments), 2)
  expect_true(all(res$coverage_segments$inventory_status == "exhausted"))
  expect_true(all(res$coverage_segments$coverage_status == "complete_discovered"))
  queries <- lapply(res$coverage_segments$query_json, jsonlite::fromJSON)
  statuses <- vapply(queries, `[[`, character(1), "tramitando")
  expect_setequal(statuses, c("S", "N"))
  expect_true(all(vapply(queries, function(q) !is.null(q$ano), logical(1))))
  expect_true(all(vapply(queries, function(q) is.null(q$sigla), logical(1))))
  plan <- senado_process_query_specs(1826:2026, c("S", "N"))
  expect_equal(length(plan), 402)
  expect_equal(plan[[1]]$year, 1826L)
  expect_equal(plan[[length(plan)]]$year, 2026L)
})

test_that("SEN-10: Fila de IDs permite retomar em blocos oficiais de até 100", {
  client <- create_senado_client(offline_mode = TRUE)
  client$register_mock("idProcesso=101&idProcesso=102", list(
    list(id = 101, sigla = "PLS", identificacao = "PLS 1/2018"),
    list(id = 102, sigla = "PEC", identificacao = "PEC 2/2024")
  ))
  client$register_mock("processo/101", list(id = 101))
  client$register_mock("processo/documento\\?idProcesso=101", list())
  client$register_mock("processo/emenda\\?idProcesso=101", list())

  res <- inventory_senado_processes(client, fetch_child_entities = TRUE, process_ids = c("101", "102"), max_processes_per_run = 1)
  expect_equal(nrow(res$propositions), 2)
  expect_equal(res$pending_process_ids, "102")
  pending <- res$metadata_checks %>% filter(status == "pending")
  expect_equal(nrow(pending), 3)
  expect_setequal(pending$entity_id, "senado:prop:processo:102")
})

test_that("SEN-11: HTTP 503 e payload inválido não viram consulta vazia/exaurida", {
  client <- create_senado_client(offline_mode = TRUE)
  client$register_mock("processo\\?ano=2024&tramitando=S", list(), status_code = 503)
  client$register_mock("processo\\?ano=2024&tramitando=N", "resposta não JSON", status_code = 200)

  res <- inventory_senado_processes(client, years = 2024, fetch_child_entities = FALSE)
  expect_equal(nrow(res$coverage_segments), 2)
  expect_true(all(res$coverage_segments$inventory_status == "error"))
  expect_true(all(res$coverage_segments$coverage_status == "partial"))
  expect_true(all(is.na(res$coverage_segments$expected_count)))
  expect_equal(nrow(res$propositions), 0)
  expect_equal(client$get_snapshots_df()$pagination_complete, c(FALSE, TRUE))
})

test_that("SEN-14: Encerrados exigem filtro documentado; anos vazios ficam parciais e a fila retoma", {
  client <- create_senado_client(offline_mode = TRUE)
  client$register_mock("processo\\?tramitando=N$", list(), status_code = 400)
  expect_equal(client$request("/processo", query = list(tramitando = "N"))$http_status, 400L)

  client$register_mock("processo\\?ano=2024&tramitando=N", list(
    list(id = "closed-1", sigla = "PEC", identificacao = "PEC 1/2024")
  ))
  client$register_mock("processo\\?ano=2025&tramitando=N", list())
  first <- inventory_senado_processes(client, years = c(2024, 2025), tramitando_filter = "N",
                                      fetch_child_entities = FALSE, max_segments_per_run = 1)
  expect_equal(nrow(first$propositions), 1)
  expect_equal(length(first$pending_segment_specs), 1)
  first_coverage <- first$coverage_segments[order(first$coverage_segments$year), ]
  expect_equal(first_coverage$inventory_status, c("exhausted", "pending"))
  expect_equal(first_coverage$coverage_status, c("complete_discovered", "pending"))

  resumed <- inventory_senado_processes(client, tramitando_filter = "N", fetch_child_entities = FALSE,
                                        segment_specs = first$pending_segment_specs)
  expect_equal(resumed$coverage_segments$year, 2025L)
  expect_equal(resumed$coverage_segments$coverage_status, "partial")
  expect_match(resumed$coverage_segments$gap_reason, "não prova ausência")
})

test_that("SEN-12: IDs solicitados ausentes na resposta permanecem em fila e cobertura parcial", {
  client <- create_senado_client(offline_mode = TRUE)
  client$register_mock("idProcesso=201&idProcesso=202", list(
    list(id = 201, sigla = "PLS", identificacao = "PLS 1/2018")
  ))
  res <- inventory_senado_processes(client, fetch_child_entities = FALSE, process_ids = c("201", "202"))
  expect_equal(res$pending_process_ids, "202")
  expect_equal(res$coverage_segments$inventory_status, "exhausted")
  expect_equal(res$coverage_segments$coverage_status, "partial")
  expect_equal(res$coverage_segments$expected_count, 2)
  expect_equal(res$coverage_segments$discovered_count, 1)
})

test_that("SEN-13: DATA_ROOT absoluto fica fora do checkout e caminho relativo resolve no checkout", {
  external_root <- file.path(tempdir(), "senado_external_data")
  expected_external <- normalizePath(external_root, winslash = "/", mustWork = FALSE)
  resolved_external <- resolve_senado_data_root(repo_root, external_root)
  expect_equal(resolved_external, expected_external)
  expect_false(startsWith(resolved_external, paste0(repo_root, "/")))

  resolved_relative <- resolve_senado_data_root(repo_root, "data")
  expect_equal(resolved_relative, normalizePath(file.path(repo_root, "data"), winslash = "/", mustWork = FALSE))
})
