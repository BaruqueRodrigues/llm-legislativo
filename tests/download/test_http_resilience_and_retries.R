# tests/download/test_http_resilience_and_retries.R
# Testes unitários para resiliência HTTP, redirects, status de erro e retentativas
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/02_DOWNLOADS.md

suppressPackageStartupMessages({
  library(testthat)
  library(tibble)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "download", "fetcher.R"))

test_that("DL-01: Redirects preservam requested_url original e final_url de destino", {
  tmp_dir <- tempfile("dl_test_redirect")
  on.exit(unlink(tmp_dir, recursive = TRUE))

  pdf_bytes <- charToRaw("%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Count 1 /Kids [] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")

  mock_redirect <- function(requested_url, attempt_no, doc_row) {
    list(
      success = TRUE,
      status = 200L,
      final_url = "https://legis.senado.leg.br/dadosabertos/v3/documento/final_resolved.pdf",
      content_type = "application/pdf",
      declared_size = length(pdf_bytes),
      raw_bytes = pdf_bytes
    )
  }

  doc_row <- list(
    document_id = "senado:doc:processo:9999",
    requested_url = "http://legis.senado.leg.br/sdleg-getter/documento?dm=9999",
    house = "senado"
  )

  res <- fetch_document(doc_row, data_root = tmp_dir, mock_transport = mock_redirect)

  expect_true(res$success)
  expect_equal(length(res$attempt_records), 1)
  att <- res$attempt_records[[1]]

  expect_equal(att$requested_url, "http://legis.senado.leg.br/sdleg-getter/documento?dm=9999")
  expect_equal(att$final_url, "https://legis.senado.leg.br/dadosabertos/v3/documento/final_resolved.pdf")
  expect_false(att$requested_url == att$final_url)
  expect_equal(att$status, "succeeded")
  expect_equal(att$http_status, 200L)
})

test_that("DL-02: HTTP 404 gera status terminal_error e registra tentativa sem salvar blob", {
  tmp_dir <- tempfile("dl_test_404")
  on.exit(unlink(tmp_dir, recursive = TRUE))

  mock_404 <- function(requested_url, attempt_no, doc_row) {
    list(
      success = TRUE,
      status = 404L,
      final_url = requested_url,
      content_type = "text/html",
      declared_size = 0,
      raw_bytes = raw(0),
      error_message = "Documento nao encontrado no portal"
    )
  }

  doc_row <- list(
    document_id = "camara:doc:api:D404",
    requested_url = "https://dadosabertos.camara.leg.br/arquivos/inexistente.pdf",
    house = "camara"
  )

  res <- fetch_document(doc_row, data_root = tmp_dir, network_cfg = list(max_retries = 3), mock_transport = mock_404)

  expect_false(res$success)
  expect_null(res$version_record)
  expect_equal(length(res$attempt_records), 1) # Erro 404 é terminal, não deve repetir
  att <- res$attempt_records[[1]]

  expect_equal(att$status, "terminal_error")
  expect_equal(att$http_status, 404L)
  expect_equal(att$error_code, "HTTP_404")
  expect_true(is.na(att$file_sha256))
  expect_true(is.na(att$version_id))

  # Conferir que nenhum blob foi criado no disco
  expect_false(dir.exists(file.path(tmp_dir, "raw")))
})

test_that("DL-03: HTTP 429 respeita Retry-After e executa retentativas", {
  tmp_dir <- tempfile("dl_test_429")
  on.exit(unlink(tmp_dir, recursive = TRUE))

  pdf_bytes <- charToRaw("%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Count 1 /Kids [] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")

  calls <- 0L
  mock_429_then_ok <- function(requested_url, attempt_no, doc_row) {
    calls <<- calls + 1L
    if (attempt_no == 1) {
      list(
        success = TRUE,
        status = 429L,
        final_url = requested_url,
        headers = list("retry-after" = "1"),
        content_type = "text/plain",
        declared_size = 0,
        raw_bytes = raw(0),
        error_message = "Rate limit exceeded"
      )
    } else {
      list(
        success = TRUE,
        status = 200L,
        final_url = requested_url,
        content_type = "application/pdf",
        declared_size = length(pdf_bytes),
        raw_bytes = pdf_bytes
      )
    }
  }

  doc_row <- list(
    document_id = "camara:doc:api:D429",
    requested_url = "https://dadosabertos.camara.leg.br/api/v2/proposicoes/429/documento",
    house = "camara"
  )

  res <- fetch_document(doc_row, data_root = tmp_dir, network_cfg = list(max_retries = 3, backoff_base_seconds = 1.0), mock_transport = mock_429_then_ok)

  expect_true(res$success)
  expect_equal(length(res$attempt_records), 2)
  expect_equal(res$attempt_records[[1]]$status, "retryable_error")
  expect_equal(res$attempt_records[[1]]$http_status, 429L)
  expect_equal(res$attempt_records[[2]]$status, "succeeded")
  expect_equal(res$attempt_records[[2]]$http_status, 200L)
  expect_true(!is.null(res$version_record))
})

test_that("DL-04: HTTP 500 esgota retries e registra retryable_error_exhausted com tentativas", {
  tmp_dir <- tempfile("dl_test_500")
  on.exit(unlink(tmp_dir, recursive = TRUE))

  calls <- 0L
  mock_500_always <- function(requested_url, attempt_no, doc_row) {
    calls <<- calls + 1L
    list(
      success = TRUE,
      status = 500L,
      final_url = requested_url,
      headers = list(),
      content_type = "text/plain",
      declared_size = 0,
      raw_bytes = raw(0),
      error_message = "Internal Server Error"
    )
  }

  doc_row <- list(
    document_id = "senado:doc:processo:D500",
    requested_url = "http://legis.senado.leg.br/sdleg-getter/documento?dm=500",
    house = "senado"
  )

  res <- fetch_document(doc_row, data_root = tmp_dir, network_cfg = list(max_retries = 3, backoff_base_seconds = 1.0), mock_transport = mock_500_always)

  expect_false(res$success)
  expect_equal(length(res$attempt_records), 3)
  expect_equal(res$attempt_records[[1]]$status, "retryable_error")
  expect_equal(res$attempt_records[[2]]$status, "retryable_error")
  expect_equal(res$attempt_records[[3]]$status, "retryable_error_exhausted")
  expect_equal(res$attempt_records[[3]]$attempt_no, 3L)
  expect_equal(res$attempt_records[[3]]$error_code, "HTTP_500")
})
