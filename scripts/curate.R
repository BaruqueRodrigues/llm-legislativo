#!/usr/bin/env Rscript
# scripts/curate.R
# CLI executável da Frente 04: Curadoria histórica, deduplicação e divisão em splits
# Uso: Rscript scripts/curate.R --input-senado <dir> --input-extraction <dir> --config configs/curation/history.yaml [--output-dir <dir>] [--release-id <id>]

suppressPackageStartupMessages({
  library(yaml)
  library(arrow)
  library(dplyr)
  library(tibble)
  library(jsonlite)
})

parse_args <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  opts <- list(
    config = "configs/curation/history.yaml",
    input_camara = NULL,
    input_senado = NULL,
    input_downloads = NULL,
    input_extraction = NULL,
    output_dir = NULL,
    release_id = NULL,
    mode = "full"
  )

  i <- 1L
  while (i <= length(args)) {
    arg <- args[i]
    if (arg %in% c("--config", "-c") && i < length(args)) {
      opts$config <- args[i + 1L]
      i <- i + 1L
    } else if (arg %in% c("--output-dir", "-o") && i < length(args)) {
      opts$output_dir <- args[i + 1L]
      i <- i + 1L
    } else if (arg %in% c("--release-id", "-r") && i < length(args)) {
      opts$release_id <- args[i + 1L]
      i <- i + 1L
    } else if (arg == "--input-camara" && i < length(args)) {
      opts$input_camara <- args[i + 1L]
      i <- i + 1L
    } else if (arg == "--input-senado" && i < length(args)) {
      opts$input_senado <- args[i + 1L]
      i <- i + 1L
    } else if (arg == "--input-downloads" && i < length(args)) {
      opts$input_downloads <- args[i + 1L]
      i <- i + 1L
    } else if (arg == "--input-extraction" && i < length(args)) {
      opts$input_extraction <- args[i + 1L]
      i <- i + 1L
    } else if (arg == "--mode" && i < length(args)) {
      opts$mode <- args[i + 1L]
      i <- i + 1L
    }
    i <- i + 1L
  }
  return(opts)
}

opts <- parse_args()

missing_explicit_inputs <- c(
  if (is.null(opts$input_senado)) "--input-senado",
  if (is.null(opts$input_extraction)) "--input-extraction"
)
if (length(missing_explicit_inputs) > 0L) {
  stop(paste0(
    "Seleção implícita de inventário/extração foi desativada para evitar escolher probes. Informe explicitamente: ",
    paste(missing_explicit_inputs, collapse = " e "),
    ". A curadoria não foi iniciada."
  ), call. = FALSE)
}

# Localizar raiz do repositório
repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))
data_root <- resolve_external_data_root(repo_root)

cat("====================================================================\n")
cat(" LLM Legislativo Brasileiro — Frente 04: Curadoria, Dedup e Splits\n")
cat(" Versão de Contrato: 2.0.0 (Câmara + Senado, Todos os Anos/Categorias)\n")
cat("====================================================================\n\n")

# Carregar módulos da Frente 04
source(file.path(repo_root, "R", "curation", "cleaner.R"))
source(file.path(repo_root, "R", "curation", "containment_dedup.R"))
source(file.path(repo_root, "R", "curation", "family_graph.R"))
source(file.path(repo_root, "R", "curation", "split_engine.R"))
source(file.path(repo_root, "R", "curation", "reconciler.R"))
source(file.path(repo_root, "R", "curation", "publisher.R"))

# 1. Carregar Configuração
cat("[1/6] Carregando configuração de curadoria:", opts$config, "\n")
if (!file.exists(opts$config)) {
  stop(paste("Arquivo de configuração não encontrado:", opts$config))
}
cfg <- yaml::read_yaml(opts$config)
opts$input_camara <- opts$input_camara %||% file.path(data_root, "staging", "inventory_camara")
opts$input_downloads <- opts$input_downloads %||% file.path(data_root, "staging", "downloads")
opts$input_camara <- assert_data_path(opts$input_camara, data_root, "input_camara")
opts$input_downloads <- assert_data_path(opts$input_downloads, data_root, "input_downloads")

