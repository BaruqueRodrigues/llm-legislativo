# R/inventory/senado/publisher.R
# Validador de integridade referencial e publicador Parquet do inventário do Senado
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0) e docs/subagents/10_SENADO.md

suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))

# Coerção estrita de tipos para casar 100% com os esquemas Arrow
coerce_df_to_arrow_schema <- function(df, table_name) {
  schemas <- get_arrow_schemas()
  if (!table_name %in% names(schemas)) {
    stop(paste("Tabela nao cadastrada nos esquemas normativos:", table_name))
  }
  target_schema <- schemas[[table_name]]
  field_names <- names(target_schema)

  # Adicionar colunas ausentes como NA tipado
  for (f in field_names) {
    if (!f %in% names(df)) {
      df[[f]] <- NA
    }
  }

  # Selecionar e ordenar exatamente como o esquema
  df <- df[, field_names, drop = FALSE]

  # Coagir campos conforme o tipo Arrow
  for (i in seq_along(field_names)) {
    f_name <- field_names[i]
    arrow_type <- target_schema[[i]]$type

    if (inherits(arrow_type, "StringType") || arrow_type$ToString() == "string") {
      df[[f_name]] <- as.character(df[[f_name]])
    } else if (inherits(arrow_type, "Int32Type") || arrow_type$ToString() == "int32") {
      df[[f_name]] <- as.integer(df[[f_name]])
    } else if (inherits(arrow_type, "Int64Type") || arrow_type$ToString() == "int64") {
      df[[f_name]] <- bit64::as.integer64(df[[f_name]])
    } else if (inherits(arrow_type, "BooleanType") || arrow_type$ToString() == "bool") {
      df[[f_name]] <- as.logical(df[[f_name]])
    } else if (inherits(arrow_type, "FloatType") || inherits(arrow_type, "DoubleType") || grepl("double|float", arrow_type$ToString())) {
      df[[f_name]] <- as.numeric(df[[f_name]])
    } else if (inherits(arrow_type, "Date32Type") || arrow_type$ToString() == "date32[day]") {
      df[[f_name]] <- as.Date(df[[f_name]])
    } else if (inherits(arrow_type, "TimestampType") || grepl("timestamp", arrow_type$ToString())) {
      df[[f_name]] <- as.POSIXct(df[[f_name]], tz = "UTC")
    }
  }

  df
}

