# R/curation/split_engine.R
# Motor determinístico de divisão em splits (group_hash e temporal_purged) sem contaminação
# Conforme docs/CONTRATOS_DADOS.md (Seção 3 e 6) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(digest)
  library(dplyr)
  library(tibble)
  library(bit64)
})

get_repo_root <- function() {
  curr <- getwd()
  while (!file.exists(file.path(curr, "AGENTS.md")) && curr != dirname(curr)) {
    curr <- dirname(curr)
  }
  return(curr)
}

source(file.path(get_repo_root(), "R", "inventory", "common", "hashing.R"))

#' Gera as atribuições de split garantindo zero vazamento entre famílias
#'
#' @param items_df Tibble de corpus items contendo corpus_item_id, family_id, content_date, etc.
#' @param config Configuração de curadoria (history.yaml)
#' @return tibble conforme esquema split_assignments
assign_splits <- function(items_df, config) {
  if (nrow(items_df) == 0) {
    return(tibble::tibble(
      split_version = character(),
      corpus_item_id = character(),
      family_id = character(),
      split = character(),
      policy = character(),
      assignment_reason = character(),
      seed = bit64::integer64(),
      temporal_cut_train = as.Date(character()),
      temporal_cut_validation = as.Date(character())
    ))
  }

  splits_cfg <- if (!is.null(config$splits)) config$splits else list()
  split_ver <- if (!is.null(config$split_version)) config$split_version else "split_v1"
  seed_val <- if (!is.null(config$seed)) as.integer(config$seed) else 42L
  policy_default <- if (!is.null(splits_cfg$policy)) splits_cfg$policy else "group_hash"

  p_train <- if (!is.null(splits_cfg$target_proportions$train)) as.numeric(splits_cfg$target_proportions$train) else 0.80
  p_val <- if (!is.null(splits_cfg$target_proportions$validation)) as.numeric(splits_cfg$target_proportions$validation) else 0.10
  p_test <- if (!is.null(splits_cfg$target_proportions$test)) as.numeric(splits_cfg$target_proportions$test) else 0.10

  temporal_cfg <- if (!is.null(splits_cfg$temporal_purged)) splits_cfg$temporal_purged else list()
  temporal_enabled <- isTRUE(temporal_cfg$enabled)
  cut_train <- if (!is.null(temporal_cfg$temporal_cut_train)) as.Date(temporal_cfg$temporal_cut_train) else as.Date("2022-12-31")
  cut_val <- if (!is.null(temporal_cfg$temporal_cut_validation)) as.Date(temporal_cfg$temporal_cut_validation) else as.Date("2023-12-31")

  # Mapeamento único por family_id
  distinct_families <- unique(items_df$family_id)

  fam_split_map <- list()

  for (fam in distinct_families) {
    fam_items <- items_df %>% filter(family_id == fam)

    # Verificar se a família deve ser purgada temporalmente
    is_temporal_purged <- FALSE
    purge_reason <- ""

    if (temporal_enabled) {
      dates <- as.Date(na.omit(fam_items$content_date))
      if (length(dates) == 0) {
        # Sem data verificada em protocolo temporal estrito
        is_temporal_purged <- TRUE
        purge_reason <- paste0(fam, " sem data verificada em protocolo temporal estrito")
      } else {
        min_d <- min(dates)
        max_d <- max(dates)
        # Cruza corte de treino ou corte de validação
        if ((min_d <= cut_train && max_d > cut_train) || (min_d <= cut_val && max_d > cut_val)) {
          is_temporal_purged <- TRUE
          purge_reason <- sprintf("%s cruza corte temporal (%s a %s)", fam, as.character(min_d), as.character(max_d))
        }
      }
    }

    if (is_temporal_purged) {
      fam_split_map[[fam]] <- list(
        split = "quarantine",
        policy = "temporal_purged",
        reason = purge_reason,
        cut_train = cut_train,
        cut_val = cut_val
      )
    } else {
      # Alocação determinística via hash uniforme (group_hash)
      hash_hex <- digest::digest(paste0(fam, ":", seed_val), algo = "sha256")
      u_val <- as.numeric(paste0("0x", substr(hash_hex, 1, 8))) / 4294967296

      assigned_split <- if (u_val < p_train) {
        "train"
      } else if (u_val < (p_train + p_val)) {
        "validation"
      } else {
        "test"
      }

      fam_split_map[[fam]] <- list(
        split = assigned_split,
        policy = "group_hash",
        reason = sprintf("%s sorteada para %s via group_hash (seed %d, u=%.4f)", fam, assigned_split, seed_val, u_val),
        cut_train = if (temporal_enabled) cut_train else as.Date(NA),
        cut_val = if (temporal_enabled) cut_val else as.Date(NA)
      )
    }
  }

  # Montar tibble para todos os itens
  n_rows <- nrow(items_df)
  splits_vec <- character(n_rows)
  policy_vec <- character(n_rows)
  reason_vec <- character(n_rows)
  cut_train_vec <- as.Date(rep(NA, n_rows))
  cut_val_vec <- as.Date(rep(NA, n_rows))

  for (i in seq_len(n_rows)) {
    fam <- items_df$family_id[i]
    alloc <- fam_split_map[[fam]]
    splits_vec[i] <- alloc$split
    policy_vec[i] <- alloc$policy
    reason_vec[i] <- alloc$reason
    cut_train_vec[i] <- alloc$cut_train
    cut_val_vec[i] <- alloc$cut_val
  }

  tibble::tibble(
    split_version = rep(split_ver, n_rows),
    corpus_item_id = items_df$corpus_item_id,
    family_id = items_df$family_id,
    split = splits_vec,
    policy = policy_vec,
    assignment_reason = reason_vec,
    seed = bit64::as.integer64(rep(seed_val, n_rows)),
    temporal_cut_train = cut_train_vec,
    temporal_cut_validation = cut_val_vec
  )
}
