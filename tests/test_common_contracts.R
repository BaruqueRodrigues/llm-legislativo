# tests/test_common_contracts.R
# Testes formais dos contratos de dados e esquemas normativos (Gate G0)

suppressPackageStartupMessages({
  library(testthat)
  library(arrow)
  library(dplyr)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

fixtures_dir <- file.path(repo_root, "tests", "fixtures", "common")


test_that("G0.8: DATA_ROOT precisa ser absoluto e externo ao checkout", {
  external <- file.path(tempdir(), "legislm-data-root-contract")
  withr::local_envvar(c(DATA_ROOT = external))
  expect_equal(resolve_external_data_root(repo_root), normalizePath(external, winslash = "/", mustWork = FALSE))
  withr::local_envvar(c(DATA_ROOT = "relative/data"))
  expect_error(resolve_external_data_root(repo_root), "absoluto")
  withr::local_envvar(c(DATA_ROOT = file.path(repo_root, "data")))
  expect_error(resolve_external_data_root(repo_root), "dentro do checkout")
})

test_that("G0.1: Todos os 31 esquemas Arrow normativos estao definidos corretamente", {
  schemas <- get_arrow_schemas()
  expect_equal(length(schemas), 31)

  # Verificar tabelas essenciais
  required_tables <- c(
    "source_snapshots", "propositions", "authors", "proposition_authors",
    "document_authors", "themes", "proposition_themes", "metadata_checks",
    "relations", "process_phases", "document_phases", "documents",
    "proposition_documents", "document_versions", "fetch_attempts",
    "use_evidence", "source_collections", "legislative_types",
    "coverage_segments", "collection_documents", "entity_aliases",
    "extraction_runs", "pages", "sections", "curated_documents",
    "corpus_item_propositions", "curated_document_sections", "dedup_pairs",
    "cleaning_events", "quality_reviews", "split_assignments"
  )
  expect_true(all(required_tables %in% names(schemas)))
})

test_that("G0.2: Construtores de identificadores com namespace evitam colisao entre casas", {
  id_camara <- build_proposition_id("camara", "100")
  id_senado <- build_proposition_id("senado", "100")
  id_senado_legado <- build_proposition_id("senado", "100", is_legado = TRUE)

  expect_equal(id_camara, "camara:prop:100")
  expect_equal(id_senado, "senado:prop:processo:100")
  expect_equal(id_senado_legado, "senado:prop:materia:100")

  # Zero colisão entre mesmo número de identificador em casas distintas
  expect_false(id_camara == id_senado)
  expect_false(id_senado == id_senado_legado)

  # Document IDs com namespace
  doc_id_camara <- build_document_id("camara", "api", "D123")
  doc_id_senado <- build_document_id("senado", "processo", "D123")
  expect_false(doc_id_camara == doc_id_senado)
})

test_that("G0.3: Hashing SHA-256 e deterministico e compativel", {
  text <- "Texto oficial de teste para hash"
  h1 <- hash_string(text)
  h2 <- hash_string(text)
  expect_equal(h1, h2)
  expect_equal(nchar(h1), 64)
  expect_true(grepl("^[0-9a-f]{64}$", h1))
})

test_that("G0.4: Fixtures sinteticas Parquet carregam perfeitamente com esquemas Arrow", {
  props <- read_parquet(file.path(fixtures_dir, "propositions.parquet"))
  expect_equal(nrow(props), 8)

  # Verificar unicidade de proposition_id (PK)
  expect_equal(length(unique(props$proposition_id)), nrow(props))

  # Verificar coexistência pacífica de ID 100 na Câmara e no Senado
  expect_true("camara:prop:100" %in% props$proposition_id)
  expect_true("senado:prop:processo:100" %in% props$proposition_id)
})

test_that("G0.5: Produto Cartesiano de autores x temas nao multiplica corpus_item_id", {
  # SYN001 tem 2 autores e 2 temas nas pontes (produto cartesiano seria 4)
  pa <- read_parquet(file.path(fixtures_dir, "proposition_authors.parquet"))
  pt <- read_parquet(file.path(fixtures_dir, "proposition_themes.parquet"))
  curated <- read_parquet(file.path(fixtures_dir, "curated_documents.parquet"))

  authors_syn001 <- pa %>% filter(proposition_id == "camara:prop:SYN001")
  themes_syn001 <- pt %>% filter(proposition_id == "camara:prop:SYN001")
  expect_equal(nrow(authors_syn001), 2)
  expect_equal(nrow(themes_syn001), 2)

  items_syn001 <- curated %>% filter(primary_proposition_id == "camara:prop:SYN001")
  expect_equal(nrow(items_syn001), 1) # EXATAMENTE 1 item curado, não 4!
})

test_that("G0.6: Deduplicacao exata preserva auditoria e seleciona representante unico", {
  curated <- read_parquet(file.path(fixtures_dir, "curated_documents.parquet"))

  syn001 <- curated %>% filter(primary_proposition_id == "camara:prop:SYN001")
  syn002 <- curated %>% filter(primary_proposition_id == "camara:prop:SYN002")

  # Ambos possuem o mesmo hash de texto exato
  expect_equal(syn001$text_sha256, syn002$text_sha256)

  # SYN001 é representante e entra no dataset
  expect_true(syn001$include_in_dataset)
  expect_equal(syn001$representative_item_id, syn001$corpus_item_id)

  # SYN002 aponta para SYN001 como representante e NÃO entra no dataset
  expect_false(syn002$include_in_dataset)
  expect_equal(syn002$representative_item_id, syn001$corpus_item_id)
})

test_that("G0.7: Diferenca substantiva e preservada no dataset e na familia", {
  curated <- read_parquet(file.path(fixtures_dir, "curated_documents.parquet"))

  syn001 <- curated %>% filter(primary_proposition_id == "camara:prop:SYN001")
  syn003 <- curated %>% filter(primary_proposition_id == "camara:prop:SYN003")

  # Hash diferente devido à alteração de 'instituído' para 'revogado'
  expect_false(syn001$text_sha256 == syn003$text_sha256)

  # Ambos são incluídos no dataset pois representam normas com diferenças substantivas
  expect_true(syn001$include_in_dataset)
  expect_true(syn003$include_in_dataset)

  # Compartilham a mesma família caso sejam versões relacionadas
  expect_equal(syn001$family_id, syn003$family_id)
})

test_that("G0.8: Familia que cruza corte temporal e purgada para quarantine", {
  splits <- read_parquet(file.path(fixtures_dir, "split_assignments.parquet"))

  syn005_split <- splits %>% filter(corpus_item_id == (read_parquet(file.path(fixtures_dir, "curated_documents.parquet")) %>% filter(primary_proposition_id == "camara:prop:SYN005"))$corpus_item_id)
  syn006_split <- splits %>% filter(corpus_item_id == (read_parquet(file.path(fixtures_dir, "curated_documents.parquet")) %>% filter(primary_proposition_id == "camara:prop:SYN006"))$corpus_item_id)

  expect_equal(syn005_split$split, "quarantine")
  expect_equal(syn006_split$split, "quarantine")
  expect_equal(syn005_split$policy, "temporal_purged")
  expect_equal(syn006_split$family_id, syn005_split$family_id)
})