# 2. Localizar Entradas do Staging
cat("[2/6] Localizando diretórios e arquivos de entrada do staging...\n")

# Os diretórios de Senado e extração são obrigatoriamente escolhidos pelo operador.
senado_dir <- opts$input_senado
extraction_dir <- opts$input_extraction

cat("      Câmara:", opts$input_camara, "\n")
cat("      Senado:", senado_dir, "\n")
cat("      Downloads:", opts$input_downloads, "\n")
cat("      Extração:", extraction_dir, "\n\n")

# Função auxiliar para leitura segura de Parquet
safe_read_parquet <- function(fpath) {
  if (!is.null(fpath) && file.exists(fpath)) {
    arrow::read_parquet(fpath)
  } else {
    NULL
  }
}

# Carregar Tabelas de Entrada
cat("[3/6] Carregando tabelas do inventário, downloads e extrações...\n")

# Proposições (Câmara + Senado)
cam_props <- safe_read_parquet(file.path(opts$input_camara, "propositions.parquet"))
sen_props <- if (!is.null(senado_dir)) safe_read_parquet(file.path(senado_dir, "propositions.parquet")) else NULL
props_combined <- dplyr::bind_rows(cam_props, sen_props)

# Documentos (Câmara + Senado)
cam_docs <- safe_read_parquet(file.path(opts$input_camara, "documents.parquet"))
sen_docs <- if (!is.null(senado_dir)) safe_read_parquet(file.path(senado_dir, "documents.parquet")) else NULL
docs_combined <- dplyr::bind_rows(cam_docs, sen_docs)

# Vínculos Documento-Proposição
cam_pdocs <- safe_read_parquet(file.path(opts$input_camara, "proposition_documents.parquet"))
sen_pdocs <- if (!is.null(senado_dir)) safe_read_parquet(file.path(senado_dir, "proposition_documents.parquet")) else NULL
pdocs_combined <- dplyr::bind_rows(cam_pdocs, sen_pdocs)

# Relações
cam_rels <- safe_read_parquet(file.path(opts$input_camara, "relations.parquet"))
sen_rels <- if (!is.null(senado_dir)) safe_read_parquet(file.path(senado_dir, "relations.parquet")) else NULL
rels_combined <- dplyr::bind_rows(cam_rels, sen_rels)

# Aliases
cam_aliases <- safe_read_parquet(file.path(opts$input_camara, "entity_aliases.parquet"))
sen_aliases <- if (!is.null(senado_dir)) safe_read_parquet(file.path(senado_dir, "entity_aliases.parquet")) else NULL
aliases_combined <- dplyr::bind_rows(cam_aliases, sen_aliases)

# Fases
cam_phases <- safe_read_parquet(file.path(opts$input_camara, "process_phases.parquet"))
sen_phases <- if (!is.null(senado_dir)) safe_read_parquet(file.path(senado_dir, "process_phases.parquet")) else NULL
phases_combined <- dplyr::bind_rows(cam_phases, sen_phases)

cam_dphases <- safe_read_parquet(file.path(opts$input_camara, "document_phases.parquet"))
sen_dphases <- if (!is.null(senado_dir)) safe_read_parquet(file.path(senado_dir, "document_phases.parquet")) else NULL
dphases_combined <- dplyr::bind_rows(cam_dphases, sen_dphases)

# Permissões
cam_use <- safe_read_parquet(file.path(opts$input_camara, "use_evidence.parquet"))
sen_use <- if (!is.null(senado_dir)) safe_read_parquet(file.path(senado_dir, "use_evidence.parquet")) else NULL
use_combined <- dplyr::bind_rows(cam_use, sen_use)

# Downloads (document_versions)
doc_versions <- safe_read_parquet(file.path(opts$input_downloads, "cumulative_document_versions.parquet"))
if (is.null(doc_versions)) {
  doc_versions <- safe_read_parquet(file.path(opts$input_downloads, "pilot_heterogeneous", "document_versions.parquet"))
}

