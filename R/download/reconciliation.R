# R/download/reconciliation.R
# Reconciliação estatística da cobertura: descobertos -> obtidos -> falhos/pendentes (Gate GH / G2)
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/02_DOWNLOADS.md

suppressPackageStartupMessages({
  library(dplyr)
  library(tibble)
  library(jsonlite)
})

#' Gera o sumário analítico de reconciliação entre documentos descobertos, obtidos e falhos
#'
#' @param queue_df DataFrame com a fila original de documentos descobertos.
#' @param attempts_df DataFrame de fetch_attempts executados.
#' @param versions_df DataFrame de document_versions gerados com sucesso.
#' @return Lista contendo tabelas e métricas de reconciliação.
compute_reconciliation_summary <- function(queue_df, attempts_df, versions_df) {
  # Total de descobertos na fila
  discovered_total <- nrow(queue_df)

  # Documentos com versão verificada obtida
  obtained_doc_ids <- if (!is.null(versions_df) && nrow(versions_df) > 0) {
    unique(versions_df$document_id[versions_df$integrity_status == "verified"])
  } else {
    character(0)
  }
  retrieved_total <- length(obtained_doc_ids)

  # Documentos com tentativas falhas sem sucesso final
  all_attempted_doc_ids <- if (!is.null(attempts_df) && nrow(attempts_df) > 0) {
    unique(attempts_df$document_id)
  } else {
    character(0)
  }

  failed_doc_ids <- setdiff(all_attempted_doc_ids, obtained_doc_ids)
  failed_total <- length(failed_doc_ids)

  # Uma versão verificada pré-existente pode não gerar tentativa HTTP nesta
  # execução por idempotência. Nesses casos, ela já conta como obtida e não
  # deve aparecer como pendente só por não existir em fetch_attempts.
  pending_doc_ids <- setdiff(queue_df$document_id, union(all_attempted_doc_ids, obtained_doc_ids))
  pending_total <- length(pending_doc_ids)

  # 1. Reconciliação por Casa Legislativa
  by_house <- queue_df %>%
    group_by(house) %>%
    summarise(
      discovered_count = n(),
      retrieved_count = sum(document_id %in% obtained_doc_ids),
      failed_count = sum(document_id %in% failed_doc_ids),
      pending_count = sum(document_id %in% pending_doc_ids),
      success_rate_pct = round(100 * (retrieved_count / discovered_count), 2),
      .groups = "drop"
    )

  # 2. Reconciliação por Tipo Legislativo (normalized_kind)
  by_kind <- queue_df %>%
    group_by(house, normalized_kind) %>%
    summarise(
      discovered_count = n(),
      retrieved_count = sum(document_id %in% obtained_doc_ids),
      failed_count = sum(document_id %in% failed_doc_ids),
      pending_count = sum(document_id %in% pending_doc_ids),
      .groups = "drop"
    )

  # 3. Diagnóstico de Erros
  error_breakdown <- if (!is.null(attempts_df) && nrow(attempts_df) > 0) {
    attempts_df %>%
      filter(status %in% c("terminal_error", "retryable_error", "retryable_error_exhausted")) %>%
      group_by(error_code, status) %>%
      summarise(
        occurrences = n(),
        unique_documents = n_distinct(document_id),
        sample_message = first(error_message),
        .groups = "drop"
      )
  } else {
    tibble(
      error_code = character(),
      status = character(),
      occurrences = integer(),
      unique_documents = integer(),
      sample_message = character()
    )
  }

  # 4. Diagnóstico de Armazenamento e Blobs
  storage_metrics <- if (!is.null(versions_df) && nrow(versions_df) > 0) {
    list(
      total_versions_count = nrow(versions_df),
      total_bytes_received = sum(as.numeric(versions_df$file_size_bytes), na.rm = TRUE),
      unique_blobs_count = n_distinct(versions_df$file_sha256),
      storage_reuse_count = nrow(versions_df) - n_distinct(versions_df$file_sha256)
    )
  } else {
    list(
      total_versions_count = 0L,
      total_bytes_received = 0,
      unique_blobs_count = 0L,
      storage_reuse_count = 0L
    )
  }

  # 5. Propostas de URLs alternativas para itens falhos
  alternative_proposals <- list()
  if (failed_total > 0 && !is.null(attempts_df)) {
    failed_attempts <- attempts_df %>%
      filter(document_id %in% failed_doc_ids & status == "terminal_error") %>%
      distinct(document_id, requested_url, error_code, error_message)

    for (i in seq_len(min(nrow(failed_attempts), 20L))) {
      row <- failed_attempts[i, ]
      doc_info <- queue_df %>% filter(document_id == row$document_id) %>% slice_head(n = 1)
      proposal <- list(
        document_id = row$document_id,
        house = if (nrow(doc_info) > 0) doc_info$house else "unknown",
        current_url = row$requested_url,
        failure_code = row$error_code,
        note = "Proposta ao Coordenador/Agente de Inventario para revisao de URL alternativa no portal oficial"
      )
      alternative_proposals[[length(alternative_proposals) + 1]] <- proposal
    }
  }

  # Determinar estado formal de fechamento histórico para Gate GH
  coverage_status <- if (discovered_total == 0) {
    "empty_verified"
  } else if (retrieved_total == discovered_total) {
    "complete_discovered"
  } else if (retrieved_total > 0 && (failed_total > 0 || pending_total > 0)) {
    "closed_with_gaps"
  } else if (retrieved_total > 0) {
    "partial"
  } else {
    "pending"
  }

  list(
    discovered_total = discovered_total,
    retrieved_total = retrieved_total,
    failed_total = failed_total,
    pending_total = pending_total,
    coverage_status = coverage_status,
    by_house = by_house,
    by_kind = by_kind,
    error_breakdown = error_breakdown,
    storage_metrics = storage_metrics,
    alternative_proposals = alternative_proposals
  )
}
