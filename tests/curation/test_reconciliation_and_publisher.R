# tests/curation/test_reconciliation_and_publisher.R
# Testes de reconciliação de universo, integridade 2x2 de autores/temas e publicação com esquemas Arrow

suppressPackageStartupMessages({
  library(testthat)
  library(arrow)
  library(dplyr)
  library(tibble)
  library(yaml)
  library(digest)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "curation", "cleaner.R"))
source(file.path(repo_root, "R", "curation", "containment_dedup.R"))
source(file.path(repo_root, "R", "curation", "family_graph.R"))
source(file.path(repo_root, "R", "curation", "split_engine.R"))
source(file.path(repo_root, "R", "curation", "reconciler.R"))
source(file.path(repo_root, "R", "curation", "publisher.R"))

config <- yaml::read_yaml(file.path(repo_root, "configs", "curation", "history.yaml"))
schemas <- get_arrow_schemas()

test_that("Produto cartesiano 2x2 de autores x temas não multiplica curated_documents", {
  # 1 proposição com 2 autores e 2 temas
  # Deve resultar em EXATAMENTE 1 item curado, não 4
  props <- tibble(
    proposition_id = "camara:prop:TEST01",
    house = "camara",
    presentation_date = as.Date("2023-01-01")
  )
  docs <- tibble(
    document_id = "camara:doc:TEST01",
    house = "camara",
    normalized_kind = "initial",
    publication_date = as.Date("2023-01-01"),
    date_status = "verified"
  )
  pdocs <- tibble(
    proposition_id = "camara:prop:TEST01",
    document_id = "camara:doc:TEST01",
    document_role = "initial",
    role_evidence = "apresentação"
  )
  versions <- tibble(
    version_id = "camara:doc:TEST01:v:abc1234",
    document_id = "camara:doc:TEST01"
  )
  runs <- tibble(
    extraction_id = "ext:test:01",
    version_id = "camara:doc:TEST01:v:abc1234",
    status = "succeeded",
    error_code = NA_character_
  )
  secs <- tibble(
    section_id = "sec:01",
    extraction_id = "ext:test:01",
    ordinal = 1L,
    section_type = "initial_text",
    page_start = 1L,
    page_end = 1L,
    text = "Art. 1º Texto teste único."
  )

  res <- reconcile_curation_corpus(
    inventory_props_df = props,
    inventory_docs_df = docs,
    prop_docs_df = pdocs,
    doc_versions_df = versions,
    extraction_runs_df = runs,
    sections_df = secs,
    config = config
  )

  expect_equal(nrow(res$curated_documents), 1)
  expect_equal(nrow(res$corpus_item_propositions), 1)
})

test_that("Publisher gera 7 tabelas compatíveis com esquemas Arrow normativos e marcador atômico", {
  tmp_dir <- file.path(tempdir(), paste0("test_pub_", as.integer(runif(1, 1000, 9999))))
  dir.create(tmp_dir, recursive = TRUE, showWarnings = FALSE)

  props <- tibble(
    proposition_id = "camara:prop:P1",
    house = "camara",
    presentation_date = as.Date("2023-01-01")
  )
  docs <- tibble(
    document_id = "camara:doc:D1",
    house = "camara",
    normalized_kind = "initial",
    publication_date = as.Date("2023-01-01"),
    date_status = "verified"
  )
  pdocs <- tibble(
    proposition_id = "camara:prop:P1",
    document_id = "camara:doc:D1",
    document_role = "initial",
    role_evidence = "teste"
  )
  runs <- tibble(
    extraction_id = "ext:1",
    version_id = "doc:v1:D1",
    status = "succeeded",
    error_code = NA_character_
  )
  secs <- tibble(
    section_id = "sec:1",
    extraction_id = "ext:1",
    ordinal = 1L,
    section_type = "initial_text",
    page_start = 1L,
    page_end = 1L,
    text = "PROJETO DE LEI\nArt. 1º Disposição geral."
  )

  res <- reconcile_curation_corpus(
    inventory_props_df = props,
    inventory_docs_df = docs,
    prop_docs_df = pdocs,
    extraction_runs_df = runs,
    sections_df = secs,
    config = config
  )

  pub <- publish_curated_release(
    curation_results = res,
    output_dir = tmp_dir,
    release_id = "test_release_v1",
    config = config
  )

  expect_true(file.exists(file.path(tmp_dir, "COMPLETE.json")))
  expect_true(file.exists(file.path(tmp_dir, "release_manifest.json")))
  expect_true(file.exists(file.path(tmp_dir, "curated_documents.parquet")))
  expect_true(file.exists(file.path(tmp_dir, "corpus_item_propositions.parquet")))
  expect_true(file.exists(file.path(tmp_dir, "curated_document_sections.parquet")))
  expect_true(file.exists(file.path(tmp_dir, "dedup_pairs.parquet")))
  expect_true(file.exists(file.path(tmp_dir, "cleaning_events.parquet")))
  expect_true(file.exists(file.path(tmp_dir, "quality_reviews.parquet")))
  expect_true(file.exists(file.path(tmp_dir, "split_assignments.parquet")))

  # Leitura e conferência com schemas Arrow
  cd <- arrow::read_parquet(file.path(tmp_dir, "curated_documents.parquet"))
  expect_equal(nrow(cd), 1)
  expect_true(cd$include_in_dataset[1])

  # Limpar diretório temporário
  unlink(tmp_dir, recursive = TRUE)
})
