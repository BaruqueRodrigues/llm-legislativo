# Recibos operacionais de blobs arquivados; não alteram document_versions/raw_path.
cloud_blob_receipt <- function(raw_path, expected_sha256, data_root) {
  if (length(raw_path) != 1L || is.na(raw_path) ||
      !grepl("^raw/sha256/[0-9a-f]{2}/[0-9a-f]{64}\\.bin$", raw_path) ||
      length(expected_sha256) != 1L || is.na(expected_sha256)) return(NULL)
  sha <- sub("\\.bin$", "", basename(raw_path))
  if (!identical(sha, tolower(expected_sha256)) ||
      !identical(basename(dirname(raw_path)), substr(sha, 1, 2))) return(NULL)
  path <- file.path(data_root, "staging", "cloud_storage", "objects", paste0(raw_path, ".json"))
  if (!file.exists(path)) return(NULL)
  receipt <- tryCatch(jsonlite::fromJSON(path), error = function(e) NULL)
  config <- tryCatch(jsonlite::fromJSON(file.path(repo_root, "configs", "storage", "drive.json")), error = function(e) NULL)
  if (is.null(receipt) || is.null(config) ||
      !identical(receipt$status, "verified") || !identical(receipt$sha256, sha) ||
      !identical(receipt$raw_path, raw_path) || !identical(receipt$folder_id, config$folder_id) ||
      !identical(receipt$remote, config$remote) ||
      is.null(receipt$remote_path) ||
      !startsWith(receipt$remote_path, paste0(config$remote, ":", config$remote_data_dir, "/packs/")) ||
      !grepl("/[0-9a-f]{64}\\.pack$", receipt$remote_path) ||
      !identical(receipt$storage_kind, "pack_v1") ||
      !identical(receipt$verification, "sha256_remote_stream") ||
      is.null(receipt$offset_bytes) || receipt$offset_bytes < 0 ||
      is.null(receipt$size_bytes) || receipt$size_bytes <= 0) return(NULL)
  receipt
}

cloud_blob_archived <- function(raw_path, expected_sha256, data_root) {
  !is.null(cloud_blob_receipt(raw_path, expected_sha256, data_root))
}

materialize_cloud_blob <- function(path, repo_root) {
  data_root <- Sys.getenv("DATA_ROOT", unset = "")
  if (!nzchar(data_root)) return(NULL)
  root <- normalizePath(data_root, winslash = "/", mustWork = TRUE)
  absolute <- normalizePath(path, winslash = "/", mustWork = FALSE)
  if (!startsWith(absolute, paste0(root, "/"))) return(NULL)
  relative <- substring(absolute, nchar(root) + 2L)
  if (!grepl("^raw/sha256/[0-9a-f]{2}/[0-9a-f]{64}\\.bin$", relative)) return(NULL)
  python <- Sys.which("python3")
  if (!nzchar(python)) stop("python3 necessário para recuperar/proteger blob do Drive.")
  code <- system2(python, c(shQuote(file.path(repo_root, "scripts", "cloud_storage.py")),
                           "--data-root", shQuote(root), "fetch", shQuote(relative), "--pin"))
  if (!identical(code, 0L)) stop("Falha ao recuperar/proteger blob do Drive: ", relative)
  list(relative = relative, root = root, python = python)
}

release_cloud_blob <- function(pin, repo_root) {
  if (is.null(pin)) return(invisible(NULL))
  code <- system2(pin$python, c(shQuote(file.path(repo_root, "scripts", "cloud_storage.py")),
                               "--data-root", shQuote(pin$root), "unpin", shQuote(pin$relative)))
  if (!identical(code, 0L)) warning("Blob permanece protegido; libere com cloud_storage.py unpin: ", pin$relative)
  invisible(NULL)
}
