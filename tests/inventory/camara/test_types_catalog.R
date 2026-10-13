# tests/inventory/camara/test_types_catalog.R
# Testes unitários para catálogo e taxonomia de tipos da Câmara dos Deputados

suppressPackageStartupMessages({
  library(testthat)
  library(dplyr)
  library(arrow)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "inventory/camara/types_catalog.R"))

test_that("G1.CAMARA.1: Preservação estrita dos 544 registros de tipos sem redução a siglas", {
  types_df <- build_legislative_types()

  # Exatamente 544 registros
  expect_equal(nrow(types_df), 544)

  # Todas as PKs devem ser únicas e não nulas
  expect_equal(n_distinct(types_df$legislative_type_id), 544)
  expect_false(any(is.na(types_df$legislative_type_id)))
  expect_true(all(grepl("^camara:type:\\d+$", types_df$legislative_type_id)))
})

test_that("G1.CAMARA.2: Preservação de registros com sigla ausente (13 registros)", {
  types_df <- build_legislative_types()

  empty_sigla <- types_df %>% filter(is.na(type_code))
  expect_equal(nrow(empty_sigla), 13)

  # Nenhum registro foi descartado por falta de sigla
  expect_true(all(!is.na(empty_df <- empty_sigla$type_label)))
  expect_true(all(empty_sigla$entity_kind == "collection"))
  expect_true(all(grepl("^AGRUPAMENTO_", empty_sigla$normalized_family)))
})

test_that("G1.CAMARA.3: Distinção de códigos numéricos oficiais com mesma sigla", {
  types_df <- build_legislative_types()

  # Ofício (OF) possui 6 códigos distintos
  of_types <- types_df %>% filter(type_code == "OF")
  expect_equal(nrow(of_types), 6)
  expect_equal(n_distinct(of_types$legislative_type_id), 6)

  # Mensagem (MSC) possui 21 códigos distintos
  msc_types <- types_df %>% filter(type_code == "MSC")
  expect_equal(nrow(msc_types), 21)
  expect_equal(n_distinct(msc_types$legislative_type_id), 21)

  # Emenda na Comissão (EMC) possui 2 códigos distintos
  emc_types <- types_df %>% filter(type_code == "EMC")
  expect_equal(nrow(emc_types), 2)
  expect_equal(n_distinct(emc_types$legislative_type_id), 2)
})

test_that("G1.CAMARA.4: Mapeamento de famílias sem filtro redutor PL/2024", {
  types_df <- build_legislative_types()

  families <- unique(types_df$normalized_family)

  # Ampla cobertura de categorias legislativas
  expect_true("PL" %in% families)
  expect_true("PLP" %in% families)
  expect_true("PEC" %in% families)
  expect_true("MPV" %in% families)
  expect_true("EMENDA" %in% families)
  expect_true("SUBEMENDA" %in% families)
  expect_true("SUBSTITUTIVO" %in% families)
  expect_true("PARECER" %in% families)
  expect_true("VOTO" %in% families)
  expect_true("REDACAO_FINAL" %in% families)
  expect_true("OFICIO" %in% families)
  expect_true("MENSAGEM" %in% families)
  expect_true("RECURSO" %in% families)

  # Compatibilidade com o esquema Arrow legislative_types
  schemas <- get_arrow_schemas()
  target_schema <- schemas$legislative_types
  tab <- arrow_table(types_df, schema = target_schema)
  expect_equal(tab$num_rows, 544)
})
