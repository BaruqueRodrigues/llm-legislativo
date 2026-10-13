# tests/download/test_schema_integrity_and_publication.R
# Testes formais de integridade Arrow, validacao de esquemas e publicacao de lote com COMPLETE.json
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0, Seção 1, 4 e 7) e docs/subagents/02_DOWNLOADS.md

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
source(file.path(repo_root, "R", "download", "publisher.R"))

test_that("SCHEMA-01: Tabelas fetch_attempts e document_versions aderem aos 31 esquemas normativos Arrow", {
  tmp_out <- tempfile("test_pub_schema")
  on.exit(unlink(tmp_out, recursive = TRUE))

  schemas <- get_arrow_schemas()
  expect_true("fetch_attempts" %in% names(schemas))
  expect_true("document_versions" %in% names(schemas))

  # Criar dados válidos sintéticos
  now_utc <- as.POSIXct(strftime(Sys.time(), "%Y-%m-%d %H:%M:%S", tz = "UTC"), tz = "UTC")
  hash_val <- "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

  attempts_raw <- tibble(
    capture_id = c("cap:test:1", "cap:test:2"),
    document_id = c("camara:doc:api:D1", "senado:doc:processo:P2"),
    requested_url = c("https://example.com/1.pdf", "https://example.com/2.pdf"),
    final_url = c("https://example.com/1.pdf", "https://example.com/2_redirect.pdf"),
    started_at = c(now_utc, now_utc),
    finished_at = c(now_utc + 1, now_utc + 1),
    attempt_no = c(1L, 1L),
    http_status = c(200L, 200L),
    declared_media_type = c("application/pdf", "application/pdf"),
    declared_size_bytes = c(2048, 4096),
    received_size_bytes = c(2048, 4096),
    file_sha256 = c(hash_val, hash_val),
    version_id = c(paste0("camara:doc:api:D1:v:", hash_val), paste0("senado:doc:processo:P2:v:", hash_val)),
    status = c("succeeded", "succeeded"),
    error_code = c(NA_character_, NA_character_),
    error_message = c(NA_character_, NA_character_),
    next_retry_at = as.POSIXct(c(NA, NA), tz = "UTC")
  )

  versions_raw <- tibble(
    version_id = c(paste0("camara:doc:api:D1:v:", hash_val), paste0("senado:doc:processo:P2:v:", hash_val)),
    document_id = c("camara:doc:api:D1", "senado:doc:processo:P2"),
    file_sha256 = c(hash_val, hash_val),
    raw_path = c(paste0("raw/sha256/e3/", hash_val, ".bin"), paste0("raw/sha256/e3/", hash_val, ".bin")),
    file_size_bytes = c(2048, 4096),
    detected_media_type = c("application/pdf", "application/pdf"),
    page_count = c(2L, 5L),
    version_kind = c("observed_capture", "observed_capture"),
    source_version_label = c(NA_character_, NA_character_),
    source_content_date = as.Date(c("2024-01-01", "2024-02-01")),
    availability_date = as.Date(c("2026-10-07", "2026-10-07")),
    version_date_status = c("verified", "verified"),
    predecessor_version_id = c(NA_character_, NA_character_),
    first_capture_id = c("cap:test:1", "cap:test:2"),
    integrity_status = c("verified", "verified")
  )

  pub_res <- publish_download_batch(
    attempts_df = attempts_raw,
    versions_df = versions_raw,
    output_dir = tmp_out,
    batch_id = "test_batch_001",
    reconciliation_summary = list(
      discovered_total = 2,
      retrieved_total = 2,
      failed_total = 0,
      pending_total = 0,
      coverage_status = "complete_discovered",
      storage_metrics = list(
        total_versions_count = 2,
        total_bytes_received = 6144,
        unique_blobs_count = 1,
        storage_reuse_count = 1
      )
    )
  )

  # Verificar presença de arquivos
  expect_true(file.exists(file.path(tmp_out, "fetch_attempts.parquet")))
  expect_true(file.exists(file.path(tmp_out, "document_versions.parquet")))
  expect_true(file.exists(file.path(tmp_out, "download_manifest.json")))
  expect_true(file.exists(file.path(tmp_out, "COMPLETE.json")))

  # 1. Validar fetch_attempts contra Arrow schema normativo
  tbl_att <- read_parquet(file.path(tmp_out, "fetch_attempts.parquet"), as_data_frame = FALSE)
  expected_att_schema <- schemas$fetch_attempts
  expect_equal(names(tbl_att$schema), names(expected_att_schema))
  for (fld_name in names(expected_att_schema)) {
    expect_equal(tbl_att$schema$GetFieldByName(fld_name)$type$name,
                 expected_att_schema$GetFieldByName(fld_name)$type$name,
                 info = paste("Campo:", fld_name))
  }

  # 2. Validar document_versions contra Arrow schema normativo
  tbl_ver <- read_parquet(file.path(tmp_out, "document_versions.parquet"), as_data_frame = FALSE)
  expected_ver_schema <- schemas$document_versions
  expect_equal(names(tbl_ver$schema), names(expected_ver_schema))
  for (fld_name in names(expected_ver_schema)) {
    expect_equal(tbl_ver$schema$GetFieldByName(fld_name)$type$name,
                 expected_ver_schema$GetFieldByName(fld_name)$type$name,
                 info = paste("Campo:", fld_name))
  }

  # 3. Validar unicidade estrita de PKs
  df_att <- as.data.frame(tbl_att)
  df_ver <- as.data.frame(tbl_ver)
  expect_equal(nrow(df_att), n_distinct(df_att$capture_id))
  expect_equal(nrow(df_ver), n_distinct(df_ver$version_id))

  # 4. Validar integridade do manifesto e marcador COMPLETE.json
  manifest_content <- fromJSON(pub_res$manifest_path)
  complete_content <- fromJSON(pub_res$complete_path)

  expect_equal(manifest_content$schema_version, "2.0.0")
  expect_equal(manifest_content$stage, "download")
  expect_equal(complete_content$manifest_file, "download_manifest.json")
  expect_equal(complete_content$manifest_sha256, pub_res$manifest_sha256)

  # Hash do manifesto deve ser de 64 hex minúsculos
  expect_match(complete_content$manifest_sha256, "^[0-9a-f]{64}$")
})
