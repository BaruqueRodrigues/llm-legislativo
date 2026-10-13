# R/extraction/pdf_extractor.R
# Adaptador de extração nativa por página (PDFKit) com OCR seletivo Apple Vision
# Conforme docs/CONTRATOS_DADOS.md (Seção 3) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(jsonlite)
  library(digest)
  library(tibble)
  library(dplyr)
  library(yaml)
  library(bit64)
})

source_relative <- function(file_name) {
  repo_root <- getwd()
  while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
    repo_root <- dirname(repo_root)
  }
  source(file.path(repo_root, file_name))
}

load_extraction_config <- function(config_path = "configs/extraction/history.yaml") {
  repo_root <- getwd()
  while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
    repo_root <- dirname(repo_root)
  }
  full_path <- if (file.exists(config_path)) config_path else file.path(repo_root, config_path)
  if (!file.exists(full_path)) {
    stop("Arquivo de configuração não encontrado: ", full_path)
  }
  yaml::read_yaml(full_path)
}

extract_document <- function(
  pdf_path,
  version_id,
  config = load_extraction_config(),
  preflight_info = NULL,
  mode = "auto",
  enable_benchmark = FALSE
) {
  repo_root <- getwd()
  while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
    repo_root <- dirname(repo_root)
  }

  source(file.path(repo_root, "R", "inventory", "common", "cloud_storage.R"))
  cloud_pin <- materialize_cloud_blob(pdf_path, repo_root)
  on.exit(release_cloud_blob(cloud_pin, repo_root), add = TRUE)

  if (is.null(preflight_info)) {
    source(file.path(repo_root, "R", "extraction", "preflight.R"))
    preflight_info <- run_extraction_preflight(repo_root)
  }

  binary_path <- preflight_info$binary_path
  if (!file.exists(binary_path)) {
    stop("Binário extract_helper não encontrado em: ", binary_path)
  }

  started_at <- as.POSIXct(Sys.time(), tz = "UTC")

  # Hash da configuração
  config_json <- jsonlite::toJSON(config, auto_unbox = TRUE, sort_keys = TRUE)
  config_hash <- digest::digest(config_json, algo = "sha256")

  # Identificador determinístico da extração
  # extraction_id = version_id + ":ext:" + hash(config_hash + helper_source_sha256 + mode)
  ext_suffix <- digest::digest(paste(config_hash, preflight_info$helper_source_sha256, mode, sep = ":"), algo = "sha256")
  extraction_id <- paste0(version_id, ":ext:", substr(ext_suffix, 1, 16))

  # Argumentos da CLI Swift
  vision_cfg <- config$apple_vision
  rec_level <- if (enable_benchmark) "accurate" else (vision_cfg$default_mode %||% "fast")
  lang <- vision_cfg$language %||% "pt-BR"
  lang_corr <- if (is.null(vision_cfg$uses_language_correction)) "true" else tolower(as.character(vision_cfg$uses_language_correction))
  min_len <- as.integer(vision_cfg$min_text_length_threshold %||% 50)
  max_rep <- as.numeric(vision_cfg$max_replacement_char_ratio %||% 0.01)
  min_prn <- as.numeric(vision_cfg$min_printable_ratio %||% 0.95)

  cmd_args <- c(
    "--input", shQuote(pdf_path),
    "--mode", mode,
    "--recognition-level", rec_level,
    "--language", lang,
    "--language-correction", lang_corr,
    "--min-text-length", as.character(min_len),
    "--max-replacement-char-ratio", as.character(max_rep),
    "--min-printable-ratio", as.character(min_prn)
  )

  if (enable_benchmark) {
    cmd_args <- c(cmd_args, "--benchmark")
  }

  full_cmd <- paste(shQuote(binary_path), paste(cmd_args, collapse = " "))

  # Execução protegida
  raw_out <- tryCatch(
    system(full_cmd, intern = TRUE, ignore.stderr = TRUE),
    error = function(e) character(0)
  )

  json_str <- paste(raw_out, collapse = "\n")
  doc_result <- tryCatch(
    jsonlite::fromJSON(json_str, simplifyVector = FALSE),
    error = function(e) NULL
  )

  if (is.null(doc_result) || is.null(doc_result$status)) {
    # Falha grave de execução
    run_df <- tibble(
      extraction_id = extraction_id,
      version_id = version_id,
      extraction_config_hash = config_hash,
      tool_versions_json = as.character(preflight_info$tool_versions_json),
      host_os_build = preflight_info$host_os_build,
      helper_source_sha256 = preflight_info$helper_source_sha256,
      started_at = started_at,
      status = "failed",
      error_code = "execution_or_parse_failed"
    )

    return(list(
      run = run_df,
      pages = tibble(),
      benchmark = list(),
      status = "failed"
    ))
  }

  run_status <- if (doc_result$status == "succeeded") "succeeded" else "failed"
  err_code <- doc_result$error_code

  run_df <- tibble(
    extraction_id = extraction_id,
    version_id = version_id,
    extraction_config_hash = config_hash,
    tool_versions_json = as.character(preflight_info$tool_versions_json),
    host_os_build = preflight_info$host_os_build,
    helper_source_sha256 = preflight_info$helper_source_sha256,
    started_at = started_at,
    status = run_status,
    error_code = if (is.null(err_code)) NA_character_ else as.character(err_code)
  )

  if (run_status != "succeeded" || length(doc_result$pages) == 0) {
    return(list(
      run = run_df,
      pages = tibble(),
      benchmark = list(),
      status = run_status
    ))
  }

  # Montagem da tabela pages conforme schemas/arrow_schemas.R
  pages_list <- lapply(doc_result$pages, function(p) {
    q_reasons_json <- jsonlite::toJSON(p$quality_reasons %||% list(), auto_unbox = FALSE)

    tibble(
      extraction_id = extraction_id,
      page_index = as.integer(p$page_index),
      method = as.character(p$method),
      engine = as.character(p$engine),
      engine_revision = if (is.null(p$engine_revision)) NA_character_ else as.character(p$engine_revision),
      recognition_level = if (is.null(p$recognition_level)) NA_character_ else as.character(p$recognition_level),
      recognition_languages_json = if (is.null(p$recognition_languages_json)) NA_character_ else as.character(p$recognition_languages_json),
      uses_language_correction = if (is.null(p$uses_language_correction)) NA else as.logical(p$uses_language_correction),
      render_width = if (is.null(p$render_width)) NA_integer_ else as.integer(p$render_width),
      render_height = if (is.null(p$render_height)) NA_integer_ else as.integer(p$render_height),
      elapsed_ms = as.numeric(p$elapsed_ms %||% NA_real_),
      raw_text = as.character(p$raw_text %||% ""),
      raw_text_sha256 = as.character(p$raw_text_sha256 %||% NA_character_),
      character_count = as.integer64(p$character_count %||% 0),
      replacement_char_ratio = as.numeric(p$replacement_char_ratio %||% 0.0),
      printable_ratio = as.numeric(p$printable_ratio %||% 1.0),
      image_area_ratio = as.numeric(p$image_area_ratio %||% 0.0),
      ocr_confidence = if (is.null(p$ocr_confidence)) NA_real_ else as.numeric(p$ocr_confidence),
      layout_path = NA_character_,
      layout_sha256 = NA_character_,
      quality_status = as.character(p$quality_status %||% "pass"),
      quality_reasons_json = as.character(q_reasons_json)
    )
  })

  pages_df <- dplyr::bind_rows(pages_list)

  # Extrair benchmarks se houver
  benchmarks_list <- lapply(doc_result$pages, function(p) {
    if (!is.null(p$benchmark)) {
      b <- p$benchmark
      b$page_index <- p$page_index
      b$extraction_id <- extraction_id
      return(b)
    }
    NULL
  })
  benchmarks_list <- Filter(Negate(is.null), benchmarks_list)

  list(
    run = run_df,
    pages = pages_df,
    benchmark = benchmarks_list,
    status = run_status,
    raw_result = doc_result
  )
}
