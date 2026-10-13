#!/usr/bin/env Rscript
# scripts/extract.R
# CLI executável do subagente 03: Extração nativa Mac (PDFKit) e OCR Apple Vision (pt-BR)
# Uso: Rscript scripts/extract.R --config configs/extraction/history.yaml [--mode auto|benchmark|smoke|full]

parse_args_fallback <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  opts <- list(
    config = "configs/extraction/history.yaml",
    mode = "auto",
    input_dir = NULL,
    output_dir = NULL,
    benchmark = FALSE,
    skip_benchmark = FALSE,
    run_id = NULL
  )

  i <- 1
  while (i <= length(args)) {
    arg <- args[i]
    if (arg %in% c("--config", "-c") && i < length(args)) {
      opts$config <- args[i + 1]
      i <- i + 1
    } else if (arg %in% c("--mode", "-m") && i < length(args)) {
      opts$mode <- args[i + 1]
      i <- i + 1
    } else if (arg %in% c("--input-dir", "-i") && i < length(args)) {
      opts$input_dir <- args[i + 1]
      i <- i + 1
    } else if (arg %in% c("--output-dir", "-o") && i < length(args)) {
      opts$output_dir <- args[i + 1]
      i <- i + 1
    } else if (arg == "--benchmark") {
      opts$benchmark <- TRUE
    } else if (arg == "--skip-benchmark") {
      opts$skip_benchmark <- TRUE
    } else if (arg == "--run-id" && i < length(args)) {
      opts$run_id <- args[i + 1]
      i <- i + 1
    }
    i <- i + 1
  }
  return(opts)
}

opts <- parse_args_fallback()

# Localizar raiz do repositório
repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

cat("====================================================================\n")
cat(" LLM Legislativo Brasileiro — Frente 03: Extração Nativa & OCR Vision\n")
cat(" Perfil: mac_native_v1 (PDFKit + Apple Vision pt-BR)\n")
cat("====================================================================\n\n")

# A resolução de DATA_ROOT e a validação de caminhos são utilitários comuns;
# carregá-los antes de usá-los aqui evita depender do preflight para defini-los.
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

# Carregar módulos da Frente 03
source(file.path(repo_root, "R", "extraction", "preflight.R"))
source(file.path(repo_root, "R", "extraction", "pdf_extractor.R"))
source(file.path(repo_root, "R", "extraction", "section_parser.R"))
source(file.path(repo_root, "R", "extraction", "quality_auditor.R"))
source(file.path(repo_root, "R", "extraction", "publisher.R"))

# A CLI de produção nunca herda a exceção de diretório temporário usada por testes unitários.
data_root <- resolve_external_data_root(repo_root)
if (!is.null(opts$output_dir)) {
  opts$output_dir <- assert_data_path(opts$output_dir, data_root, "output_dir")
}
if (!is.null(opts$input_dir)) {
  opts$input_dir <- assert_data_path(opts$input_dir, data_root, "input_dir")
}

# 1. Preflight
cat("[1/5] Executando preflight do ambiente macOS...\n")
preflight <- run_extraction_preflight(repo_root)
if (!preflight$preflight_passed) {
  stop("Preflight falhou: Apple Vision com pt-BR não disponível.")
}
cat("      SO:", preflight$host_os_build, "\n")
cat("      Vision Revision:", preflight$details$vision_default_revision, "\n")
cat("      Helper compilado SHA-256:", substr(preflight$helper_binary_sha256, 1, 16), "...\n\n")

# 2. Carregar configuração
cat("[2/5] Carregando configuração de extração:", opts$config, "\n")
cfg <- load_extraction_config(opts$config)

# 3. Descobrir PDFs para extração
cat("[3/5] Identificando documentos para processamento...\n")
pdf_files <- if (!is.null(opts$input_dir) && dir.exists(opts$input_dir)) {
  list.files(opts$input_dir, pattern = "\\.pdf$", full.names = TRUE)
} else if (opts$mode == "smoke") {
  # Fixtures sintéticas somente quando o modo de smoke é explicitamente pedido.
  fixtures_dir <- file.path(repo_root, "tests", "extraction", "fixtures")
  list.files(fixtures_dir, pattern = "\\.pdf$", full.names = TRUE)
} else {
  stop("Informe --input-dir com PDFs de DATA_ROOT; fixtures só são usadas com --mode smoke.")
}

if (length(pdf_files) == 0) {
  stop("Nenhum arquivo PDF encontrado para extração.")
}
cat("      Encontrados", length(pdf_files), "documentos PDF.\n\n")

# 4. Extração e Parse de Seções
cat("[4/5] Processando documentos por página e segmentando seções...\n")
all_runs <- list()
all_pages <- list()
all_sections <- list()

source_map_path <- if (!is.null(opts$input_dir)) {
  file.path(dirname(opts$input_dir), "source_members.csv")
} else ""
source_map <- NULL
if (nzchar(source_map_path) && file.exists(source_map_path)) {
  source_map <- utils::read.csv(source_map_path, stringsAsFactors = FALSE, check.names = FALSE)
  required_source_map <- c("member", "version_id")
  if (!all(required_source_map %in% names(source_map))) {
    stop("source_members.csv must contain member and version_id columns")
  }
  source_map$member_stem <- tools::file_path_sans_ext(basename(source_map$member))
  if (anyDuplicated(source_map$member_stem)) {
    stop("source_members.csv has ambiguous member basenames")
  }
}

