# R/curation/containment_dedup.R
# Deduplicação exata binária/textual, detecção de containment de passagens e preservação de variantes substantivas
# Conforme docs/CONTRATOS_DADOS.md (Seção 6) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(digest)
  library(dplyr)
  library(tibble)
  library(stringr)
})

get_repo_root <- function() {
  curr <- getwd()
  while (!file.exists(file.path(curr, "AGENTS.md")) && curr != dirname(curr)) {
    curr <- dirname(curr)
  }
  return(curr)
}

source(file.path(get_repo_root(), "R", "inventory", "common", "hashing.R"))

#' Extrai conjunto de shingles de n palavras de um texto
get_word_shingles <- function(text, n = 5L) {
  if (is.null(text) || is.na(text) || nchar(text) == 0) {
    return(character())
  }
  # Extrair palavras em minúsculas preservando acentos
  words <- unlist(stringr::str_extract_all(tolower(text), "[\\p{L}\\p{N}]+"))
  if (length(words) == 0) {
    return(character())
  }
  if (length(words) < n) {
    return(paste(words, collapse = " "))
  }
  vapply(seq_len(length(words) - n + 1L), function(i) {
    paste(words[i:(i + n - 1L)], collapse = " ")
  }, character(1))
}

#' Detecta se há diferenças substantivas (números, datas, negações, verbos normativos operacionais)
#' entre dois textos com alta similaridade lexical
has_substantive_difference <- function(text_a, text_b) {
  # 1. Extração e comparação de numerais / valores monetários / artigos
  nums_a <- sort(unique(unlist(stringr::str_extract_all(text_a, "\\b\\d+([.,]\\d+)?\\b"))))
  nums_b <- sort(unique(unlist(stringr::str_extract_all(text_b, "\\b\\d+([.,]\\d+)?\\b"))))
  if (!identical(nums_a, nums_b)) {
    return(TRUE)
  }

  # 2. Termos normativos substantivos e palavras operacionais de negação/alteração
  operative_terms <- c(
    "não", "revoga", "revogado", "revogada", "institui", "instituído", "instituída",
    "veda", "vedado", "vedada", "autoriza", "autorizado", "dispõe", "altera",
    "acrescenta", "suprime", "modifica", "exceto", "salvo", "proíbe", "proibido",
    "obriga", "obrigatório", "faculta", "facultativo", "isenta", "aumenta", "reduz"
  )

  words_a <- tolower(unlist(stringr::str_extract_all(text_a, "[\\p{L}]+")))
  words_b <- tolower(unlist(stringr::str_extract_all(text_b, "[\\p{L}]+")))

  for (term in operative_terms) {
    count_a <- sum(words_a == term)
    count_b <- sum(words_b == term)
    if (count_a != count_b) {
      return(TRUE)
    }
  }

  return(FALSE)
}

