# R/download/fetcher.R
# Cliente de captura HTTP resiliente com retries, backoff, jitter, Retry-After, rate limiting e suporte a mocks
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0, Seção 2 e 5)

suppressPackageStartupMessages({
  library(httr2)
  library(digest)
  library(stringr)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "download", "validator.R"))
source(file.path(repo_root, "R", "download", "blob_store.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

# Ambiente de rastreamento de concorrência e ritmo por host
.host_tracker_env <- new.env(parent = emptyenv())

#' Extrai o host de uma URL
get_url_host <- function(url_str) {
  tryCatch({
    m <- regmatches(url_str, regexpr("^[a-zA-Z]+://([^/:]+)", url_str, perl = TRUE))
    if (length(m) > 0) {
      sub("^[a-zA-Z]+://", "", m[1])
    } else {
      "default_host"
    }
  }, error = function(e) "default_host")
}

#' Aplica rate limiting suave por host para respeitar os portais oficiais
pace_host_request <- function(host, min_interval_seconds = 0.2) {
  now <- as.numeric(Sys.time())
  last_time <- .host_tracker_env[[host]]
  if (!is.null(last_time)) {
    elapsed <- now - last_time
    if (elapsed < min_interval_seconds) {
      Sys.sleep(min_interval_seconds - elapsed)
    }
  }
  .host_tracker_env[[host]] <- as.numeric(Sys.time())
}

#' Executa a captura de um único documento, gerenciando retries e validando conteúdo
#'
#' @param doc_row Linha da fila de documentos (document_id, requested_url, house, publication_date, etc.).
#' @param data_root Diretório base dos dados.
#' @param network_cfg Configuração de rede (max_retries, timeout, backoff, user_agent, etc.).
#' @param mock_transport Função mock opcional para interceptar requisições em testes.
#' @return Lista contendo: success (logical), attempt_records (lista de tentativas), version_record (registro de versão ou NULL), raw_bytes (se sucesso).
fetch_document <- function(doc_row,
                           data_root = NULL,
                           network_cfg = list(),
                           mock_transport = NULL) {
  data_root <- resolve_download_data_root(data_root)
  document_id <- as.character(doc_row$document_id)
  requested_url <- as.character(doc_row$requested_url)
  house <- if (!is.null(doc_row$house)) as.character(doc_row$house) else "unknown"
  pub_date <- if (!is.null(doc_row$publication_date)) doc_row$publication_date else as.Date(NA)

  max_retries <- if (!is.null(network_cfg$max_retries)) as.integer(network_cfg$max_retries) else 5L
  connect_timeout <- if (!is.null(network_cfg$connect_timeout_seconds)) as.numeric(network_cfg$connect_timeout_seconds) else 10
  read_timeout <- if (!is.null(network_cfg$read_timeout_seconds)) as.numeric(network_cfg$read_timeout_seconds) else 120
  backoff_base <- if (!is.null(network_cfg$backoff_base_seconds)) as.numeric(network_cfg$backoff_base_seconds) else 1.5
  jitter_enabled <- if (!is.null(network_cfg$jitter)) as.logical(network_cfg$jitter) else TRUE
  user_agent <- if (!is.null(network_cfg$user_agent)) as.character(network_cfg$user_agent) else "LLM-Legislativo/2.0 (pesquisa educacional)"

  host <- get_url_host(requested_url)

  attempt_records <- list()
  attempt_no <- 1L
  final_success <- FALSE
  version_record <- NULL

  while (attempt_no <= max_retries) {
    started_at <- Sys.time()
    next_retry_at <- as.POSIXct(NA, tz = "UTC")
    capture_id <- paste0("cap:", hash_string(paste0(document_id, ":", requested_url, ":", strftime(started_at, "%Y%m%d%H%M%S%OS3", tz = "UTC"), ":", attempt_no)))

    # Aplicar ritmo por host
    pace_host_request(host)

    # Executar requisição via mock_transport ou httr2
    req_result <- NULL
    if (!is.null(mock_transport)) {
      req_result <- tryCatch({
        mock_transport(requested_url = requested_url, attempt_no = attempt_no, doc_row = doc_row)
      }, error = function(e) {
        list(success = FALSE, error = e, status = 0L)
      })
    }

    if (is.null(req_result)) {
      # Requisição HTTP real
      req_result <- tryCatch({
        req <- request(requested_url) %>%
          req_user_agent(user_agent) %>%
          req_timeout(read_timeout)

        resp <- req_perform(req)
        final_url <- resp_url(resp)
        http_status <- resp_status(resp)
        headers <- resp_headers(resp)

        content_type <- resp_header(resp, "content-type")
        content_length_str <- resp_header(resp, "content-length")
        content_length <- if (!is.null(content_length_str) && !is.na(as.numeric(content_length_str))) as.numeric(content_length_str) else NA_real_

        raw_body <- resp_body_raw(resp)

        list(
          success = TRUE,
          status = http_status,
          final_url = final_url,
          content_type = content_type,
          declared_size = content_length,
          raw_bytes = raw_body,
          headers = headers,
          error = NULL
        )
      }, error = function(e) {
        list(
          success = FALSE,
          status = 0L,
          final_url = requested_url,
          content_type = NA_character_,
          declared_size = NA_real_,
          raw_bytes = raw(0),
          headers = list(),
          error = e
        )
      })
    }

    finished_at <- Sys.time()

    # Processar resultado da tentativa
    if (req_result$success && req_result$status >= 200 && req_result$status < 300) {
      final_url <- if (!is.null(req_result$final_url)) req_result$final_url else requested_url
      declared_mime <- if (!is.null(req_result$content_type)) req_result$content_type else NA_character_
      declared_size <- if (!is.null(req_result$declared_size)) as.numeric(req_result$declared_size) else NA_real_
      raw_bytes <- if (!is.null(req_result$raw_bytes)) req_result$raw_bytes else raw(0)
      received_size <- length(raw_bytes)

      # Validação estrita de conteúdo
      validation <- validate_download_content(
        raw_bytes = raw_bytes,
        declared_media_type = declared_mime,
        declared_size_bytes = declared_size,
        is_binary_expected = TRUE
      )

      if (validation$valid) {
        # Sucesso absoluto: salvar blob imutável
        file_sha256 <- tolower(hash_bytes(raw_bytes))
        blob_info <- store_raw_blob(raw_bytes, data_root = data_root)
        version_id <- paste0(document_id, ":v:", file_sha256)

        attempt_record <- list(
          capture_id = capture_id,
          document_id = document_id,
          requested_url = requested_url,
          final_url = final_url,
          started_at = started_at,
          finished_at = finished_at,
          attempt_no = attempt_no,
          http_status = as.integer(req_result$status),
          declared_media_type = as.character(declared_mime),
          declared_size_bytes = if (!is.na(declared_size)) as.numeric(declared_size) else as.numeric(received_size),
          received_size_bytes = as.numeric(received_size),
          file_sha256 = file_sha256,
          version_id = version_id,
          status = "succeeded",
          error_code = NA_character_,
          error_message = NA_character_,
          next_retry_at = as.POSIXct(NA, tz = "UTC")
        )
        attempt_records[[length(attempt_records) + 1]] <- attempt_record

        # Construir registro de document_versions
        version_record <- list(
          version_id = version_id,
          document_id = document_id,
          file_sha256 = file_sha256,
          raw_path = blob_info$raw_path,
          file_size_bytes = as.numeric(received_size),
          detected_media_type = validation$detected_media_type,
          page_count = if (!is.na(validation$page_count)) as.integer(validation$page_count) else NA_integer_,
          version_kind = "observed_capture",
          source_version_label = NA_character_,
          source_content_date = if (!is.na(pub_date)) as.Date(pub_date) else as.Date(NA),
          availability_date = as.Date(strftime(Sys.time(), "%Y-%m-%d", tz = "UTC")),
          version_date_status = if (!is.na(pub_date)) "verified" else "unknown",
          predecessor_version_id = NA_character_,
          first_capture_id = capture_id,
          integrity_status = "verified"
        )

        final_success <- TRUE
        break # Sai do loop de tentativas
      } else {
        # Erro de validação (ex: HTML 200, arquivo truncado, etc.)
        status_kind <- if (validation$error_code %in% c("TRUNCATED_FILE")) "retryable_error" else "terminal_error"

        if (status_kind == "retryable_error" && attempt_no < max_retries) {
          wait_sec <- (backoff_base ^ attempt_no) + if (jitter_enabled) stats::runif(1, 0.1, 0.5) else 0
          next_retry_at <- Sys.time() + wait_sec
        }

        attempt_record <- list(
          capture_id = capture_id,
          document_id = document_id,
          requested_url = requested_url,
          final_url = final_url,
          started_at = started_at,
          finished_at = finished_at,
          attempt_no = attempt_no,
          http_status = as.integer(req_result$status),
          declared_media_type = as.character(declared_mime),
          declared_size_bytes = if (!is.na(declared_size)) as.numeric(declared_size) else NA_real_,
          received_size_bytes = as.numeric(received_size),
          file_sha256 = NA_character_,
          version_id = NA_character_,
          status = status_kind,
          error_code = validation$error_code,
          error_message = validation$error_message,
          next_retry_at = next_retry_at
        )
        attempt_records[[length(attempt_records) + 1]] <- attempt_record

        if (status_kind == "terminal_error") {
          break # Erro terminal não deve ser retentado
        } else {
          Sys.sleep(min(wait_sec, 10))
        }
      }
    } else {
      # Falha HTTP ou conexão
      status_code <- if (!is.null(req_result$status) && req_result$status > 0) req_result$status else NA_integer_
      is_retryable <- is.na(status_code) || status_code %in% c(429L, 500L, 502L, 503L, 504L)

      err_code <- if (is.na(status_code) || status_code == 0) {
        "NETWORK_ERROR"
      } else {
        paste0("HTTP_", status_code)
      }

      err_msg <- if (!is.null(req_result$error)) {
        if (inherits(req_result$error, "condition")) {
          conditionMessage(req_result$error)
        } else {
          as.character(req_result$error)
        }
      } else if (!is.null(req_result$error_message)) {
        as.character(req_result$error_message)
      } else {
        paste("HTTP error status:", status_code)
      }

      if (is_retryable && attempt_no < max_retries) {
        # Verificar Retry-After
        retry_after_val <- if (!is.null(req_result$headers)) req_result$headers[["retry-after"]] else NULL
        wait_sec <- if (!is.null(retry_after_val) && !is.na(as.numeric(retry_after_val))) {
          as.numeric(retry_after_val)
        } else {
          (backoff_base ^ attempt_no) + if (jitter_enabled) stats::runif(1, 0.1, 0.5) else 0
        }
        next_retry_at <- Sys.time() + wait_sec
        status_kind <- "retryable_error"
      } else {
        status_kind <- if (is_retryable) "retryable_error_exhausted" else "terminal_error"
        wait_sec <- 0
      }

      attempt_record <- list(
        capture_id = capture_id,
        document_id = document_id,
        requested_url = requested_url,
        final_url = if (!is.null(req_result$final_url)) req_result$final_url else requested_url,
        started_at = started_at,
        finished_at = finished_at,
        attempt_no = attempt_no,
        http_status = if (!is.na(status_code)) as.integer(status_code) else NA_integer_,
        declared_media_type = NA_character_,
        declared_size_bytes = NA_real_,
        received_size_bytes = 0,
        file_sha256 = NA_character_,
        version_id = NA_character_,
        status = status_kind,
        error_code = err_code,
        error_message = err_msg,
        next_retry_at = next_retry_at
      )
      attempt_records[[length(attempt_records) + 1]] <- attempt_record

      if (!is_retryable) {
        break # Terminal (404, 401, 403, 410)
      } else if (attempt_no < max_retries) {
        Sys.sleep(min(wait_sec, 10))
      }
    }

    attempt_no <- attempt_no + 1L
  }

  list(
    success = final_success,
    attempt_records = attempt_records,
    version_record = version_record
  )
}
