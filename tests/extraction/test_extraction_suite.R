# tests/extraction/test_extraction_suite.R
# Suite de testes unitários para a Frente 03 — Extração Nativa e OCR Apple Vision
# Cobertura: Preflight, PDFKit Nativo, Apple Vision OCR, Documentos Mistos, Corrompidos,
# Detecção de Seções com Offsets Unicode, Benchmark de Latência/Qualidade e Publicação Parquet Arrow

suppressPackageStartupMessages({
  library(testthat)
  library(arrow)
  library(dplyr)
  library(tibble)
  library(jsonlite)
  library(digest)
  library(bit64)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "extraction", "preflight.R"))
source(file.path(repo_root, "R", "extraction", "pdf_extractor.R"))
source(file.path(repo_root, "R", "extraction", "section_parser.R"))
source(file.path(repo_root, "R", "extraction", "quality_auditor.R"))
source(file.path(repo_root, "R", "extraction", "publisher.R"))

fixtures_dir <- file.path(repo_root, "tests", "extraction", "fixtures")

# -----------------------------------------------------------------------------
# 1. Preflight do Ambiente macOS e Apple Vision
# -----------------------------------------------------------------------------
test_that("G3.1: Preflight valida ambiente macOS, PDFKit e Vision com pt-BR", {
  preflight <- run_extraction_preflight(repo_root)

  expect_true(preflight$preflight_passed)
  expect_true(file.exists(preflight$binary_path))
  expect_equal(nchar(preflight$helper_source_sha256), 64)
  expect_equal(nchar(preflight$helper_binary_sha256), 64)

  # Validação de suporte a pt-BR
  expect_true(preflight$details$supports_pt_br)
  expect_true(preflight$details$vision_available)
  expect_gte(preflight$details$vision_default_revision, 3L)

  # Tool versions JSON válido
  tv <- jsonlite::fromJSON(preflight$tool_versions_json)
  expect_true(tv$vision_supports_pt_br)
  expect_match(tv$macos_version, "Version")
})

# -----------------------------------------------------------------------------
# 2. Extração Nativa Digital com PDFKit
# -----------------------------------------------------------------------------
test_that("G3.2: PDF digital é extraído nativamente via PDFKit sem invocar OCR desnecessário", {
  pdf_path <- file.path(fixtures_dir, "native_digital.pdf")
  skip_if_not(file.exists(pdf_path))

  doc <- extract_document(pdf_path, "test:doc:native_01", mode = "auto")

  expect_equal(doc$status, "succeeded")
  expect_equal(nrow(doc$pages), 2L)

  # Ambas as páginas devem usar método native e motor pdfkit
  expect_true(all(doc$pages$method == "native"))
  expect_true(all(doc$pages$engine == "pdfkit"))

  # Métricas de qualidade
  expect_true(all(doc$pages$printable_ratio >= 0.95))
  expect_true(all(doc$pages$replacement_char_ratio <= 0.01))
  expect_true(all(doc$pages$character_count >= 50L))
  expect_true(all(doc$pages$quality_status == "pass"))

  # Latência nativa deve ser sub-milissegundo por página
  expect_lt(mean(doc$pages$elapsed_ms), 50.0)

  # Conteúdo textual esperado preservado
  expect_match(doc$pages$raw_text[1], "PROJETO DE LEI")
  expect_match(doc$pages$raw_text[1], "Art\\. 1º")
  expect_match(doc$pages$raw_text[2], "JUSTIFICAÇÃO")
})

# -----------------------------------------------------------------------------
# 3. OCR Seletivo com Apple Vision em Página Escaneada
# -----------------------------------------------------------------------------
test_that("G3.3: Página escaneada ativa fallback seletivo para Apple Vision em pt-BR", {
  pdf_path <- file.path(fixtures_dir, "scanned_image.pdf")
  skip_if_not(file.exists(pdf_path))

  doc <- extract_document(pdf_path, "test:doc:scanned_01", mode = "auto")

  expect_equal(doc$status, "succeeded")
  expect_equal(nrow(doc$pages), 1L)

  # Método deve ser OCR e motor Apple Vision
  expect_equal(doc$pages$method[1], "ocr")
  expect_equal(doc$pages$engine[1], "apple_vision")
  expect_match(doc$pages$recognition_languages_json[1], "pt-BR")
  expect_true(doc$pages$uses_language_correction[1])
  expect_equal(doc$pages$image_area_ratio[1], 1.0)
  expect_gte(doc$pages$ocr_confidence[1], 0.3)

  # Texto reconhecido contém termos jurídicos fundamentais
  raw_txt <- doc$pages$raw_text[1]
  expect_match(raw_txt, "PARECER")
  expect_match(raw_txt, "RELATÓRIO")
  expect_match(raw_txt, "VOTO DO RELATOR")
})