for (idx in seq_along(pdf_files)) {
  p_file <- pdf_files[idx]
  fname <- basename(p_file)
  ver_id <- NULL
  if (!is.null(source_map)) {
    matches <- which(source_map$member_stem == tools::file_path_sans_ext(fname))
    if (length(matches) != 1L || is.na(source_map$version_id[matches])) {
      stop("source_members.csv does not uniquely map PDF input: ", fname)
    }
    ver_id <- source_map$version_id[matches]
  }
  if (is.null(ver_id)) {
    ver_id <- paste0("doc:v1:", tools::file_path_sans_ext(fname))
  }

  cat(sprintf("      [%d/%d] Extraindo: %s\n", idx, length(pdf_files), fname))

  doc_ext <- extract_document(
    pdf_path = p_file,
    version_id = ver_id,
    config = cfg,
    preflight_info = preflight,
    mode = if (opts$mode == "benchmark") "auto" else opts$mode,
    enable_benchmark = (opts$benchmark || opts$mode == "benchmark")
  )

  all_runs[[idx]] <- doc_ext$run

  if (nrow(doc_ext$pages) > 0) {
    all_pages[[idx]] <- doc_ext$pages
    secs <- parse_document_sections(doc_ext$run$extraction_id, doc_ext$pages)
    all_sections[[idx]] <- secs
  }
}

runs_df <- dplyr::bind_rows(all_runs)
pages_df <- if (length(all_pages) > 0) dplyr::bind_rows(all_pages) else tibble()
sections_df <- if (length(all_sections) > 0) dplyr::bind_rows(all_sections) else tibble()

# 5. Auditoria de Qualidade e Benchmark Comparativo
cat("[5/5] Executando auditoria de qualidade e medição de latência...\n")
bench_audit <- if (opts$skip_benchmark) {
  list(results = list(), quality_reviews = tibble())
} else run_extraction_benchmark(
  test_fixtures = c(
    "tests/extraction/fixtures/scanned_image.pdf",
    "tests/extraction/fixtures/native_digital.pdf",
    "tests/extraction/fixtures/mixed_document.pdf",
    "tests/extraction/fixtures/two_columns.pdf"
  )
)
quality_reviews_df <- bench_audit$quality_reviews

# Benchmark cria execuções identificáveis próprias. Seus resultados e pages entram
# nas mesmas tabelas para que cada quality_review aponte ao documento realmente medido.
if (length(bench_audit$results) > 0) {
  bench_runs <- lapply(bench_audit$results, function(doc) doc$run)
  bench_pages <- lapply(bench_audit$results, function(doc) doc$pages)
  bench_sections <- lapply(bench_audit$results, function(doc) {
    if (nrow(doc$pages) > 0) parse_document_sections(doc$run$extraction_id, doc$pages) else tibble()
  })
  runs_df <- dplyr::bind_rows(runs_df, dplyr::bind_rows(bench_runs))
  pages_df <- dplyr::bind_rows(pages_df, dplyr::bind_rows(bench_pages))
  sections_df <- dplyr::bind_rows(sections_df, dplyr::bind_rows(bench_sections))
}

valid_run_ids <- unique(runs_df$extraction_id)
if (nrow(quality_reviews_df) > 0 && !all(quality_reviews_df$extraction_id %in% valid_run_ids)) {
  stop("quality_reviews contém extraction_id sem execution correspondente; publicação abortada.")
}

# 6. Publicação das Tabelas Parquet
run_id <- opts$run_id %||% format(Sys.time(), "extraction_%Y%m%d_%H%M%S", tz = "UTC")
pub_result <- publish_extraction_tables(
  extraction_runs_df = runs_df,
  pages_df = pages_df,
  sections_df = sections_df,
  quality_reviews_df = quality_reviews_df,
  run_id = run_id,
  output_dir = opts$output_dir
)

# Validar publicação
val_res <- validate_extraction_publication(pub_result$output_dir)
if (!val_res$valid) {
  stop("Falha na validação da publicação: ", val_res$error)
}

cat("\n====================================================================\n")
cat(" EXTRAÇÃO CONCLUÍDA COM SUCESSO!\n")
cat("====================================================================\n")
cat(" Diretório de publicação:", pub_result$output_dir, "\n")
cat(" Manifest SHA-256:       ", pub_result$manifest_sha256, "\n")
cat(" Extraction Runs:        ", nrow(runs_df), "\n")
cat(" Páginas Extraídas:      ", nrow(pages_df), "\n")
cat("   - Método Nativo:      ", sum(pages_df$method == "native"), "\n")
cat("   - Método OCR Vision:  ", sum(pages_df$method == "ocr"), "\n")
cat("   - Nenhum/Vazio:       ", sum(pages_df$method == "none"), "\n")
cat(" Seções Identificadas:   ", nrow(sections_df), "\n")
cat(" Reviews de Qualidade:   ", nrow(quality_reviews_df), "\n")
cat(" COMPLETE.json gravado e verificado com sucesso!\n")
cat("====================================================================\n")
