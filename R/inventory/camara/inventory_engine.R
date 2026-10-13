# R/inventory/camara/inventory_engine.R
# Motor de execução do inventário histórico da Câmara dos Deputados
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/01_INVENTARIO.md

suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
  library(yaml)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))
source(file.path(repo_root, "R", "inventory", "common", "http_client.R"))

source(file.path(repo_root, "R", "inventory", "camara", "types_catalog.R"))
source(file.path(repo_root, "R", "inventory", "camara", "sources_discovery.R"))
source(file.path(repo_root, "R", "inventory", "camara", "api_client.R"))
source(file.path(repo_root, "R", "inventory", "camara", "portal_reconciliation.R"))
source(file.path(repo_root, "R", "inventory", "camara", "historical_collections.R"))
source(file.path(repo_root, "R", "inventory", "camara", "enrichment.R"))

# Cria data.frames vazios com tipos R coerentes com os contratos Arrow.
camara_empty_contract_table <- function(table_name) {
  target <- get_arrow_schemas()[[table_name]]
  cols <- lapply(target$fields, function(field) {
    type_name <- field$type$ToString()
    if (grepl("^date32", type_name)) return(as.Date(character()))
    if (grepl("^timestamp", type_name)) return(as.POSIXct(character(), tz = "UTC"))
    if (type_name %in% c("int32", "int64")) return(integer())
    if (type_name %in% c("float", "double")) return(numeric())
    if (type_name == "bool") return(logical())
    character()
  })
  names(cols) <- target$names
  as.data.frame(cols, stringsAsFactors = FALSE)
}

camara_write_json_atomic <- function(value, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  part <- paste0(path, ".part")
  writeLines(jsonlite::toJSON(value, auto_unbox = TRUE, null = "null", pretty = TRUE), part, useBytes = TRUE)
  if (!file.rename(part, path)) stop("Não foi possível promover checkpoint: ", path)
}

camara_segment_id <- function(year, quarter) {
  paste0("camara:col:api_v2:proposicoes:presentation:", year, ":Q", quarter)
}

camara_query_url <- function(base, year, quarter, page = NULL) {
  windows <- generate_quarterly_windows(year)
  w <- windows[[quarter]]
  req <- httr2::request(paste0(sub("/+$", "", base), "/proposicoes")) |>
    httr2::req_url_query(
      dataApresentacaoInicio = w$start, dataApresentacaoFim = w$end,
      itens = 100, ordem = "ASC", ordenarPor = "id"
    )
  if (!is.null(page)) req <- httr2::req_url_query(req, pagina = page)
  req$url
}

camara_snapshot_row <- function(snapshot, id_override = NULL) {
  scalar <- function(x, default=NA_character_) if (is.null(x) || !length(x)) default else x[[1]]
  collected <- scalar(snapshot$collected_at, as.POSIXct(NA,tz="UTC"))
  data.frame(
    snapshot_id = if (is.null(id_override)) as.character(scalar(snapshot$snapshot_id)) else id_override,
    house = "camara", source_kind = as.character(scalar(snapshot$source_kind,"api")), request_url = as.character(scalar(snapshot$request_url)),
    query_json = as.character(scalar(snapshot$query_json,"{}")),
    collected_at = as.POSIXct(collected, tz = "UTC"),
    http_status = as.integer(scalar(snapshot$http_status, NA_integer_)),
    payload_sha256 = as.character(scalar(snapshot$payload_sha256, NA_character_)), raw_path = NA_character_,
    pagination_complete = isTRUE(snapshot$pagination_complete),
    source_schema_version = as.character(scalar(snapshot$source_schema_version,NA_character_)),
    license_evidence_id = "camara:use:dados_abertos_politica", stringsAsFactors = FALSE
  )
}

