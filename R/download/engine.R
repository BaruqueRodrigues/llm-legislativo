# R/download/engine.R
# Motor de orquestração do pipeline de downloads históricos (Frente 02)
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/02_DOWNLOADS.md

suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
  library(yaml)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "download", "validator.R"))
source(file.path(repo_root, "R", "download", "blob_store.R"))
source(file.path(repo_root, "R", "download", "queue.R"))
source(file.path(repo_root, "R", "download", "fetcher.R"))
source(file.path(repo_root, "R", "download", "reconciliation.R"))
source(file.path(repo_root, "R", "download", "publisher.R"))
source(file.path(repo_root, "R", "download", "camara_annual_csv.R"))
source(file.path(repo_root, "R", "download", "senado_links_csv.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

#' Executa o pipeline completo de download de documentos
#'
#' @param config_path Caminho do arquivo de configuração (history.yaml).
#' @param output_dir Diretório onde serão gravadas as tabelas e manifestos de saída.
#' @param is_sample Se TRUE, executa em lote heterogêneo amostral representativo.
#' @param sample_size Tamanho alvo da amostra por casa (default 5).
#' @param batch_size Limite de documentos a processar nesta execução (NULL para sem limite).
#' @param house_filter Filtro por casa: "all", "camara" ou "senado".
#' @param dry_run Se TRUE, apenas planeja e exibe a fila sem executar requisições.
#' @param mock_transport Função mock opcional para injeção de respostas em testes.
#' @return Lista contendo sumário de execução, reconciliação, tabelas e paths de publicação.
run_download_pipeline <- function(config_path = NULL,
                                  output_dir = NULL,
                                  is_sample = TRUE,
                                  sample_size = 5,
                                  batch_size = NULL,
                                  house_filter = "all",
                                  dry_run = FALSE,
                                  mock_transport = NULL) {
  if (is.null(config_path)) {
    config_path <- file.path(repo_root, "configs", "data", "history.yaml")
  }

  cfg <- if (file.exists(config_path)) yaml::read_yaml(config_path) else list()
  data_root <- resolve_external_data_root(repo_root)
  network_cfg <- if (!is.null(cfg$network)) cfg$network else list()

  batch_timestamp <- strftime(Sys.time(), "%Y%m%d_%H%M%S", tz = "UTC")
  batch_id <- paste0("dl_batch_", batch_timestamp)

  if (is.null(output_dir)) {
    output_dir <- file.path(data_root, "staging", "downloads", batch_id)
  }
  output_dir <- assert_data_path(output_dir, data_root, "output_dir")
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  leases_dir <- file.path(data_root, "staging", "download_leases")
  clean_expired_leases(leases_dir, timeout_seconds = 600)

  cat("=================================================================\n")
  cat("Subagente 02: Pipeline de Downloads Históricos e Proveniência\n")
  cat("Batch ID:", batch_id, "\n")
  cat("Data Root:", data_root, "\n")
  cat("Output Dir:", output_dir, "\n")
  cat("Modo:", if (is_sample) paste("Amostra Heterogênea (n =", sample_size, "por casa)") else "Fila Completa", "\n")
  cat("Filtro Casa:", house_filter, "\n")
  cat("Dry Run:", dry_run, "\n")
  cat("=================================================================\n\n")

  # 1. Construção da fila normalizada
  cat("[1/5] Construindo fila normalizada a partir dos inventários homologados...\n")
  queue_df <- build_download_queue(
    data_root = data_root,
    house_filter = house_filter,
    is_sample = is_sample,
    sample_size_per_house = sample_size
  )

  if (nrow(queue_df) == 0) {
    cat("Aviso: Nenhum documento elegível encontrado na fila de download.\n")
    return(list(
      status = "empty",
      queue_count = 0,
      batch_id = batch_id
    ))
  }

  # Aplicar batch_size se especificado
  if (!is.null(batch_size) && batch_size > 0 && nrow(queue_df) > batch_size) {
    queue_df <- queue_df %>% slice_head(n = batch_size)
  }

  cat("Total de documentos na fila:", nrow(queue_df), "\n")
  print(table(queue_df$house, queue_df$normalized_kind))

  if (dry_run) {
    cat("\nModo dry-run ativado. Execução concluída sem downloads.\n")
    return(list(
      status = "dry_run",
      queue = queue_df,
      batch_id = batch_id
    ))
  }

  # 2. Execução de downloads com leases e idempotência
  cat("\n[2/5] Executando downloads com leases, idempotência e controle de concorrência...\n")
  all_attempts <- list()
  all_versions <- list()

  # Verificar versões já existentes em execuções anteriores no data_root
  existing_versions_file <- file.path(data_root, "staging", "downloads", "cumulative_document_versions.parquet")
  existing_versions_df <- if (file.exists(existing_versions_file)) {
    as.data.frame(read_parquet(existing_versions_file))
  } else NULL

  for (i in seq_len(nrow(queue_df))) {
    doc_row <- queue_df[i, ]
    doc_id <- doc_row$document_id

    # Checar se já foi baixado com integridade conferida
    if (is_document_completed(doc_id, existing_versions_df, data_root = data_root)) {
      cat(sprintf("[%d/%d] Documento ja baixado e integro (idempotente): %s\n", i, nrow(queue_df), doc_id))
      # Recuperar registro de versão existente
      prior_ver <- existing_versions_df %>% filter(document_id == doc_id & integrity_status == "verified") %>% slice_head(n = 1)
      all_versions[[length(all_versions) + 1]] <- as.list(prior_ver)
      next
    }

    # Adquirir lease atômico
    has_lease <- acquire_lease(doc_id, leases_dir, timeout_seconds = 600)
    if (!has_lease) {
      cat(sprintf("[%d/%d] Documento em processamento concorrente (lease ativo), pulando: %s\n", i, nrow(queue_df), doc_id))
      next
    }

    cat(sprintf("[%d/%d] Baixando: %s (%s, %s)\n", i, nrow(queue_df), doc_id, doc_row$house, doc_row$normalized_kind))
    cat(sprintf("       URL: %s\n", doc_row$requested_url))

    fetch_res <- fetch_document(
      doc_row = doc_row,
      data_root = data_root,
      network_cfg = network_cfg,
      mock_transport = mock_transport
    )

    # Coletar tentativas
    if (length(fetch_res$attempt_records) > 0) {
      all_attempts <- c(all_attempts, fetch_res$attempt_records)
    }

    # Coletar versão se sucesso
    if (fetch_res$success && !is.null(fetch_res$version_record)) {
      all_versions[[length(all_versions) + 1]] <- fetch_res$version_record
      cat(sprintf("       -> Sucesso! Versao: %s (MIME: %s, %d bytes)\n",
                  fetch_res$version_record$version_id,
                  fetch_res$version_record$detected_media_type,
                  fetch_res$version_record$file_size_bytes))
    } else {
      last_att <- tail(fetch_res$attempt_records, 1)[[1]]
      cat(sprintf("       -> Falha: %s (Erro: %s - %s)\n",
                  last_att$status,
                  if (!is.na(last_att$error_code)) last_att$error_code else "HTTP",
                  if (!is.na(last_att$error_message)) last_att$error_message else ""))
    }

    # Liberar lease
    release_lease(doc_id, leases_dir)
  }

  # 3. Converter listas para DataFrames
  cat("\n[3/5] Consolidando tentativas e versões...\n")
  attempts_df <- if (length(all_attempts) > 0) bind_rows(all_attempts) else tibble()
  versions_df <- if (length(all_versions) > 0) bind_rows(all_versions) else tibble()

  # 4. Reconciliação de cobertura
  cat("[4/5] Executando reconciliação estatística da cobertura...\n")
  reconciliation <- compute_reconciliation_summary(queue_df, attempts_df, versions_df)

  cat(sprintf("--- Sumário de Reconciliação ---\n"))
  cat(sprintf("Total Descobertos: %d\n", reconciliation$discovered_total))
  cat(sprintf("Total Obtidos:     %d\n", reconciliation$retrieved_total))
  cat(sprintf("Total Falhos:      %d\n", reconciliation$failed_total))
  cat(sprintf("Total Pendentes:   %d\n", reconciliation$pending_total))
  cat(sprintf("Status Cobertura:  %s\n", reconciliation$coverage_status))
  cat(sprintf("Blobs Unicos:      %d (Reuso: %d)\n",
              reconciliation$storage_metrics$unique_blobs_count,
              reconciliation$storage_metrics$storage_reuse_count))
  cat(sprintf("Bytes Recebidos:   %d\n\n", reconciliation$storage_metrics$total_bytes_received))

  # 5. Publicação do lote com COMPLETE.json
  cat("[5/5] Publicando lote com tabelas Parquet tipadas, manifesto e COMPLETE.json...\n")
  pub_result <- publish_download_batch(
    attempts_df = attempts_df,
    versions_df = versions_df,
    output_dir = output_dir,
    batch_id = batch_id,
    reconciliation_summary = reconciliation
  )

  # Atualizar cumulativo para idempotência futura
  if (nrow(versions_df) > 0) {
    dir.create(dirname(existing_versions_file), recursive = TRUE, showWarnings = FALSE)
    cumulative_df <- if (!is.null(existing_versions_df)) {
      bind_rows(existing_versions_df, clean_document_versions_df(versions_df)) %>% distinct(version_id, .keep_all = TRUE)
    } else {
      clean_document_versions_df(versions_df)
    }
    write_contract_parquet(cumulative_df, "document_versions", existing_versions_file)
  }

  cat("Lote publicado com sucesso em:", output_dir, "\n")
  cat("Manifesto:", pub_result$manifest_path, "\n")
  cat("COMPLETE.json:", pub_result$complete_path, "\n\n")

  list(
    status = "succeeded",
    batch_id = batch_id,
    queue_df = queue_df,
    attempts_df = clean_fetch_attempts_df(attempts_df),
    versions_df = clean_document_versions_df(versions_df),
    reconciliation = reconciliation,
    publication = pub_result
  )
}
