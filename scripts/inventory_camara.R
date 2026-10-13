#!/usr/bin/env Rscript
# scripts/inventory_camara.R
# CLI de descoberta e inventário histórico da Câmara dos Deputados (Subagente 01)
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/01_INVENTARIO.md

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

source(file.path(root_dir, "R", "inventory", "camara", "inventory_engine.R"))

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  config_path <- file.path(root_dir, "configs", "data", "history.yaml")
  output_dir <- NULL
  is_sample <- FALSE
  mode_explicit <- FALSE
  max_segments <- NULL
  max_pages_per_segment <- NULL
  max_enrichment_requests <- NULL

  i <- 1
  while (i <= length(args)) {
    arg <- args[i]
    if (arg == "--config" && (i + 1) <= length(args)) {
      config_path <- args[i + 1]
      i <- i + 2
    } else if (arg == "--output-dir" && (i + 1) <= length(args)) {
      output_dir <- args[i + 1]
      i <- i + 2
    } else if (arg == "--full") {
      is_sample <- FALSE
      mode_explicit <- TRUE
      i <- i + 1
    } else if (arg == "--sample") {
      is_sample <- TRUE
      mode_explicit <- TRUE
      i <- i + 1
    } else if (arg == "--max-segments" && (i + 1) <= length(args)) {
      max_segments <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--max-pages" && (i + 1) <= length(args)) {
      max_pages_per_segment <- as.integer(args[i + 1])
      i <- i + 2
    } else if (arg == "--max-enrichment-requests" && (i + 1) <= length(args)) {
      max_enrichment_requests <- as.integer(args[i + 1])
      i <- i + 2
    } else {
      i <- i + 1
    }
  }

  if (!mode_explicit) stop("Informe --full para inventário oficial ou --sample para fixture sintética.")

  cat("=================================================================\n")
  cat("Inventário Histórico da Câmara dos Deputados (Frente 01)\n")
  cat("Configuração:", config_path, "\n")
  cat("Modo:", if (is_sample) "Fixture sintética (não oficial)" else "API oficial incremental (resultado parcial)", "\n")
  cat("=================================================================\n\n")

  if (!file.exists(config_path)) {
    stop(paste("Arquivo de configuracao nao encontrado:", config_path))
  }

  data_root <- resolve_external_data_root(root_dir)
  if (!is.null(output_dir)) output_dir <- assert_data_path(output_dir, data_root, "output_dir")

  res <- run_camara_inventory(config_path = config_path, output_dir = output_dir,
                              is_sample = is_sample, max_segments = max_segments,
                              max_pages_per_segment = max_pages_per_segment,
                              max_enrichment_requests = max_enrichment_requests)

  cat("\n=================================================================\n")
  cat("Lote de inventário publicado; cobertura histórica não declarada completa.\n")
  cat("Tabelas geradas:", length(res$written_files), "\n")
  cat("Tipos preservados:", res$manifest$summary$legislative_types_count, "\n")
  cat("Segmentos de cobertura:", res$manifest$summary$coverage_segments_count, "\n")
  cat("Estado:", res$manifest$status, "\n")
  if (!is_sample) {
    cat("Retomada da listagem:", res$manifest$progress_file, "\n")
    cat("Fila de enriquecimento:", res$manifest$enrichment_queue_file, "\n")
    cat("Páginas de enriquecimento nesta execução:", res$manifest$enrichment$endpoint_pages_used, "\n")
    cat("Tentativas HTTP desta execução:", res$manifest$enrichment$http_attempts, "\n")
    cat("Tarefas de endpoint pendentes:", res$manifest$enrichment$endpoint_tasks_pending, "\n")
  }
  cat("=================================================================\n")
  quit(status = 0)
}

if (!interactive()) {
  main()
}