# -----------------------------------------------------------------------------
# 4. Documento Misto e Prevenção de Duplicação
# -----------------------------------------------------------------------------
test_that("G3.4: Documento misto extrai P1 nativa e P2 OCR sem duplicar conteúdo", {
  pdf_path <- file.path(fixtures_dir, "mixed_document.pdf")
  skip_if_not(file.exists(pdf_path))

  doc <- extract_document(pdf_path, "test:doc:mixed_01", mode = "auto")

  expect_equal(doc$status, "succeeded")
  expect_equal(nrow(doc$pages), 2L)

  # P1 deve ser nativa e P2 deve ser OCR
  expect_equal(doc$pages$method[1], "native")
  expect_equal(doc$pages$engine[1], "pdfkit")
  expect_equal(doc$pages$method[2], "ocr")
  expect_equal(doc$pages$engine[2], "apple_vision")

  # Conteúdos distintos e não duplicados
  expect_match(doc$pages$raw_text[1], "EMENDA MODIFICATIVA")
  expect_match(doc$pages$raw_text[2], "ANEXO ÚNICO")
  expect_false(grepl("ANEXO ÚNICO", doc$pages$raw_text[1]))
})

# -----------------------------------------------------------------------------
# 5. Tratamento Resiliente de PDFs Corrompidos e Layout em Colunas
# -----------------------------------------------------------------------------
test_that("G3.5: PDF corrompido falha graciosamente e layout em colunas preserva ordem", {
  # Corrompido
  corrupt_path <- file.path(fixtures_dir, "corrupt.pdf")
  skip_if_not(file.exists(corrupt_path))

  doc_corrupt <- extract_document(corrupt_path, "test:doc:corrupt_01")
  expect_equal(doc_corrupt$status, "failed")
  expect_equal(doc_corrupt$run$status, "failed")
  expect_equal(doc_corrupt$run$error_code, "pdf_open_failed")
  expect_equal(nrow(doc_corrupt$pages), 0L)

  # Duas Colunas
  cols_path <- file.path(fixtures_dir, "two_columns.pdf")
  skip_if_not(file.exists(cols_path))

  doc_cols <- extract_document(cols_path, "test:doc:cols_01", mode = "auto")
  expect_equal(doc_cols$status, "succeeded")
  cols_text <- doc_cols$pages$raw_text[1]

  # Ordem de leitura: Coluna 1 antes de Coluna 2
  pos_col1 <- regexpr("DIARIO DO CONGRESSO|DIÁRIO DO CONGRESSO", cols_text)[1]
  pos_col2 <- regexpr("SUMARIO DA SESSÁO|SUMÁRIO DA SESSÃO", cols_text)[1]
  expect_gt(pos_col1, 0)
  expect_gt(pos_col2, 0)
  expect_lt(pos_col1, pos_col2)
})

# -----------------------------------------------------------------------------
# 6. Segmentação Estruturada de Seções com Offsets Unicode [start, end)
# -----------------------------------------------------------------------------
test_that("G3.6: Segmentador identifica seções legislativas e valida offsets em delimitador \\n\\f\\n", {
  pdf_path <- file.path(fixtures_dir, "native_digital.pdf")
  doc <- extract_document(pdf_path, "test:doc:sections_01", mode = "auto")
  secs <- parse_document_sections(doc$run$extraction_id, doc$pages)

  expect_gte(nrow(secs), 2L)

  # Verificar tipos normativos
  types_found <- unique(secs$section_type)
  expect_true(any(c("initial_text", "justification") %in% types_found))

  # Reconstrução do texto delimitado por \n\f\n
  full_concat <- paste(doc$pages$raw_text, collapse = "\n\f\n")

  for (i in seq_len(nrow(secs))) {
    s <- secs[i, ]
    # 0-based code point offsets [start_char, end_char)
    # Em R 1-based: substr(start_char + 1, end_char)
    expected_substr <- substr(full_concat, as.numeric(s$start_char) + 1, as.numeric(s$end_char))
    expect_equal(s$text, expected_substr)
  }

  # Ordinal sequencial 1..N
  expect_equal(secs$ordinal, seq_len(nrow(secs)))
  # Referential integrity
  expect_true(all(secs$extraction_id == doc$run$extraction_id))
})

