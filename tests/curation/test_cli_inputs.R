# Garante que o CLI não escolha silenciosamente probes de Senado/extração.
suppressPackageStartupMessages(library(testthat))

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

run_curate_cli <- function(args) {
  rscript <- Sys.which("Rscript")
  if (!nzchar(rscript)) skip("Rscript indisponível para teste da CLI")
  script <- file.path(repo_root, "scripts", "curate.R")
  output <- suppressWarnings(system2(
    rscript,
    args = c(shQuote(script), args),
    stdout = TRUE,
    stderr = TRUE,
    env = paste0("DATA_ROOT=", tempdir())
  ))
  status <- attr(output, "status")
  if (is.null(status)) status <- 0L
  list(output = paste(output, collapse = "\n"), status = status)
}

test_that("CLI exige caminho explícito do inventário Senado antes de iniciar", {
  result <- run_curate_cli(c("--input-extraction", "external/extraction"))
  expect_false(identical(result$status, 0L))
  expect_match(result$output, "--input-senado")
  expect_match(result$output, "A curadoria não foi iniciada")
})

test_that("CLI exige caminho explícito da extração antes de iniciar", {
  result <- run_curate_cli(c("--input-senado", "external/senado"))
  expect_false(identical(result$status, 0L))
  expect_match(result$output, "--input-extraction")
  expect_match(result$output, "A curadoria não foi iniciada")
})
