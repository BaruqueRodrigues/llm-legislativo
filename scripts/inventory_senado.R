#!/usr/bin/env Rscript
# scripts/inventory_senado.R
# CLI executável para inventário histórico do Senado Federal (Gate G1 / GH)
# Uso: Rscript scripts/inventory_senado.R [--config configs/data/history.yaml] [--mode smoke|audit|full] [--offline]

suppressPackageStartupMessages({
  library(yaml)
  library(jsonlite)
  library(dplyr)
  library(arrow)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory", "senado", "client.R"))
source(file.path(repo_root, "R", "inventory", "senado", "taxonomies.R"))
source(file.path(repo_root, "R", "inventory", "senado", "collections.R"))
source(file.path(repo_root, "R", "inventory", "senado", "inventory_engine.R"))
source(file.path(repo_root, "R", "inventory", "senado", "publisher.R"))

# Parse CLI arguments using base R commandArgs
args <- commandArgs(trailingOnly = TRUE)
opt <- list(
  config = "configs/data/history.yaml",
  mode = NULL,
  offline = FALSE,
  output_dir = NULL,
  year = NULL,
  max_items = 50L,
  max_segments = 20L,
  tramitando = NULL,
  process_ids_file = NULL,
  segments_file = NULL
)

i <- 1
while (i <= length(args)) {
  arg <- args[i]
  if (arg %in% c("-c", "--config") && i < length(args)) {
    opt$config <- args[i + 1]
    i <- i + 2
  } else if (arg %in% c("-m", "--mode") && i < length(args)) {
    opt$mode <- args[i + 1]
    i <- i + 2
  } else if (arg %in% c("-o", "--offline")) {
    opt$offline <- TRUE
    i <- i + 1
  } else if (arg %in% c("-d", "--output_dir") && i < length(args)) {
    opt$output_dir <- args[i + 1]
    i <- i + 2
  } else if (arg %in% c("-y", "--year") && i < length(args)) {
    opt$year <- as.integer(args[i + 1])
    i <- i + 2
  } else if (arg %in% c("-l", "--max_items") && i < length(args)) {
    opt$max_items <- as.integer(args[i + 1])
    i <- i + 2
  } else if (arg == "--max-processes" && i < length(args)) {
    opt$max_items <- as.integer(args[i + 1])
    i <- i + 2
  } else if (arg == "--max-segments" && i < length(args)) {
    opt$max_segments <- as.integer(args[i + 1])
    i <- i + 2
  } else if (arg == "--tramitando" && i < length(args)) {
    opt$tramitando <- toupper(args[i + 1])
    i <- i + 2
  } else if (arg == "--process-ids-file" && i < length(args)) {
    opt$process_ids_file <- args[i + 1]
    i <- i + 2
  } else if (arg == "--segments-file" && i < length(args)) {
    opt$segments_file <- args[i + 1]
    i <- i + 2
  } else {
    i <- i + 1
  }
}

cat("=================================================================\n")
cat("      INVENTÁRIO HISTÓRICO DO SENADO FEDERAL - FRENTE 10         \n")
cat("=================================================================\n")
cat("Configuracao: ", opt$config, "\n")
cat("Modo:         ", opt$mode, "\n")
cat("Offline:      ", opt$offline, "\n")
if (is.null(opt$mode) || !opt$mode %in% c("smoke", "audit", "full")) stop("Informe --mode smoke|audit|full.")

# Carregar arquivo de configuração
config_path <- file.path(repo_root, opt$config)
cfg <- if (file.exists(config_path)) yaml::read_yaml(config_path) else list()

base_url <- cfg$senado$base_api_url %||% "https://legis.senado.leg.br/dadosabertos/v3"
user_agent <- cfg$network$user_agent %||% "LLM-Legislativo-Pesquisa-Educacional/2.0"
data_root_path <- resolve_external_data_root(repo_root)

target_dir <- if (!is.null(opt$output_dir)) {
  opt$output_dir
} else {
  file.path(data_root_path, "staging", "inventory", "senado")
}
target_dir <- assert_data_path(target_dir, data_root_path, "output_dir")

cat("Base API:     ", base_url, "\n")
cat("Target Dir:   ", target_dir, "\n\n")

# Criar cliente HTTP / Snapshot recorder
client <- create_senado_client(
  base_url = base_url,
  user_agent = user_agent,
  offline_mode = opt$offline,
  snapshot_store_dir = file.path(data_root_path, "raw", "snapshots", "senado")
)

# 1. Descoberta de Taxonomias
cat("[1/5] Descobrindo taxonomias, siglas e tipos documentais...\n")
taxonomies_df <- discover_senado_taxonomies(client)
cat("      -> Total de tipos legislativos catalogados:", nrow(taxonomies_df), "\n")

# 2. Registro de Coleções e Evidências
cat("[2/5] Registrando coleções oficiais e evidências de uso...\n")
initial_snap_id <- client$snapshots_log[[1]]$snapshot_id %||% hash_string("initial_senado_snap")
collections_df <- register_senado_collections(initial_snap_id)
use_evidence_df <- build_senado_use_evidence(initial_snap_id)
cat("      -> Total de coleções registradas:", nrow(collections_df), "\n")

# 3. Construção de Segmentos de Cobertura
cat("[3/5] Estruturando segmentos de cobertura histórica (G1/GH)...\n")
coverage_segments_df <- build_senado_coverage_segments(collections_df, initial_snap_id)
cat("      -> Total de segmentos de cobertura:", nrow(coverage_segments_df), "\n")

# 4. Execução do Inventário de Processos
cat("[4/5] Inventariando processos, documentos, fases e emendas...\n")
years_to_run <- if (!is.null(opt$year)) c(opt$year) else if (opt$mode == "smoke") c(2024) else NULL
siglas_to_run <- if (opt$mode == "smoke") c("PL") else NULL
tramitando_filter <- if (!is.null(opt$tramitando)) {
  if (!opt$tramitando %in% c("S", "N")) stop("--tramitando aceita S ou N.")
  opt$tramitando
} else c("S", "N")
max_children <- opt$max_items
process_ids <- NULL
segment_specs <- NULL
if (!is.null(opt$segments_file)) {
  if (!file.exists(opt$segments_file)) stop("Arquivo de segmentos não encontrado: ", opt$segments_file)
  segment_specs <- jsonlite::fromJSON(opt$segments_file, simplifyVector = FALSE)
}
if (!is.null(opt$process_ids_file)) {
  if (!file.exists(opt$process_ids_file)) stop("Arquivo de IDs não encontrado: ", opt$process_ids_file)
  process_ids <- trimws(readLines(opt$process_ids_file, warn = FALSE))
  process_ids <- process_ids[nzchar(process_ids)]
  process_ids <- unique(process_ids)
}
cat("Escopo processo: full usa fatias anuais por sigla e estado, derivadas das vigências no catálogo oficial; siglas sem início verificável permanecem pending.\n")
cat("Limite operacional de processos com consultas filhas nesta execução:", max_children, "\n")
cat("Limite operacional de segmentos anuais nesta execução:", opt$max_segments, "\n")
if (!is.null(segment_specs)) cat("Retomada de fila explícita:", length(segment_specs), "segmentos recebidos.\n")
if (!is.null(process_ids)) cat("Retomada dirigida por IDs: ", length(process_ids), " processos em blocos documentados de até 100.\n", sep = "")

# Executar inventário em ambos os estados: tramitando ('S') e encerrados ('N')
engine_out <- inventory_senado_processes(
  client = client,
  years = years_to_run,
  siglas = siglas_to_run,
  tramitando_filter = tramitando_filter,
  fetch_child_entities = TRUE,
  max_processes_per_run = max_children,
  process_ids = process_ids,
  max_segments_per_run = opt$max_segments,
  segment_specs = segment_specs
)

# Substituir os segmentos API pending pelos estados medidos nesta execução;
# coleções de Anais/Diários continuam pending sem enumeração de unidades.
for (j in seq_len(nrow(engine_out$coverage_segments))) {
  seg <- engine_out$coverage_segments[j, , drop = FALSE]
  existing <- which(coverage_segments_df$segment_id == seg$segment_id)
  if (length(existing) == 1L) coverage_segments_df[existing, ] <- seg
  else coverage_segments_df <- rbind(coverage_segments_df, seg)
}

cat("      -> Proposicoes descobertas:     ", nrow(engine_out$propositions), "\n")
cat("      -> Documentos descobertos:      ", nrow(engine_out$documents), "\n")
cat("      -> Pontes processo-documento:   ", nrow(engine_out$proposition_documents), "\n")
cat("      -> Fases de processo:           ", nrow(engine_out$process_phases), "\n")
cat("      -> Pontes documento-fase:       ", nrow(engine_out$document_phases), "\n")
cat("      -> Autores catalogados:         ", nrow(engine_out$authors), "\n")
cat("      -> Aliases (MATE legado / CD):  ", nrow(engine_out$entity_aliases), "\n")
cat("      -> Verificacoes de endpoint:    ", nrow(engine_out$metadata_checks), "\n")

# 5. Agregação e Publicação Parquet
cat("[5/5] Consolidando tabelas e publicando Parquets normativos...\n")
snapshots_df <- client$get_snapshots_df()

all_tables <- list(
  source_snapshots = snapshots_df,
  source_collections = collections_df,
  use_evidence = use_evidence_df,
  legislative_types = taxonomies_df,
  coverage_segments = coverage_segments_df,
  propositions = engine_out$propositions,
  process_phases = engine_out$process_phases,
  documents = engine_out$documents,
  proposition_documents = engine_out$proposition_documents,
  document_phases = engine_out$document_phases,
  authors = engine_out$authors,
  proposition_authors = engine_out$proposition_authors,
  document_authors = engine_out$document_authors,
  relations = engine_out$relations,
  entity_aliases = engine_out$entity_aliases,
  metadata_checks = engine_out$metadata_checks
)

pub_res <- publish_senado_inventory(
  tables = all_tables,
  target_dir = target_dir
)

if (length(engine_out$pending_process_ids) > 0L) {
  pending_path <- file.path(target_dir, paste0("pending_process_ids_", pub_res$run_id, ".txt"))
  writeLines(engine_out$pending_process_ids, pending_path, useBytes = TRUE)
  cat("Fila de retomada por ID: ", pending_path, " (", length(engine_out$pending_process_ids), " IDs)\n", sep = "")
}
if (length(engine_out$pending_segment_specs) > 0L) {
  pending_segments_path <- file.path(target_dir, paste0("pending_segments_", pub_res$run_id, ".json"))
  writeLines(jsonlite::toJSON(engine_out$pending_segment_specs, auto_unbox = TRUE, pretty = TRUE, null = "null"), pending_segments_path, useBytes = TRUE)
  cat("Fila de retomada anual: ", pending_segments_path, " (", length(engine_out$pending_segment_specs), " segmentos; reutilizar com --segments-file)", "\n", sep = "")
}

cat("\n=================================================================\n")
cat("             PUBLICAÇÃO CONCLUÍDA COM SUCESSO!                   \n")
cat("=================================================================\n")
cat("Run ID:         ", pub_res$run_id, "\n")
cat("Diretorio:      ", pub_res$output_dir, "\n")
cat("Manifesto:      ", pub_res$manifest_path, "\n")
cat("COMPLETE.json:  ", pub_res$complete_path, "\n\n")

cat("Resumo de Linhas Publicadas por Tabela:\n")
for (tname in names(pub_res$tables_summary)) {
  cat(sprintf("  %-25s : %6d linhas\n", tname, pub_res$tables_summary[[tname]]))
}
cat("=================================================================\n")
