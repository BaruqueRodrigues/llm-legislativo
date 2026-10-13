# tests/download/test_reconciliation_and_gh_closure.R
# Testes unitários para reconciliação estatística da cobertura e fechamento histórico (Gate GH / G2)
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/02_DOWNLOADS.md

suppressPackageStartupMessages({
  library(testthat)
  library(tibble)
  library(dplyr)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "download", "reconciliation.R"))

test_that("REC-01: Reconciliacao de cobertura calcula totais por casa e tipo com exatidao", {
  queue <- tibble(
    document_id = paste0("doc:", 1:6),
    house = c("camara", "camara", "camara", "senado", "senado", "senado"),
    normalized_kind = c("initial", "vote", "diary", "initial", "report", "amendment"),
    requested_url = paste0("https://example.com/", 1:6)
  )

  # Sucesso nos docs 1, 2, 4, 5; Falha no doc 3; Pendente doc 6
  attempts <- tibble(
    document_id = c("doc:1", "doc:2", "doc:3", "doc:4", "doc:5"),
    status = c("succeeded", "succeeded", "terminal_error", "succeeded", "succeeded"),
    error_code = c(NA, NA, "HTTP_404", NA, NA),
    error_message = c(NA, NA, "Pagina nao encontrada", NA, NA),
    requested_url = paste0("https://example.com/", 1:5)
  )

  # Docs 1 e 4 compartilham o mesmo hash binário
  versions <- tibble(
    document_id = c("doc:1", "doc:2", "doc:4", "doc:5"),
    file_sha256 = c("hash_compartilhado", "hash_2", "hash_compartilhado", "hash_5"),
    file_size_bytes = c(1000, 2000, 1000, 3000),
    integrity_status = c("verified", "verified", "verified", "verified")
  )

  rec <- compute_reconciliation_summary(queue, attempts, versions)

  expect_equal(rec$discovered_total, 6L)
  expect_equal(rec$retrieved_total, 4L)
  expect_equal(rec$failed_total, 1L)
  expect_equal(rec$pending_total, 1L)
  expect_equal(rec$coverage_status, "closed_with_gaps")

  # Conferir métricas de armazenamento
  expect_equal(rec$storage_metrics$total_versions_count, 4L)
  expect_equal(rec$storage_metrics$total_bytes_received, 7000)
  expect_equal(rec$storage_metrics$unique_blobs_count, 3L)
  expect_equal(rec$storage_metrics$storage_reuse_count, 1L)

  # Conferir estratificação por casa
  h_camara <- rec$by_house %>% filter(house == "camara")
  expect_equal(h_camara$discovered_count, 3L)
  expect_equal(h_camara$retrieved_count, 2L)
  expect_equal(h_camara$failed_count, 1L)

  h_senado <- rec$by_house %>% filter(house == "senado")
  expect_equal(h_senado$discovered_count, 3L)
  expect_equal(h_senado$retrieved_count, 2L)
  expect_equal(h_senado$pending_count, 1L)

  # Conferir proposta de URL alternativa para doc 3 falho
  expect_equal(length(rec$alternative_proposals), 1L)
  expect_equal(rec$alternative_proposals[[1]]$document_id, "doc:3")
  expect_equal(rec$alternative_proposals[[1]]$failure_code, "HTTP_404")
})

test_that("REC-02: Status completo_discovered quando 100% dos documentos sao obtidos", {
  queue <- tibble(
    document_id = paste0("doc:", 1:2),
    house = c("camara", "senado"),
    normalized_kind = c("initial", "initial"),
    requested_url = paste0("https://example.com/", 1:2)
  )

  attempts <- tibble(
    document_id = paste0("doc:", 1:2),
    status = c("succeeded", "succeeded"),
    error_code = c(NA, NA),
    error_message = c(NA, NA),
    requested_url = paste0("https://example.com/", 1:2)
  )

  versions <- tibble(
    document_id = paste0("doc:", 1:2),
    file_sha256 = c("h1", "h2"),
    file_size_bytes = c(500, 600),
    integrity_status = c("verified", "verified")
  )

  rec <- compute_reconciliation_summary(queue, attempts, versions)
  expect_equal(rec$coverage_status, "complete_discovered")
  expect_equal(rec$failed_total, 0L)
  expect_equal(rec$pending_total, 0L)
})

test_that("REC-03: versao previa verificada conta como obtida sem tentativa HTTP nova", {
  queue <- tibble(
    document_id = c("doc:capturado", "doc:idempotente"),
    house = c("camara", "camara"),
    normalized_kind = c("initial", "initial"),
    requested_url = c("https://example.com/new", "https://example.com/existing")
  )

  # Somente o documento novo teve tentativa nesta execução. A versão do outro
  # documento veio do cumulativo e foi reutilizada após validação do blob.
  attempts <- tibble(
    document_id = "doc:capturado",
    status = "succeeded",
    error_code = NA_character_,
    error_message = NA_character_,
    requested_url = "https://example.com/new"
  )
  versions <- tibble(
    document_id = c("doc:capturado", "doc:idempotente"),
    file_sha256 = c("hash-novo", "hash-existente"),
    file_size_bytes = c(1000, 2000),
    integrity_status = c("verified", "verified")
  )

  rec <- compute_reconciliation_summary(queue, attempts, versions)

  expect_equal(rec$discovered_total, 2L)
  expect_equal(rec$retrieved_total, 2L)
  expect_equal(rec$failed_total, 0L)
  expect_equal(rec$pending_total, 0L)
  expect_equal(rec$coverage_status, "complete_discovered")
})
