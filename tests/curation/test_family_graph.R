# tests/curation/test_family_graph.R
# Testes unitários do grafo global de famílias e prevenção de componentes gigantes (Frente 04)

suppressPackageStartupMessages({
  library(testthat)
  library(digest)
  library(dplyr)
  library(tibble)
  library(yaml)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "curation", "family_graph.R"))

config <- yaml::read_yaml(file.path(repo_root, "configs", "curation", "history.yaml"))

test_that("Vínculo entre casas (Câmara e Senado) via aliases verificado une a mesma família", {
  items <- tibble(
    corpus_item_id = c("item:cam:100", "item:sen:100"),
    primary_proposition_id = c("camara:prop:100", "senado:prop:processo:100"),
    document_id = c("camara:doc:100", "senado:doc:100"),
    logical_unit_id = c("camara:doc:100", "senado:doc:100")
  )

  aliases <- tibble(
    alias_id = "alias:1",
    entity_kind = "proposition",
    alias_namespace = "senado",
    alias_source_id = "senado:prop:processo:100",
    canonical_entity_id = "camara:prop:100",
    evidence_uri = "https://example.invalid/link",
    snapshot_id = "snap-1",
    status = "verified"
  )

  res <- build_family_graph(items_df = items, entity_aliases_df = aliases, config = config)

  # Ambas as casas compartilham o mesmo family_id
  expect_equal(res$family_id[1], res$family_id[2])
})

test_that("Relações com grouping_policy 'bind' unem famílias, mas 'do_not_bind' ou menções não unem", {
  items <- tibble(
    corpus_item_id = c("item:p1", "item:p2", "item:p3"),
    primary_proposition_id = c("camara:prop:1", "camara:prop:2", "camara:prop:3"),
    document_id = c("doc:1", "doc:2", "doc:3"),
    logical_unit_id = c("doc:1", "doc:2", "doc:3")
  )

  # P1 e P2 apensadas (bind)
  # P2 e P3 com menção genérica (do_not_bind)
  relations <- tibble(
    relation_id = c("rel:1", "rel:2"),
    source_proposition_id = c("camara:prop:1", "camara:prop:2"),
    target_proposition_id = c("camara:prop:2", "camara:prop:3"),
    relation_type = c("apensada", "citacao_generica"),
    grouping_policy = c("bind", "do_not_bind")
  )

  res <- build_family_graph(items_df = items, relations_df = relations, config = config)

  # P1 e P2 na mesma família
  expect_equal(res$family_id[1], res$family_id[2])

  # P3 em família independente (não contamina P1 e P2!)
  expect_false(res$family_id[1] == res$family_id[3])
})

test_that("Versões e substitutivos da mesma unidade lógica pertencem à mesma família", {
  items <- tibble(
    corpus_item_id = c("item:v1", "item:v2"),
    primary_proposition_id = c("camara:prop:50", "camara:prop:50"),
    document_id = c("doc:50", "doc:50"),
    logical_unit_id = c("doc:50", "doc:50")
  )

  res <- build_family_graph(items_df = items, config = config)

  expect_equal(res$family_id[1], res$family_id[2])
})
