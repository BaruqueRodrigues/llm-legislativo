# R/inventory/senado/inventory_engine.R
# Motor de inventário e extração documental de processos do Senado Federal
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0) e docs/subagents/10_SENADO.md

suppressPackageStartupMessages({
  library(dplyr)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))
source(file.path(repo_root, "R", "inventory", "senado", "taxonomies.R"))

senado_http_ok <- function(response) isTRUE(!is.null(response$http_status) && response$http_status == 200L)

senado_process_query_specs <- function(years, statuses) {
  specs <- list()
  for (yr in years) for (tram in statuses) {
    specs[[length(specs) + 1L]] <- list(year = as.integer(yr), sigla = NA_character_, tram = tram)
  }
  specs
}

normalize_senado_segment_specs <- function(specs) {
  lapply(specs, function(spec) {
    if (is.null(spec$year) || !length(spec$year)) spec$year <- NA_integer_ else spec$year <- as.integer(spec$year)
    if (is.null(spec$sigla) || !length(spec$sigla)) spec$sigla <- NA_character_ else spec$sigla <- as.character(spec$sigla)
    if (is.null(spec$tram) || !length(spec$tram)) spec$tram <- NA_character_ else spec$tram <- as.character(spec$tram)
    spec
  })
}

inventory_senado_processes <- function(client,
                                       years = NULL,
                                       siglas = NULL,
                                       tramitando_filter = c("S", "N"),
                                       fetch_child_entities = TRUE,
                                       max_processes_per_run = Inf,
                                       process_ids = NULL,
                                       max_segments_per_run = Inf,
                                       segment_specs = NULL) {

  # Listas acumuladoras de entidades para as tabelas normativas
  acc_propositions <- list()
  acc_process_phases <- list()
  acc_documents <- list()
  acc_proposition_documents <- list()
  acc_document_phases <- list()
  acc_authors <- list()
  acc_proposition_authors <- list()
  acc_document_authors <- list()
  acc_relations <- list()
  acc_themes <- list()
  acc_proposition_themes <- list()
  acc_entity_aliases <- list()
  acc_metadata_checks <- list()
  acc_coverage_segments <- list()
  pending_process_ids <- character()
  retry_segment_specs <- list()

  # Rastrear IDs únicos de proposições e documentos já processados
  seen_prop_ids <- character()
  seen_doc_ids <- character()
  seen_author_ids <- character()
  seen_theme_ids <- character()
  request_safe <- function(...) {
    tryCatch(client$request(...), error = function(e) list(
      data = NULL, snapshot = list(snapshot_id = NA_character_),
      http_status = NA_integer_, error = conditionMessage(e)
    ))
  }

  # /processo não documenta page/limit e exige filtros para tramitando=N.
  # O modo histórico usa fatias anuais de todos os tipos, sem filtro sigla.
  explicit_scope <- length(years) > 0L || length(siglas) > 0L
  if (length(process_ids) > 0L) {
    # OpenAPI documenta idProcesso como array com máximo de 100 itens. Cada
    # bloco é uma unidade retomável; não se inventa paginação para /processo.
    id_batches <- split(unique(as.character(process_ids)), ceiling(seq_along(unique(as.character(process_ids))) / 100L))
    query_specs <- lapply(id_batches, function(ids) list(year = NA_integer_, sigla = NA_character_, tram = NA_character_, process_ids = ids))
  } else if (!explicit_scope && !is.null(segment_specs)) {
    query_specs <- normalize_senado_segment_specs(segment_specs)
  } else if (!explicit_scope) {
    # Busca anual desde 1826, início da 1ª Legislatura e dos Anais oficiais.
    # Isso define o universo consultado na API; não afirma que a API contenha
    # documentos desde então. Anais/Diários permanecem coleções separadas.
    query_specs <- senado_process_query_specs(1826L:as.integer(format(Sys.Date(), "%Y")), tramitando_filter)
  } else {
    if (is.null(years) || length(years) == 0L) years <- NA_integer_
    if (is.null(siglas) || length(siglas) == 0L) siglas <- NA_character_
    query_specs <- list()
    for (yr in years) for (sig in siglas) for (tram in tramitando_filter) {
      query_specs[[length(query_specs) + 1L]] <- list(year = yr, sigla = sig, tram = tram)
    }
  }

  deferred_specs <- list()
  if (is.finite(max_segments_per_run) && length(query_specs) > max_segments_per_run) {
    deferred_specs <- query_specs[seq.int(max_segments_per_run + 1L, length(query_specs))]
    query_specs <- query_specs[seq_len(max_segments_per_run)]
  }
  for (spec in deferred_specs) {
    yr <- spec$year; sig <- spec$sigla; tram <- spec$tram
    seg_id <- paste0("senado:collection:api:processo:", if (is.na(yr)) "unknown_year" else yr, ":", if (is.na(sig)) "ALL" else sig, ":", if (is.na(tram)) "unknown_status" else tram)
    acc_coverage_segments[[length(acc_coverage_segments) + 1L]] <- list(
      segment_id = seg_id, collection_id = "senado:collection:api:processo", house = "senado",
      legislative_type_id = if (is.na(sig)) NA_character_ else paste0("senado:type:sigla:", tolower(sig)),
      year = if (is.na(yr)) NA_integer_ else as.integer(yr),
      period_start = if (is.na(yr)) as.Date(NA) else as.Date(paste0(yr, "-01-01")),
      period_end = if (is.na(yr)) as.Date(NA) else as.Date(paste0(yr, "-12-31")), date_axis = "presentation",
      snapshot_cutoff_utc = as.POSIXct(Sys.time(), tz = "UTC"),
      query_json = toJSON(list(ano = yr, sigla = sig, tramitando = tram), auto_unbox = TRUE),
      inventory_status = "pending", coverage_status = "pending", expected_count = NA_integer_,
      discovered_count = 0L, retrieved_count = 0L, accepted_count = 0L, count_unit = "process",
      exhaustion_evidence = NA_character_, gap_reason = "Segmento anual adiado pelo limite operacional; retomar pela fila de segmentos.", snapshot_id = NA_character_
    )
  }

  child_process_count <- 0L
  for (spec in query_specs) {
        yr <- spec$year
        sig <- spec$sigla
        tram <- spec$tram
        query_params <- list()
        if (length(spec$process_ids) > 0L) query_params$idProcesso <- spec$process_ids
        if (!is.na(yr)) query_params$ano <- as.integer(yr)
        if (!is.na(sig) && nzchar(sig)) query_params$sigla <- as.character(sig)
        if (!is.null(tram) && !is.na(tram)) query_params$tramitando <- as.character(tram)

        seg_label <- if (length(spec$process_ids) > 0L) paste0("ids_", hash_string(paste(spec$process_ids, collapse = ","))) else if (is.na(yr) && is.na(sig)) paste0("all_years_status_", tram) else paste(yr, ifelse(is.na(sig), "ALL", sig), tram, sep = "_")
        seg_id <- if (is.na(yr) && is.na(sig) && length(spec$process_ids) == 0L) paste0("senado:collection:api:processo:all_years:status:", tram) else paste0("senado:collection:api:processo:", seg_label)

        if (!is.null(spec$pending_reason)) {
          acc_coverage_segments[[length(acc_coverage_segments) + 1L]] <- list(
            segment_id = seg_id, collection_id = "senado:collection:api:processo", house = "senado",
            legislative_type_id = if (is.na(sig)) NA_character_ else paste0("senado:type:sigla:", tolower(sig)),
            year = if (is.na(yr)) NA_integer_ else as.integer(yr),
            period_start = as.Date(NA), period_end = as.Date(NA), date_axis = "catalog_period",
            snapshot_cutoff_utc = as.POSIXct(Sys.time(), tz = "UTC"), query_json = toJSON(list(sigla = sig), auto_unbox = TRUE),
            inventory_status = "pending", coverage_status = "pending", expected_count = NA_integer_,
            discovered_count = 0L, retrieved_count = 0L, accepted_count = 0L, count_unit = "process",
            exhaustion_evidence = NA_character_, gap_reason = as.character(spec$pending_reason), snapshot_id = NA_character_
          )
          next
        }

        # Realizar requisição com gravação de snapshot
        resp <- tryCatch(client$request(
          endpoint = "/processo", query = query_params,
          accept = "application/json", source_kind = "api"
        ), error = function(e) list(data = NULL, snapshot = list(snapshot_id = NA_character_),
                                     http_status = NA_integer_, error = conditionMessage(e)))

        snap_id <- resp$snapshot$snapshot_id
        proc_list <- resp$data
        valid_array <- is.list(proc_list)
        query_ok <- identical(as.integer(resp$http_status), 200L) && valid_array
        discovered <- if (valid_array) length(proc_list) else 0L
        returned_ids <- if (valid_array && discovered > 0L) vapply(proc_list, function(x) if (!is.null(x$id)) as.character(x$id) else NA_character_, character(1)) else character()
        missing_ids <- if (query_ok && length(spec$process_ids) > 0L) setdiff(spec$process_ids, returned_ids) else character()
        if (!query_ok && length(spec$process_ids) > 0L) {
          pending_process_ids <- unique(c(pending_process_ids, spec$process_ids))
        }
        if (!query_ok && length(spec$process_ids) == 0L) retry_segment_specs[[length(retry_segment_specs) + 1L]] <- spec
        if (length(missing_ids) > 0L) pending_process_ids <- unique(c(pending_process_ids, missing_ids))
        acc_coverage_segments[[length(acc_coverage_segments) + 1L]] <- list(
          segment_id = seg_id,
          collection_id = "senado:collection:api:processo",
          house = "senado",
          legislative_type_id = NA_character_,
          year = if (is.na(yr)) NA_integer_ else as.integer(yr),
          period_start = if (is.na(yr)) as.Date(NA) else as.Date(paste0(yr, "-01-01")),
          period_end = if (is.na(yr)) as.Date(NA) else as.Date(paste0(yr, "-12-31")),
          date_axis = if (is.na(yr)) "catalog_period" else "presentation",
          snapshot_cutoff_utc = as.POSIXct(Sys.time(), tz = "UTC"),
          query_json = toJSON(query_params, auto_unbox = TRUE),
          inventory_status = if (query_ok) "exhausted" else "error",
          coverage_status = if (!query_ok || length(missing_ids) > 0L || discovered == 0L) "partial" else "complete_discovered",
          expected_count = if (length(spec$process_ids) > 0L) as.integer(length(spec$process_ids)) else NA_integer_,
          discovered_count = as.integer(discovered),
          retrieved_count = as.integer(discovered),
          accepted_count = 0L,
          count_unit = "process",
          exhaustion_evidence = if (query_ok) "HTTP 200; payload JSON em array conforme operação /processo do OpenAPI; nenhum parâmetro de paginação consta no contrato publicado." else NA_character_,
          gap_reason = if (!query_ok) paste("Consulta não concluída:", resp$error %||% paste("HTTP", resp$http_status)) else if (length(missing_ids) > 0L) paste("IDs solicitados não retornados na consulta:", paste(missing_ids, collapse = ",")) else if (discovered == 0L) "Consulta anual sem resultados; resposta vazia não prova ausência no acervo." else NA_character_,
          snapshot_id = snap_id
        )
        if (!query_ok || discovered == 0L) next

        for (item in proc_list) {
          id_proc <- if (!is.null(item$id)) as.character(item$id) else next
          prop_id <- build_proposition_id("senado", id_proc)

          if (prop_id %in% seen_prop_ids) next
          seen_prop_ids <- c(seen_prop_ids, prop_id)

          cod_mat <- if (!is.null(item$codigoMateria)) as.character(item$codigoMateria) else NA_character_
          sigla_val <- if (!is.null(item$sigla) && nzchar(as.character(item$sigla))) as.character(item$sigla) else if (!is.na(sig)) sig else NA_character_
          tipo_doc <- if (!is.null(item$tipoDocumento) && nzchar(as.character(item$tipoDocumento))) as.character(item$tipoDocumento) else "unknown"
          ident <- if (!is.null(item$identificacao) && nzchar(as.character(item$identificacao))) as.character(item$identificacao) else paste("processo", id_proc)
          ementa_txt <- if (!is.null(item$ementa)) as.character(item$ementa) else NA_character_
          dt_apres <- if (!is.null(item$dataApresentacao)) as.Date(item$dataApresentacao) else NA
          dt_apres_raw <- if (!is.null(item$dataApresentacao)) as.character(item$dataApresentacao) else NA_character_
          url_doc <- if (!is.null(item$urlDocumento)) as.character(item$urlDocumento) else NA_character_
          casa_ident <- if (!is.null(item$casaIdentificadora)) as.character(item$casaIdentificadora) else "SF"
          objetivo_val <- if (!is.null(item$objetivo)) as.character(item$objetivo) else "Iniciadora"

          # 1. Tabela PROPOSITIONS
          # Extrair número e ano da identificação se não informados
          num_val <- NA_integer_
          ano_val <- NA_integer_
          if (grepl("^[A-Z0-9.-]+\\s+([0-9]+)/([0-9]{4})", ident)) {
            parts <- regmatches(ident, regexec("^[A-Z0-9.-]+\\s+([0-9]+)/([0-9]{4})", ident))[[1]]
            if (length(parts) == 3) {
              num_val <- as.integer(parts[2])
              ano_val <- as.integer(parts[3])
            }
          }

          leg_type_id <- if (!is.na(sigla_val)) paste0("senado:type:sigla:", tolower(sigla_val)) else NA_character_

          acc_propositions[[length(acc_propositions) + 1]] <- list(
            proposition_id = prop_id,
            house = "senado",
            source_id = id_proc,
            type_code = sigla_val,
            type_source_id = sigla_val,
            type_label = tipo_doc,
            legislative_type_id = leg_type_id,
            source_namespace = "senado_api_processo",
            number = num_val,
            numbering_year = ano_val,
            number_raw = ident,
            identifier_label = ident,
            presentation_date = dt_apres,
            presentation_raw = dt_apres_raw,
            origin_house = if (objetivo_val == "Revisora") "CD" else casa_ident,
            legislative_body = casa_ident,
            title = ementa_txt,
            summary = ementa_txt,
            source_uri = paste0("https://legis.senado.leg.br/dadosabertos/processo/", id_proc),
            whole_text_url = url_doc,
            snapshot_id = snap_id,
            cohort_status = "candidate",
            cohort_reason = "Acervo oficial do Senado Federal catalogado na API v3"
          )

          # 2. Tabela ENTITY_ALIASES (Código legado codigoMateria do MATE)
          if (!is.na(cod_mat) && nchar(cod_mat) > 0) {
            alias_id_mate <- hash_string(paste0("senado_materia|", cod_mat, "|", prop_id))
            acc_entity_aliases[[length(acc_entity_aliases) + 1]] <- list(
              alias_id = alias_id_mate,
              entity_kind = "proposition",
              alias_namespace = "senado_materia",
              alias_source_id = cod_mat,
              canonical_entity_id = prop_id,
              evidence_uri = paste0("https://legis.senado.leg.br/dadosabertos/processo/", id_proc),
              snapshot_id = snap_id,
              status = "verified"
            )
          }

          # 3. Tabela PROCESS_PHASES
          phase_kind_val <- if (objetivo_val == "Iniciadora") "initiating" else if (objetivo_val == "Revisora") "reviewing" else "other"
          phase_id_val <- build_phase_id("senado", "processo", prop_id, phase_identity = paste0("fase:", objetivo_val))

          acc_process_phases[[length(acc_process_phases) + 1]] <- list(
            phase_id = phase_id_val,
            process_proposition_id = prop_id,
            house = "senado",
            source_namespace = "senado_processo_fase",
            source_phase_id = NA_character_,
            phase_kind = phase_kind_val,
            legislative_body = casa_ident,
            committee_source_id = NA_character_,
            number_raw = ident,
            type_code = sigla_val,
            numbering_year = ano_val,
            date_start = dt_apres,
            date_end = if (!is.null(item$dataSituacaoAtual)) as.Date(item$dataSituacaoAtual) else NA,
            source_uri = paste0("https://legis.senado.leg.br/dadosabertos/processo/", id_proc),
            snapshot_id = snap_id
          )

          # 4. Autor da proposição (a partir do resumo de autoria na listagem)
          if (!is.null(item$autoria) && nchar(trimws(as.character(item$autoria))) > 0) {
            author_str <- trimws(as.character(item$autoria))
            auth_id <- build_author_id("senado", name = author_str)

            if (!(auth_id %in% seen_author_ids)) {
              seen_author_ids <- c(seen_author_ids, auth_id)
              acc_authors[[length(acc_authors) + 1]] <- list(
                author_id = auth_id,
                house = "senado",
                source_id = NA_character_,
                name = author_str,
                author_type = "parliamentary_or_body",
                source_uri = paste0("https://legis.senado.leg.br/dadosabertos/processo/", id_proc),
                snapshot_id = snap_id
              )
            }

            acc_proposition_authors[[length(acc_proposition_authors) + 1]] <- list(
              proposition_id = prop_id,
              author_id = auth_id,
              role = "author",
              is_proponent = TRUE,
              signature_order = 1L,
              snapshot_id = snap_id
            )
          }

          # 5. Entidades filhas (Documentos, Emendas, Detalhes)
          if (fetch_child_entities) {
            if (child_process_count >= max_processes_per_run) {
              pending_process_ids <- unique(c(pending_process_ids, id_proc))
              for (endpoint_kind in c("processo_detail", "processo_documento", "processo_emenda")) {
                acc_metadata_checks[[length(acc_metadata_checks) + 1L]] <- list(
                  entity_kind = "proposition", entity_id = prop_id,
                  endpoint_kind = endpoint_kind, status = "pending",
                  snapshot_id = NA_character_, last_checked_at = as.POSIXct(NA, tz = "UTC"),
                  reason = "Limite operacional de entidades filhas desta execução atingido; retomar em outra execução."
                )
              }
              next
            }
            child_process_count <- child_process_count + 1L
            # 5a. Detalhe do Processo (/processo/{id})
            resp_detail <- request_safe(
              endpoint = paste0("/processo/", id_proc),
              accept = "application/json",
              source_kind = "api"
            )
            snap_detail_id <- resp_detail$snapshot$snapshot_id

            acc_metadata_checks[[length(acc_metadata_checks) + 1]] <- list(
              entity_kind = "proposition",
              entity_id = prop_id,
              endpoint_kind = "processo_detail",
              status = if (senado_http_ok(resp_detail) && is.list(detail_data <- resp_detail$data)) "success_nonempty" else if (senado_http_ok(resp_detail)) "success_empty" else if (is.null(resp_detail$http_status) || is.na(resp_detail$http_status) || resp_detail$http_status >= 500) "retryable_error" else "terminal_error",
              snapshot_id = snap_detail_id,
              last_checked_at = as.POSIXct(Sys.time(), tz = "UTC"),
              reason = paste("Status HTTP:", resp_detail$http_status)
            )

            detail_data <- resp_detail$data

            # Se houver identificacaoProcessoInicial (ligação Câmara ↔ Senado)
            if (is.list(detail_data) && !is.null(detail_data$identificacaoProcessoInicial)) {
              ext_label <- trimws(as.character(detail_data$identificacaoProcessoInicial))
              if (nchar(ext_label) > 0) {
                alias_ext_id <- hash_string(paste0("camara_prop_label|", ext_label, "|", prop_id))
                acc_entity_aliases[[length(acc_entity_aliases) + 1]] <- list(
                  alias_id = alias_ext_id,
                  entity_kind = "proposition",
                  alias_namespace = "camara_prop_label",
                  alias_source_id = ext_label,
                  canonical_entity_id = prop_id,
                  evidence_uri = paste0("https://legis.senado.leg.br/dadosabertos/processo/", id_proc),
                  snapshot_id = snap_detail_id,
                  status = "verified"
                )
              }
            }

            # Processos relacionados
            if (is.list(detail_data) && is.list(detail_data$processosRelacionados)) {
              for (rel in detail_data$processosRelacionados) {
                id_outro <- if (!is.null(rel$idOutroProcesso)) as.character(rel$idOutroProcesso) else next
                tipo_rel <- if (!is.null(rel$tipoRelacao)) as.character(rel$tipoRelacao) else "REFERENCIA"
                target_prop_id <- build_proposition_id("senado", id_outro)
                rel_id <- paste0(prop_id, ":rel:", id_outro)

                group_policy <- if (tipo_rel %in% c("APENSADA", "SUBSTITUTIVO")) "bind" else "do_not_bind"

                acc_relations[[length(acc_relations) + 1]] <- list(
                  relation_id = rel_id,
                  source_proposition_id = prop_id,
                  target_proposition_id = target_prop_id,
                  relation_type = tipo_rel,
                  snapshot_id = snap_detail_id,
                  source_uri = paste0("https://legis.senado.leg.br/dadosabertos/processo/", id_proc),
                  grouping_policy = group_policy
                )
              }
            }

            # 5b. Documentos do Processo (/processo/documento?idProcesso={id})
            resp_docs <- request_safe(
              endpoint = "/processo/documento",
              query = list(idProcesso = id_proc),
              accept = "application/json",
              source_kind = "api"
            )
            snap_docs_id <- resp_docs$snapshot$snapshot_id

            docs_list <- resp_docs$data
            doc_count <- if (is.list(docs_list)) length(docs_list) else 0

            acc_metadata_checks[[length(acc_metadata_checks) + 1]] <- list(
              entity_kind = "proposition",
              entity_id = prop_id,
              endpoint_kind = "processo_documento",
              status = if (senado_http_ok(resp_docs) && doc_count > 0) "success_nonempty" else if (senado_http_ok(resp_docs)) "success_empty" else if (is.null(resp_docs$http_status) || is.na(resp_docs$http_status) || resp_docs$http_status >= 500) "retryable_error" else "terminal_error",
              snapshot_id = snap_docs_id,
              last_checked_at = as.POSIXct(Sys.time(), tz = "UTC"),
              reason = paste("Documentos encontrados:", doc_count)
            )

            # Documento inicial de detalhe (fallback se não estiver na lista)
            initial_doc_id_detail <- NULL
            if (is.list(detail_data) && is.list(detail_data$documento) && !is.null(detail_data$documento$id)) {
              initial_doc_id_detail <- as.character(detail_data$documento$id)
            }

            doc_order <- 0L

            if (is.list(docs_list) && doc_count > 0) {
              for (d in docs_list) {
                doc_order <- doc_order + 1L
                d_id <- if (!is.null(d$id)) as.character(d$id) else next
                doc_norm_id <- build_document_id("senado", "processo", id_oficial = d_id)

                d_sigla_tipo <- if (!is.null(d$siglaTipo)) as.character(d$siglaTipo) else ""
                d_desc_tipo <- if (!is.null(d$descricaoTipo)) as.character(d$descricaoTipo) else "Documento Legislativo"
                d_url <- if (!is.null(d$urlDocumento)) as.character(d$urlDocumento) else paste0("https://legis.senado.leg.br/sdleg-getter/documento?dm=", d_id)
                d_date_raw <- if (!is.null(d$dataDocumento)) d$dataDocumento else if (!is.null(d$dataRecebimento)) d$dataRecebimento else NA
                d_date <- if (!is.na(d_date_raw)) as.Date(d_date_raw) else dt_apres

                norm_kind <- map_doc_type_to_normalized_kind(d_sigla_tipo, d_desc_tipo)
                is_initial <- (!is.null(initial_doc_id_detail) && d_id == initial_doc_id_detail) || norm_kind == "initial"
                doc_role <- map_doc_type_to_document_role(d_sigla_tipo, d_desc_tipo, is_initial = is_initial)

                if (!(doc_norm_id %in% seen_doc_ids)) {
                  seen_doc_ids <- c(seen_doc_ids, doc_norm_id)

                  acc_documents[[length(acc_documents) + 1]] <- list(
                    document_id = doc_norm_id,
                    house = "senado",
                    source_document_id = d_id,
                    source_namespace = "senado_processo_documento",
                    identity_url = d_url,
                    document_type = d_desc_tipo,
                    document_type_source_id = d_sigla_tipo,
                    legislative_type_id = paste0("senado:type:doc:", d_id),
                    legislative_body = if (!is.null(d$siglaColegiadoRecebedor)) as.character(d$siglaColegiadoRecebedor) else casa_ident,
                    normalized_kind = norm_kind,
                    publication_date = d_date,
                    date_range_start = d_date,
                    date_range_end = d_date,
                    date_status = "verified",
                    source_uri = d_url,
                    snapshot_id = snap_docs_id
                  )
                }

                # Ponte PROPOSITION_DOCUMENTS
                acc_proposition_documents[[length(acc_proposition_documents) + 1]] <- list(
                  proposition_id = prop_id,
                  document_id = doc_norm_id,
                  document_role = doc_role,
                  role_status = "verified",
                  role_evidence = paste("Tipo:", d_sigla_tipo, "| Descricao:", d_desc_tipo),
                  document_date = d_date,
                  source_order = doc_order,
                  snapshot_id = snap_docs_id
                )

                # Ponte DOCUMENT_PHASES
                acc_document_phases[[length(acc_document_phases) + 1]] <- list(
                  document_id = doc_norm_id,
                  phase_id = phase_id_val,
                  role = doc_role,
                  evidence = paste("Documento associado ao processo na fase", objetivo_val),
                  snapshot_id = snap_docs_id
                )

                # Autoria do Documento (DOCUMENT_AUTHORS)
                if (is.list(d$autores) && length(d$autores) > 0) {
                  doc_auth_order <- 0L
                  for (da in d$autores) {
                    doc_auth_order <- doc_auth_order + 1L
                    da_name <- if (!is.null(da$autor)) as.character(da$autor) else "Autor Desconhecido"
                    da_code <- if (!is.null(da$codigoParlamentar)) as.character(da$codigoParlamentar) else NULL
                    da_id <- build_author_id("senado", source_id = da_code, name = da_name)

                    if (!(da_id %in% seen_author_ids)) {
                      seen_author_ids <- c(seen_author_ids, da_id)
                      acc_authors[[length(acc_authors) + 1]] <- list(
                        author_id = da_id,
                        house = "senado",
                        source_id = if (!is.null(da_code)) da_code else NA_character_,
                        name = da_name,
                        author_type = if (!is.null(da$descricaoTipo)) as.character(da$descricaoTipo) else "author",
                        source_uri = if (!is.null(da_code)) paste0("https://legis.senado.leg.br/dadosabertos/senador/", da_code) else NA_character_,
                        snapshot_id = snap_docs_id
                      )
                    }

                    da_role <- if (norm_kind == "report") "rapporteur" else "author"

                    acc_document_authors[[length(acc_document_authors) + 1]] <- list(
                      document_id = doc_norm_id,
                      author_id = da_id,
                      role = da_role,
                      signature_order = doc_auth_order,
                      source_uri = d_url,
                      snapshot_id = snap_docs_id
                    )
                  }
                }
              }
            }

            # 5c. Emendas do Processo (/processo/emenda?idProcesso={id})
            resp_emendas <- request_safe(
              endpoint = "/processo/emenda",
              query = list(idProcesso = id_proc),
              accept = "application/json",
              source_kind = "api"
            )
            snap_emendas_id <- resp_emendas$snapshot$snapshot_id

            emendas_list <- resp_emendas$data
            emendas_count <- if (is.list(emendas_list)) length(emendas_list) else 0

            acc_metadata_checks[[length(acc_metadata_checks) + 1]] <- list(
              entity_kind = "proposition",
              entity_id = prop_id,
              endpoint_kind = "processo_emenda",
              status = if (senado_http_ok(resp_emendas) && emendas_count > 0) "success_nonempty" else if (senado_http_ok(resp_emendas)) "success_empty" else if (is.null(resp_emendas$http_status) || is.na(resp_emendas$http_status) || resp_emendas$http_status >= 500) "retryable_error" else "terminal_error",
              snapshot_id = snap_emendas_id,
              last_checked_at = as.POSIXct(Sys.time(), tz = "UTC"),
              reason = paste("Emendas encontradas:", emendas_count)
            )

            if (is.list(emendas_list) && emendas_count > 0) {
              for (em in emendas_list) {
                doc_order <- doc_order + 1L
                em_doc_id_val <- if (!is.null(em$idDocumentoEmenda)) as.character(em$idDocumentoEmenda) else paste0("emenda_", em$id)
                em_norm_doc_id <- build_document_id("senado", "processo", id_oficial = em_doc_id_val)

                em_url <- if (!is.null(em$urlDocumentoEmenda)) as.character(em$urlDocumentoEmenda) else paste0("https://legis.senado.leg.br/sdleg-getter/documento?dm=", em_doc_id_val)
                em_date <- if (!is.null(em$dataApresentacao)) as.Date(em$dataApresentacao) else dt_apres
                em_ident <- if (!is.null(em$identificacao)) as.character(em$identificacao) else paste("Emenda ao", ident)

                if (!(em_norm_doc_id %in% seen_doc_ids)) {
                  seen_doc_ids <- c(seen_doc_ids, em_norm_doc_id)

                  acc_documents[[length(acc_documents) + 1]] <- list(
                    document_id = em_norm_doc_id,
                    house = "senado",
                    source_document_id = em_doc_id_val,
                    source_namespace = "senado_processo_emenda",
                    identity_url = em_url,
                    document_type = "Emenda Legislativa",
                    document_type_source_id = "EMENDA",
                    legislative_type_id = "senado:type:doc:emenda",
                    legislative_body = if (!is.null(em$siglaColegiado)) as.character(em$siglaColegiado) else casa_ident,
                    normalized_kind = "amendment",
                    publication_date = em_date,
                    date_range_start = em_date,
                    date_range_end = em_date,
                    date_status = "verified",
                    source_uri = em_url,
                    snapshot_id = snap_emendas_id
                  )
                }

                # Ponte PROPOSITION_DOCUMENTS
                acc_proposition_documents[[length(acc_proposition_documents) + 1]] <- list(
                  proposition_id = prop_id,
                  document_id = em_norm_doc_id,
                  document_role = "amendment",
                  role_status = "verified",
                  role_evidence = paste("Emenda apresentada:", em_ident),
                  document_date = em_date,
                  source_order = doc_order,
                  snapshot_id = snap_emendas_id
                )

                # Ponte DOCUMENT_PHASES
                acc_document_phases[[length(acc_document_phases) + 1]] <- list(
                  document_id = em_norm_doc_id,
                  phase_id = phase_id_val,
                  role = "amendment",
                  evidence = paste("Emenda anexada ao processo na fase", objetivo_val),
                  snapshot_id = snap_emendas_id
                )
              }
            }
            if (any(is.na(c(resp_detail$http_status, resp_docs$http_status, resp_emendas$http_status))) ||
                any(c(resp_detail$http_status, resp_docs$http_status, resp_emendas$http_status) != 200L)) {
              pending_process_ids <- unique(c(pending_process_ids, id_proc))
            }
          }
        }
      }

  # Helper para converter lista em data frame respeitando colunas vazias
  list_to_df <- function(lst, schema_name) {
    schemas <- get_arrow_schemas()
    target_schema <- schemas[[schema_name]]
    field_names <- names(target_schema)

    if (length(lst) == 0) {
      empty_list <- list()
      for (f in field_names) {
        empty_list[[f]] <- vector(mode = "character", length = 0)
      }
      return(as.data.frame(empty_list, stringsAsFactors = FALSE))
    }

    df <- do.call(rbind, lapply(lst, as.data.frame, stringsAsFactors = FALSE))
    df
  }

  # Montar dicionário com todas as tabelas
  list(
    propositions = list_to_df(acc_propositions, "propositions"),
    process_phases = list_to_df(acc_process_phases, "process_phases"),
    documents = list_to_df(acc_documents, "documents"),
    proposition_documents = list_to_df(acc_proposition_documents, "proposition_documents"),
    document_phases = list_to_df(acc_document_phases, "document_phases"),
    authors = list_to_df(acc_authors, "authors"),
    proposition_authors = list_to_df(acc_proposition_authors, "proposition_authors"),
    document_authors = list_to_df(acc_document_authors, "document_authors"),
    relations = list_to_df(acc_relations, "relations"),
    entity_aliases = list_to_df(acc_entity_aliases, "entity_aliases"),
    metadata_checks = list_to_df(acc_metadata_checks, "metadata_checks"),
    coverage_segments = list_to_df(acc_coverage_segments, "coverage_segments"),
    pending_process_ids = pending_process_ids,
    pending_segment_specs = c(deferred_specs, retry_segment_specs, Filter(function(spec) !is.null(spec$pending_reason), query_specs))
  )
}
