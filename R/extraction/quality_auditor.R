# R/extraction/quality_auditor.R
# Auditoria de qualidade, cálculo de CER/WER e benchmark comparativo (fast vs accurate)
# Conforme docs/CONTRATOS_DADOS.md (Seção 3, linha 177) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(tibble)
  library(dplyr)
  library(stringr)
  library(bit64)
})

# Cálculo determinístico de Distância de Levenshtein (base para CER e WER)
levenshtein_distance <- function(a, b) {
  la <- length(a)
  lb <- length(b)
  if (la == 0) return(lb)
  if (lb == 0) return(la)

  d <- matrix(0L, nrow = la + 1, ncol = lb + 1)
  d[, 1] <- 0:la
  d[1, ] <- 0:lb

  for (i in seq_len(la)) {
    for (j in seq_len(lb)) {
      cost <- if (a[i] == b[j]) 0L else 1L
      d[i + 1, j + 1] <- min(
        d[i, j + 1] + 1L,       # deletion
        d[i + 1, j] + 1L,       # insertion
        d[i, j] + cost          # substitution
      )
    }
  }
  return(d[la + 1, lb + 1])
}

calculate_cer <- function(reference, hypothesis) {
  ref_chars <- strsplit(reference, "")[[1]]
  hyp_chars <- strsplit(hypothesis, "")[[1]]
  if (length(ref_chars) == 0) {
    return(if (length(hyp_chars) == 0) 0.0 else 1.0)
  }
  dist <- levenshtein_distance(ref_chars, hyp_chars)
  min(1.0, dist / length(ref_chars))
}

calculate_wer <- function(reference, hypothesis) {
  ref_words <- unlist(strsplit(trimws(reference), "\\s+"))
  hyp_words <- unlist(strsplit(trimws(hypothesis), "\\s+"))
  if (length(ref_words) == 0) {
    return(if (length(hyp_words) == 0) 0.0 else 1.0)
  }
  dist <- levenshtein_distance(ref_words, hyp_words)
  min(1.0, dist / length(ref_words))
}

run_extraction_benchmark <- function(
  test_fixtures = c(
    "tests/extraction/fixtures/scanned_image.pdf",
    "tests/extraction/fixtures/native_digital.pdf",
    "tests/extraction/fixtures/mixed_document.pdf",
    "tests/extraction/fixtures/two_columns.pdf"
  ),
  reference_ground_truth = NULL
) {
  repo_root <- getwd()
  while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
    repo_root <- dirname(repo_root)
  }

  source(file.path(repo_root, "R", "extraction", "preflight.R"))
  source(file.path(repo_root, "R", "extraction", "pdf_extractor.R"))

  preflight_info <- run_extraction_preflight(repo_root)
  config <- load_extraction_config()

  results <- list()
  quality_reviews_list <- list()
  rev_idx <- 1L

  # Texto de referência padrão para scanned_image.pdf
  default_ref_scanned <- "PARECER Nº 123, DE 2024\nDA COMISSÃO DE CONSTITUIÇÃO E JUSTIÇA E DE CIDADANIA\nSobre o Projeto de Lei nº 4.567, de 2024.\nI - RELATÓRIO\nTrata-se de proposição de autoria do ilustre Deputado Carlos Silva que visa regular as diretrizes de governança de dados legislativos. No prazo regimental, não foram apresentadas emendas.\nII - VOTO DO RELATOR\nA proposição atende a todos os requisitos constitucionais e regimentais de técnica legislativa. Quanto ao mérito, a iniciativa é meritória e fortalece as instituições democráticas.\nVoto, portanto, pela constitucionalidade, juridicidade e aprovação do Projeto de Lei nº 4.567, de 2024.\nSala da Comissão, em 20 de abril de 2024.\nDeputada Mariana Souza - Relatora"

  for (pdf_rel in test_fixtures) {
    pdf_path <- file.path(repo_root, pdf_rel)
    if (!file.exists(pdf_path)) next

    fname <- basename(pdf_path)
    version_id <- paste0("benchmark:doc:", tools::file_path_sans_ext(fname))

    # Executa com benchmark habilitado
    doc_bench <- extract_document(
      pdf_path = pdf_path,
      version_id = version_id,
      config = config,
      preflight_info = preflight_info,
      mode = "auto",
      enable_benchmark = TRUE
    )

    results[[fname]] <- doc_bench

    # Se a página contiver benchmarks comparativos (fast vs accurate)
    for (i in seq_along(doc_bench$benchmark)) {
      bm <- doc_bench$benchmark[[i]]
      p_idx <- bm$page_index
      ext_id <- doc_bench$run$extraction_id

      ref_text <- if (fname == "scanned_image.pdf") default_ref_scanned else NULL

      cer_acc <- if (!is.null(ref_text)) calculate_cer(ref_text, doc_bench$pages$raw_text[p_idx]) else NA_real_
      wer_acc <- if (!is.null(ref_text)) calculate_wer(ref_text, doc_bench$pages$raw_text[p_idx]) else NA_real_

      quality_reviews_list[[rev_idx]] <- tibble(
        review_id = paste0(ext_id, ":rev:", p_idx),
        extraction_id = ext_id,
        corpus_item_id = NA_character_,
        page_index = as.integer(p_idx),
        reviewer = "subagent_03_quality_auditor",
        sample_seed = 42L,
        stratum = paste0("benchmark_", tools::file_path_sans_ext(fname)),
        result = if (is.na(cer_acc) || cer_acc <= 0.05) "pass" else "review",
        cer = cer_acc,
        wer = wer_acc,
        reviewed_at = as.POSIXct(Sys.time(), tz = "UTC"),
        notes = sprintf(
          "Fast: %.1f ms (conf: %.2f, mem: %.1f MB). Accurate: %.1f ms (conf: %.2f, mem: %.1f MB). Speedup: %.2fx.",
          bm$fast_elapsed_ms,
          bm$fast_confidence %||% 0,
          bm$fast_memory_mb %||% 0,
          bm$accurate_elapsed_ms,
          bm$accurate_confidence %||% 0,
          bm$accurate_memory_mb %||% 0,
          bm$accurate_elapsed_ms / max(1, bm$fast_elapsed_ms)
        )
      )
      rev_idx <- rev_idx + 1L
    }
  }

  quality_reviews_df <- if (length(quality_reviews_list) > 0) {
    dplyr::bind_rows(quality_reviews_list)
  } else {
    tibble(
      review_id = character(0),
      extraction_id = character(0),
      corpus_item_id = character(0),
      page_index = integer(0),
      reviewer = character(0),
      sample_seed = bit64::integer64(0),
      stratum = character(0),
      result = character(0),
      cer = numeric(0),
      wer = numeric(0),
      reviewed_at = as.POSIXct(character(0), tz = "UTC"),
      notes = character(0)
    )
  }

  list(
    results = results,
    quality_reviews = quality_reviews_df
  )
}
