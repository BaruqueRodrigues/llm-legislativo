# R/download/blob_store.R
# Armazenamento imutável de blobs por SHA-256 com reuso de armazenamento e integridade estrita
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0, Seção 4 e 5)

suppressPackageStartupMessages({
  library(digest)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

resolve_download_data_root <- function(data_root = NULL) {
  root <- resolve_external_data_root(repo_root)
  if (is.null(data_root) || !nzchar(data_root)) return(root)

  candidate <- normalizePath(path.expand(data_root), winslash = "/", mustWork = FALSE)
  temp_root <- normalizePath(tempdir(), winslash = "/", mustWork = TRUE)
  candidate_parent <- normalizePath(dirname(path.expand(data_root)), winslash = "/", mustWork = TRUE)
  candidate <- file.path(candidate_parent, basename(path.expand(data_root)))
  if (identical(candidate_parent, temp_root) || startsWith(candidate_parent, paste0(temp_root, "/"))) {
    return(candidate)
  }
  assert_data_path(candidate, root, "data_root")
}

# Interrompe novas gravações quando o volume de dados está perto de encher.
# LLM_DO_ZERO_MIN_FREE_GIB controla a reserva (padrão: 10 GiB).
camara_assert_download_disk_space <- function(path, minimum_free_gib = NULL) {
  if (is.null(minimum_free_gib)) {
    minimum_free_gib <- suppressWarnings(as.numeric(Sys.getenv("LLM_DO_ZERO_MIN_FREE_GIB", "10")))
  }
  if (length(minimum_free_gib) != 1L || is.na(minimum_free_gib) || minimum_free_gib < 0) {
    stop("LLM_DO_ZERO_MIN_FREE_GIB deve ser um número não negativo.")
  }
  probe <- path.expand(path)
  while (!dir.exists(probe) && !file.exists(probe) && dirname(probe) != probe) probe <- dirname(probe)
  if (file.exists(probe) && !dir.exists(probe)) probe <- dirname(probe)
  output <- suppressWarnings(system2("df", c("-Pk", shQuote(probe)), stdout = TRUE, stderr = TRUE))
  status <- attr(output, "status")
  lines <- strsplit(trimws(output), "\\s+")
  rows <- Filter(function(x) length(x) >= 4L && grepl("^[0-9]+$", x[[4L]]), lines)
  if (!is.null(status) && status != 0L || !length(rows)) {
    stop("Não foi possível verificar espaço livre em disco; download interrompido por segurança.")
  }
  available_bytes <- as.numeric(tail(rows, 1L)[[1L]][[4L]]) * 1024
  minimum_bytes <- minimum_free_gib * 1024^3
  if (identical(Sys.getenv("LLM_CLOUD_OFFLOAD"), "1")) {
    cloud_config <- jsonlite::fromJSON(file.path(repo_root, "configs", "storage", "drive.json"))
    trigger_gib <- max(minimum_free_gib, cloud_config$minimum_free_gib) + 2 * cloud_config$batch_gib + 4
    if (available_bytes < trigger_gib * 1024^3) {
      python <- Sys.which("python3")
      if (!nzchar(python)) stop("python3 necessário para arquivamento automático no Drive.")
      cat("Reserva local atingida; arquivando lote verificado no Drive antes de continuar.\n")
      code <- system2(python, c(shQuote(file.path(repo_root, "scripts", "cloud_storage.py")),
                               "--data-root", shQuote(resolve_download_data_root()),
                               "offload", "--max-gib", as.character(cloud_config$batch_gib), "--evict"))
      if (!identical(code, 0L)) stop("Arquivamento no Drive falhou; coleta interrompida preservando arquivos locais.")
      # Recheck through the same disk guard, without recursively starting another upload.
      Sys.setenv(LLM_CLOUD_OFFLOAD = "0")
      on.exit(Sys.setenv(LLM_CLOUD_OFFLOAD = "1"), add = TRUE)
      return(camara_assert_download_disk_space(path, minimum_free_gib))
    }
  }
  if (available_bytes < minimum_bytes) {
    condition <- structure(list(
      message = sprintf("Espaço livre abaixo do limite: %.2f GiB livres; mínimo configurado %.2f GiB. Download pausado.",
        available_bytes / 1024^3, minimum_free_gib),
      call = NULL, available_bytes = available_bytes, minimum_bytes = minimum_bytes
    ), class = c("download_disk_space_error", "error", "condition"))
    stop(condition)
  }
  invisible(list(available_bytes = available_bytes, minimum_bytes = minimum_bytes, path = probe))
}

#' Armazena um buffer de bytes brutos de forma imutável, endereçado por SHA-256
#'
#' @param raw_bytes Vetor raw dos bytes a armazenar.
#' @param data_root Diretório base dos dados (DATA_ROOT).
#' @param raw_blobs_subdir Subdiretório relativo de blobs (default "raw/sha256").
#' @return Lista contendo sha256, raw_path (relativo a data_root), absolute_path, file_size_bytes, reused.
store_raw_blob <- function(raw_bytes,
                           data_root = NULL,
                           raw_blobs_subdir = "raw/sha256") {
  if (is.null(data_root) || !nzchar(data_root)) data_root <- Sys.getenv("DATA_ROOT", unset = "")
  data_root <- resolve_download_data_root(data_root)
  if (is.null(raw_bytes) || length(raw_bytes) == 0) {
    stop("store_raw_blob: nao e permitido armazenar buffer vazio")
  }

  if (!is.character(raw_blobs_subdir) || length(raw_blobs_subdir) != 1L || is.na(raw_blobs_subdir) ||
      grepl("(^|[/\\])\\.\\.([/\\]|$)", raw_blobs_subdir) || startsWith(raw_blobs_subdir, "/")) {
    stop("raw_blobs_subdir deve ser relativo e não pode escapar de DATA_ROOT.")
  }

  calc_sha256 <- tolower(hash_bytes(raw_bytes))
  size_bytes <- length(raw_bytes)

  # Particionamento por prefixo de 2 caracteres hexadecimais: <hh>/<hash>.bin
  prefix <- substr(calc_sha256, 1, 2)
  filename <- paste0(calc_sha256, ".bin")

  rel_path <- file.path(raw_blobs_subdir, prefix, filename)
  abs_path <- assert_data_path(file.path(data_root, rel_path), data_root, "blob target")
  rel_path <- substring(abs_path, nchar(data_root) + 2L)

  # Verificar se o blob já existe (Reuso de Armazenamento)
  if (file.exists(abs_path)) {
    existing_size <- file.info(abs_path)$size
    if (existing_size == size_bytes) {
      # Verificar se o hash do arquivo existente bate com o hash esperado
      existing_hash <- tolower(hash_file(abs_path))
      if (existing_hash == calc_sha256) {
        return(list(
          sha256 = calc_sha256,
          raw_path = rel_path,
          absolute_path = abs_path,
          file_size_bytes = size_bytes,
          reused = TRUE
        ))
      }
    }
    # Se o arquivo existente estiver corrompido, será reescrito
  }

  # Escrita atômica via .part
  camara_assert_download_disk_space(dirname(abs_path))
  dir.create(dirname(abs_path), recursive = TRUE, showWarnings = FALSE)
  part_path <- paste0(abs_path, ".part")

  writeBin(raw_bytes, part_path)

  # Verificar integridade imediata antes da promoção
  part_hash <- tolower(hash_file(part_path))
  if (part_hash != calc_sha256) {
    unlink(part_path)
    stop(paste("Falha critica de integridade ao gravar blob:", abs_path,
               "Esperado:", calc_sha256, "Obtido:", part_hash))
  }

  success <- file.rename(part_path, abs_path)
  if (!success) {
    file.copy(part_path, abs_path, overwrite = TRUE)
    unlink(part_path)
  }

  list(
    sha256 = calc_sha256,
    raw_path = rel_path,
    absolute_path = abs_path,
    file_size_bytes = size_bytes,
    reused = FALSE
  )
}

#' Verifica a integridade de um blob já existente no disco
#'
#' @param raw_path Caminho relativo do blob dentro de data_root.
#' @param data_root Diretório base dos dados.
#' @param expected_sha256 Hash esperado de 64 caracteres hexadecimais.
#' @return Logical indicando se o blob existe e confere o hash.
verify_blob_integrity <- function(raw_path, data_root = NULL, expected_sha256 = NULL) {
  if (is.null(data_root) || !nzchar(data_root)) data_root <- Sys.getenv("DATA_ROOT", unset = "")
  data_root <- resolve_download_data_root(data_root)
  abs_path <- assert_data_path(file.path(data_root, raw_path), data_root, "raw_path")
  if (!file.exists(abs_path)) {
    if (is.null(expected_sha256)) expected_sha256 <- sub("\\.bin$", "", basename(abs_path))
    return(cloud_blob_archived(raw_path, expected_sha256, data_root))
  }

  if (is.null(expected_sha256)) {
    # Tenta extrair o hash do próprio nome do arquivo
    fname <- basename(abs_path)
    expected_sha256 <- sub("\\.bin$", "", fname)
  }

  actual_hash <- tolower(hash_file(abs_path))
  return(actual_hash == tolower(expected_sha256))
}
