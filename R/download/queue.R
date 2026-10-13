# R/download/queue.R
# Normalização da fila de documentos, gestão de leases atômicos e idempotência
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0, Seção 4 e 5)

suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "download", "blob_store.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

#' Localiza os diretórios mais recentes de inventário da Câmara e do Senado
#'
#' @param data_root Caminho base dos dados.
#' @return Lista com caminhos para inventory_camara e inventory_senado.
find_inventory_dirs <- function(data_root = NULL) {
  data_root <- resolve_download_data_root(data_root)
  staging_dir <- file.path(data_root, "staging")

  # 1. Câmara
  camara_dir <- file.path(staging_dir, "inventory_camara")
  if (!dir.exists(camara_dir) || !file.exists(file.path(camara_dir, "documents.parquet"))) {
    camara_dir <- NULL
  }

  # 2. Senado (procura pasta com timestamp mais recente ou subpasta direta)
  senado_base <- file.path(staging_dir, "inventory", "senado")
  senado_dir <- NULL
  if (dir.exists(senado_base)) {
    candidates <- sort(list.files(senado_base, pattern = "senado_inventory_", full.names = TRUE), decreasing = TRUE)
    for (cand in candidates) {
      if (file.exists(file.path(cand, "documents.parquet"))) {
        senado_dir <- cand
        break
      }
    }
  }

  list(
    camara = camara_dir,
    senado = senado_dir
  )
}

#' Constrói e normaliza a fila completa ou amostrada de documentos a baixar
#'
#' @param data_root Diretório base dos dados.
#' @param camara_dir Diretório opcional de inventário da Câmara.
#' @param senado_dir Diretório opcional de inventário do Senado.
#' @param house_filter "all", "camara" ou "senado".
#' @param is_sample Se TRUE, seleciona amostra heterogênea equilibrada (ambas as casas e múltiplos tipos).
#' @param sample_size_per_house Tamanho alvo por casa em modo sample (default 10).
#' @return Tibble contendo a fila normalizada de documentos.
build_download_queue <- function(data_root = NULL,
                                 camara_dir = NULL,
                                 senado_dir = NULL,
                                 house_filter = "all",
                                 is_sample = FALSE,
                                 sample_size_per_house = 10) {
  inv_dirs <- find_inventory_dirs(data_root)
  if (is.null(camara_dir)) camara_dir <- inv_dirs$camara
  if (is.null(senado_dir)) senado_dir <- inv_dirs$senado

  docs_list <- list()

  # 1. Carregar documentos da Câmara
  if (house_filter %in% c("all", "camara") && !is.null(camara_dir) && file.exists(file.path(camara_dir, "documents.parquet"))) {
    c_docs <- as.data.frame(read_parquet(file.path(camara_dir, "documents.parquet")))
    if (nrow(c_docs) > 0) {
      c_queue <- c_docs %>%
        filter(!is.na(identity_url) & nchar(trimws(identity_url)) > 0) %>%
        transmute(
          document_id = as.character(document_id),
          house = "camara",
          requested_url = trimws(as.character(identity_url)),
          source_uri = as.character(source_uri),
          source_namespace = as.character(source_namespace),
          normalized_kind = as.character(normalized_kind),
          publication_date = as.Date(publication_date)
        )
      docs_list[["camara"]] <- c_queue
    }
  }

  # 2. Carregar documentos do Senado
  if (house_filter %in% c("all", "senado") && !is.null(senado_dir) && file.exists(file.path(senado_dir, "documents.parquet"))) {
    s_docs <- as.data.frame(read_parquet(file.path(senado_dir, "documents.parquet")))
    if (nrow(s_docs) > 0) {
      s_queue <- s_docs %>%
        filter(!is.na(identity_url) & nchar(trimws(identity_url)) > 0) %>%
        transmute(
          document_id = as.character(document_id),
          house = "senado",
          requested_url = trimws(as.character(identity_url)),
          source_uri = as.character(source_uri),
          source_namespace = as.character(source_namespace),
          normalized_kind = as.character(normalized_kind),
          publication_date = as.Date(publication_date)
        )
      docs_list[["senado"]] <- s_queue
    }
  }

  if (length(docs_list) == 0) {
    warning("Nenhum documento encontrado nos inventários disponíveis.")
    return(tibble(
      document_id = character(),
      house = character(),
      requested_url = character(),
      source_uri = character(),
      source_namespace = character(),
      normalized_kind = character(),
      publication_date = as.Date(character())
    ))
  }

  # Se modo sample: estratificar para garantir diversidade de tipos em ambas as casas
  if (is_sample) {
    sample_subsets <- list()
    for (h in names(docs_list)) {
      df_h <- docs_list[[h]]
      # Agrupar por normalized_kind e selecionar representantes
      kinds <- unique(df_h$normalized_kind)
      per_kind_target <- max(1L, ceiling(sample_size_per_house / length(kinds)))
      sampled_h <- df_h %>%
        group_by(normalized_kind) %>%
        slice_head(n = per_kind_target) %>%
        ungroup() %>%
        slice_head(n = sample_size_per_house)
      sample_subsets[[h]] <- sampled_h
    }
    final_queue <- bind_rows(sample_subsets)
  } else {
    final_queue <- bind_rows(docs_list)
  }

  # Deduplicação estrita por document_id
  final_queue <- final_queue %>% distinct(document_id, .keep_all = TRUE)
  return(final_queue)
}

