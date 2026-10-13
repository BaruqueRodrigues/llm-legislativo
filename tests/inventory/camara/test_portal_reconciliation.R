# tests/inventory/camara/test_portal_reconciliation.R
# Testes unitários para reconciliação Portal Web x API v2, caso DVT 1/404 e sobrevivência documental

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
source(file.path(repo_root, "R", "inventory/camara/portal_reconciliation.R"))

test_that("G1.CAMARA.9: Peça do Portal Web com 404 na API (DVT 1 / PL 2/2024) sobrevive integralmente", {
  # Simulação oficial: DVT 1 (id 2422083) sobre PL 2/2024 (camara:prop:2416804)
  rec_res <- reconcile_portal_document(
    portal_doc_id = "2422083",
    main_proposition_id = "camara:prop:2416804",
    doc_type = "DVT",
    doc_role = "vote",
    identity_url = "https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=2422083",
    source_portal_url = "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2422083",
    doc_date = "2024-03-20",
    api_http_status = 404L,
    snapshot_id = "camara:snap:test_portal"
  )

  # 1. Tabela documents: documento existe e está preservado
  doc_df <- rec_res$documents
  expect_equal(nrow(doc_df), 1)
  expect_equal(doc_df$document_id, "camara:doc:portal_proposicoes:2422083")
  expect_equal(doc_df$house, "camara")
  expect_equal(doc_df$normalized_kind, "vote")
  expect_equal(doc_df$date_status, "verified")
  expect_equal(as.character(doc_df$publication_date), "2024-03-20")

  # 2. Tabela proposition_documents: vínculo com PL 2/2024 preservado
  prop_doc_df <- rec_res$proposition_documents
  expect_equal(nrow(prop_doc_df), 1)
  expect_equal(prop_doc_df$proposition_id, "camara:prop:2416804")
  expect_equal(prop_doc_df$document_id, "camara:doc:portal_proposicoes:2422083")
  expect_equal(prop_doc_df$document_role, "vote")
  expect_equal(prop_doc_df$role_status, "verified")
})

test_that("G1.CAMARA.10: Registro em entity_aliases mapeia identidade do portal com evidência", {
  rec_res <- reconcile_portal_document(
    portal_doc_id = "2422083",
    main_proposition_id = "camara:prop:2416804",
    doc_type = "DVT",
    doc_role = "vote",
    snapshot_id = "camara:snap:test_portal"
  )

  aliases_df <- rec_res$entity_aliases
  expect_equal(nrow(aliases_df), 1)
  expect_equal(aliases_df$alias_id, "camara:alias:portal:2422083")
  expect_equal(aliases_df$canonical_entity_id, "camara:doc:portal_proposicoes:2422083")
  expect_equal(aliases_df$status, "verified")
  expect_true(grepl("fichadetramitacao", aliases_df$evidence_uri))
})

test_that("G1.CAMARA.11: Registro explícito em metadata_checks documenta erro 404 da API", {
  rec_res <- reconcile_portal_document(
    portal_doc_id = "2422083",
    main_proposition_id = "camara:prop:2416804",
    api_http_status = 404L,
    snapshot_id = "camara:snap:test_portal"
  )

  checks_df <- rec_res$metadata_checks
  expect_equal(nrow(checks_df), 1)
  expect_equal(checks_df$entity_kind, "document")
  expect_equal(checks_df$entity_id, "camara:doc:portal_proposicoes:2422083")
  expect_equal(checks_df$status, "terminal_error")
  expect_true(grepl("404", checks_df$reason))
})

test_that("G1.CAMARA.12: Criação de documento inicial a partir de urlInteiroTeor", {
  prop_fake <- list(
    proposition_id = "camara:prop:2319130",
    source_id = "2319130",
    type_code = "PL",
    type_source_id = "139",
    legislative_type_id = "camara:type:139",
    legislative_body = "Câmara dos Deputados",
    presentation_date = as.Date("2022-03-31"),
    source_uri = "https://dadosabertos.camara.leg.br/api/v2/proposicoes/2319130",
    whole_text_url = "https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=2154796"
  )

  init_res <- create_initial_document(prop_fake, "camara:snap:test")
  expect_equal(nrow(init_res$documents), 1)
  expect_equal(nrow(init_res$proposition_documents), 1)
  expect_equal(init_res$documents$normalized_kind, "initial")
  expect_equal(init_res$proposition_documents$document_role, "initial")
  expect_equal(init_res$proposition_documents$role_status, "verified")
})
