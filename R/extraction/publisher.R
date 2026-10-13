# R/extraction/publisher.R
# Validação e publicação Parquet das 4 tabelas normativas de extração com integridade referencial
# Tabelas: extraction_runs, pages, sections, quality_reviews
# Conforme docs/CONTRATOS_DADOS.md (Seção 3 e 7) e schemas/arrow_schemas.R

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

publish_extraction_tables <- function(
  extraction_runs_df,
  pages_df,
  sections_df,
  quality_reviews_df,
  run_id = NULL,
  output_dir = NULL
) {
  repo_root <- get_repo_root()
  source(file.path(repo_root, "R", "inventory", "common", "storage.R"))
  source(file.path(repo_root, "schemas", "arrow_schemas.R"))
  data_root <- resolve_external_data_root(repo_root, output_dir)
  schemas <- get_arrow_schemas()

  if (is.null(run_id)) {
    run_id <- format(Sys.time(), "extraction_%Y%m%d_%H%M%S", tz = "UTC")
  }

  if (is.null(output_dir)) {
    output_dir <- file.path(data_root, "staging", "extraction", run_id)
  }
  output_dir <- assert_data_path(output_dir, data_root, "output_dir")
  data_root_normalized <- normalizePath(data_root, winslash = "/", mustWork = FALSE)
  output_dir_normalized <- normalizePath(output_dir, winslash = "/", mustWork = FALSE)
  output_dir_relative <- if (identical(output_dir_normalized, data_root_normalized)) {
    ""
  } else {
    substring(output_dir_normalized, nchar(data_root_normalized) + 2L)
  }
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  # 1. Validação de Chaves Primárias e Integridade Referencial
  # PK extraction_runs
  if (nrow(extraction_runs_df) == 0 || any(is.na(extraction_runs_df$extraction_id))) {
    stop("extraction_runs possui linhas com extraction_id nulo ou tabela vazia")
  }
  if (any(duplicated(extraction_runs_df$extraction_id))) {
    stop("extraction_runs possui extraction_id duplicado")
  }

  valid_ext_ids <- unique(extraction_runs_df$extraction_id)

  # PK e FK pages
  if (nrow(pages_df) > 0) {
    if (any(is.na(pages_df$extraction_id)) || any(is.na(pages_df$page_index))) {
      stop("pages possui chaves primárias nulas")
    }
    page_keys <- paste(pages_df$extraction_id, pages_df$page_index, sep = "::")
    if (any(duplicated(page_keys))) {
      stop("pages possui chave composta (extraction_id, page_index) duplicada")
    }
    if (!all(pages_df$extraction_id %in% valid_ext_ids)) {
      stop("pages possui extraction_id órfão sem correspondência em extraction_runs")
    }
  }

  # PK e FK sections
  if (nrow(sections_df) > 0) {
    if (any(is.na(sections_df$section_id)) || any(is.na(sections_df$extraction_id))) {
      stop("sections possui section_id ou extraction_id nulos")
    }
    if (any(duplicated(sections_df$section_id))) {
      stop("sections possui section_id duplicado")
    }
    if (!all(sections_df$extraction_id %in% valid_ext_ids)) {
      stop("sections possui extraction_id órfão sem correspondência em extraction_runs")
    }
  }

  # PK e FK quality_reviews
  if (nrow(quality_reviews_df) > 0) {
    if (any(is.na(quality_reviews_df$review_id)) || any(is.na(quality_reviews_df$extraction_id))) {
      stop("quality_reviews possui review_id ou extraction_id nulos")
    }
    if (any(duplicated(quality_reviews_df$review_id))) {
      stop("quality_reviews possui review_id duplicado")
    }
    if (!all(quality_reviews_df$extraction_id %in% valid_ext_ids)) {
      stop("quality_reviews possui extraction_id órfão sem correspondência em extraction_runs")
    }
  }

  # 2. Conformação estrita de tipos para esquemas Arrow
  align_table <- function(df, target_schema) {
    field_names <- names(target_schema)
    aligned_list <- list()

    for (fname in field_names) {
      target_type <- target_schema[[fname]]$type$name
      col_data <- if (fname %in% names(df)) df[[fname]] else rep(NA, nrow(df))

      # Conversão de tipo
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
      } else if (grepl("timestamp", target_type)) {
        aligned_list[[fname]] <- as.POSIXct(col_data, tz = "UTC")
      } else {
        aligned_list[[fname]] <- col_data
      }
    }

    tibble::as_tibble(aligned_list)
  }

  ext_runs_aligned <- align_table(extraction_runs_df, schemas$extraction_runs)
  pages_aligned <- align_table(pages_df, schemas$pages)
  sections_aligned <- align_table(sections_df, schemas$sections)
  reviews_aligned <- align_table(quality_reviews_df, schemas$quality_reviews)

  # 3. Escrita dos arquivos Parquet com esquema explícito
  files_meta <- list()

  write_and_record <- function(df, schema, table_name) {
    fpath <- file.path(output_dir, paste0(table_name, ".parquet"))
    arrow_table <- arrow::arrow_table(df, schema = schema)
    arrow::write_parquet(arrow_table, fpath)

    f_bytes <- file.size(fpath)
    f_sha <- digest::digest(file = fpath, algo = "sha256")

    files_meta[[table_name]] <<- list(
      path = file.path(output_dir_relative, paste0(table_name, ".parquet")),
      table_name = table_name,
      row_count = nrow(df),
      size_bytes = as.numeric(f_bytes),
      sha256 = f_sha
    )
  }

  write_and_record(ext_runs_aligned, schemas$extraction_runs, "extraction_runs")
  write_and_record(pages_aligned, schemas$pages, "pages")
  write_and_record(sections_aligned, schemas$sections, "sections")
  write_and_record(reviews_aligned, schemas$quality_reviews, "quality_reviews")

  # 4. Geração do manifesto de publicação
  published_at <- format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
  manifest <- list(
    schema_version = "2.0.0",
    stage = "extraction",
    run_id = run_id,
    created_at_utc = published_at,
    summary = list(
      extraction_runs_count = nrow(ext_runs_aligned),
      pages_count = nrow(pages_aligned),
      sections_count = nrow(sections_aligned),
      quality_reviews_count = nrow(reviews_aligned)
    ),
    files = files_meta
  )

  manifest_json <- jsonlite::toJSON(manifest, pretty = TRUE, auto_unbox = TRUE)
  manifest_path <- file.path(output_dir, "extraction_manifest.json")
  writeLines(manifest_json, manifest_path)

  manifest_sha256 <- digest::digest(file = manifest_path, algo = "sha256")

  # 5. Marcador de conclusão atômica COMPLETE.json
  complete_marker <- list(
    manifest_file = "extraction_manifest.json",
    manifest_sha256 = manifest_sha256,
    published_at_utc = published_at
  )
  complete_json <- jsonlite::toJSON(complete_marker, pretty = TRUE, auto_unbox = TRUE)
  complete_path <- file.path(output_dir, "COMPLETE.json")
  writeLines(complete_json, complete_path)

  message("Publicação de extração concluída com sucesso em: ", output_dir)
  list(
    run_id = run_id,
    output_dir = output_dir,
    manifest = manifest,
    manifest_sha256 = manifest_sha256
  )
}

