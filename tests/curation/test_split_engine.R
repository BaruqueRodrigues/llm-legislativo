# tests/curation/test_split_engine.R
# Testes unitários do motor de divisão em splits (Frente 04)

suppressPackageStartupMessages({
  library(testthat)
  library(dplyr)
  library(tibble)
  library(yaml)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "curation", "split_engine.R"))

config <- yaml::read_yaml(file.path(repo_root, "configs", "curation", "history.yaml"))

test_that("Group hash aloca todos os itens da mesma família no mesmo split sem vazamento", {
  # 20 itens divididos em 5 famílias
  items <- tibble(
    corpus_item_id = paste0("item:", 1:20),
    family_id = rep(paste0("fam:", 1:5), each = 4),
    content_date = as.Date("2023-01-01") + 1:20
  )

  splits_df <- assign_splits(items, config)

  # Invariante absoluta: zero famílias divididas entre splits
  leaks <- splits_df %>%
    group_by(family_id) %>%
    summarise(n_splits = n_distinct(split), .groups = "drop") %>%
    filter(n_splits > 1)

  expect_equal(nrow(leaks), 0)
  expect_true(all(splits_df$split %in% c("train", "validation", "test")))
})

test_that("Itens sem data são preservados na política group_hash", {
  items <- tibble(
    corpus_item_id = c("item:undated:1", "item:undated:2"),
    family_id = c("fam:u1", "fam:u2"),
    content_date = as.Date(c(NA, NA))
  )

  splits_df <- assign_splits(items, config)

  expect_true(all(splits_df$split %in% c("train", "validation", "test")))
  expect_equal(splits_df$policy[1], "group_hash")
})

test_that("Família que cruza corte temporal é purgada para quarantine quando temporal_purged habilitado", {
  cfg_temporal <- config
  cfg_temporal$splits$temporal_purged$enabled <- TRUE
  cfg_temporal$splits$temporal_purged$temporal_cut_train <- "2022-12-31"
  cfg_temporal$splits$temporal_purged$temporal_cut_validation <- "2023-12-31"

  # Família que cruza o corte de 2022 (um item em 2021 e outro em 2024)
  items_cross <- tibble(
    corpus_item_id = c("item:syn005", "item:syn006"),
    family_id = c("fam:cross_temporal", "fam:cross_temporal"),
    content_date = as.Date(c("2021-05-10", "2024-02-01"))
  )

  splits_df <- assign_splits(items_cross, cfg_temporal)

  expect_equal(splits_df$split[1], "quarantine")
  expect_equal(splits_df$split[2], "quarantine")
  expect_equal(splits_df$policy[1], "temporal_purged")
  expect_equal(splits_df$policy[2], "temporal_purged")
  expect_true(grepl("cruza corte temporal", splits_df$assignment_reason[1]))
})
