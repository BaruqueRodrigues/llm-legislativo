# R/extraction/preflight.R
# Validação do ambiente macOS, PDFKit, Apple Vision e compilação do helper nativo Swift
# Conforme docs/CONTRATOS_DADOS.md e Frente 03

suppressPackageStartupMessages({
  library(jsonlite)
  library(digest)
})

get_repo_root <- function() {
  curr <- getwd()
  while (!file.exists(file.path(curr, "AGENTS.md")) && curr != dirname(curr)) {
    curr <- dirname(curr)
  }
  return(curr)
}

source_hashing <- function() {
  repo_root <- get_repo_root()
  hashing_path <- file.path(repo_root, "R", "inventory", "common", "hashing.R")
  if (file.exists(hashing_path)) source(hashing_path)
}

compile_swift_helper <- function(repo_root = get_repo_root(), force = FALSE) {
  native_dir <- file.path(repo_root, "R", "extraction", "native", "macos")
  source_file <- file.path(native_dir, "extract_helper.swift")
  if (!file.exists(source_file)) stop("Arquivo fonte Swift não encontrado: ", source_file)

  source_sha <- digest::digest(file = source_file, algo = "sha256")
  source(file.path(repo_root, "R", "inventory", "common", "storage.R"))
  data_root <- resolve_external_data_root(repo_root)
  bin_dir <- file.path(data_root, "cache", "macos", "extraction", source_sha)
  cache_dir <- file.path(bin_dir, "module-cache")
  dir.create(cache_dir, recursive = TRUE, showWarnings = FALSE)
  binary_file <- file.path(bin_dir, "extract_helper")
  stamp_file <- file.path(bin_dir, "extract_helper.sha256")

  should_compile <- force || !file.exists(binary_file)
  if (!should_compile && file.exists(stamp_file)) {
    cached_sha <- readLines(stamp_file, n = 1, warn = FALSE)
    if (cached_sha != source_sha) {
      should_compile <- TRUE
    }
  } else if (!should_compile && !file.exists(stamp_file)) {
    should_compile <- TRUE
  }

  if (should_compile) {
    message("Compilando helper nativo Swift (extract_helper)...")
    cmd <- sprintf(
      "swiftc -O -module-cache-path %s %s -o %s",
      shQuote(cache_dir),
      shQuote(source_file),
      shQuote(binary_file)
    )
    res <- system(cmd, intern = FALSE)
    if (res != 0) {
      stop("Falha ao compilar helper nativo Swift (código de erro: ", res, ")")
    }
    writeLines(source_sha, stamp_file)
    message("Compilação concluída com sucesso: ", binary_file)
  }

  bin_sha <- digest::digest(file = binary_file, algo = "sha256")
  list(
    binary_path = binary_file,
    source_path = source_file,
    source_sha256 = source_sha,
    binary_sha256 = bin_sha
  )
}

run_extraction_preflight <- function(repo_root = get_repo_root(), force_compile = FALSE) {
  compile_info <- compile_swift_helper(repo_root, force = force_compile)
  binary_file <- compile_info$binary_path

  # Executar preflight do helper
  cmd <- sprintf("%s --preflight", shQuote(binary_file))
  out <- tryCatch(
    system(cmd, intern = TRUE),
    error = function(e) {
      stop("Erro ao executar extract_helper --preflight: ", e$message)
    }
  )

  json_raw <- paste(out, collapse = "\n")
  preflight_data <- jsonlite::fromJSON(json_raw)

  # Obter dados do compilador Swift e SO
  swift_ver_out <- tryCatch(
    system("swift --version 2>/dev/null", intern = TRUE),
    error = function(e) "Swift desconhecido"
  )
  swift_version_str <- paste(swift_ver_out, collapse = " | ")

  sw_vers_out <- tryCatch(
    system("sw_vers 2>/dev/null", intern = TRUE),
    error = function(e) character(0)
  )
  host_build <- if (length(sw_vers_out) >= 3) {
    paste(sw_vers_out, collapse = "; ")
  } else {
    preflight_data$os_version
  }

  tool_versions <- list(
    swift_version = swift_version_str,
    macos_version = preflight_data$os_version,
    vision_default_revision = preflight_data$vision_default_revision,
    vision_supports_pt_br = isTRUE(preflight_data$supports_pt_br),
    helper_binary_sha256 = compile_info$binary_sha256,
    helper_source_sha256 = compile_info$source_sha256
  )

  list(
    preflight_passed = isTRUE(preflight_data$preflight_passed),
    host_os_build = host_build,
    helper_source_sha256 = compile_info$source_sha256,
    helper_binary_sha256 = compile_info$binary_sha256,
    tool_versions_json = as.character(jsonlite::toJSON(tool_versions, auto_unbox = TRUE)),
    binary_path = binary_file,
    details = preflight_data
  )
}
