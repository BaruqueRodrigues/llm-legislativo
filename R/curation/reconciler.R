# R/curation/reconciler.R
# Reconciliação do universo histórico e encadeamento fonte -> documento -> captura -> versão -> página -> texto
# Conforme docs/CONTRATOS_DADOS.md (Seção 1, 2, 3 e 4) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(digest)
  library(dplyr)
  library(tibble)
  library(jsonlite)
  library(bit64)
})

get_repo_root <- function() {
  curr <- getwd()
  while (!file.exists(file.path(curr, "AGENTS.md")) && curr != dirname(curr)) {
    curr <- dirname(curr)
  }
  return(curr)
}

repo_root <- get_repo_root()
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))
source(file.path(repo_root, "R", "curation", "cleaner.R"))
source(file.path(repo_root, "R", "curation", "containment_dedup.R"))
source(file.path(repo_root, "R", "curation", "family_graph.R"))
source(file.path(repo_root, "R", "curation", "split_engine.R"))

#' Reconcilia os dados do inventário, downloads e extração em tabelas curadas
reconcile_curation_corpus <- function(
  inventory_props_df = NULL,
  inventory_docs_df = NULL,
  prop_docs_df = NULL,
  relations_df = NULL,
  entity_aliases_df = NULL,
  process_phases_df = NULL,
  document_phases_df = NULL,
  use_evidence_df = NULL,
  doc_versions_df = NULL,
  extraction_runs_df = NULL,
  pages_df = NULL,
  sections_df = NULL,
  quality_reviews_df = NULL,
  config = NULL
) {
  clean_version <- if (!is.null(config$cleaning_version)) config$cleaning_version else "clean_v1"
  composition_id <- "comp_standard_v1"

  # Listas acumuladoras
  raw_items_list <- list()
  cleaning_events_list <- list()
  curated_sections_list <- list()
  item_props_list <- list()

  # Se houver extrações, iterar sobre cada extraction_run
  if (!is.null(extraction_runs_df) && nrow(extraction_runs_df) > 0) {
    for (i in seq_len(nrow(extraction_runs_df))) {
      ext_row <- extraction_runs_df[i, ]
      ext_id <- ext_row$extraction_id
      ver_id <- ext_row$version_id
      ext_status <- ext_row$status

      # Identificar documento correspondente
      doc_id <- NA_character_
      if (!is.null(doc_versions_df) && nrow(doc_versions_df) > 0) {
        matching_ver <- doc_versions_df %>% filter(version_id == ver_id)
        if (nrow(matching_ver) > 0) {
          doc_id <- matching_ver$document_id[1]
        }
      }

      # Fallback determinístico de document_id se não encontrado em doc_versions
      if (is.na(doc_id) || doc_id == "") {
        if (grepl("^doc:v1:", ver_id)) {
          doc_id <- paste0("doc:", sub("^doc:v1:", "", ver_id))
        } else if (grepl(":v:", ver_id)) {
          doc_id <- sub(":v:.*", "", ver_id)
        } else {
          doc_id <- paste0("doc:", hash_string(ver_id))
        }
      }

      # Buscar metadados do documento em inventory_docs_df
      doc_meta <- NULL
      if (!is.null(inventory_docs_df) && nrow(inventory_docs_df) > 0) {
        matching_doc <- inventory_docs_df %>% filter(document_id == doc_id)
        if (nrow(matching_doc) > 0) {
          doc_meta <- matching_doc[1, ]
        }
      }

      house_val <- if (!is.null(doc_meta) && !is.na(doc_meta$house)) {
        doc_meta$house
      } else if (grepl("^senado", doc_id)) {
        "senado"
      } else {
        "camara"
      }

      norm_kind <- if (!is.null(doc_meta) && !is.na(doc_meta$normalized_kind)) {
        doc_meta$normalized_kind
      } else {
        "initial"
      }

      pub_date <- if (!is.null(doc_meta) && !is.na(doc_meta$publication_date)) {
        as.Date(doc_meta$publication_date)
      } else {
        as.Date(NA)
      }

      logical_unit <- build_logical_unit_id(doc_id)

      # Reconstituir texto a partir de sections ou pages
      doc_text <- ""
      doc_sections <- if (!is.null(sections_df) && nrow(sections_df) > 0) {
        sections_df %>% filter(extraction_id == ext_id) %>% arrange(page_start, ordinal)
      } else {
        tibble::tibble()
      }

      if (nrow(doc_sections) > 0) {
        doc_text <- paste(doc_sections$text, collapse = "\n\n")
      } else if (!is.null(pages_df) && nrow(pages_df) > 0) {
        doc_pages <- pages_df %>% filter(extraction_id == ext_id) %>% arrange(page_index)
        if (nrow(doc_pages) > 0) {
          doc_text <- paste(doc_pages$raw_text, collapse = "\n\f\n")
        }
      }

      # Gerar corpus_item_id canônico determinístico
      canonical_meta <- list(
        document_id = doc_id,
        version_id = ver_id,
        extraction_id = ext_id,
        logical_unit_id = logical_unit,
        composition_id = composition_id
      )
      corpus_item_id <- paste0("item:", hash_string(jsonlite::toJSON(canonical_meta, auto_unbox = TRUE)))

      # Limpeza textual com registro de eventos
      cleaned_res <- clean_document_text(doc_text, corpus_item_id, config)
      cleaned_text <- cleaned_res$cleaned_text
      if (nrow(cleaned_res$events) > 0) {
        cleaning_events_list[[length(cleaning_events_list) + 1L]] <- cleaned_res$events
      }

      # Registrar pontes com sections
      if (nrow(doc_sections) > 0) {
        cur_sec_df <- tibble::tibble(
          corpus_item_id = rep(corpus_item_id, nrow(doc_sections)),
          section_id = doc_sections$section_id,
          output_order = as.integer(doc_sections$ordinal),
          included = rep(TRUE, nrow(doc_sections)),
          reason = rep("canonical_section", nrow(doc_sections))
        )
        curated_sections_list[[length(curated_sections_list) + 1L]] <- cur_sec_df
      }

      # Buscar vinculações com proposições
      primary_prop_id <- NA_character_
      pres_date <- as.Date(NA)

      if (!is.null(prop_docs_df) && nrow(prop_docs_df) > 0) {
        matching_pdocs <- prop_docs_df %>% filter(document_id == doc_id)
        if (nrow(matching_pdocs) > 0) {
          primary_prop_id <- matching_pdocs$proposition_id[1]

          for (p_idx in seq_len(nrow(matching_pdocs))) {
            p_row <- matching_pdocs[p_idx, ]
            l_type <- if (!is.na(p_row$document_role)) p_row$document_role else "document_for"
            g_pol <- if (l_type == "mention") "do_not_bind" else "bind"

            item_props_list[[length(item_props_list) + 1L]] <- tibble::tibble(
              corpus_item_id = corpus_item_id,
              proposition_id = p_row$proposition_id,
              link_type = l_type,
              grouping_policy = g_pol,
              evidence = if (!is.na(p_row$role_evidence)) p_row$role_evidence else "reconciliation"
            )
          }

          if (!is.null(inventory_props_df) && nrow(inventory_props_df) > 0) {
            matching_prop <- inventory_props_df %>% filter(proposition_id == primary_prop_id)
            if (nrow(matching_prop) > 0 && !is.na(matching_prop$presentation_date[1])) {
              pres_date <- as.Date(matching_prop$presentation_date[1])
            }
          }
        }
      }

      # Se pub_date for nula, usar pres_date como fallback conservador
      final_content_date <- if (!is.na(pub_date)) pub_date else pres_date
      date_evid <- if (!is.na(pub_date)) "publication_date" else if (!is.na(pres_date)) "presentation_date" else "none"
      date_stat <- if (!is.na(final_content_date)) "verified" else "unknown"

      # Avaliação de qualidade do item
      q_status <- "accepted"
      elig_reason <- "elegivel"

      if (ext_status == "failed" || nchar(trimws(cleaned_text)) == 0) {
        q_status <- "quarantined"
        elig_reason <- paste0("falha_extracao_ou_vazio: ", ifelse(is.na(ext_row$error_code), "sem_texto", ext_row$error_code))
      }

      # Permissão de uso
      perm_stat <- "allowed"
      if (!is.null(use_evidence_df) && nrow(use_evidence_df) > 0) {
        if ("permission_status" %in% names(use_evidence_df)) {
          perm_stat <- use_evidence_df$permission_status[1]
        }
      }

      txt_sha <- hash_string(cleaned_text)
      cmp_sha <- hash_string(stringr::str_squish(cleaned_text))

      raw_items_list[[length(raw_items_list) + 1L]] <- tibble::tibble(
        corpus_item_id = corpus_item_id,
        primary_proposition_id = primary_prop_id,
        document_id = doc_id,
        house = house_val,
        normalized_kind = norm_kind,
        content_date = final_content_date,
        content_date_start = as.Date(NA),
        content_date_end = as.Date(NA),
        temporal_date_evidence = date_evid,
        temporal_date_status = date_stat,
        version_id = ver_id,
        extraction_id = ext_id,
        composition_id = composition_id,
        logical_unit_id = logical_unit,
        source_span_start = 0L,
        source_span_end = as.integer(nchar(cleaned_text)),
        text = cleaned_text,
        text_sha256 = txt_sha,
        comparison_sha256 = cmp_sha,
        utf8_bytes = as.integer(nchar(cleaned_text, type = "bytes")),
        character_count = as.integer(nchar(cleaned_text)),
        cleaning_version = clean_version,
        presentation_date = pres_date,
        quality_status = q_status,
        eligibility_reason = elig_reason,
        exact_cluster_id = NA_character_,
        family_id = NA_character_,
        near_cluster_id = NA_character_,
        representative_item_id = corpus_item_id,
        include_in_dataset = (q_status == "accepted"),
        permission_status = perm_stat
      )
    }
  }

  items_df <- if (length(raw_items_list) > 0) {
    dplyr::bind_rows(raw_items_list)
  } else {
    tibble::tibble(
      corpus_item_id = character(),
      primary_proposition_id = character(),
      document_id = character(),
      house = character(),
      normalized_kind = character(),
      content_date = as.Date(character()),
      content_date_start = as.Date(character()),
      content_date_end = as.Date(character()),
      temporal_date_evidence = character(),
      temporal_date_status = character(),
      version_id = character(),
      extraction_id = character(),
      composition_id = character(),
      logical_unit_id = character(),
      source_span_start = integer(),
      source_span_end = integer(),
      text = character(),
      text_sha256 = character(),
      comparison_sha256 = character(),
      utf8_bytes = integer(),
      character_count = integer(),
      cleaning_version = character(),
      presentation_date = as.Date(character()),
      quality_status = character(),
      eligibility_reason = character(),
      exact_cluster_id = character(),
      family_id = character(),
      near_cluster_id = character(),
      representative_item_id = character(),
      include_in_dataset = logical(),
      permission_status = character()
    )
  }

  cleaning_events_df <- if (length(cleaning_events_list) > 0) {
    dplyr::bind_rows(cleaning_events_list)
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

  curated_sections_df <- if (length(curated_sections_list) > 0) {
    dplyr::bind_rows(curated_sections_list)
  } else {
    tibble::tibble(
      corpus_item_id = character(),
      section_id = character(),
      output_order = integer(),
      included = logical(),
      reason = character()
    )
  }

  item_props_df <- if (length(item_props_list) > 0) {
    dplyr::bind_rows(item_props_list)
  } else {
    tibble::tibble(
      corpus_item_id = character(),
      proposition_id = character(),
      link_type = character(),
      grouping_policy = character(),
      evidence = character()
    )
  }

  # Executar deduplicação exata e próxima
  dedup_res <- run_deduplication(items_df, config)
  items_df <- dedup_res$items
  dedup_pairs_df <- dedup_res$dedup_pairs

  # Construir grafo de famílias e atribuir family_id
  items_df <- build_family_graph(
    items_df = items_df,
    relations_df = relations_df,
    proposition_documents_df = prop_docs_df,
    entity_aliases_df = entity_aliases_df,
    process_phases_df = process_phases_df,
    document_phases_df = document_phases_df,
    dedup_pairs_df = dedup_pairs_df,
    config = config
  )

  # Atribuir splits (group_hash / temporal_purged)
  splits_df <- assign_splits(items_df, config)

  # Quality reviews (passar adiante se houver)
  q_reviews_df <- if (!is.null(quality_reviews_df) && nrow(quality_reviews_df) > 0) {
    # Mapear corpus_item_id se nulo
    rev_df <- quality_reviews_df
    if (!"corpus_item_id" %in% names(rev_df) || any(is.na(rev_df$corpus_item_id))) {
      ext_to_item <- setNames(items_df$corpus_item_id, items_df$extraction_id)
      rev_df$corpus_item_id <- ext_to_item[rev_df$extraction_id]
    }
    rev_df
  } else {
    tibble::tibble(
      review_id = character(),
      extraction_id = character(),
      corpus_item_id = character(),
      page_index = integer(),
      reviewer = character(),
      sample_seed = bit64::integer64(),
      stratum = character(),
      result = character(),
      cer = numeric(),
      wer = numeric(),
      reviewed_at = as.POSIXct(character(), tz = "UTC"),
      notes = character()
    )
  }

  list(
    curated_documents = items_df,
    corpus_item_propositions = item_props_df,
    curated_document_sections = curated_sections_df,
    dedup_pairs = dedup_pairs_df,
    cleaning_events = cleaning_events_df,
    quality_reviews = q_reviews_df,
    split_assignments = splits_df
  )
}
