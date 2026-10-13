# R/download/publisher.R
# Publicador atômico de tabelas Parquet tipadas, manifesto JSON e marcador COMPLETE.json
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0, Seção 1, 4 e 7)

suppressPackageStartupMessages({
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
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

#' Formata e valida o DataFrame de fetch_attempts para garantir 100% de conformidade com o esquema Arrow
clean_fetch_attempts_df <- function(df) {
  if (is.null(df) || nrow(df) == 0) {
    return(tibble(
      capture_id = character(),
      document_id = character(),
      requested_url = character(),
      final_url = character(),
      started_at = as.POSIXct(character(), tz = "UTC"),
      finished_at = as.POSIXct(character(), tz = "UTC"),
      attempt_no = integer(),
      http_status = integer(),
      declared_media_type = character(),
      declared_size_bytes = numeric(),
      received_size_bytes = numeric(),
      file_sha256 = character(),
      version_id = character(),
      status = character(),
      error_code = character(),
      error_message = character(),
      next_retry_at = as.POSIXct(character(), tz = "UTC")
    ))
  }

  tibble(
    capture_id = as.character(df$capture_id),
    document_id = as.character(df$document_id),
    requested_url = as.character(df$requested_url),
    final_url = if ("final_url" %in% names(df) && !all(is.na(df$final_url))) as.character(df$final_url) else as.character(df$requested_url),
    started_at = as.POSIXct(df$started_at, tz = "UTC"),
    finished_at = as.POSIXct(df$finished_at, tz = "UTC"),
    attempt_no = as.integer(df$attempt_no),
    http_status = as.integer(df$http_status),
    declared_media_type = as.character(df$declared_media_type),
    declared_size_bytes = as.numeric(df$declared_size_bytes),
    received_size_bytes = as.numeric(df$received_size_bytes),
    file_sha256 = as.character(df$file_sha256),
    version_id = as.character(df$version_id),
    status = as.character(df$status),
    error_code = as.character(df$error_code),
    error_message = as.character(df$error_message),
    next_retry_at = as.POSIXct(df$next_retry_at, tz = "UTC")
  )
}

#' Formata e valida o DataFrame de document_versions para conformidade com o esquema Arrow
clean_document_versions_df <- function(df) {
  if (is.null(df) || nrow(df) == 0) {
    return(tibble(
      version_id = character(),
      document_id = character(),
      file_sha256 = character(),
      raw_path = character(),
      file_size_bytes = numeric(),
      detected_media_type = character(),
      page_count = integer(),
      version_kind = character(),
      source_version_label = character(),
      source_content_date = as.Date(character()),
      availability_date = as.Date(character()),
      version_date_status = character(),
      predecessor_version_id = character(),
      first_capture_id = character(),
      integrity_status = character()
    ))
  }

  tibble(
    version_id = as.character(df$version_id),
    document_id = as.character(df$document_id),
    file_sha256 = as.character(df$file_sha256),
    raw_path = as.character(df$raw_path),
    file_size_bytes = as.numeric(df$file_size_bytes),
    detected_media_type = as.character(df$detected_media_type),
    page_count = as.integer(df$page_count),
    version_kind = as.character(df$version_kind),
    source_version_label = as.character(df$source_version_label),
    source_content_date = as.Date(df$source_content_date),
    availability_date = as.Date(df$availability_date),
    version_date_status = as.character(df$version_date_status),
    predecessor_version_id = as.character(df$predecessor_version_id),
    first_capture_id = as.character(df$first_capture_id),
    integrity_status = as.character(df$integrity_status)
  )
}

#' Publica as tabelas de download, o manifesto do lote e o marcador COMPLETE.json
#'
#' @param attempts_df DataFrame bruto de tentativas.
#' @param versions_df DataFrame bruto de versões obtidas.
#' @param output_dir Diretório de saída para gravação do lote.
#' @param batch_id Identificador único do lote.
#' @param reconciliation_summary Sumário estatístico gerado pela reconciliação.
#' @return Lista contendo paths dos arquivos publicados, manifesto e marcador COMPLETE.json.
publish_download_batch <- function(attempts_df,
                                   versions_df,
                                   output_dir,
                                   batch_id,
                                   reconciliation_summary = list()) {
  data_root <- resolve_external_data_root(repo_root, explicit_test_path = output_dir)
  output_dir <- assert_data_path(output_dir, data_root, "output_dir", allow_temp = TRUE)
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  # 1. Limpeza e tipagem dos DataFrames
  c_attempts <- clean_fetch_attempts_df(attempts_df)
  c_versions <- clean_document_versions_df(versions_df)

  # Deduplicação de versões (garantir unicidade de PK version_id)
  if (nrow(c_versions) > 0) {
    c_versions <- c_versions %>% distinct(version_id, .keep_all = TRUE)
  }

  # Deduplicação de tentativas (garantir unicidade de PK capture_id)
  if (nrow(c_attempts) > 0) {
    c_attempts <- c_attempts %>% distinct(capture_id, .keep_all = TRUE)
  }

  # 2. Gravar Parquets com esquemas Arrow normativos
  files_meta <- list()

  # Gravar fetch_attempts.parquet
  attempts_path <- file.path(output_dir, "fetch_attempts.parquet")
  meta_attempts <- write_contract_parquet(c_attempts, "fetch_attempts", attempts_path)
  files_meta[[length(files_meta) + 1]] <- meta_attempts

  # Gravar document_versions.parquet
  versions_path <- file.path(output_dir, "document_versions.parquet")
  meta_versions <- write_contract_parquet(c_versions, "document_versions", versions_path)
  files_meta[[length(files_meta) + 1]] <- meta_versions

  # 3. Gerar manifesto do lote
  manifest_obj <- list(
    schema_version = "2.0.0",
    batch_id = batch_id,
    stage = "download",
    created_at_utc = strftime(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    reconciliation_summary = list(
      discovered_total = reconciliation_summary$discovered_total,
      retrieved_total = reconciliation_summary$retrieved_total,
      failed_total = reconciliation_summary$failed_total,
      pending_total = reconciliation_summary$pending_total,
      coverage_status = reconciliation_summary$coverage_status,
      storage_metrics = reconciliation_summary$storage_metrics
    ),
    files = files_meta
  )

  manifest_path <- file.path(output_dir, "download_manifest.json")
  pub_res <- publish_manifest_with_complete(manifest_obj, manifest_path)

  list(
    output_dir = output_dir,
    batch_id = batch_id,
    files = files_meta,
    manifest_path = pub_res$manifest_path,
    manifest_sha256 = pub_res$manifest_sha256,
    complete_path = pub_res$complete_path
  )
}
