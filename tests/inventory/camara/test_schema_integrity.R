# tests/inventory/camara/test_schema_integrity.R
# Testes formais de integridade Arrow, gravação Parquet e publicação do manifesto da Câmara

suppressPackageStartupMessages({
  library(testthat)
  library(dplyr)
  library(arrow)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "inventory/camara/inventory_engine.R"))

test_that("G1.CAMARA.18: Geração e validação de todas as tabelas em Parquet conforme 31 esquemas normativos", {
  temp_out <- file.path(tempdir(), "test_camara_inventory_schema")
  dir.create(temp_out, recursive = TRUE, showWarnings = FALSE)

  res <- run_camara_inventory(output_dir = temp_out, is_sample = TRUE)
  schemas <- get_arrow_schemas()

  # Verificar cada arquivo Parquet gerado
  for (tname in names(res$written_files)) {
    finfo <- res$written_files[[tname]]
    expect_true(file.exists(finfo$path), info = paste("Arquivo ausente:", finfo$path))
    expect_true(finfo$size_bytes > 0, info = paste("Tamanho zero:", finfo$path))

    # Leitura via Arrow e conferência de esquema
    tab <- read_parquet(finfo$path, as_data_frame = FALSE)
    expected_schema <- schemas[[tname]]

    expect_equal(names(tab$schema), names(expected_schema),
                 info = paste("Colunas divergentes na tabela:", tname))
  }
})

test_that("G1.CAMARA.19: Unicidade e não-nulidade estrita de Primary Keys (PKs)", {
  temp_out <- file.path(tempdir(), "test_camara_inventory_pk")
  dir.create(temp_out, recursive = TRUE, showWarnings = FALSE)

  res <- run_camara_inventory(output_dir = temp_out, is_sample = TRUE)
  tables <- res$tables

  # propositions: PK proposition_id
  expect_equal(n_distinct(tables$propositions$proposition_id), nrow(tables$propositions))
  expect_false(any(is.na(tables$propositions$proposition_id)))

  # authors: PK author_id
  expect_equal(n_distinct(tables$authors$author_id), nrow(tables$authors))
  expect_false(any(is.na(tables$authors$author_id)))

  # A fixture é sintética e contém somente seu tipo explicitamente rotulado.
  expect_equal(n_distinct(tables$legislative_types$legislative_type_id), 1)
  expect_true(all(tables$legislative_types$source_namespace == "sample_fixture"))
  expect_false(any(is.na(tables$legislative_types$legislative_type_id)))

  # coverage_segments: PK segment_id
  expect_equal(n_distinct(tables$coverage_segments$segment_id), nrow(tables$coverage_segments))
  expect_false(any(is.na(tables$coverage_segments$segment_id)))

  # documents: PK document_id
  expect_equal(n_distinct(tables$documents$document_id), nrow(tables$documents))
  expect_false(any(is.na(tables$documents$document_id)))

  # source_collections: PK collection_id
  expect_equal(n_distinct(tables$source_collections$collection_id), nrow(tables$source_collections))

  # use_evidence: PK evidence_id
  expect_equal(n_distinct(tables$use_evidence$evidence_id), nrow(tables$use_evidence))
})

test_that("G1.CAMARA.20: Validação do manifesto de publicação e marcador COMPLETE.json", {
  temp_out <- file.path(tempdir(), "test_camara_inventory_manifest")
  dir.create(temp_out, recursive = TRUE, showWarnings = FALSE)

  res <- run_camara_inventory(output_dir = temp_out, is_sample = TRUE)

  manifest_file <- file.path(temp_out, "inventory_camara_manifest.json")
  complete_file <- file.path(temp_out, "COMPLETE.json")

  expect_true(file.exists(manifest_file))
  expect_true(file.exists(complete_file))

  # COMPLETE.json deve apontar exatamente para o hash SHA-256 do manifesto
  manifest_sha <- hash_file(manifest_file)
  complete_data <- jsonlite::fromJSON(complete_file)

  expect_equal(complete_data$manifest_file, "inventory_camara_manifest.json")
  expect_equal(complete_data$manifest_sha256, manifest_sha)

  # Resumo do manifesto
  manifest_data <- jsonlite::fromJSON(manifest_file)
  expect_equal(manifest_data$stage, "inventory_camara")
  expect_equal(manifest_data$house, "camara")
  expect_equal(manifest_data$summary$legislative_types_count, 1)
  expect_equal(manifest_data$mode, "sample_fixture")
  expect_equal(manifest_data$status, "sample_only")
  expect_false(manifest_data$summary$inventory_complete)
  expect_match(manifest_data$summary$reason, "sintética")
})