# -----------------------------------------------------------------------------
# 7. Benchmark de Latência, Memória e Acurácia (CER/WER)
# -----------------------------------------------------------------------------
test_that("G3.7: Benchmark comparativo fast vs accurate mede latências, memória e qualidade", {
  bench <- run_extraction_benchmark(
    test_fixtures = c("tests/extraction/fixtures/scanned_image.pdf")
  )

  reviews <- bench$quality_reviews
  expect_gte(nrow(reviews), 1L)

  rev <- reviews[1, ]
  expect_match(rev$notes, "Fast:")
  expect_match(rev$notes, "Accurate:")
  expect_match(rev$notes, "Speedup:")

  # CER deve ser baixo (acurácia > 95% no texto escaneado limpo)
  expect_false(is.na(rev$cer))
  expect_lt(rev$cer, 0.05)
  expect_equal(rev$result, "pass")
})

# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# 9. Proveniência de benchmark e integridade de caminho relativo
# -----------------------------------------------------------------------------
test_that("G3.9: Reviews de benchmark preservam execution_id original", {
  bench <- run_extraction_benchmark(test_fixtures = c("tests/extraction/fixtures/scanned_image.pdf"))
  expect_true(all(bench$quality_reviews$extraction_id %in% vapply(bench$results, function(doc) doc$run$extraction_id, character(1))))
  for (i in seq_len(nrow(bench$quality_reviews))) {
    review <- bench$quality_reviews[i, ]
    doc <- bench$results[["scanned_image.pdf"]]
    expect_equal(review$extraction_id, doc$run$extraction_id)
    expect_true(review$page_index %in% doc$pages$page_index)
  }
})

# 8. Publicação Arrow Parquet e Marcador COMPLETE.json
# -----------------------------------------------------------------------------
test_that("G3.8: Publicador Arrow valida integridade referencial, esquemas e COMPLETE.json", {
  pdf_path <- file.path(fixtures_dir, "native_digital.pdf")
  doc <- extract_document(pdf_path, "test:doc:pub_01", mode = "auto")
  secs <- parse_document_sections(doc$run$extraction_id, doc$pages)

  dummy_reviews <- tibble(
    review_id = paste0(doc$run$extraction_id, ":rev:1"),
    extraction_id = doc$run$extraction_id,
    corpus_item_id = NA_character_,
    page_index = 1L,
    reviewer = "testthat_suite",
    sample_seed = 42L,
    stratum = "unit_test",
    result = "pass",
    cer = 0.0,
    wer = 0.0,
    reviewed_at = as.POSIXct(Sys.time(), tz = "UTC"),
    notes = "Validacao formal de teste unitario"
  )

  data_root <- normalizePath(Sys.getenv("DATA_ROOT"), winslash = "/", mustWork = TRUE)
  test_run_dir <- file.path(data_root, "staging", "extraction", paste0("unit_test_", basename(tempfile())))
  pub <- publish_extraction_tables(
    extraction_runs_df = doc$run,
    pages_df = doc$pages,
    sections_df = secs,
    quality_reviews_df = dummy_reviews,
    run_id = "unit_test_run",
    output_dir = test_run_dir
  )

  expect_true(dir.exists(test_run_dir))
  expect_true(file.exists(file.path(test_run_dir, "COMPLETE.json")))
  expect_true(file.exists(file.path(test_run_dir, "extraction_manifest.json")))
  expect_true(file.exists(file.path(test_run_dir, "extraction_runs.parquet")))
  expect_true(file.exists(file.path(test_run_dir, "pages.parquet")))
  expect_true(file.exists(file.path(test_run_dir, "sections.parquet")))
  expect_true(file.exists(file.path(test_run_dir, "quality_reviews.parquet")))

  # Validador oficial
  val <- validate_extraction_publication(test_run_dir)
  expect_true(val$valid)
  manifest <- jsonlite::fromJSON(file.path(test_run_dir, "extraction_manifest.json"))
  expect_match(manifest$files$pages$path, "^staging/extraction/unit_test_")
  expect_equal(
    normalizePath(file.path(data_root, manifest$files$pages$path), winslash = "/"),
    normalizePath(file.path(test_run_dir, "pages.parquet"), winslash = "/")
  )

  # Validação estrita de esquemas lendo de volta os arquivos Parquet
  schemas <- get_arrow_schemas()
  tab_runs <- arrow::read_parquet(file.path(test_run_dir, "extraction_runs.parquet"), as_data_frame = FALSE)
  tab_pages <- arrow::read_parquet(file.path(test_run_dir, "pages.parquet"), as_data_frame = FALSE)
  tab_secs <- arrow::read_parquet(file.path(test_run_dir, "sections.parquet"), as_data_frame = FALSE)
  tab_revs <- arrow::read_parquet(file.path(test_run_dir, "quality_reviews.parquet"), as_data_frame = FALSE)

  expect_equal(names(tab_runs$schema), names(schemas$extraction_runs))
  expect_equal(names(tab_pages$schema), names(schemas$pages))
  expect_equal(names(tab_secs$schema), names(schemas$sections))
  expect_equal(names(tab_revs$schema), names(schemas$quality_reviews))
})