#' Executa a deduplicação completa (exata + próxima + containment) sobre um tibble de corpus items
#'
#' @param items_df Tibble com colunas corpus_item_id, text, quality_status, primary_proposition_id, content_date, etc.
#' @param config Configuração de curadoria (history.yaml)
#' @return list(items = items_df_atualizado, dedup_pairs = dedup_pairs_df)
run_deduplication <- function(items_df, config) {
  if (nrow(items_df) == 0) {
    return(list(
      items = items_df,
      dedup_pairs = tibble::tibble(
        left_item_id = character(),
        right_item_id = character(),
        method = character(),
        similarity = numeric(),
        decision = character(),
        evidence = character(),
        policy_version = character()
      )
    ))
  }

  dedup_cfg <- if (!is.null(config$deduplication)) config$deduplication else list()
  policy_ver <- if (!is.null(config$dedup_policy_version)) config$dedup_policy_version else "dedup_v1"
  shingle_w <- if (!is.null(dedup_cfg$near_dedup_shingle_words)) as.integer(dedup_cfg$near_dedup_shingle_words) else 5L
  jaccard_thresh <- if (!is.null(dedup_cfg$near_dedup_jaccard_threshold)) as.numeric(dedup_cfg$near_dedup_jaccard_threshold) else 0.90
  containment_on <- isTRUE(dedup_cfg$containment_detection)
  containment_min_tokens <- if (!is.null(dedup_cfg$containment_min_passage_tokens)) as.integer(dedup_cfg$containment_min_passage_tokens) else 30L

  # 1. Hashing e Deduplicação Exata
  # Adicionar hashes se não existirem
  if (!"text_sha256" %in% names(items_df)) {
    items_df$text_sha256 <- vapply(items_df$text, hash_string, character(1))
  }
  if (!"comparison_sha256" %in% names(items_df)) {
    items_df$comparison_sha256 <- vapply(items_df$text, function(tx) {
      hash_string(stringr::str_squish(tx))
    }, character(1))
  }
  if (!"character_count" %in% names(items_df)) {
    items_df$character_count <- as.integer(nchar(items_df$text))
  }
  if (!"utf8_bytes" %in% names(items_df)) {
    items_df$utf8_bytes <- as.integer(nchar(items_df$text, type = "bytes"))
  }

  # Inicializar campos de dedup
  if (!"eligibility_reason" %in% names(items_df)) {
    items_df$eligibility_reason <- rep("elegivel", nrow(items_df))
  }
  items_df$exact_cluster_id <- character(nrow(items_df))
  items_df$near_cluster_id <- rep(NA_character_, nrow(items_df))
  items_df$representative_item_id <- items_df$corpus_item_id
  items_df$include_in_dataset <- rep(TRUE, nrow(items_df))

  dedup_pairs_list <- list()
  pair_idx <- 1L

  # Agrupamento exato por text_sha256
  clusters <- split(seq_len(nrow(items_df)), items_df$text_sha256)
  cl_num <- 1L

  for (cl_hash in names(clusters)) {
    idx_group <- clusters[[cl_hash]]
    cl_id <- paste0("cl_exact_", substr(cl_hash, 1, 12))
    items_df$exact_cluster_id[idx_group] <- cl_id

    if (length(idx_group) == 1L) {
      # Único no cluster
      row_i <- idx_group[1]
      items_df$representative_item_id[row_i] <- items_df$corpus_item_id[row_i]
      items_df$include_in_dataset[row_i] <- (items_df$quality_status[row_i] == "accepted")
    } else {
      # Múltiplos itens idênticos: selecionar representante determinístico
      # Critérios de ordenação:
      # 1. Qualidade: "accepted" > "quarantined"
      # 2. Completude de metadados: primary_proposition_id não nulo, content_date não nulo
      # 3. Menor corpus_item_id lexicograficamente
      sub_df <- items_df[idx_group, ]
      score_quality <- ifelse(sub_df$quality_status == "accepted", 2L, 0L)
      score_meta <- as.integer(!is.na(sub_df$primary_proposition_id)) + as.integer(!is.na(sub_df$content_date))

      order_idx <- order(
        -score_quality,
        -score_meta,
        sub_df$corpus_item_id
      )
      rep_row_pos <- idx_group[order_idx[1]]
      rep_item_id <- items_df$corpus_item_id[rep_row_pos]

      for (pos in idx_group) {
        items_df$representative_item_id[pos] <- rep_item_id
        if (pos == rep_row_pos) {
          items_df$include_in_dataset[pos] <- (items_df$quality_status[pos] == "accepted")
        } else {
          items_df$include_in_dataset[pos] <- FALSE
          items_df$eligibility_reason[pos] <- paste0("duplicata exata de ", rep_item_id)

          # Gravar par de duplicata exata
          left_id <- min(rep_item_id, items_df$corpus_item_id[pos])
          right_id <- max(rep_item_id, items_df$corpus_item_id[pos])
          dedup_pairs_list[[pair_idx]] <- list(
            left_item_id = left_id,
            right_item_id = right_id,
            method = "exact_text_sha256",
            similarity = 1.0,
            decision = "exact",
            evidence = paste0("text_sha256=", cl_hash),
            policy_version = policy_ver
          )
          pair_idx <- pair_idx + 1L
        }
      }
    }
    cl_num <- cl_num + 1L
  }

  # 2. Near-Deduplication e Containment
  n_items <- nrow(items_df)
  if (n_items > 1) {
    # Pré-computar shingles para itens
    shingles_cache <- lapply(seq_len(n_items), function(i) {
      get_word_shingles(items_df$text[i], n = shingle_w)
    })
    token_counts <- vapply(seq_len(n_items), function(i) {
      length(unlist(stringr::str_extract_all(items_df$text[i], "\\S+")))
    }, integer(1))

    # Comparar pares de clusters exatos distintos
    distinct_exact_clusters <- unique(items_df$exact_cluster_id)
    # Selecionar apenas representantes de cada cluster exato para busca aproximada
    rep_indices <- which(items_df$corpus_item_id == items_df$representative_item_id)

    if (length(rep_indices) > 1) {
      for (i_idx in seq_along(rep_indices)) {
        i <- rep_indices[i_idx]
        sA <- shingles_cache[[i]]
        lenA <- length(sA)
        if (lenA == 0) next

        for (j_idx in (i_idx + 1):length(rep_indices)) {
          if (j_idx > length(rep_indices)) break
          j <- rep_indices[j_idx]
          sB <- shingles_cache[[j]]
          lenB <- length(sB)
          if (lenB == 0) next

          # Intersecção de shingles
          inter_len <- length(intersect(sA, sB))
          if (inter_len == 0) next

          union_len <- length(union(sA, sB))
          jaccard <- inter_len / union_len
          min_len <- min(lenA, lenB)
          containment_ratio <- inter_len / min_len

          # Para textos curtos (onde 5-shingles são muito sensíveis a 1 palavra), calcular sobreposição de palavras
          words_a <- tolower(unlist(stringr::str_extract_all(items_df$text[i], "[\\p{L}\\p{N}]+")))
          words_b <- tolower(unlist(stringr::str_extract_all(items_df$text[j], "[\\p{L}\\p{N}]+")))
          w_inter <- length(intersect(words_a, words_b))
          w_min <- min(length(words_a), length(words_b))
          w_union <- length(union(words_a, words_b))
          w_overlap <- if (w_min > 0) w_inter / w_min else 0
          w_jaccard <- if (w_union > 0) w_inter / w_union else 0

          is_cand_near <- (jaccard >= jaccard_thresh) || (w_overlap >= 0.90 && w_min < 50) || (w_jaccard >= 0.85)
          is_cand_contain <- (containment_on && containment_ratio >= 0.85 && min(token_counts[i], token_counts[j]) >= containment_min_tokens)

          if (is_cand_near || is_cand_contain) {
            # Verificar se é variante substantiva
            is_substantive <- has_substantive_difference(items_df$text[i], items_df$text[j])

            method_str <- if (is_cand_contain && !is_cand_near) "containment_passage_index" else "shingle_jaccard"
            sim_val <- if (is_cand_contain && !is_cand_near) containment_ratio else jaccard

            decision_str <- if (is_substantive) {
              "substantive_variant"
            } else if (is_cand_near) {
              "equivalent"
            } else {
              "containment_detected"
            }

            evidence_str <- if (is_cand_contain && !is_cand_near) {
              sprintf("passage containment=%.3f (tokens: %d vs %d, substantive=%s)",
                      containment_ratio, token_counts[i], token_counts[j], is_substantive)
            } else {
              sprintf("jaccard=%.3f (substantive=%s)", jaccard, is_substantive)
            }

            left_id <- min(items_df$corpus_item_id[i], items_df$corpus_item_id[j])
            right_id <- max(items_df$corpus_item_id[i], items_df$corpus_item_id[j])

            dedup_pairs_list[[pair_idx]] <- list(
              left_item_id = left_id,
              right_item_id = right_id,
              method = method_str,
              similarity = as.numeric(sim_val),
              decision = decision_str,
              evidence = evidence_str,
              policy_version = policy_ver
            )
            pair_idx <- pair_idx + 1L

            # Se for substantive_variant, ambos permanecem no dataset!
            # Se for equivalent e não substantivo, o representante já é mantido e o outro é registrado
            near_cl <- paste0("cl_near_", substr(hash_string(paste(left_id, right_id)), 1, 10))
            if (is.na(items_df$near_cluster_id[i])) items_df$near_cluster_id[i] <- near_cl
            if (is.na(items_df$near_cluster_id[j])) items_df$near_cluster_id[j] <- near_cl
          }
        }
      }
    }
  }

  dedup_pairs_df <- if (length(dedup_pairs_list) > 0) {
    dplyr::bind_rows(lapply(dedup_pairs_list, tibble::as_tibble)) %>%
      dplyr::distinct(left_item_id, right_item_id, .keep_all = TRUE)
  } else {
    tibble::tibble(
      left_item_id = character(),
      right_item_id = character(),
      method = character(),
      similarity = numeric(),
      decision = character(),
      evidence = character(),
      policy_version = character()
    )
  }

  list(
    items = items_df,
    dedup_pairs = dedup_pairs_df
  )
}