#' Executa um lote retomável do inventário da Câmara.
#'
#' O modo completo consulta somente respostas oficiais efetivamente recebidas.
#' Cada segmento é uma janela trimestral; páginas são persistidas antes de avançar.
#' Segmentos e endpoints ainda não consultados permanecem pendentes.
run_camara_inventory <- function(config_path = NULL, output_dir = NULL, is_sample = FALSE,
                                 request_fn = NULL, max_segments = NULL, max_pages_per_segment = NULL,
                                 max_enrichment_requests = NULL) {
  if (is.null(config_path)) config_path <- file.path(repo_root, "configs", "data", "history.yaml")
  cfg <- if (file.exists(config_path)) yaml::read_yaml(config_path) else list()
  cam_cfg <- cfg$camara %||% list()
  disc_cfg <- cam_cfg$discovery %||% list()
  api_base <- cam_cfg$base_api_url %||% "https://dadosabertos.camara.leg.br/api/v2"
  data_root <- resolve_external_data_root(repo_root, output_dir)
  if (is.null(output_dir)) output_dir <- file.path(data_root, "staging", "inventory_camara")
  if (!is_sample) {
    normalized_out <- normalizePath(output_dir, winslash="/", mustWork=FALSE)
    normalized_repo <- normalizePath(repo_root, winslash="/", mustWork=FALSE)
    if (identical(normalized_out, normalized_repo) || startsWith(normalized_out, paste0(normalized_repo, "/"))) {
      stop("Modo oficial grava respostas e checkpoints; defina DATA_ROOT externo ao repositório ou passe --output-dir externo.")
    }
  }
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  now <- as.POSIXct(Sys.time(), tz = "UTC")
  run_suffix <- format(now, "%Y%m%d%H%M%S", tz = "UTC")
  snapshot_id <- paste0("camara:snap:", if (is_sample) "sample:" else "run:", run_suffix)
  table_names <- c("source_snapshots", "propositions", "authors", "proposition_authors",
    "document_authors", "themes", "proposition_themes", "metadata_checks", "relations",
    "process_phases", "document_phases", "documents", "proposition_documents",
    "source_collections", "legislative_types", "coverage_segments", "collection_documents",
    "entity_aliases", "use_evidence")
  tables <- setNames(lapply(table_names, camara_empty_contract_table), table_names)
  snapshots <- list()
  segments <- list()
  props <- list()
  api_calls <- list()
  mode <- if (is_sample) "sample_fixture" else "official_api_incremental"

  if (is_sample) {
    # O fixture é deliberadamente sintético, usa URI mock e nunca é apresentado
    # como resposta API, fonte oficial ou cobertura histórica.
    fixture <- list(id = "SYN-CAMARA-001", siglaTipo = "PL", codTipo = "fixture-PL",
      descricaoTipo = "Fixture de teste (não oficial)", numero = 1L, ano = 2024L,
      dataApresentacao = "2024-01-01", ementa = "Fixture de homologação; conteúdo sintético.",
      uri = "mock://camara/proposicoes/SYN-CAMARA-001", source_namespace = "sample_fixture")
    fixture_payload <- jsonlite::toJSON(fixture, auto_unbox = TRUE)
    fixture_snap <- list(snapshot_id = snapshot_id, house = "camara", source_kind = "sample_fixture",
      request_url = "mock://camara/proposicoes", query_json = '{"mode":"sample_fixture"}',
      collected_at = now, http_status = NA_integer_, payload_sha256 = hash_string(fixture_payload),
      pagination_complete = TRUE, source_schema_version = "fixture-v1")
    snapshots[[1]] <- camara_snapshot_row(fixture_snap)
    props[[1]] <- parse_camara_propositions(list(fixture), snapshot_id)
    tables$coverage_segments <- data.frame(
      segment_id = "camara:sample:fixture:propositions", collection_id = "camara:col:api_v2",
      house = "camara", legislative_type_id = NA_character_, year = 2024L,
      period_start = as.Date("2024-01-01"), period_end = as.Date("2024-12-31"),
      date_axis = "presentation", snapshot_cutoff_utc = now,
      query_json = '{"mode":"sample_fixture"}', inventory_status = "pending",
      coverage_status = "partial", expected_count = NA_integer_, discovered_count = 1L,
      retrieved_count = 0L, accepted_count = 0L, count_unit = "fixture_records",
      exhaustion_evidence = NA_character_, gap_reason = "Fixture sintético; sem cobertura oficial.",
      snapshot_id = snapshot_id, stringsAsFactors = FALSE)
  } else {
    start_year <- as.integer(disc_cfg$annual_catalog_start_year %||% 1934L)
    cutoff <- as.Date(substr(cfg$snapshot_cutoff_utc %||% format(now, "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"), 1, 10))
    end_year <- as.integer(format(cutoff, "%Y"))
    max_segments <- as.integer(max_segments %||% disc_cfg$max_segments_per_run %||% 4L)
    max_pages <- as.integer(max_pages_per_segment %||% disc_cfg$max_pages_per_segment %||% 10L)
    max_enrichment_requests <- as.integer(max_enrichment_requests %||% disc_cfg$max_enrichment_requests_per_run %||% 100L)
    if (max_segments < 1L || max_pages < 1L || max_enrichment_requests < 0L) stop("Limites de execução precisam ser positivos.")

    state_path <- file.path(output_dir, "progress.json")
    state <- if (file.exists(state_path)) jsonlite::fromJSON(state_path, simplifyVector = FALSE) else
      list(year = start_year, quarter = 1L, next_url = NULL, completed_segments = 0L)
    collected_props <- list()
    collected_snapshots <- list()
    segment_rows <- list()
    remaining <- max_segments

    # Captura de taxonomia é tentativa real separada; falha fica explícita.
    types_url <- paste0(sub("/+$", "", api_base), "/referencias/proposicoes/siglaTipo")
    type_response <- tryCatch(
      if (is.function(request_fn)) request_fn(types_url, 1L) else perform_resilient_request(types_url),
      error = function(e) list(status = "error", http_status = NA_integer_, error_message = conditionMessage(e)))
    type_body <- NULL
    type_snap_id <- paste0(snapshot_id, ":types")
    if (identical(type_response$status, "succeeded")) {
      type_body <- if (!is.null(type_response$body)) type_response$body else httr2::resp_body_json(type_response$response, simplifyVector = FALSE)
      type_json <- jsonlite::toJSON(type_body, auto_unbox = TRUE)
      collected_snapshots[[length(collected_snapshots) + 1L]] <- camara_snapshot_row(list(
        snapshot_id = type_snap_id, request_url = types_url,
        query_json = '{"endpoint":"referencias/proposicoes/siglaTipo"}',
        collected_at = type_response$finished_at %||% now, http_status = type_response$http_status,
        payload_sha256 = hash_string(type_json), pagination_complete = TRUE, source_schema_version = NA_character_))
      raw_types <- type_body$dados %||% list()
      if (length(raw_types)) tables$legislative_types <- build_legislative_types(raw_types, type_snap_id)
    } else {
      collected_snapshots[[length(collected_snapshots) + 1L]] <- camara_snapshot_row(list(
        snapshot_id = type_snap_id, request_url = types_url,
        query_json = '{"endpoint":"referencias/proposicoes/siglaTipo"}',
        collected_at = type_response$finished_at %||% now, http_status = type_response$http_status %||% NA_integer_,
        payload_sha256 = NA_character_, pagination_complete = FALSE, source_schema_version = NA_character_))
      api_calls[[length(api_calls) + 1L]] <- list(endpoint = types_url, status = type_response$status,
        http_status = type_response$http_status %||% NA_integer_, error = type_response$error_message %||% "Falha sem resposta")
    }

    while (remaining > 0L && state$year <= end_year) {
      year <- as.integer(state$year); quarter <- as.integer(state$quarter)
      seg_id <- camara_segment_id(year, quarter)
      seg_dir <- file.path(output_dir, "pages", paste0(year, "-Q", quarter))
      dir.create(seg_dir, recursive = TRUE, showWarnings = FALSE)
      initial_url <- state$next_url %||% camara_query_url(api_base, year, quarter)
      page_files <- sort(list.files(seg_dir, pattern = "^page-[0-9]+[.]json$", full.names = TRUE))
      prior_pages <- lapply(page_files, function(f) jsonlite::fromJSON(f, simplifyVector = FALSE))
      prior_items <- unlist(lapply(prior_pages, function(pg) pg$body$dados %||% list()), recursive = FALSE)
      prior_snaps <- lapply(prior_pages, function(pg) pg$snapshot)
      page_offset <- length(prior_pages)
      page_count <- 0L
      last_event <- NULL
      on_page <- function(event) {
        page_count <<- page_count + 1L
        event$page <- page_offset + page_count
        event$snapshot$pagination_complete <- isTRUE(event$terminal)
        camara_write_json_atomic(event, file.path(seg_dir, sprintf("page-%06d.json", event$page)))
        state$next_url <<- event$next_url
        state$year <<- year; state$quarter <<- quarter
        camara_write_json_atomic(state, state_path)
        last_event <<- event
      }
      resumed_terminal <- length(prior_pages) > 0L && isTRUE(prior_pages[[length(prior_pages)]]$terminal)
      paged <- if (resumed_terminal) {
        list(raw_items = list(), snapshots = list(), pagination_complete = TRUE, pages_read = 0L)
      } else paginate_camara_api(initial_url, max_pages = max_pages,
        request_fn = if (is.function(request_fn)) function(url, p) request_fn(url, page_offset + p) else NULL,
        on_page = on_page)
      all_items <- c(prior_items, paged$raw_items)
      all_snaps <- c(prior_snaps, paged$snapshots)
      # Keep each record attached to the exact page payload that yielded it.
      for (pg in c(prior_pages, if (page_count > 0L) lapply(seq_len(page_count), function(i) {
        jsonlite::fromJSON(file.path(seg_dir, sprintf("page-%06d.json", page_offset + i)), simplifyVector = FALSE)
      }) else list())) {
        page_items <- pg$body$dados %||% list()
        if (length(page_items)) collected_props[[length(collected_props) + 1L]] <-
          parse_camara_propositions(page_items, pg$snapshot$snapshot_id)
      }
      succeeded <- !is.null(last_event) || length(prior_pages) > 0L
      exhausted <- isTRUE(paged$pagination_complete)
      nitems <- length(all_items)
      inv_status <- if (exhausted) "exhausted" else if (succeeded) "running" else "error"
      cov_status <- if (!exhausted) "partial" else if (nitems == 0L) "closed_with_gaps" else "complete_discovered"
      gap_reason <- if (!exhausted) "Paginação incompleta; retomar pelo next_url salvo." else if (nitems == 0L)
        "Consulta API esgotada sem resultados; resposta vazia não prova ausência documental noutras fontes." else NA_character_
      segment_rows[[length(segment_rows) + 1L]] <- data.frame(
        segment_id = seg_id, collection_id = "camara:col:api_v2", house = "camara",
        legislative_type_id = NA_character_, year = year,
        period_start = as.Date(generate_quarterly_windows(year)[[quarter]]$start),
        period_end = as.Date(generate_quarterly_windows(year)[[quarter]]$end), date_axis = "presentation",
        snapshot_cutoff_utc = now,
        query_json = as.character(jsonlite::toJSON(list(endpoint = "proposicoes", year = year, quarter = quarter,
          start = generate_quarterly_windows(year)[[quarter]]$start,
          end = generate_quarterly_windows(year)[[quarter]]$end), auto_unbox = TRUE)),
        inventory_status = inv_status, coverage_status = cov_status,
        expected_count = NA_integer_, discovered_count = as.integer(nitems), retrieved_count = as.integer(nitems),
        accepted_count = 0L, count_unit = "propositions", exhaustion_evidence = if (exhausted) "API v2 HATEOAS: resposta HTTP bem-sucedida sem rel=next para consulta segmentada" else NA_character_,
        gap_reason = gap_reason, snapshot_id = if (length(all_snaps)) all_snaps[[length(all_snaps)]]$snapshot_id else type_snap_id,
        stringsAsFactors = FALSE)
      segment_path <- file.path(output_dir, "segments", paste0(year, "-Q", quarter, ".rds"))
      dir.create(dirname(segment_path), recursive=TRUE, showWarnings=FALSE)
      saveRDS(segment_rows[[length(segment_rows)]], segment_path)

      remaining <- remaining - 1L
      if (exhausted) {
        state$completed_segments <- as.integer(state$completed_segments %||% 0L) + 1L
        if (quarter < 4L) { state$year <- year; state$quarter <- quarter + 1L }
        else { state$year <- year + 1L; state$quarter <- 1L }
        state$next_url <- NULL
        camara_write_json_atomic(state, state_path)
      } else break
    }
    # Rebuild cumulative outputs from page shards and segment checkpoints. This
    # keeps earlier completed work available when the cursor advances.
    all_page_files <- list.files(file.path(output_dir,"pages"), pattern="^page-[0-9]+[.]json$",
      recursive=TRUE, full.names=TRUE)
    all_page_records <- lapply(all_page_files, function(f) jsonlite::fromJSON(f, simplifyVector=FALSE))
    all_page_records <- Filter(function(pg) !is.null(pg$body), all_page_records)
    for (pg in all_page_records) {
      page_items <- pg$body$dados %||% list()
      if (length(page_items)) collected_props[[length(collected_props)+1L]] <-
        parse_camara_propositions(page_items, pg$snapshot$snapshot_id)
    }
    page_snapshots <- lapply(all_page_records, function(pg) pg$snapshot)
    collected_snapshots <- c(collected_snapshots, lapply(page_snapshots, camara_snapshot_row))
    if (length(collected_props)) tables$propositions <- dplyr::bind_rows(collected_props) |> dplyr::distinct(proposition_id, .keep_all=TRUE)
    segment_files <- list.files(file.path(output_dir,"segments"), pattern="[.]rds$", full.names=TRUE)
    if (length(segment_files)) tables$coverage_segments <- dplyr::bind_rows(lapply(segment_files, readRDS))
    snapshots <- if (length(collected_snapshots)) dplyr::bind_rows(collected_snapshots) |> dplyr::distinct(snapshot_id,.keep_all=TRUE) else camara_empty_contract_table("source_snapshots")
    # Include source definitions tied to the actual type-reference request.
    tables$source_collections <- build_source_collections(type_snap_id)
    tables$source_snapshots <- if (length(snapshots)) dplyr::bind_rows(snapshots) else camara_empty_contract_table("source_snapshots")
    if (nrow(tables$coverage_segments) == 0L) {
      # The unvisited range is not called exhausted. Publish explicit pending
      # rows for the next bounded slice only; progress.json is the cursor.
      y <- as.integer(state$year); q <- as.integer(state$quarter)
      if (!is.na(y) && y <= end_year) {
        w <- generate_quarterly_windows(y)[[q]]
        tables$coverage_segments <- data.frame(segment_id = camara_segment_id(y, q),
          collection_id = "camara:col:api_v2", house = "camara", legislative_type_id = NA_character_,
          year = y, period_start = as.Date(w$start), period_end = as.Date(w$end), date_axis = "presentation",
          snapshot_cutoff_utc = now, query_json = as.character(jsonlite::toJSON(list(endpoint="proposicoes",year=y,quarter=q),auto_unbox=TRUE)),
          inventory_status = "pending", coverage_status = "pending", expected_count=NA_integer_, discovered_count=0L,
          retrieved_count=0L, accepted_count=0L, count_unit="propositions", exhaustion_evidence=NA_character_,
          gap_reason="Ainda não consultado; retomada pelo progress.json.", snapshot_id=type_snap_id, stringsAsFactors=FALSE)
      }
    }
    # Process a bounded number of endpoint pages. Queue and response shards are
    # durable, so 200/empty/error outcomes and pagination can resume next run.
    enrichment <- run_camara_enrichment(tables$propositions, output_dir, api_base,
      request_fn=request_fn, max_requests=max_enrichment_requests)
    tables$propositions <- enrichment$propositions
    tables$authors <- enrichment$authors
    tables$proposition_authors <- enrichment$proposition_authors
    tables$themes <- enrichment$themes
    tables$proposition_themes <- enrichment$proposition_themes
    tables$process_phases <- enrichment$process_phases
    tables$relations <- enrichment$relations
    tables$documents <- enrichment$documents
    tables$proposition_documents <- enrichment$proposition_documents
    tables$metadata_checks <- enrichment$metadata_checks
    tables$source_snapshots <- dplyr::bind_rows(tables$source_snapshots,enrichment$source_snapshots) |>
      dplyr::distinct(snapshot_id,.keep_all=TRUE)
    listed_props <- camara_listing_ids_by_segment(output_dir,tables$coverage_segments)
    tables$coverage_segments <- camara_update_enrichment_coverage(tables$coverage_segments,
      tables$propositions,enrichment$queue,listed_props)
    segment_files <- list.files(file.path(output_dir,"segments"),pattern="[.]rds$",full.names=TRUE)
    for (sf in segment_files) {
      old_segment <- readRDS(sf)
      listed_one <- camara_listing_ids_by_segment(output_dir,old_segment)
      updated <- camara_update_enrichment_coverage(old_segment,tables$propositions,enrichment$queue,listed_one)
      saveRDS(updated,sf)
    }
  }

  if (is_sample) {
    tables$source_collections <- build_source_collections(snapshot_id)
    tables$source_snapshots <- dplyr::bind_rows(snapshots)
    tables$propositions <- dplyr::bind_rows(props)
    tables$legislative_types <- data.frame(legislative_type_id="camara:type:fixture-PL", house="camara",
      source_namespace="sample_fixture", type_source_id="fixture-PL", type_code="PL",
      type_label="Fixture de teste (não oficial)", entity_kind="proposition", normalized_family="PL",
      mapping_status="sample_only", snapshot_id=snapshot_id, stringsAsFactors=FALSE)
  }

  for (nm in names(tables)) {
    if (nrow(tables[[nm]]) == 0L) tables[[nm]] <- camara_empty_contract_table(nm)
  }
  written_files <- list()
  for (nm in names(tables)) {
    path <- file.path(output_dir, paste0(nm, ".parquet"))
    written_files[[nm]] <- write_contract_parquet(tables[[nm]], nm, path)
  }
  manifest <- list(schema_version="2.0.0", stage="inventory_camara", house="camara",
    mode=mode, status=if (is_sample) "sample_only" else "partial", snapshot_id=snapshot_id,
    created_at_utc=format(now, "%Y-%m-%dT%H:%M:%SZ", tz="UTC"), files=written_files,
    progress_file=if (is_sample) NULL else file.path(output_dir,"progress.json"),
    enrichment_queue_file=if (is_sample) NULL else file.path(output_dir,"enrichment","queue.rds"),
    enrichment_responses_path=if (is_sample) NULL else file.path(output_dir,"enrichment","responses"),
    enrichment=if (is_sample) list(status="not_run_sample_fixture") else list(
      endpoint_pages_used=enrichment$requests_used, http_attempts=enrichment$http_attempts,
      endpoint_tasks_total=nrow(enrichment$queue), endpoint_tasks_pending=sum(enrichment$queue$status %in% c("pending","running","retryable_error")),
      endpoint_tasks_terminal_error=sum(enrichment$queue$status=="terminal_error"),
      base_endpoint_requests_per_proposition=length(camara_enrichment_endpoints),
      retry_cap_per_request=as.integer(cfg$network$max_retries %||% 5L)+1L,
      estimated_http_attempt_cap_per_base_proposition=length(camara_enrichment_endpoints)*(as.integer(cfg$network$max_retries %||% 5L)+1L),
      note="Estimativa cobre cinco endpoints API; páginas adicionais e proposições relacionadas adicionam chamadas. Sem estimativa de latência."),
    summary=list(source_collections_count=nrow(tables$source_collections),
      legislative_types_count=nrow(tables$legislative_types), coverage_segments_count=nrow(tables$coverage_segments),
      propositions_count=nrow(tables$propositions), documents_count=nrow(tables$documents),
      inventory_complete=FALSE, reason=if (is_sample) "Homologação sintética; não é dado oficial." else
        "Lote limitado; endpoints/portal, arquivos anuais e coleções históricas ainda pendentes."))
  published <- publish_manifest_with_complete(manifest, file.path(output_dir,"inventory_camara_manifest.json"))
  list(tables=tables, written_files=written_files, manifest=manifest, publication=published)
}
