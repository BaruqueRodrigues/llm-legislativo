# tests/inventory/camara/test_historical_collections_and_gaps.R
# Testes unitários para lacunas históricas (1936-1944), evento 2026 sobre projeto 1988, undated e coleções

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
source(file.path(repo_root, "R", "inventory/camara/sources_discovery.R"))
source(file.path(repo_root, "R", "inventory/camara/historical_collections.R"))
source(file.path(repo_root, "R", "inventory/camara/api_client.R"))

test_that("Segmentos anuais não consultados permanecem pendentes", {
  segs_df <- build_coverage_segments(start_year=1934,end_year=1945)
  years <- segs_df %>% filter(year %in% 1936:1944, collection_id == "camara:col:api_v2")
  expect_equal(nrow(years), 9L * 4L)
  expect_true(all(years$inventory_status == "pending"))
  expect_true(all(years$coverage_status == "pending"))
  expect_true(all(is.na(years$exhaustion_evidence)))
  expect_true(all(grepl("não consultado", years$gap_reason)))
})

test_that("G1.CAMARA.14: Separação de eixos temporais - evento 2026 sobre projeto de 1988", {
  # Simulação de evento de tramitação em 2026 para uma PEC apresentada em 1988
  sample_pec <- list(
    id = "1001988", siglaTipo = "PEC", codTipo = "136", descricaoTipo = "Proposta de Emenda à Constituição",
    numero = 101, ano = 1988, dataApresentacao = "1988-10-10T16:00",
    ementa = "Transição tributária constituinte", uri = "https://mock.api/proposicoes/1001988"
  )
  prop_df <- parse_camara_propositions(list(sample_pec), "snap_test")

  # Tramitação ocorrida em 2026
  sample_tram_2026 <- list(
    list(sequencia = 2, siglaOrgao = "CCJC", dataHora = "2026-03-01T11:00", descricaoTramitacao = "Desarquivamento em 2026")
  )
  phases_df <- parse_camara_tramitacoes(sample_tram_2026, "camara:prop:1001988", "snap_test")

  # Verificação estrita: o ano da proposição continua 1988
  expect_equal(prop_df$numbering_year, 1988L)
  expect_equal(as.character(prop_df$presentation_date), "1988-10-10")

  # A fase de tramitação registra a data de 2026 separadamente
  expect_equal(as.character(phases_df$date_start), "2026-03-01")
  expect_equal(phases_df$numbering_year, 2026L)

  # Não há contaminação da proposição histórica
  expect_false(prop_df$numbering_year == phases_df$numbering_year)
})

test_that("G1.CAMARA.15: Tratamento de documento sem data ou número (undated / ano 0)", {
  segs_df <- build_coverage_segments()

  undated_seg <- segs_df %>% filter(date_axis == "undated")
  expect_equal(nrow(undated_seg), 1)
  expect_true(is.na(undated_seg$year))
  expect_equal(undated_seg$coverage_status, "pending")
  expect_true(grepl("não consultado", undated_seg$gap_reason))

  # Parse de proposição undated
  sample_undated <- list(
    id = "9999000", siglaTipo = "DOC", codTipo = "845", descricaoTipo = "Documento diverso",
    numero = NULL, ano = NULL, dataApresentacao = NULL,
    ementa = "Registro sem data", uri = "https://mock.api/9999000"
  )
  prop_df <- parse_camara_propositions(list(sample_undated), "snap_test")
  expect_equal(nrow(prop_df), 1)
  expect_true(is.na(prop_df$number))
  expect_true(is.na(prop_df$numbering_year))
  expect_true(is.na(prop_df$presentation_date))
})

test_that("G1.CAMARA.16: Coleções históricas - não digitalizado vira lacuna, nunca documento fictício", {
  sample_archival <- list(
    list(id = "DIG-1", has_digital_file = TRUE, tipo = "ARQUIVO", url = "https://mock.camara/1.pdf", data_publicacao = "1850-01-01", codigo_referencia = "CX-1"),
    list(id = "FIS-2", has_digital_file = FALSE, tipo = "ARQUIVO", url = NA_character_, data_publicacao = "1810-01-01", codigo_referencia = "CX-2")
  )

  res <- inventory_archival_units(sample_archival, "snap_test")

  # Apenas o item com arquivo digital vira linha em documents
  expect_equal(nrow(res$documents), 1)
  expect_equal(res$documents$document_id, "camara:doc:diarios_anais:DIG-1")

  # O item sem arquivo é contabilizado como lacuna pura
  expect_equal(res$non_digitized_gaps_count, 1L)

  # collection_documents contém o item digitalizado
  expect_equal(nrow(res$collection_documents), 1)
})
