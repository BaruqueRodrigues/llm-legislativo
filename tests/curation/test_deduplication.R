# tests/curation/test_deduplication.R
# Testes unitários de deduplicação exata, quase-duplicatas, variantes substantivas e containment (Frente 04)

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

source(file.path(repo_root, "R", "curation", "containment_dedup.R"))

config <- yaml::read_yaml(file.path(repo_root, "configs", "curation", "history.yaml"))

test_that("Deduplicação exata agrupa itens idênticos e seleciona representante determinístico único", {
  text_sample <- "PROJETO DE LEI\nArt. 1º Fica instituído o programa exemplo.\n\nJUSTIFICAÇÃO\nTexto comum."

  items <- tibble(
    corpus_item_id = c("item:001", "item:002"),
    text = c(text_sample, text_sample),
    quality_status = c("accepted", "accepted"),
    primary_proposition_id = c("camara:prop:100", "camara:prop:200"),
    content_date = as.Date(c("2023-01-01", "2023-01-02"))
  )

  res <- run_deduplication(items, config)
  res_items <- res$items
  res_pairs <- res$dedup_pairs

  # Mesmo cluster exato
  expect_equal(res_items$exact_cluster_id[1], res_items$exact_cluster_id[2])

  # Apenas 1 incluído no dataset
  expect_true(res_items$include_in_dataset[1])
  expect_false(res_items$include_in_dataset[2])

  # Representante é o primeiro (menor corpus_item_id)
  expect_equal(res_items$representative_item_id[1], "item:001")
  expect_equal(res_items$representative_item_id[2], "item:001")

  # Par registrado em dedup_pairs com decision = 'exact'
  expect_equal(nrow(res_pairs), 1)
  expect_equal(res_pairs$left_item_id[1], "item:001")
  expect_equal(res_pairs$right_item_id[1], "item:002")
  expect_equal(res_pairs$decision[1], "exact")
})

test_that("Variantes substantivas (instituído vs revogado) são preservadas no dataset", {
  text_orig <- "PROJETO DE LEI\nArt. 1º Fica instituído o programa nacional de infraestrutura com recursos do Tesouro Nacional."
  text_mod <- "PROJETO DE LEI\nArt. 1º Fica revogado o programa nacional de infraestrutura com recursos do Tesouro Nacional."

  items <- tibble(
    corpus_item_id = c("item:sub1", "item:sub2"),
    text = c(text_orig, text_mod),
    quality_status = c("accepted", "accepted"),
    primary_proposition_id = c("camara:prop:10", "camara:prop:10"),
    content_date = as.Date(c("2023-01-01", "2023-02-01"))
  )

  res <- run_deduplication(items, config)
  res_items <- res$items
  res_pairs <- res$dedup_pairs

  # Ambos os itens permanecem incluídos no dataset pois representam normas divergentes substantivas!
  expect_true(res_items$include_in_dataset[1])
  expect_true(res_items$include_in_dataset[2])

  # Par registrado com decision = 'substantive_variant'
  expect_equal(nrow(res_pairs), 1)
  expect_equal(res_pairs$decision[1], "substantive_variant")
})

test_that("Containment detecta peça legislativa contida em volume maior ou dossiê", {
  # Texto curto (emenda ou parecer de 40 tokens)
  text_short <- paste(
    "Dê-se ao Art. 1º a seguinte redação:",
    "Art. 1º O prazo para prestação de contas será de sessenta dias contados da notificação oficial.",
    "Sala das Comissões, em 10 de maio de 2023."
  )

  # Texto longo (dossiê ou anais contendo o texto curto embutido)
  text_long <- paste(
    "ATA DA 45ª REUNIÃO ORDINÁRIA DA COMISSÃO DE CONSTITUIÇÃO E JUSTIÇA.",
    "Sob a presidência do Deputado Presidente, iniciam-se os trabalhos.",
    "Passa-se à apreciação da Emenda nº 1 ao Projeto de Lei nº 500 de 2023.",
    text_short,
    "Em votação, a emenda foi aprovada por unanimidade dos presentes.",
    "Nada mais havendo a tratar, encerra-se a reunião às dezoito horas."
  )

  items <- tibble(
    corpus_item_id = c("item:long", "item:short"),
    text = c(text_long, text_short),
    quality_status = c("accepted", "accepted"),
    primary_proposition_id = c(NA_character_, "camara:prop:500"),
    content_date = as.Date(c("2023-05-10", "2023-05-10"))
  )

  res <- run_deduplication(items, config)
  res_pairs <- res$dedup_pairs

  # Deve registrar par com containment
  expect_true(nrow(res_pairs) >= 1)
  expect_true(any(res_pairs$method == "containment_passage_index" | res_pairs$decision %in% c("containment_detected", "substantive_variant")))
})
