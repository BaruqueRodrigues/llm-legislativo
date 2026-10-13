# R/curation/cleaner.R
# Limpeza mínima e preservação de conteúdo substantivo com rastreamento de eventos
# Conforme docs/CONTRATOS_DADOS.md (Seção 6) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(digest)
  library(jsonlite)
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

#' Limpa o texto de um documento conforme as regras configuradas,
#' gerando registros para cleaning_events sempre que houver alteração.
#'
#' @param text String com o texto original da extração
#' @param corpus_item_id Identificador determinístico do item curado
#' @param config Configuração carregada de history.yaml
#' @return list(cleaned_text = string, events = tibble(cleaning_events))
clean_document_text <- function(text, corpus_item_id, config) {
  if (is.null(text) || is.na(text) || nchar(text) == 0) {
    return(list(
      cleaned_text = "",
      events = tibble::tibble(
        event_id = character(),
        corpus_item_id = character(),
        rule_id = character(),
        before_sha256 = character(),
        after_sha256 = character(),
        affected_spans_json = character(),
        reason = character()
      )
    ))
  }

  current_text <- text
  events_list <- list()
  evt_idx <- 1L

  clean_cfg <- if (!is.null(config$cleaning)) config$cleaning else list()
  preserve_case <- isTRUE(clean_cfg$preserve_case)
  preserve_accents <- isTRUE(clean_cfg$preserve_accents)
  preserve_structure <- isTRUE(clean_cfg$preserve_structure)
  normalize_crlf <- isTRUE(clean_cfg$normalize_linebreaks_crlf_to_lf)
  remove_signatures <- isTRUE(clean_cfg$remove_digital_signatures)
  remove_headers_footers <- isTRUE(clean_cfg$remove_running_headers_footers)

  # 1. Normalização de quebras de linha CRLF / CR -> LF
  if (normalize_crlf) {
    if (grepl("\r", current_text, fixed = TRUE)) {
      before_hash <- hash_string(current_text)
      # Achar posições afetadas
      cr_matches <- stringr::str_locate_all(current_text, "\r\n|\r")[[1]]
      spans <- if (nrow(cr_matches) > 0) {
        lapply(seq_len(min(nrow(cr_matches), 50L)), function(i) {
          list(start = as.integer(cr_matches[i, 1] - 1L), end = as.integer(cr_matches[i, 2]))
        })
      } else {
        list()
      }

      current_text <- gsub("\r\n", "\n", current_text, fixed = TRUE)
      current_text <- gsub("\r", "\n", current_text, fixed = TRUE)
      after_hash <- hash_string(current_text)

      if (before_hash != after_hash) {
        event_id <- paste0("clean_evt:", hash_string(paste(corpus_item_id, "crlf_to_lf", before_hash)))
        events_list[[evt_idx]] <- list(
          event_id = event_id,
          corpus_item_id = corpus_item_id,
          rule_id = "crlf_to_lf",
          before_sha256 = before_hash,
          after_sha256 = after_hash,
          affected_spans_json = jsonlite::toJSON(spans, auto_unbox = TRUE),
          reason = "Uniformização determinística de quebras CRLF/CR para LF"
        )
        evt_idx <- evt_idx + 1L
      }
    }
  }

  # 2. Remoção de assinaturas digitais / carimbos de certificação
  # Preserva assinaturas substantivas de parlamentares (ex: "Deputado Fulano, Relator")
  if (remove_signatures) {
    sig_pattern <- "(?i)(\n[^\n]*(Assinado digitalmente por|Documento assinado digitalmente|ICP-Brasil|Para verificar as assinaturas, acesse|Chave de verificação:|Este documento foi assinado digitalmente|Certificação digital)[^\n]*)"
    if (grepl(sig_pattern, current_text, perl = TRUE)) {
      before_hash <- hash_string(current_text)
      sig_matches <- stringr::str_locate_all(current_text, stringr::regex(sig_pattern, dotall = FALSE))[[1]]
      spans <- if (nrow(sig_matches) > 0) {
        lapply(seq_len(nrow(sig_matches)), function(i) {
          list(start = as.integer(sig_matches[i, 1] - 1L), end = as.integer(sig_matches[i, 2]))
        })
      } else {
        list()
      }

      current_text <- stringr::str_replace_all(current_text, stringr::regex(sig_pattern, dotall = FALSE), "\n")
      # Limpar eventuais quebras múltiplas geradas na cauda
      current_text <- gsub("\n{3,}", "\n\n", current_text)
      after_hash <- hash_string(current_text)

      if (before_hash != after_hash) {
        event_id <- paste0("clean_evt:", hash_string(paste(corpus_item_id, "remove_digital_signatures", before_hash)))
        events_list[[evt_idx]] <- list(
          event_id = event_id,
          corpus_item_id = corpus_item_id,
          rule_id = "remove_digital_signatures",
          before_sha256 = before_hash,
          after_sha256 = after_hash,
          affected_spans_json = jsonlite::toJSON(spans, auto_unbox = TRUE),
          reason = "Remoção de carimbo/metadados de certificação digital externa sem alterar nomes substantivos"
        )
        evt_idx <- evt_idx + 1L
      }
    }
  }

  # 3. Remoção de cabeçalhos/rodapés correntes repetitivos e números de página
  if (remove_headers_footers) {
    # Padrão: linhas isoladas com numeração de página ou códigos mecânicos de tramitação
    hf_pattern <- "(?i)(\n[ \t]*(Página|Pag\\.|Folha|Fl\\.)[ \t]+\\d+([ \t]+de[ \t]+\\d+)?[ \t]*\n|\n[ \t]*(CD|SF)/\\d{6,}[ \t]*\n)"
    if (grepl(hf_pattern, current_text, perl = TRUE)) {
      before_hash <- hash_string(current_text)
      hf_matches <- stringr::str_locate_all(current_text, stringr::regex(hf_pattern, dotall = FALSE))[[1]]
      spans <- if (nrow(hf_matches) > 0) {
        lapply(seq_len(nrow(hf_matches)), function(i) {
          list(start = as.integer(hf_matches[i, 1] - 1L), end = as.integer(hf_matches[i, 2]))
        })
      } else {
        list()
      }

      current_text <- stringr::str_replace_all(current_text, stringr::regex(hf_pattern, dotall = FALSE), "\n")
      current_text <- gsub("\n{3,}", "\n\n", current_text)
      after_hash <- hash_string(current_text)

      if (before_hash != after_hash) {
        event_id <- paste0("clean_evt:", hash_string(paste(corpus_item_id, "remove_running_headers_footers", before_hash)))
        events_list[[evt_idx]] <- list(
          event_id = event_id,
          corpus_item_id = corpus_item_id,
          rule_id = "remove_running_headers_footers",
          before_sha256 = before_hash,
          after_sha256 = after_hash,
          affected_spans_json = jsonlite::toJSON(spans, auto_unbox = TRUE),
          reason = "Remoção de cabeçalhos/rodapés correntes mecânicos e números de página isolados"
        )
        evt_idx <- evt_idx + 1L
      }
    }
  }

  # Invariantes: Preservar maiúsculas/minúsculas, acentuação e estrutura jurídica
  # O texto final mantém sua formatação original
  events_df <- if (length(events_list) > 0) {
    dplyr::bind_rows(lapply(events_list, tibble::as_tibble))
  } else {
    tibble::tibble(
      event_id = character(),
      corpus_item_id = character(),
      rule_id = character(),
      before_sha256 = character(),
      after_sha256 = character(),
      affected_spans_json = character(),
      reason = character()
    )
  }

  list(
    cleaned_text = current_text,
    events = events_df
  )
}