# Extrações
ext_runs <- if (!is.null(extraction_dir)) safe_read_parquet(file.path(extraction_dir, "extraction_runs.parquet")) else NULL
pages <- if (!is.null(extraction_dir)) safe_read_parquet(file.path(extraction_dir, "pages.parquet")) else NULL
sections <- if (!is.null(extraction_dir)) safe_read_parquet(file.path(extraction_dir, "sections.parquet")) else NULL
q_reviews <- if (!is.null(extraction_dir)) safe_read_parquet(file.path(extraction_dir, "quality_reviews.parquet")) else NULL

cat("      Proposições carregadas:", nrow(props_combined), "\n")
cat("      Documentos de inventário:", nrow(docs_combined), "\n")
cat("      Versões binárias baixadas:", if (!is.null(doc_versions)) nrow(doc_versions) else 0, "\n")
cat("      Extrações disponíveis:", if (!is.null(ext_runs)) nrow(ext_runs) else 0, "\n\n")

# 4. Executar Reconciliação, Limpeza, Deduplicação e Grafo de Famílias
cat("[4/6] Executando reconciliação, limpeza, dedup, grafo e splits...\n")
curation_res <- reconcile_curation_corpus(
  inventory_props_df = props_combined,
  inventory_docs_df = docs_combined,
  prop_docs_df = pdocs_combined,
  relations_df = rels_combined,
  entity_aliases_df = aliases_combined,
  process_phases_df = phases_combined,
  document_phases_df = dphases_combined,
  use_evidence_df = use_combined,
  doc_versions_df = doc_versions,
  extraction_runs_df = ext_runs,
  pages_df = pages,
  sections_df = sections,
  quality_reviews_df = q_reviews,
  config = cfg
)

cat("      Total de itens curados:", nrow(curation_res$curated_documents), "\n")
cat("      Itens elegíveis para o dataset:", sum(curation_res$curated_documents$include_in_dataset == TRUE), "\n")
cat("      Pares deduplicados registrados:", nrow(curation_res$dedup_pairs), "\n")
cat("      Eventos de limpeza registrados:", nrow(curation_res$cleaning_events), "\n")
cat("      Famílias legislativas únicas:", n_distinct(curation_res$curated_documents$family_id), "\n\n")

# 5. Publicação da Release Curada com Verificação de Invariantes
cat("[5/6] Validando contratos de dados e publicando Parquet + manifestos...\n")
rel_id <- opts$release_id %||% format(Sys.time(), "release_curated_gh_2.0.0_%Y%m%d_%H%M%S", tz = "UTC")
out_dir <- opts$output_dir %||% file.path(data_root, "staging", "curation", rel_id)
out_dir <- assert_data_path(out_dir, data_root, "output_dir")
if (!is.null(senado_dir)) senado_dir <- assert_data_path(senado_dir, data_root, "input_senado")
if (!is.null(extraction_dir)) extraction_dir <- assert_data_path(extraction_dir, data_root, "input_extraction")

pub_res <- publish_curated_release(
  curation_results = curation_res,
  output_dir = out_dir,
  release_id = rel_id,
  config = cfg,
  coverage_status = "closed_with_gaps"
)

# 6. Exibir Resumo Final
cat("\n[6/6] Curadoria finalizada com sucesso!\n")
cat("====================================================================\n")
cat(" Release ID:", pub_res$release_id, "\n")
cat(" Diretório de Destino:", pub_res$output_dir, "\n")
cat(" Manifesto SHA-256:", pub_res$manifest_sha256, "\n")
cat(" Splits - Train:", pub_res$manifest$summary$splits$items_count$train, "itens |",
    pub_res$manifest$summary$splits$utf8_bytes$train, "bytes\n")
cat(" Splits - Validation:", pub_res$manifest$summary$splits$items_count$validation, "itens |",
    pub_res$manifest$summary$splits$utf8_bytes$validation, "bytes\n")
cat(" Splits - Test:", pub_res$manifest$summary$splits$items_count$test, "itens |",
    pub_res$manifest$summary$splits$utf8_bytes$test, "bytes\n")
cat(" Splits - Quarantine:", pub_res$manifest$summary$splits$items_count$quarantine, "itens |",
    pub_res$manifest$summary$splits$utf8_bytes$quarantine, "bytes\n")
cat("====================================================================\n")