#' Adquire um lease atômico para um documento
#'
#' @param document_id ID do documento.
#' @param leases_dir Diretório onde ficam os arquivos de lease.
#' @param timeout_seconds Tempo em segundos após o qual um lease abandonado expira (default 600).
#' @return Logical TRUE se lease adquirido, FALSE se já estiver ativo por outro worker.
acquire_lease <- function(document_id, leases_dir, timeout_seconds = 600) {
  dir.create(leases_dir, recursive = TRUE, showWarnings = FALSE)
  doc_hash <- hash_string(document_id)
  lease_file <- file.path(leases_dir, paste0(doc_hash, ".lease"))

  if (file.exists(lease_file)) {
    mtime <- file.info(lease_file)$mtime
    age_sec <- as.numeric(difftime(Sys.time(), mtime, units = "secs"))

    # Checar se o PID no mesmo host ja morreu (recuperacao imediata de crash)
    lease_data <- tryCatch(fromJSON(readLines(lease_file, warn = FALSE)), error = function(e) NULL)
    is_same_host <- !is.null(lease_data) && isTRUE(lease_data$hostname == Sys.info()["nodename"])
    is_dead_process <- FALSE
    if (is_same_host && !is.null(lease_data$pid)) {
      is_alive <- tryCatch(tools::pskill(as.integer(lease_data$pid), signal = 0), error = function(e) FALSE)
      if (!is_alive) is_dead_process <- TRUE
    }

    if ((!is.na(age_sec) && age_sec > timeout_seconds) || is_dead_process) {
      # Lease abandonado expirou ou processo dono morreu, assume a posse
      unlink(lease_file)
    } else {
      # Lease ainda ativo por processo vivo
      return(FALSE)
    }
  }

  lease_info <- list(
    document_id = document_id,
    pid = Sys.getpid(),
    hostname = Sys.info()["nodename"],
    started_at_utc = strftime(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
  )

  part_file <- paste0(lease_file, ".part")
  writeLines(toJSON(lease_info, auto_unbox = TRUE), part_file)
  success <- file.rename(part_file, lease_file)
  if (!success) {
    file.copy(part_file, lease_file, overwrite = TRUE)
    unlink(part_file)
  }

  return(TRUE)
}

#' Libera o lease de um documento
#'
#' @param document_id ID do documento.
#' @param leases_dir Diretório de leases.
release_lease <- function(document_id, leases_dir) {
  doc_hash <- hash_string(document_id)
  lease_file <- file.path(leases_dir, paste0(doc_hash, ".lease"))
  if (file.exists(lease_file)) {
    unlink(lease_file)
  }
}

#' Limpa leases expirados no diretório
#'
#' @param leases_dir Diretório de leases.
#' @param timeout_seconds Limite de expiração.
#' @return Quantidade de leases órfãos removidos.
clean_expired_leases <- function(leases_dir, timeout_seconds = 600) {
  if (!dir.exists(leases_dir)) return(0L)
  files <- list.files(leases_dir, pattern = "\\.lease$", full.names = TRUE)
  cleaned <- 0L
  now <- Sys.time()
  for (f in files) {
    mtime <- file.info(f)$mtime
    age_sec <- as.numeric(difftime(now, mtime, units = "secs"))
    lease_data <- tryCatch(fromJSON(readLines(f, warn = FALSE)), error = function(e) NULL)
    is_same_host <- !is.null(lease_data) && isTRUE(lease_data$hostname == Sys.info()["nodename"])
    is_dead_process <- FALSE
    if (is_same_host && !is.null(lease_data$pid)) {
      is_alive <- tryCatch(tools::pskill(as.integer(lease_data$pid), signal = 0), error = function(e) FALSE)
      if (!is_alive) is_dead_process <- TRUE
    }

    if ((!is.na(age_sec) && age_sec > timeout_seconds) || is_dead_process) {
      unlink(f)
      cleaned <- cleaned + 1L
    }
  }
  cleaned
}

#' Verifica se um documento já foi baixado com sucesso e seu blob está íntegro
#'
#' @param document_id ID do documento.
#' @param existing_versions_df DataFrame existente de document_versions (se houver).
#' @param data_root Diretório base dos dados.
#' @return Logical indicando se já existe versão verified e blob íntegro.
is_document_completed <- function(document_id, existing_versions_df = NULL, data_root = NULL) {
  data_root <- resolve_download_data_root(data_root)
  if (is.null(existing_versions_df) || nrow(existing_versions_df) == 0) {
    return(FALSE)
  }

  matched <- existing_versions_df %>%
    filter(document_id == !!document_id & integrity_status == "verified")

  if (nrow(matched) == 0) {
    return(FALSE)
  }

  # Conferir se o arquivo físico do blob existe e é íntegro
  for (i in seq_len(nrow(matched))) {
    row <- matched[i, ]
    if (!is.na(row$raw_path) && !is.na(row$file_sha256)) {
      if (verify_blob_integrity(row$raw_path, data_root = data_root, expected_sha256 = row$file_sha256)) {
        return(TRUE)
      }
    }
  }

  return(FALSE)
}
