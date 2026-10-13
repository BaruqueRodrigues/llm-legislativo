# tests/download/test_queue_and_leases.R
# Testes unitários para a fila normalizada, estratificação amostral, leases e idempotência
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/02_DOWNLOADS.md

suppressPackageStartupMessages({
  library(testthat)
  library(dplyr)
  library(tibble)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "download", "queue.R"))
source(file.path(repo_root, "R", "download", "blob_store.R"))

make_inventory_fixture <- function(house, kinds) {
  directory <- tempfile(paste0("inventory_", house, "_"))
  dir.create(directory, recursive = TRUE)
  docs <- tibble(
    document_id = paste0(house, ":doc:", seq_along(kinds)),
    identity_url = paste0("https://example.invalid/", house, "/", seq_along(kinds)),
    source_uri = paste0("fixture:", house, ":", seq_along(kinds)),
    source_namespace = house,
    normalized_kind = kinds,
    publication_date = as.Date("2024-01-01")
  )
  arrow::write_parquet(docs, file.path(directory, "documents.parquet"))
  directory
}

test_that("QUEUE-01: Fila normalizada carrega documentos de ambas as casas e multiplos tipos", {
  camara_dir <- make_inventory_fixture("camara", c("initial", "amendment", "report"))
  senado_dir <- make_inventory_fixture("senado", c("initial", "opinion", "diary"))
  on.exit(unlink(c(camara_dir, senado_dir), recursive = TRUE))
  queue <- build_download_queue(data_root = Sys.getenv("DATA_ROOT"), camara_dir = camara_dir, senado_dir = senado_dir, is_sample = FALSE)

  expect_true(nrow(queue) > 0)
  expect_true("camara" %in% queue$house)
  expect_true("senado" %in% queue$house)

  # Verificar presença de múltiplos tipos legislativos
  kinds <- unique(queue$normalized_kind)
  expect_true("initial" %in% kinds)
  expect_true("report" %in% kinds || "opinion" %in% kinds || "diary" %in% kinds || "annals" %in% kinds)

  # Chaves únicas
  expect_equal(nrow(queue), n_distinct(queue$document_id))
})

test_that("QUEUE-02: Amostra estratificada preserva diversidade de casas e tipos", {
  camara_dir <- make_inventory_fixture("camara", c("initial", "amendment", "report", "diary"))
  senado_dir <- make_inventory_fixture("senado", c("initial", "opinion", "annals", "amendment"))
  on.exit(unlink(c(camara_dir, senado_dir), recursive = TRUE))
  sample_queue <- build_download_queue(data_root = Sys.getenv("DATA_ROOT"), camara_dir = camara_dir, senado_dir = senado_dir, is_sample = TRUE, sample_size_per_house = 4)

  expect_true(nrow(sample_queue) > 0)
  expect_true(nrow(sample_queue) <= 8)
  expect_true(all(c("camara", "senado") %in% sample_queue$house))

  # Ambas as casas têm múltiplos tipos representados
  camara_kinds <- unique(sample_queue$normalized_kind[sample_queue$house == "camara"])
  senado_kinds <- unique(sample_queue$normalized_kind[sample_queue$house == "senado"])

  expect_true(length(camara_kinds) >= 2)
  expect_true(length(senado_kinds) >= 2)
})

test_that("QUEUE-03: Gestao de leases atomicos e concorrencia entre workers", {
  tmp_leases <- tempfile("test_leases")
  on.exit(unlink(tmp_leases, recursive = TRUE))

  doc_id <- "camara:doc:api:TESTE_LEASE"

  # 1. Primeiro worker adquire o lease
  l1 <- acquire_lease(doc_id, tmp_leases, timeout_seconds = 600)
  expect_true(l1)

  # 2. Segundo worker tenta adquirir o mesmo lease e é bloqueado
  l2 <- acquire_lease(doc_id, tmp_leases, timeout_seconds = 600)
  expect_false(l2)

  # 3. Primeiro worker libera o lease
  release_lease(doc_id, tmp_leases)

  # 4. Agora o segundo worker consegue adquirir
  l3 <- acquire_lease(doc_id, tmp_leases, timeout_seconds = 600)
  expect_true(l3)

  release_lease(doc_id, tmp_leases)
})

test_that("QUEUE-04: Lease expirado e reincorporado (recuperacao de abandono)", {
  tmp_leases <- tempfile("test_lease_expiry")
  on.exit(unlink(tmp_leases, recursive = TRUE))

  doc_id <- "senado:doc:processo:EXPIRED"

  # Adquire lease com timeout de 1 segundo
  acquire_lease(doc_id, tmp_leases, timeout_seconds = 1)

  # Forçar mtime no passado
  lease_file <- file.path(tmp_leases, paste0(hash_string(doc_id), ".lease"))
  Sys.setFileTime(lease_file, Sys.time() - 10)

  # Limpeza de leases expirados
  cleaned <- clean_expired_leases(tmp_leases, timeout_seconds = 2)
  expect_equal(cleaned, 1L)
  expect_false(file.exists(lease_file))

  # Agora novo worker pode adquirir normalmente
  expect_true(acquire_lease(doc_id, tmp_leases, timeout_seconds = 600))
  release_lease(doc_id, tmp_leases)
})

test_that("QUEUE-05: Idempotencia nao re-baixa documento integro ja capturado", {
  tmp_root <- tempfile("test_idempotent_queue")
  on.exit(unlink(tmp_root, recursive = TRUE))

  doc_id <- "camara:doc:api:IDEM_DOC"
  bytes <- charToRaw("%PDF-1.4 Mock de documento")
  h <- hash_bytes(bytes)
  b <- store_raw_blob(bytes, data_root = tmp_root)

  existing_df <- tibble(
    document_id = doc_id,
    version_id = paste0(doc_id, ":v:", h),
    file_sha256 = h,
    raw_path = b$raw_path,
    integrity_status = "verified"
  )

  # Deve detectar como já concluído
  expect_true(is_document_completed(doc_id, existing_df, data_root = tmp_root))

  # Se o blob tiver sido deletado ou corrompido, não deve ser considerado concluído
  unlink(b$absolute_path)
  expect_false(is_document_completed(doc_id, existing_df, data_root = tmp_root))
})


test_that("QUEUE-06: DATA_ROOT interno ao checkout é rejeitado", {
  expect_error(find_inventory_dirs(file.path(repo_root, "data")), "DATA_ROOT")
})
