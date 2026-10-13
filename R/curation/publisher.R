# R/curation/publisher.R
# Validação de integridade referencial, conformidade Arrow e publicação imutável da release curada
# Tabelas: curated_documents, corpus_item_propositions, curated_document_sections,
#          dedup_pairs, cleaning_events, quality_reviews, split_assignments
# Conforme docs/CONTRATOS_DADOS.md (Seção 4 e 7) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
  library(tibble)
  library(jsonlite)
  library(digest)
  library(bit64)
})

get_repo_root <- function() {
  curr <- getwd()
  while (!file.exists(file.path(curr, "AGENTS.md")) && curr != dirname(curr)) {
    curr <- dirname(curr)
  }
  return(curr)
}

#' Alinha tipos de colunas estritamente com o esquema Arrow de destino
align_curation_table <- function(df, target_schema) {
  field_names <- names(target_schema)
  aligned_list <- list()

  for (fname in field_names) {
    target_type <- target_schema[[fname]]$type$name
    col_data <- if (fname %in% names(df)) df[[fname]] else rep(NA, nrow(df))

    if (target_type == "string" || target_type == "utf8") {
      aligned_list[[fname]] <- as.character(col_data)
    } else if (target_type == "int32") {
      aligned_list[[fname]] <- as.integer(col_data)
    } else if (target_type == "int64") {
      aligned_list[[fname]] <- bit64::as.integer64(col_data)
    } else if (target_type == "double" || target_type == "float64") {
      aligned_list[[fname]] <- as.numeric(col_data)
    } else if (target_type == "bool" || target_type == "boolean") {
      aligned_list[[fname]] <- as.logical(col_data)
    } else if (target_type == "date32") {
      aligned_list[[fname]] <- as.Date(col_data)
    } else if (grepl("timestamp", target_type)) {
      aligned_list[[fname]] <- as.POSIXct(col_data, tz = "UTC")
    } else {
      aligned_list[[fname]] <- col_data
    }
  }

  tibble::as_tibble(aligned_list)
}