# Verificação rigorosa de integridade referencial (FK) e unicidade de chaves (PK)
validate_senado_integrity <- function(tables) {
  errors <- character()

  # 1. Unicidade de PKs
  check_pk_uniqueness <- function(df, pk_col, table_name) {
    if (nrow(df) > 0) {
      dups <- sum(duplicated(df[[pk_col]]))
      if (dups > 0) {
        return(paste0("Chave primaria duplicada em ", table_name, "$", pk_col, ": ", dups, " registros"))
      }
    }
    NULL
  }

  err <- check_pk_uniqueness(tables$source_snapshots, "snapshot_id", "source_snapshots")
  if (!is.null(err)) errors <- c(errors, err)

  err <- check_pk_uniqueness(tables$propositions, "proposition_id", "propositions")
  if (!is.null(err)) errors <- c(errors, err)

  err <- check_pk_uniqueness(tables$documents, "document_id", "documents")
  if (!is.null(err)) errors <- c(errors, err)

  err <- check_pk_uniqueness(tables$authors, "author_id", "authors")
  if (!is.null(err)) errors <- c(errors, err)

  err <- check_pk_uniqueness(tables$process_phases, "phase_id", "process_phases")
  if (!is.null(err)) errors <- c(errors, err)

  err <- check_pk_uniqueness(tables$source_collections, "collection_id", "source_collections")
  if (!is.null(err)) errors <- c(errors, err)

  err <- check_pk_uniqueness(tables$coverage_segments, "segment_id", "coverage_segments")
  if (!is.null(err)) errors <- c(errors, err)

  # 2. Integridade Referencial (FKs)
  # proposition_documents -> propositions e documents
  if (nrow(tables$proposition_documents) > 0) {
    missing_prop <- setdiff(tables$proposition_documents$proposition_id, tables$propositions$proposition_id)
    if (length(missing_prop) > 0) {
      errors <- c(errors, paste("proposition_documents referencia proposition_id inexistente:", length(missing_prop)))
    }
    missing_doc <- setdiff(tables$proposition_documents$document_id, tables$documents$document_id)
    if (length(missing_doc) > 0) {
      errors <- c(errors, paste("proposition_documents referencia document_id inexistente:", length(missing_doc)))
    }
  }

  # document_phases -> documents e process_phases
  if (nrow(tables$document_phases) > 0) {
    missing_doc <- setdiff(tables$document_phases$document_id, tables$documents$document_id)
    if (length(missing_doc) > 0) {
      errors <- c(errors, paste("document_phases referencia document_id inexistente:", length(missing_doc)))
    }
    missing_phase <- setdiff(tables$document_phases$phase_id, tables$process_phases$phase_id)
    if (length(missing_phase) > 0) {
      errors <- c(errors, paste("document_phases referencia phase_id inexistente:", length(missing_phase)))
    }
  }

  # proposition_authors -> propositions e authors
  if (nrow(tables$proposition_authors) > 0) {
    missing_prop <- setdiff(tables$proposition_authors$proposition_id, tables$propositions$proposition_id)
    if (length(missing_prop) > 0) {
      errors <- c(errors, paste("proposition_authors referencia proposition_id inexistente:", length(missing_prop)))
    }
    missing_auth <- setdiff(tables$proposition_authors$author_id, tables$authors$author_id)
    if (length(missing_auth) > 0) {
      errors <- c(errors, paste("proposition_authors referencia author_id inexistente:", length(missing_auth)))
    }
  }

  # document_authors -> documents e authors
  if (nrow(tables$document_authors) > 0) {
    missing_doc <- setdiff(tables$document_authors$document_id, tables$documents$document_id)
    if (length(missing_doc) > 0) {
      errors <- c(errors, paste("document_authors referencia document_id inexistente:", length(missing_doc)))
    }
    missing_auth <- setdiff(tables$document_authors$author_id, tables$authors$author_id)
    if (length(missing_auth) > 0) {
      errors <- c(errors, paste("document_authors referencia author_id inexistente:", length(missing_auth)))
    }
  }

  # coverage_segments -> source_collections
  if (nrow(tables$coverage_segments) > 0) {
    missing_col <- setdiff(tables$coverage_segments$collection_id, tables$source_collections$collection_id)
    if (length(missing_col) > 0) {
      errors <- c(errors, paste("coverage_segments referencia collection_id inexistente:", length(missing_col)))
    }
  }

  if (length(errors) > 0) {
    stop(paste("Falhas de integridade referencial encontradas:\n", paste(errors, collapse = "\n")))
  }

  TRUE
}

# Publicação atômica das tabelas Parquet com COMPLETE.json
publish_senado_inventory <- function(tables, target_dir, run_id = NULL) {
  if (is.null(run_id)) {
    run_id <- paste0("senado_inventory_", format(Sys.time(), "%Y%m%d_%H%M%S", tz = "UTC"))
  }

  # Validar integridade referencial antes de gravar
  validate_senado_integrity(tables)

  output_dir <- file.path(target_dir, run_id)
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  published_files <- list()
  table_summaries <- list()

  for (t_name in names(tables)) {
    raw_df <- tables[[t_name]]
    typed_df <- coerce_df_to_arrow_schema(raw_df, t_name)

    target_file <- file.path(output_dir, paste0(t_name, ".parquet"))
    res <- write_contract_parquet(typed_df, t_name, target_file)

    published_files[[t_name]] <- list(
      file = basename(res$path),
      row_count = res$row_count,
      size_bytes = res$size_bytes,
      sha256 = res$sha256
    )

    table_summaries[[t_name]] <- res$row_count
  }

  # Montar manifesto da publicação
  manifest_obj <- list(
    manifest_version = "2.0.0",
    house = "senado",
    run_id = run_id,
    published_at_utc = strftime(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    gate = "G1",
    tables = published_files,
    summary = table_summaries
  )

  manifest_path <- file.path(output_dir, "manifest.json")
  pub_res <- publish_manifest_with_complete(manifest_obj, manifest_path)

  list(
    run_id = run_id,
    output_dir = output_dir,
    manifest_path = pub_res$manifest_path,
    complete_path = pub_res$complete_path,
    tables_summary = table_summaries
  )
}
