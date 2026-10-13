# R/inventory/common/storage.R
# Gerenciamento de armazenamento atômico, Parquet tipado e manifestos com COMPLETE.json

suppressPackageStartupMessages({
  library(arrow)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "inventory", "common", "cloud_storage.R"))

resolve_external_data_root <- function(repo_root = getwd(), explicit_test_path = NULL) {
  raw_root <- Sys.getenv("DATA_ROOT", unset = "")
  if (!is.null(explicit_test_path)) {
    candidate <- path.expand(explicit_test_path)
    temp_root <- normalizePath(tempdir(), winslash = "/", mustWork = TRUE)
    # Canonicalizar o ancestral existente evita diferenças de symlink em macOS
    # (por exemplo /var/folders versus /private/var/folders) para tempfile() ainda inexistente.
    unresolved <- basename(candidate)
    existing_parent <- dirname(candidate)
    while (!dir.exists(existing_parent) && existing_parent != dirname(existing_parent)) {
      unresolved <- file.path(basename(existing_parent), unresolved)
      existing_parent <- dirname(existing_parent)
    }
    canonical_parent <- normalizePath(existing_parent, winslash = "/", mustWork = TRUE)
    candidate_canonical <- normalizePath(file.path(canonical_parent, unresolved), winslash = "/", mustWork = FALSE)
    if (identical(candidate_canonical, temp_root) || startsWith(candidate_canonical, paste0(temp_root, "/"))) {
      return(candidate_canonical)
    }
    checkout <- normalizePath(repo_root, winslash = "/", mustWork = FALSE)
    if (identical(candidate_canonical, checkout) || startsWith(candidate_canonical, paste0(checkout, "/"))) {
      stop("DATA_ROOT não pode estar dentro do checkout.")
    }
    configured_root <- if (nzchar(raw_root)) normalizePath(path.expand(raw_root), winslash = "/", mustWork = FALSE) else ""
    configured_absolute <- startsWith(raw_root, "/") || grepl("^[A-Za-z]:[/]", raw_root)
    if (!nzchar(configured_root) || !configured_absolute ||
        (identical(configured_root, checkout) || startsWith(configured_root, paste0(checkout, "/")))) {
      stop("DATA_ROOT explícito deve ser absoluto e externo ao checkout.")
    }
    if (identical(candidate_canonical, configured_root) || startsWith(candidate_canonical, paste0(configured_root, "/"))) {
      return(configured_root)
    }
    stop("O caminho de dados explícito deve estar em DATA_ROOT ou em um diretório temporário de teste.")
  }
  if (!nzchar(raw_root)) stop("DATA_ROOT é obrigatório e deve apontar para um diretório externo ao checkout.")
  is_absolute <- startsWith(raw_root, "/") || grepl("^[A-Za-z]:[/]", raw_root)
  if (!is_absolute) stop("DATA_ROOT deve ser um caminho absoluto.")
  data_root <- normalizePath(path.expand(raw_root), winslash = "/", mustWork = FALSE)
  checkout <- normalizePath(repo_root, winslash = "/", mustWork = FALSE)
  if (identical(data_root, checkout) || startsWith(data_root, paste0(checkout, "/"))) {
    stop("DATA_ROOT não pode estar dentro do checkout.")
  }
  data_root
}

assert_data_path <- function(path, data_root, label = "caminho", allow_temp = FALSE) {
  resolved <- normalizePath(path.expand(path), winslash = "/", mustWork = FALSE)
  root <- normalizePath(path.expand(data_root), winslash = "/", mustWork = FALSE)
  if (allow_temp) {
    temp_root <- normalizePath(tempdir(), winslash = "/", mustWork = TRUE)
    parent <- normalizePath(dirname(path.expand(path)), winslash = "/", mustWork = TRUE)
    if (identical(parent, temp_root) || startsWith(parent, paste0(temp_root, "/"))) return(resolved)
  }
  if (!identical(resolved, root) && !startsWith(resolved, paste0(root, "/"))) {
    stop(label, " deve permanecer dentro de DATA_ROOT: ", resolved)
  }
  resolved
}

atomic_write_raw <- function(raw_bytes, target_path, expected_sha256 = NULL) {
  dir.create(dirname(target_path), recursive = TRUE, showWarnings = FALSE)
  part_path <- paste0(target_path, ".part")

  writeBin(raw_bytes, part_path)

  # Verificar tamanho e hash
  calc_sha256 <- hash_file(part_path)
  if (!is.null(expected_sha256) && tolower(calc_sha256) != tolower(expected_sha256)) {
    unlink(part_path)
    stop(paste("Falha de integridade SHA-256 no arquivo:", target_path,
               "Esperado:", expected_sha256, "Obtido:", calc_sha256))
  }

  success <- file.rename(part_path, target_path)
  if (!success) {
    # Em caso de sistemas de arquivo sem rename atômico direto, copiar e remover
    file.copy(part_path, target_path, overwrite = TRUE)
    unlink(part_path)
  }

  list(
    path = target_path,
    sha256 = calc_sha256,
    size_bytes = file.info(target_path)$size
  )
}

write_contract_parquet <- function(df, table_name, target_path) {
  dir.create(dirname(target_path), recursive = TRUE, showWarnings = FALSE)
  part_path <- paste0(target_path, ".part")

  schemas <- get_arrow_schemas()
  if (!table_name %in% names(schemas)) {
    stop(paste("Tabela nao encontrada nos esquemas normativos:", table_name))
  }
  target_schema <- schemas[[table_name]]

  table <- arrow_table(df, schema = target_schema)
  write_parquet(table, part_path, compression = "zstd")

  success <- file.rename(part_path, target_path)
  if (!success) {
    file.copy(part_path, target_path, overwrite = TRUE)
    unlink(part_path)
  }

  list(
    path = target_path,
    table_name = table_name,
    row_count = nrow(df),
    size_bytes = file.info(target_path)$size,
    sha256 = hash_file(target_path)
  )
}

publish_manifest_with_complete <- function(manifest_obj, target_manifest_path) {
  dir.create(dirname(target_manifest_path), recursive = TRUE, showWarnings = FALSE)

  manifest_json <- toJSON(manifest_obj, auto_unbox = TRUE, pretty = TRUE)
  part_path <- paste0(target_manifest_path, ".part")
  writeLines(manifest_json, part_path, useBytes = TRUE)
  file.rename(part_path, target_manifest_path)

  manifest_sha256 <- hash_file(target_manifest_path)

  # Criar COMPLETE.json por último
  complete_path <- file.path(dirname(target_manifest_path), "COMPLETE.json")
  complete_obj <- list(
    manifest_file = basename(target_manifest_path),
    manifest_sha256 = manifest_sha256,
    published_at_utc = strftime(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
  )
  complete_json <- toJSON(complete_obj, auto_unbox = TRUE, pretty = TRUE)
  complete_part <- paste0(complete_path, ".part")
  writeLines(complete_json, complete_part, useBytes = TRUE)
  file.rename(complete_part, complete_path)

  list(
    manifest_path = target_manifest_path,
    manifest_sha256 = manifest_sha256,
    complete_path = complete_path
  )
}