validate_extraction_publication <- function(staging_dir, data_root = Sys.getenv("DATA_ROOT", unset = "")) {
  repo_root <- get_repo_root()
  source(file.path(repo_root, "schemas", "arrow_schemas.R"))
  schemas <- get_arrow_schemas()

  complete_path <- file.path(staging_dir, "COMPLETE.json")
  if (!file.exists(complete_path)) {
    return(list(valid = FALSE, error = "COMPLETE.json ausente"))
  }

  complete_data <- jsonlite::fromJSON(readLines(complete_path, warn = FALSE))
  manifest_name <- complete_data$manifest_file
  manifest_path <- file.path(staging_dir, manifest_name)

  if (!file.exists(manifest_path)) {
    return(list(valid = FALSE, error = paste("Manifesto", manifest_name, "ausente")))
  }

  actual_manifest_sha <- digest::digest(file = manifest_path, algo = "sha256")
  if (actual_manifest_sha != complete_data$manifest_sha256) {
    return(list(valid = FALSE, error = "Hash do manifesto não confere com COMPLETE.json"))
  }

  manifest_data <- jsonlite::fromJSON(readLines(manifest_path, warn = FALSE))
  if (!nzchar(data_root)) {
    return(list(valid = FALSE, error = "DATA_ROOT obrigatório para resolver os caminhos do manifesto"))
  }
  data_root <- normalizePath(path.expand(data_root), winslash = "/", mustWork = FALSE)
  staging_dir <- normalizePath(path.expand(staging_dir), winslash = "/", mustWork = FALSE)

  # Conferir cada arquivo Parquet e resolver o caminho relativo ao DATA_ROOT.

  for (tname in names(manifest_data$files)) {
    finfo <- manifest_data$files[[tname]]
    relative_path <- as.character(finfo$path)
    relative_parts <- strsplit(gsub("\\\\", "/", relative_path), "/", fixed = TRUE)[[1]]
    if (!nzchar(relative_path) || startsWith(relative_path, "/") || any(relative_parts == "..")) {
      return(list(valid = FALSE, error = paste("Caminho do manifesto inválido:", relative_path)))
    }
    fpath <- normalizePath(file.path(data_root, relative_path), winslash = "/", mustWork = FALSE)
    if (!identical(fpath, file.path(staging_dir, paste0(tname, ".parquet")))) {
      return(list(valid = FALSE, error = paste("Caminho do manifesto não corresponde à tabela:", tname)))
    }
    if (!file.exists(fpath)) {
      return(list(valid = FALSE, error = paste("Arquivo Parquet ausente:", tname)))
    }
    actual_f_sha <- digest::digest(file = fpath, algo = "sha256")
    if (actual_f_sha != finfo$sha256) {
      return(list(valid = FALSE, error = paste("Hash do arquivo Parquet corrompido:", tname)))
    }

    # Leitura e verificação de esquema Arrow
    arrow_tab <- arrow::read_parquet(fpath, as_data_frame = FALSE)
    expected_schema <- schemas[[tname]]
    if (!identical(names(arrow_tab$schema), names(expected_schema))) {
      return(list(valid = FALSE, error = paste("Colunas não conferem com esquema normativo:", tname)))
    }
  }

  list(valid = TRUE, run_id = manifest_data$run_id, summary = manifest_data$summary)
}
