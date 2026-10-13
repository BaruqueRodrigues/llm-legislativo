suppressPackageStartupMessages({library(testthat); library(jsonlite)})
repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) repo_root <- dirname(repo_root)
source(file.path(repo_root, "R/inventory/camara/inventory_engine.R"))

test_that("modo oficial usa páginas reais/mockadas, retoma e não fabrica entidades", {
  out <- tempfile("camara-resume-")
  calls <- character()
  mock <- function(url, page) {
    calls <<- c(calls, url)
    if (grepl("referencias/proposicoes/siglaTipo", url, fixed=TRUE)) {
      return(list(status="succeeded", http_status=200L, finished_at=Sys.time(),
        body=list(dados=list(list(cod="fixture-PEC",sigla="PEC",nome="Mock PEC",descricao="")),links=list())))
    }
    if (page == 1L) return(list(status="succeeded", http_status=200L, finished_at=Sys.time(),
      body=list(dados=list(list(id="MOCK-1",siglaTipo="PEC",codTipo="fixture-PEC",descricaoTipo="Mock PEC",
        numero=1L,ano=1934L,dataApresentacao="1934-02-01",ementa="Mock page one",
        uri="https://mock.api/proposicoes/MOCK-1")),
        links=list(list(rel="next",href="https://mock.api/proposicoes?pagina=2")))))
    list(status="succeeded", http_status=200L, finished_at=Sys.time(),
      body=list(dados=list(list(id="MOCK-2",siglaTipo="PEC",codTipo="fixture-PEC",descricaoTipo="Mock PEC",
        numero=2L,ano=1934L,dataApresentacao="1934-02-02",ementa="Mock page two",
        uri="https://mock.api/proposicoes/MOCK-2")),links=list()))
  }
  first <- run_camara_inventory(output_dir=out,is_sample=FALSE,request_fn=mock,max_segments=1L,max_pages_per_segment=1L,max_enrichment_requests=0L)
  expect_equal(first$manifest$status,"partial")
  expect_equal(first$tables$coverage_segments$inventory_status,"running")
  expect_true(file.exists(file.path(out,"progress.json")))
  expect_true(file.exists(file.path(out,"pages/1934-Q1/page-000001.json")))
  expect_equal(nrow(first$tables$propositions),1L)
  expect_equal(first$tables$propositions$source_id,"MOCK-1")
  expect_true(all(first$tables$propositions$snapshot_id %in% first$tables$source_snapshots$snapshot_id))

  second <- run_camara_inventory(output_dir=out,is_sample=FALSE,request_fn=mock,max_segments=1L,max_pages_per_segment=1L,max_enrichment_requests=0L)
  expect_equal(second$tables$coverage_segments$inventory_status,"running")
  expect_equal(second$tables$coverage_segments$coverage_status,"partial")
  expect_equal(sort(second$tables$propositions$source_id),c("MOCK-1","MOCK-2"))
  expect_false(any(second$tables$authors$author_id == "camara:author:local:parlamentar_voto"))
  expect_true(all(second$tables$source_snapshots$http_status == 200L))
  expect_true(all(second$tables$source_snapshots$payload_sha256 != ""))
  expect_false(second$manifest$summary$inventory_complete)
  expect_true(all(grepl("mock|dadosabertos", second$tables$propositions$source_uri)))
})

test_that("run_camara_inventory integra enriquecimento ao lote e à cobertura", {
  out <- tempfile("camara-e2e-enrichment-")
  good <- function(body) list(status="succeeded",http_status=200L,attempts=1L,finished_at=Sys.time(),body=body)
  mock <- function(url,page) {
    if (grepl("referencias/proposicoes/siglaTipo",url,fixed=TRUE)) return(good(list(
      dados=list(list(cod="139",sigla="PL",nome="Projeto de Lei",descricao="")),links=list())))
    if (grepl("/autores$",url)) return(good(list(dados=list(list(nome="Autor",tipo="Deputado",
      uri="https://dadosabertos.camara.leg.br/api/v2/deputados/55",proponente=1,ordemAssinatura=1)),links=list())))
    if (grepl("/temas$",url) || grepl("/relacionadas$",url) || grepl("/tramitacoes$",url))
      return(good(list(dados=list(),links=list())))
    if (grepl("/proposicoes/E2E-1$",url)) return(good(list(dados=list(id="E2E-1",siglaTipo="PL",
      codTipo="139",numero=1L,ano=1934L,dataApresentacao="1934-02-01",ementa="Detalhe",
      urlInteiroTeor="https://www.camara.leg.br/inteiro?codteor=55"),links=list())))
    good(list(dados=list(list(id="E2E-1",siglaTipo="PL",codTipo="139",numero=1L,ano=1934L,
      dataApresentacao="1934-02-01",ementa="Listagem",uri="https://dadosabertos.camara.leg.br/api/v2/proposicoes/E2E-1")),links=list()))
  }
  result <- run_camara_inventory(output_dir=out,is_sample=FALSE,request_fn=mock,max_segments=1L,
    max_pages_per_segment=10L,max_enrichment_requests=5L)
  expect_equal(result$manifest$status,"partial")
  expect_equal(result$manifest$enrichment$endpoint_pages_used,5L)
  expect_equal(result$tables$propositions$summary,"Detalhe")
  expect_equal(nrow(result$tables$authors),1L)
  expect_equal(nrow(result$tables$documents),1L)
  expect_equal(result$tables$coverage_segments$coverage_status,"closed_with_gaps")
  expect_equal(result$tables$coverage_segments$retrieved_count,1L)
  expect_true(all(result$tables$metadata_checks$status %in% c("success_nonempty","success_empty")))
})