#' Valida e publica as 7 tabelas curadas, gerando release_manifest.json e COMPLETE.json
publish_curated_release <- function(
  curation_results,
  output_dir = NULL,
  release_id = NULL,
  config = NULL,
  coverage_status = "closed_with_gaps"
) {
  repo_root <- get_repo_root()
  source(file.path(repo_root, "R", "inventory", "common", "storage.R"))
  source(file.path(repo_root, "schemas", "arrow_schemas.R"))
  data_root <- resolve_external_data_root(repo_root, output_dir)
  schemas <- get_arrow_schemas()

  if (is.null(release_id)) {
    release_id <- format(Sys.time(), "release_curated_%Y%m%d_%H%M%S", tz = "UTC")
  }

  if (is.null(output_dir)) {
    output_dir <- file.path(data_root, "staging", "curation", release_id)
  }
  output_dir <- assert_data_path(output_dir, data_root, "output_dir", allow_temp = TRUE)
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  cur_docs <- curation_results$curated_documents
  cur_props <- curation_results$corpus_item_propositions
  cur_secs <- curation_results$curated_document_sections
  dedup_pairs <- curation_results$dedup_pairs
  clean_events <- curation_results$cleaning_events
  q_reviews <- curation_results$quality_reviews
  split_assigns <- curation_results$split_assignments

  # =========================================================================
  # 1. Validação Formal de Chaves e Invariantes do Gate G2
  # =========================================================================

  # PK curated_documents
  if (nrow(cur_docs) == 0) {
    stop("curated_documents não pode ser vazia na release.")
  }
  if (any(is.na(cur_docs$corpus_item_id))) {
    stop("curated_documents possui corpus_item_id nulo.")
  }
  if (any(duplicated(cur_docs$corpus_item_id))) {
    stop("curated_documents possui corpus_item_id duplicado (PK violada).")
  }
  valid_item_ids <- unique(cur_docs$corpus_item_id)

  # FK representative_item_id
  if (!all(cur_docs$representative_item_id %in% valid_item_ids)) {
    stop("curated_documents possui representative_item_id que não existe no conjunto de itens.")
  }

  # Invariante G2: Zero representantes exatos repetidos no dataset de treino
  included_items <- cur_docs %>% filter(include_in_dataset == TRUE)
  dup_exact_included <- included_items %>%
    group_by(exact_cluster_id) %>%
    filter(n() > 1)
  if (nrow(dup_exact_included) > 0) {
    stop("Invariante violada: Mais de um representante incluído no dataset para o mesmo exact_cluster_id!")
  }

  # PK e FK corpus_item_propositions
  if (nrow(cur_props) > 0) {
    if (any(is.na(cur_props$corpus_item_id)) || any(is.na(cur_props$proposition_id))) {
      stop("corpus_item_propositions possui chave composta nula.")
    }
    prop_keys <- paste(cur_props$corpus_item_id, cur_props$proposition_id, sep = "::")
    if (any(duplicated(prop_keys))) {
      stop("corpus_item_propositions possui chave composta duplicada.")
    }
    if (!all(cur_props$corpus_item_id %in% valid_item_ids)) {
      stop("corpus_item_propositions possui corpus_item_id órfão.")
    }
  }

  # PK e FK curated_document_sections
  if (nrow(cur_secs) > 0) {
    if (any(is.na(cur_secs$corpus_item_id)) || any(is.na(cur_secs$section_id))) {
      stop("curated_document_sections possui chave composta nula.")
    }
    sec_keys <- paste(cur_secs$corpus_item_id, cur_secs$section_id, sep = "::")
    if (any(duplicated(sec_keys))) {
      stop("curated_document_sections possui chave composta duplicada.")
    }
    if (!all(cur_secs$corpus_item_id %in% valid_item_ids)) {
      stop("curated_document_sections possui corpus_item_id órfão.")
    }
  }

  # PK e FK dedup_pairs
  if (nrow(dedup_pairs) > 0) {
    if (any(is.na(dedup_pairs$left_item_id)) || any(is.na(dedup_pairs$right_item_id))) {
      stop("dedup_pairs possui chave composta nula.")
    }
    pair_keys <- paste(dedup_pairs$left_item_id, dedup_pairs$right_item_id, sep = "::")
    if (any(duplicated(pair_keys))) {
      stop("dedup_pairs possui chave composta duplicada.")
    }
    # Checar ordem lexicográfica esquerda < direita
    if (any(dedup_pairs$left_item_id >= dedup_pairs$right_item_id)) {
      stop("dedup_pairs deve ter estritamente left_item_id < right_item_id.")
    }
    if (!all(dedup_pairs$left_item_id %in% valid_item_ids) || !all(dedup_pairs$right_item_id %in% valid_item_ids)) {
      stop("dedup_pairs possui item_id órfão.")
    }
  }

  # PK e FK cleaning_events
  if (nrow(clean_events) > 0) {
    if (any(is.na(clean_events$event_id))) {
      stop("cleaning_events possui event_id nulo.")
    }
    if (any(duplicated(clean_events$event_id))) {
      stop("cleaning_events possui event_id duplicado.")
    }
    if (!all(clean_events$corpus_item_id %in% valid_item_ids)) {
      stop("cleaning_events possui corpus_item_id órfão.")
    }
  }

  # PK e FK split_assignments
  if (nrow(split_assigns) > 0) {
    if (any(is.na(split_assigns$split_version)) || any(is.na(split_assigns$corpus_item_id))) {
      stop("split_assignments possui chave composta nula.")
    }
    split_keys <- paste(split_assigns$split_version, split_assigns$corpus_item_id, sep = "::")
    if (any(duplicated(split_keys))) {
      stop("split_assignments possui chave composta duplicada.")
    }
    if (!all(split_assigns$corpus_item_id %in% valid_item_ids)) {
      stop("split_assignments possui corpus_item_id órfão.")
    }

    # Invariante G2: Zero famílias cruzando splits (1 família -> 1 split)
    fam_splits <- split_assigns %>%
      group_by(family_id) %>%
      summarise(n_splits = n_distinct(split), .groups = "drop")
    leaked_fams <- fam_splits %>% filter(n_splits > 1)
    if (nrow(leaked_fams) > 0) {
      stop(sprintf("Invariante violada: %d família(s) cruzando múltiplos splits!", nrow(leaked_fams)))
    }
  }

  # =========================================================================
  # 2. Conformação aos Esquemas Arrow Normativos
  # =========================================================================

  docs_aligned <- align_curation_table(cur_docs, schemas$curated_documents)
  props_aligned <- align_curation_table(cur_props, schemas$corpus_item_propositions)
  secs_aligned <- align_curation_table(cur_secs, schemas$curated_document_sections)
  dedup_aligned <- align_curation_table(dedup_pairs, schemas$dedup_pairs)
  events_aligned <- align_curation_table(clean_events, schemas$cleaning_events)
  reviews_aligned <- align_curation_table(q_reviews, schemas$quality_reviews)
  splits_aligned <- align_curation_table(split_assigns, schemas$split_assignments)

  # =========================================================================
  # 3. Gravação Parquet e Cálculo de Metadados
  # =========================================================================

  files_meta <- list()

  write_parquet_checked <- function(df, schema, table_name) {
    fpath <- file.path(output_dir, paste0(table_name, ".parquet"))
    arrow_tbl <- arrow::arrow_table(df, schema = schema)
    arrow::write_parquet(arrow_tbl, fpath)

    f_size <- file.size(fpath)
    f_sha <- digest::digest(file = fpath, algo = "sha256")

    rel_path <- file.path(basename(dirname(output_dir)), basename(output_dir), paste0(table_name, ".parquet"))

    files_meta[[table_name]] <<- list(
      path = rel_path,
      table_name = table_name,
      row_count = nrow(df),
      size_bytes = as.numeric(f_size),
      sha256 = f_sha
    )
  }

  write_parquet_checked(docs_aligned, schemas$curated_documents, "curated_documents")
  write_parquet_checked(props_aligned, schemas$corpus_item_propositions, "corpus_item_propositions")
  write_parquet_checked(secs_aligned, schemas$curated_document_sections, "curated_document_sections")
  write_parquet_checked(dedup_aligned, schemas$dedup_pairs, "dedup_pairs")
  write_parquet_checked(events_aligned, schemas$cleaning_events, "cleaning_events")
  write_parquet_checked(reviews_aligned, schemas$quality_reviews, "quality_reviews")
  write_parquet_checked(splits_aligned, schemas$split_assignments, "split_assignments")

  # =========================================================================
  # 4. Geração de Métricas e release_manifest.json
  # =========================================================================

  # Resumo por split
  merged_split_items <- cur_docs %>%
    left_join(split_assigns %>% select(corpus_item_id, split), by = "corpus_item_id")

  split_counts <- list()
  split_bytes <- list()

  for (sp_name in c("train", "validation", "test", "quarantine")) {
    sp_items <- merged_split_items %>% filter(split == sp_name)
    split_counts[[sp_name]] <- nrow(sp_items)
    split_bytes[[sp_name]] <- sum(as.numeric(sp_items$utf8_bytes), na.rm = TRUE)
  }

  house_counts <- as.list(table(cur_docs$house))
  kind_counts <- as.list(table(cur_docs$normalized_kind))

  created_at <- format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
  manifest <- list(
    schema_version = "2.0.0",
    stage = "curation",
    corpus_version = release_id,
    created_at_utc = created_at,
    cohort_definition = "Corpus Legislativo Histórico Brasileiro (Câmara dos Deputados e Senado Federal, todas categorias textuais)",
    history_scope = "all_available",
    houses = sort(unique(cur_docs$house)),
    coverage_status = coverage_status,
    selection_policy = "representative_dedup_family_split",
    cleaning_version = if (!is.null(config$cleaning_version)) config$cleaning_version else "clean_v1",
    dedup_policy_version = if (!is.null(config$dedup_policy_version)) config$dedup_policy_version else "dedup_v1",
    split_version = if (!is.null(config$split_version)) config$split_version else "split_v1",
    seed = if (!is.null(config$seed)) as.integer(config$seed) else 42L,
    summary = list(
      total_items = nrow(cur_docs),
      accepted_items = sum(cur_docs$quality_status == "accepted"),
      quarantined_items = sum(cur_docs$quality_status == "quarantined"),
      include_in_dataset_items = sum(cur_docs$include_in_dataset == TRUE),
      exact_clusters_count = n_distinct(cur_docs$exact_cluster_id),
      families_count = n_distinct(cur_docs$family_id),
      dedup_pairs_count = nrow(dedup_pairs),
      cleaning_events_count = nrow(clean_events),
      splits = list(
        items_count = split_counts,
        utf8_bytes = split_bytes
      ),
      houses_count = house_counts,
      kinds_count = kind_counts
    ),
    files = files_meta
  )

  manifest_path <- file.path(output_dir, "release_manifest.json")
  jsonlite::write_json(manifest, manifest_path, pretty = TRUE, auto_unbox = TRUE)
  manifest_sha <- digest::digest(file = manifest_path, algo = "sha256")

  # =========================================================================
  # 5. Publicação do Marcador Atômico COMPLETE.json
  # =========================================================================

  complete_marker <- list(
    schema_version = "2.0.0",
    stage = "curation",
    corpus_version = release_id,
    manifest_sha256 = manifest_sha,
    completed_at_utc = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    status = "success"
  )

  complete_path <- file.path(output_dir, "COMPLETE.json")
  jsonlite::write_json(complete_marker, complete_path, pretty = TRUE, auto_unbox = TRUE)

  message(sprintf("[CURATION PUBLISHER] Release '%s' publicada com sucesso em '%s'.", release_id, output_dir))
  message(sprintf("                      Manifesto SHA-256: %s", manifest_sha))

  list(
    output_dir = output_dir,
    release_id = release_id,
    manifest_sha256 = manifest_sha,
    manifest = manifest
  )
}
