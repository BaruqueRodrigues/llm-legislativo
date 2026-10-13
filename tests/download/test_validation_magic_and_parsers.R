# tests/download/test_validation_magic_and_parsers.R
# Testes unitários para validação de conteúdo, falsos positivos HTML 200, arquivos truncados e contagem de páginas
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/02_DOWNLOADS.md

suppressPackageStartupMessages({
  library(testthat)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "download", "validator.R"))
source(file.path(repo_root, "R", "download", "fetcher.R"))

test_that("VAL-01: HTML 200 falso positivo e rejeitado e classificado como erro", {
  # Simula um portal que responde status HTTP 200, mas o corpo é um HTML com mensagem de erro
  html_error_payload <- charToRaw("<!DOCTYPE html><html><head><title>Erro</title></head><body><h1>Erro 404</h1><p>Proposicao nao encontrada na base oficial.</p></body></html>")

  val <- validate_download_content(
    raw_bytes = html_error_payload,
    declared_media_type = "text/html",
    is_binary_expected = TRUE
  )

  expect_false(val$valid)
  expect_equal(val$detected_media_type, "text/html")
  expect_equal(val$error_code, "HTML_200_FALSE_POSITIVE")
  expect_equal(val$integrity_status, "quarantined")
  expect_true(is.na(val$page_count))

  # Testar através do fetch_document
  tmp_dir <- tempfile("val_html200")
  on.exit(unlink(tmp_dir, recursive = TRUE))

  mock_html200 <- function(requested_url, attempt_no, doc_row) {
    list(
      success = TRUE,
      status = 200L, # HTTP 200 retornado pelo servidor!
      final_url = requested_url,
      content_type = "text/html",
      declared_size = length(html_error_payload),
      raw_bytes = html_error_payload
    )
  }

  doc_row <- list(
    document_id = "camara:doc:portal:2422083",
    requested_url = "https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=2422083",
    house = "camara"
  )

  res <- fetch_document(doc_row, data_root = tmp_dir, mock_transport = mock_html200)

  expect_false(res$success)
  expect_null(res$version_record)
  expect_equal(length(res$attempt_records), 1)
  expect_equal(res$attempt_records[[1]]$status, "terminal_error")
  expect_equal(res$attempt_records[[1]]$error_code, "HTML_200_FALSE_POSITIVE")
  expect_equal(res$attempt_records[[1]]$http_status, 200L) # Status HTTP 200 registrado fielmente
})

test_that("VAL-01b: verificação de segurança do Senado fica explícita como HTML 200", {
  challenge_payload <- charToRaw(paste0(
    "<!DOCTYPE html><meta name=\"viewport\" content=\"width=device-width\">",
    "<title>Verificação de segurança — Senado Federal</title>"
  ))
  val <- validate_download_content(
    raw_bytes = challenge_payload,
    declared_media_type = "text/html",
    is_binary_expected = TRUE
  )

  expect_false(val$valid)
  expect_equal(val$error_code, "HTML_200_FALSE_POSITIVE")
  expect_match(val$error_message, "verificação de segurança do Senado Federal")
})

test_that("VAL-02: Arquivo truncado e detectado e rejeitado", {
  full_payload <- charToRaw("%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Count 1 /Kids [] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")
  declared_len <- length(full_payload)
  truncated_bytes <- full_payload[1:30]

  val <- validate_download_content(
    raw_bytes = truncated_bytes,
    declared_size_bytes = declared_len,
    is_binary_expected = TRUE
  )

  expect_false(val$valid)
  expect_equal(val$error_code, "TRUNCATED_FILE")
  expect_equal(val$integrity_status, "quarantined")
})

test_that("VAL-03: Arquivo de zero bytes e detectado e rejeitado", {
  val <- validate_download_content(
    raw_bytes = raw(0),
    declared_size_bytes = 0,
    is_binary_expected = TRUE
  )

  expect_false(val$valid)
  expect_equal(val$error_code, "EMPTY_FILE")
  expect_equal(val$integrity_status, "quarantined")
})

test_that("VAL-04: PDF valido com magic %PDF e contagem de paginas > 0", {
  pdf_payload <- charToRaw("%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Count 4 /Kids [] >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")

  val <- validate_download_content(
    raw_bytes = pdf_payload,
    declared_media_type = "application/pdf",
    is_binary_expected = TRUE
  )

  expect_true(val$valid)
  expect_equal(val$detected_media_type, "application/pdf")
  expect_equal(val$page_count, 4L)
  expect_equal(val$integrity_status, "verified")
})

test_that("VAL-05: Deteccao de tipos de midia (MIME) por magic numbers", {
  # RTF
  rtf_raw <- charToRaw("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}}")
  expect_equal(detect_media_type(rtf_raw), "application/rtf")

  # DOCX / OpenXML (PK\x03\x04)
  docx_raw <- as.raw(c(0x50, 0x4b, 0x03, 0x04, 0x14, 0x00))
  expect_equal(detect_media_type(docx_raw), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

  # DOC legado CFBF (\xd0\xcf\x11\xe0)
  doc_raw <- as.raw(c(0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1))
  expect_equal(detect_media_type(doc_raw), "application/msword")

  # XML
  xml_raw <- charToRaw("<?xml version=\"1.0\" encoding=\"UTF-8\"?><root></root>")
  expect_equal(detect_media_type(xml_raw), "application/xml")

  # Plain text
  txt_raw <- charToRaw("Texto legislativo em formato texto puro.")
  expect_equal(detect_media_type(txt_raw), "text/plain")
})
