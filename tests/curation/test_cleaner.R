# tests/curation/test_cleaner.R
# Testes unitários do módulo de limpeza e preservação textual (Frente 04)

suppressPackageStartupMessages({
  library(testthat)
  library(digest)
  library(dplyr)
  library(yaml)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "curation", "cleaner.R"))

config <- yaml::read_yaml(file.path(repo_root, "configs", "curation", "history.yaml"))

test_that("Cleaner preserva maiúsculas, minúsculas, acentuação e numerais", {
  text_orig <- "PROJETO DE LEI Nº 1.234/2023\nArt. 1º Fica instituído o Programa Nacional de Aceleração com R$ 1.500.000,00."
  res <- clean_document_text(text_orig, "item:test:01", config)

  expect_equal(res$cleaned_text, text_orig)
  expect_equal(nrow(res$events), 0)
})

test_that("Cleaner converte CRLF para LF e registra evento em cleaning_events", {
  text_crlf <- "PROJETO DE LEI\r\nArt. 1º Artigo de exemplo.\r\nJUSTIFICAÇÃO\r\nJustificativa."
  res <- clean_document_text(text_crlf, "item:test:crlf", config)

  expect_false(grepl("\r", res$cleaned_text))
  expect_equal(res$cleaned_text, "PROJETO DE LEI\nArt. 1º Artigo de exemplo.\nJUSTIFICAÇÃO\nJustificativa.")
  expect_equal(nrow(res$events), 1)
  expect_equal(res$events$rule_id[1], "crlf_to_lf")
  expect_equal(res$events$corpus_item_id[1], "item:test:crlf")
  expect_equal(res$events$after_sha256[1], hash_string(res$cleaned_text))
})

test_that("Cleaner remove assinaturas digitais/carimbos sem remover assinaturas substantivas de relatores", {
  text_with_sig <- paste0(
    "PROJETO DE LEI\nArt. 1º Exemplo.\n\n",
    "Sala das Sessões, 15 de março de 2023.\n",
    "Deputado João da Silva\nRelator\n",
    "Assinado digitalmente por JOAO DA SILVA:123456789 ICP-Brasil chave 987654321.\n"
  )

  res <- clean_document_text(text_with_sig, "item:test:sig", config)

  # Assinatura substantiva do parlamentar deve ser preservada
  expect_true(grepl("Deputado João da Silva", res$cleaned_text))
  expect_true(grepl("Relator", res$cleaned_text))

  # Carimbo eletrônico digital externo deve ser removido
  expect_false(grepl("ICP-Brasil", res$cleaned_text))
  expect_false(grepl("Assinado digitalmente por", res$cleaned_text))

  # Evento registrado
  expect_true(any(res$events$rule_id == "remove_digital_signatures"))
})

test_that("Cleaner remove cabeçalhos/rodapés repetitivos de numeração de página", {
  text_with_pages <- paste0(
    "PROJETO DE LEI\nArt. 1º Artigo primeiro.\n",
    "Página 1 de 10\n",
    "Art. 2º Artigo segundo.\n",
    "CD/23456789\n",
    "Art. 3º Artigo terceiro.\n"
  )

  res <- clean_document_text(text_with_pages, "item:test:pages", config)

  expect_false(grepl("Página 1 de 10", res$cleaned_text))
  expect_false(grepl("CD/23456789", res$cleaned_text))
  expect_true(grepl("Art. 1º", res$cleaned_text))
  expect_true(grepl("Art. 2º", res$cleaned_text))
  expect_true(grepl("Art. 3º", res$cleaned_text))

  expect_true(any(res$events$rule_id == "remove_running_headers_footers"))
})
