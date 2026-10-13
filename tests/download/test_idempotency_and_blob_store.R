# tests/download/test_idempotency_and_blob_store.R
# Testes unitários para armazenamento de blobs SHA-256, deduplicação física e preservação de vínculos entre casas
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0, Seção 1, 4 e 5) e docs/subagents/02_DOWNLOADS.md

suppressPackageStartupMessages({
  library(testthat)
  library(digest)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "download", "blob_store.R"))
source(file.path(repo_root, "R", "download", "fetcher.R"))

test_that("BLOB-01: Gravacao de blob imutavel com particionamento de 2 hexadecimais e SHA-256", {
  tmp_root <- tempfile("blob_test_1")
  on.exit(unlink(tmp_root, recursive = TRUE))

  test_bytes <- charToRaw("%PDF-1.4 Exemplo de documento oficial legislativo")
  expected_hash <- tolower(hash_bytes(test_bytes))
  expected_prefix <- substr(expected_hash, 1, 2)

  blob_info <- store_raw_blob(test_bytes, data_root = tmp_root)

  expect_equal(blob_info$sha256, expected_hash)
  expect_equal(blob_info$file_size_bytes, length(test_bytes))
  expect_false(blob_info$reused)
  expect_true(file.exists(blob_info$absolute_path))

  # Conferir caminho particionado
  expected_rel_path <- file.path("raw/sha256", expected_prefix, paste0(expected_hash, ".bin"))
  expect_equal(blob_info$raw_path, expected_rel_path)

  # Hash recalculado sobre o arquivo gravado
  disk_hash <- tolower(hash_file(blob_info$absolute_path))
  expect_equal(disk_hash, expected_hash)
})

test_that("BLOB-02: Reuso de armazenamento (mesmos bytes em Camara e Senado preservam vinculos distintos)", {
  tmp_root <- tempfile("blob_test_reused")
  on.exit(unlink(tmp_root, recursive = TRUE))

  # Matéria legislativa compartilhada (mesmo PDF que tramitou na Câmara e seguiu para o Senado)
  shared_bytes <- charToRaw("%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Count 1 /Kids [] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")
  shared_hash <- tolower(hash_bytes(shared_bytes))

  mock_shared <- function(requested_url, attempt_no, doc_row) {
    list(
      success = TRUE,
      status = 200L,
      final_url = requested_url,
      content_type = "application/pdf",
      declared_size = length(shared_bytes),
      raw_bytes = shared_bytes
    )
  }

  # 1. Download pela Câmara
  doc_camara <- list(
    document_id = "camara:doc:api:D_COMPARTILHADO",
    requested_url = "https://dadosabertos.camara.leg.br/arquivos/doc_compartilhado.pdf",
    house = "camara"
  )
  res_camara <- fetch_document(doc_camara, data_root = tmp_root, mock_transport = mock_shared)

  # 2. Download pelo Senado com os MESMOS bytes
  doc_senado <- list(
    document_id = "senado:doc:processo:P_COMPARTILHADO",
    requested_url = "http://legis.senado.leg.br/sdleg-getter/documento?dm=compartilhado",
    house = "senado"
  )
  res_senado <- fetch_document(doc_senado, data_root = tmp_root, mock_transport = mock_shared)

  expect_true(res_camara$success)
  expect_true(res_senado$success)

  # Mesma representação binária e mesmo raw_path
  expect_equal(res_camara$version_record$file_sha256, shared_hash)
  expect_equal(res_senado$version_record$file_sha256, shared_hash)
  expect_equal(res_camara$version_record$raw_path, res_senado$version_record$raw_path)

  # Identificadores de versão separados com namespace da respectiva entidade
  expect_equal(res_camara$version_record$version_id, paste0("camara:doc:api:D_COMPARTILHADO:v:", shared_hash))
  expect_equal(res_senado$version_record$version_id, paste0("senado:doc:processo:P_COMPARTILHADO:v:", shared_hash))
  expect_false(res_camara$version_record$version_id == res_senado$version_record$version_id)

  # Apenas UM arquivo físico no disco (reuso de armazenamento)
  expected_prefix <- substr(shared_hash, 1, 2)
  canonical_root <- normalizePath(tmp_root, winslash = "/", mustWork = TRUE)
  bin_dir <- file.path(canonical_root, "raw/sha256", expected_prefix)
  files_in_dir <- list.files(bin_dir, pattern = "\\.bin$")
  expect_equal(length(files_in_dir), 1L)
  expect_equal(files_in_dir, paste0(shared_hash, ".bin"))
})

test_that("BLOB-03: Verificacao de integridade de blob detecta corrupcao ou integridade", {
  tmp_root <- tempfile("blob_test_integ")
  on.exit(unlink(tmp_root, recursive = TRUE))

  data_bytes <- charToRaw("Conteudo valido")
  b <- store_raw_blob(data_bytes, data_root = tmp_root)

  # Verificação positiva
  expect_true(verify_blob_integrity(b$raw_path, data_root = tmp_root, expected_sha256 = b$sha256))

  # Se corromper os bytes no disco
  writeBin(charToRaw("Conteudo corrompido"), b$absolute_path)
  expect_false(verify_blob_integrity(b$raw_path, data_root = tmp_root, expected_sha256 = b$sha256))

  # Se o arquivo não existir
  expect_false(verify_blob_integrity("raw/sha256/xx/inexistente.bin", data_root = tmp_root))
})


test_that("BLOB-05: Subdiretório de blobs não pode escapar de DATA_ROOT", {
  tmp_root <- tempfile("blob_path_escape_")
  dir.create(tmp_root, recursive = TRUE)
  on.exit(unlink(tmp_root, recursive = TRUE))

  expect_error(
    store_raw_blob(charToRaw("fixture"), data_root = tmp_root, raw_blobs_subdir = "../outside"),
    "DATA_ROOT"
  )
})
