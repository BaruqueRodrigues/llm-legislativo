# R/inventory/common/hashing.R
# Utilitários de hashing determinístico (SHA-256) em hex minúsculo de 64 caracteres

suppressPackageStartupMessages({
  library(digest)
})

hash_string <- function(text) {
  if (is.null(text) || length(text) == 0 || is.na(text)) {
    return(NA_character_)
  }
  digest(enc2utf8(as.character(text)), algo = "sha256", serialize = FALSE)
}

hash_bytes <- function(raw_vec) {
  if (is.null(raw_vec) || length(raw_vec) == 0) {
    return(digest(raw(0), algo = "sha256", serialize = FALSE))
  }
  digest(raw_vec, algo = "sha256", serialize = FALSE)
}

hash_file <- function(filepath) {
  if (!file.exists(filepath)) {
    stop(paste("Arquivo nao encontrado para hash:", filepath))
  }
  digest(filepath, algo = "sha256", file = TRUE)
}
