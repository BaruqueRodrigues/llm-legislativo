#!/usr/bin/env Rscript
# scripts/download.R
# CLI oficial de captura, preservação e proveniência de documentos legislativos (Subagente 02)
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/02_DOWNLOADS.md

suppressPackageStartupMessages({
  library(yaml)
  library(arrow)
  library(dplyr)
  library(jsonlite)
})

get_script_dir <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg) > 0) {
    return(dirname(normalizePath(sub("^--file=", "", file_arg))))
  }
  return(file.path(getwd(), "scripts"))
}
root_dir <- normalizePath(file.path(get_script_dir(), ".."))

source(file.path(root_dir, "R", "download", "engine.R"))

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  config_path <- file.path(root_dir, "configs", "data", "history.yaml")
  output_dir <- NULL
  camara_annual_mode <- FALSE
  senado_links_csv <- NULL
  senado_per_host_concurrency <- 4L
  senado_min_host_interval <- 0.2
  annual_index <- NULL
  from_year <- NULL
  through_year <- NULL
  documents_through_year <- NULL
  max_concurrency <- 40L
  min_free_gib <- 10
  retry_failures <- FALSE
  probe_only <- FALSE
  dry_run <- FALSE
  is_sample <- NULL
  sample_size <- 5L
  batch_size <- NULL
  house_filter <- "all"
  dry_run <- FALSE

  i <- 1
  while (i <= length(args)) {
    arg <- args[i]
    if (arg == "--camara-annual-csv") {
      camara_annual_mode <- TRUE
      i <- i + 1
    } else if (arg == "--senado-links-csv" && (i + 1) <= length(args)) {
      senado_links_csv <- args[i + 1]
      i <- i + 2
    } else if (arg == "--per-host-concurrency" && (i + 1) <= length(args)) {
      senado_per_host_concurrency <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--min-host-interval" && (i + 1) <= length(args)) {
      senado_min_host_interval <- as.numeric(args[i + 1])
      i <- i + 2
    } else if (arg == "--annual-index" && (i + 1) <= length(args)) {
      annual_index <- args[i + 1]
      i <- i + 2
    } else if (arg == "--from-year" && (i + 1) <= length(args)) {
      from_year <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--through-year" && (i + 1) <= length(args)) {
      through_year <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--documents-through-year" && (i + 1) <= length(args)) {
      documents_through_year <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--max-concurrency" && (i + 1) <= length(args)) {
      max_concurrency <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--min-free-gib" && (i + 1) <= length(args)) {
      min_free_gib <- suppressWarnings(as.numeric(args[i + 1]))
      i <- i + 2
    } else if (arg == "--cloud-offload") {
      Sys.setenv(LLM_CLOUD_OFFLOAD = "1")
      i <- i + 1
    } else if (arg == "--retry-failures") {
      retry_failures <- TRUE
      i <- i + 1
    } else if (arg == "--probe-only") {
      probe_only <- TRUE
      i <- i + 1
    } else if (arg == "--config" && (i + 1) <= length(args)) {
      config_path <- args[i + 1]
      i <- i + 2
    } else if (arg == "--output-dir" && (i + 1) <= length(args)) {
      output_dir <- args[i + 1]
      i <- i + 2
    } else if (arg == "--sample") {
      is_sample <- TRUE
      i <- i + 1
    } else if (arg == "--full") {
      is_sample <- FALSE
      i <- i + 1
    } else if (arg == "--sample-size" && (i + 1) <= length(args)) {
      sample_size <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--batch-size" && (i + 1) <= length(args)) {
      batch_size <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--house" && (i + 1) <= length(args)) {
      house_filter <- tolower(args[i + 1])
      i <- i + 2
    } else if (arg == "--dry-run") {
      dry_run <- TRUE
      i <- i + 1
    } else {
      i <- i + 1
    }
  }

  if (length(min_free_gib) != 1L || is.na(min_free_gib) || min_free_gib < 0) {
    stop("--min-free-gib deve ser um número não negativo.")
  }
  Sys.setenv(LLM_DO_ZERO_MIN_FREE_GIB = format(min_free_gib, scientific = FALSE))

  if (!is.null(senado_links_csv)) {
    result <- senado_download_links_csv(csv_path=senado_links_csv,max_concurrency=max_concurrency,
      per_host_concurrency=senado_per_host_concurrency,min_host_interval=senado_min_host_interval,
      retry_failures=retry_failures,dry_run=dry_run,output_dir=output_dir)
    cat("Downloader do inventário CSV do Senado:",result$status,"\n")
    cat("Linhas de origem:",result$input_rows,"\n")
    cat("URLs distintas:",result$unique_urls,"\n")
    cat("Concorrência global:",result$max_concurrency,"\n")
    cat("Concorrência por host:",result$per_host_concurrency,"\n")
    cat("Intervalo mínimo por host:",result$min_host_interval,"s\n")
    cat("Diretório/checkpoint:",result$output_dir,"\n")
    if (!is.null(result$publication)) cat("COMPLETE.json:",result$publication$complete_path,"\n")
    quit(status=0)
  }

  if (camara_annual_mode) {
    result <- run_camara_annual_csv(
      annual_index = annual_index,
      from_year = from_year,
      through_year = through_year,
      documents_through_year = documents_through_year,
      probe_only = probe_only,
      dry_run = dry_run,
      max_concurrency = max_concurrency,
      retry_failures = retry_failures
    )
    cat("Rotina CSV anual da Câmara:", result$status, "\n")
    cat("Run ID:", result$run_id, "\n")
    cat("Manifesto de status:", result$status_path, "\n")
    quit(status = 0)
  }

  if (is.null(is_sample)) stop("Informe --sample para lote piloto ou --full para fila completa.")

  cat("=================================================================\n")
  cat("CLI de Downloads Históricos e Proveniência (Frente 02)\n")
  cat("Configuração:", config_path, "\n")
  cat("Modo:", if (is_sample) paste("Amostra Heterogênea (", sample_size, "por casa)") else "Fila Completa Histórica", "\n")
  cat("Filtro Casa:", house_filter, "\n")
  if (!is.null(batch_size)) cat("Tamanho do Lote (Batch Size):", batch_size, "\n")
  if (dry_run) cat("Dry-Run Ativo: Apenas planejamento da fila\n")
  cat("=================================================================\n\n")

  if (!file.exists(config_path)) {
    stop(paste("Arquivo de configuracao nao encontrado:", config_path))
  }

  res <- run_download_pipeline(
    config_path = config_path,
    output_dir = output_dir,
    is_sample = is_sample,
    sample_size = sample_size,
    batch_size = batch_size,
    house_filter = house_filter,
    dry_run = dry_run
  )

  if (res$status == "succeeded") {
    cat("Download pipeline finalizado com exito.\n")
    cat("Status de Cobertura GH:", res$reconciliation$coverage_status, "\n")
    quit(status = 0)
  } else if (res$status == "dry_run") {
    cat("Planejamento dry-run concluido com exito.\n")
    quit(status = 0)
  } else {
    cat("Pipeline finalizado sem novos documentos processados.\n")
    quit(status = 0)
  }
}

if (!interactive()) {
  main()
}
