# R/inventory/senado/client.R
# Cliente HTTP resiliente e gravador de snapshots para o Senado Federal
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0) e docs/subagents/10_SENADO.md

suppressPackageStartupMessages({
  library(httr2)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "http_client.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

# Compatibilidade para callers de teste; o CLI de produção usa diretamente
# resolve_external_data_root() e não aceita caminhos relativos.
resolve_senado_data_root <- function(repo_root, data_root) {
  root <- path.expand(as.character(data_root))
  is_absolute <- grepl("^(/|[A-Za-z]:[/\\]|\\\\)", root)
  if (!is_absolute) root <- file.path(repo_root, root)
  normalizePath(root, winslash = "/", mustWork = FALSE)
}

create_senado_client <- function(base_url = "https://legis.senado.leg.br/dadosabertos/v3",
                                 user_agent = "LLM-Legislativo-Pesquisa-Educacional/2.0 (pesquisa academica; contato oficial)",
                                 timeout_seconds = 60,
                                 max_retries = 5,
                                 offline_mode = FALSE,
                                 mock_registry = list(),
                                 snapshot_store_dir = NULL) {

  client <- new.env(parent = emptyenv())
  client$base_url <- sub("/+$", "", base_url)
  client$user_agent <- user_agent
  client$timeout_seconds <- timeout_seconds
  client$max_retries <- max_retries
  client$offline_mode <- offline_mode
  client$mock_registry <- mock_registry
  client$snapshot_store_dir <- snapshot_store_dir
  client$snapshots_log <- list()

  client$register_mock <- function(path_pattern, response_data, status_code = 200, headers = list()) {
    client$mock_registry[[length(client$mock_registry) + 1]] <- list(
      pattern = path_pattern,
      data = response_data,
      status = status_code,
      headers = headers
    )
  }

  client$request <- function(endpoint, query = list(), accept = "application/json", source_kind = "api") {
    # Montar URL completa
    if (grepl("^https?://", endpoint)) {
      full_url <- endpoint
    } else {
      clean_endpoint <- sub("^/+", "", endpoint)
      api_base <- sub("/v3$", "", client$base_url)
      if (grepl("^v3/", clean_endpoint) || grepl("api-docs", clean_endpoint)) {
        full_url <- paste0(client$base_url, "/", clean_endpoint)
      } else {
        full_url <- paste0(api_base, "/", clean_endpoint)
      }
    }

    # Serializar query para JSON estável
    query_json <- if (length(query) > 0) {
      toJSON(query[order(names(query))], auto_unbox = TRUE)
    } else {
      "{}"
    }

    collected_at <- as.POSIXct(Sys.time(), tz = "UTC")
    snapshot_seed <- paste0("senado|", full_url, "|", query_json, "|", as.character(as.numeric(collected_at)))
    snapshot_id <- hash_string(snapshot_seed)

    query_str <- if (length(query) > 0) {
      paste(names(query), sapply(query, as.character), sep = "=", collapse = "&")
    } else {
      ""
    }
    url_with_query <- if (nchar(query_str) > 0) paste0(full_url, "?", query_str) else full_url

    # 1. Modo offline / Mock
    if (client$offline_mode || length(client$mock_registry) > 0) {
      for (m in client$mock_registry) {
        if (grepl(m$pattern, url_with_query) || grepl(m$pattern, full_url) || grepl(m$pattern, endpoint)) {
          mock_body <- if (is.character(m$data)) {
            charToRaw(m$data)
          } else if (is.raw(m$data)) {
            m$data
          } else {
            charToRaw(toJSON(m$data, auto_unbox = TRUE))
          }

          payload_sha256 <- hash_bytes(mock_body)
          raw_path <- NULL

          if (!is.null(client$snapshot_store_dir)) {
            raw_path <- file.path(client$snapshot_store_dir, paste0(payload_sha256, ".json"))
            dir.create(dirname(raw_path), recursive = TRUE, showWarnings = FALSE)
            writeBin(mock_body, raw_path)
          }

          parsed_data <- tryCatch({
            fromJSON(rawToChar(mock_body), simplifyVector = FALSE)
          }, error = function(e) rawToChar(mock_body))

          snap_record <- list(
            snapshot_id = snapshot_id,
            house = "senado",
            source_kind = source_kind,
            request_url = full_url,
            query_json = query_json,
            collected_at = collected_at,
            http_status = as.integer(m$status),
            payload_sha256 = payload_sha256,
            raw_path = if (!is.null(raw_path)) raw_path else NA_character_,
            pagination_complete = as.integer(m$status) >= 200L && as.integer(m$status) < 300L,
            source_schema_version = "4.1.3.99",
            license_evidence_id = "senado:lic:politica_uso_dados_abertos"
          )
          client$snapshots_log[[length(client$snapshots_log) + 1]] <- snap_record

          return(list(
            data = parsed_data,
            snapshot = snap_record,
            raw_bytes = mock_body,
            http_status = as.integer(m$status),
            headers = m$headers
          ))
        }
      }

      if (client$offline_mode) {
        stop(paste("Nenhum mock registrado para a URL:", full_url, "em modo offline"))
      }
    }

    # 2. Modo rede real
    req_headers <- list(Accept = accept)
    req_res <- perform_resilient_request(
      url = full_url,
      query = query,
      headers = req_headers,
      max_retries = client$max_retries,
      timeout_seconds = client$timeout_seconds,
      user_agent = client$user_agent
    )

    if (is.null(req_res$response)) {
      # Falha de conexão
      snap_record <- list(
        snapshot_id = snapshot_id,
        house = "senado",
        source_kind = source_kind,
        request_url = full_url,
        query_json = query_json,
        collected_at = collected_at,
        http_status = NA_integer_,
        payload_sha256 = NA_character_,
        raw_path = NA_character_,
        pagination_complete = FALSE,
        source_schema_version = NA_character_,
        license_evidence_id = "senado:lic:politica_uso_dados_abertos"
      )
      client$snapshots_log[[length(client$snapshots_log) + 1]] <- snap_record

      return(list(
        data = NULL,
        snapshot = snap_record,
        raw_bytes = raw(0),
        http_status = NA_integer_,
        headers = list(),
        error = req_res$error_message
      ))
    }

    resp <- req_res$response
    status <- resp_status(resp)
    raw_body <- resp_body_raw(resp)
    payload_sha256 <- if (length(raw_body) > 0) hash_bytes(raw_body) else hash_string("")
    raw_path <- NULL

    if (!is.null(client$snapshot_store_dir) && length(raw_body) > 0) {
      ext <- if (grepl("json", accept)) ".json" else ".bin"
      raw_path <- file.path(client$snapshot_store_dir, paste0(payload_sha256, ext))
      dir.create(dirname(raw_path), recursive = TRUE, showWarnings = FALSE)
      writeBin(raw_body, raw_path)
    }

    parsed_data <- NULL
    if (status < 400 && length(raw_body) > 0) {
      if (grepl("json", accept) || grepl("application/json", resp_header(resp, "content-type") %||% "")) {
        parsed_data <- tryCatch({
          fromJSON(rawToChar(raw_body), simplifyVector = FALSE)
        }, error = function(e) rawToChar(raw_body))
      } else {
        parsed_data <- rawToChar(raw_body)
      }
    }

    # Verificar headers de depreciação/sunset
    headers_list <- resp_headers(resp)
    if (!is.null(headers_list[["deprecation"]])) {
      warning(paste("Endpoint depreciado detectado:", full_url, "- Deprecation:", headers_list[["deprecation"]]))
    }

    snap_record <- list(
      snapshot_id = snapshot_id,
      house = "senado",
      source_kind = source_kind,
      request_url = full_url,
      query_json = query_json,
      collected_at = collected_at,
      http_status = as.integer(status),
      payload_sha256 = payload_sha256,
      raw_path = if (!is.null(raw_path)) raw_path else NA_character_,
      pagination_complete = status >= 200L && status < 300L,
      source_schema_version = "4.1.3.99",
      license_evidence_id = "senado:lic:politica_uso_dados_abertos"
    )
    client$snapshots_log[[length(client$snapshots_log) + 1]] <- snap_record

    list(
      data = parsed_data,
      snapshot = snap_record,
      raw_bytes = raw_body,
      http_status = as.integer(status),
      headers = headers_list
    )
  }

  client$get_snapshots_df <- function() {
    if (length(client$snapshots_log) == 0) {
      return(data.frame(
        snapshot_id = character(),
        house = character(),
        source_kind = character(),
        request_url = character(),
        query_json = character(),
        collected_at = as.POSIXct(character(), tz = "UTC"),
        http_status = integer(),
        payload_sha256 = character(),
        raw_path = character(),
        pagination_complete = logical(),
        source_schema_version = character(),
        license_evidence_id = character(),
        stringsAsFactors = FALSE
      ))
    }

    df <- do.call(rbind, lapply(client$snapshots_log, function(x) {
      data.frame(
        snapshot_id = as.character(x$snapshot_id),
        house = as.character(x$house),
        source_kind = as.character(x$source_kind),
        request_url = as.character(x$request_url),
        query_json = as.character(x$query_json),
        collected_at = as.POSIXct(x$collected_at, tz = "UTC"),
        http_status = as.integer(x$http_status),
        payload_sha256 = as.character(x$payload_sha256),
        raw_path = as.character(x$raw_path),
        pagination_complete = as.logical(x$pagination_complete),
        source_schema_version = as.character(x$source_schema_version),
        license_evidence_id = as.character(x$license_evidence_id),
        stringsAsFactors = FALSE
      )
    }))
    df
  }

  client
}
