suppressPackageStartupMessages({library(testthat); library(jsonlite)})
repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) repo_root <- dirname(repo_root)
source(file.path(repo_root,"R/inventory/camara/inventory_engine.R"))

make_prop <- function(id="77") parse_camara_propositions(list(list(id=id,siglaTipo="PL",codTipo="139",
  descricaoTipo="Projeto de Lei",numero=2L,ano=2024L,dataApresentacao="2024-02-01",
  uri=paste0("https://dadosabertos.camara.leg.br/api/v2/proposicoes/",id))),"camara:snap:list")

ok <- function(body) list(status="succeeded",http_status=200L,attempts=1L,finished_at=Sys.time(),body=body)

test_that("enriquecimento faz detalhe/autores/temas/tramitações/relacionadas e retoma idempotente", {
  out<-tempfile("camara-enrichment-"); props<-make_prop()
  mock<-function(url,page) {
    if(grepl("/autores$",url)) return(ok(list(dados=list(list(nome="Autoria oficial",tipo="Deputado",
      uri="https://dadosabertos.camara.leg.br/api/v2/deputados/123",proponente=1,ordemAssinatura=1)),links=list())))
    if(grepl("/temas$",url)) return(ok(list(dados=list(),links=list())))
    if(grepl("/tramitacoes$",url)) return(ok(list(dados=list(list(sequencia=3L,siglaOrgao="CCJC",
      dataHora="2024-03-01T10:00",descricaoTramitacao="Distribuição",url="https://mock/tram/3")),links=list())))
    if(grepl("/relacionadas$",url)) return(ok(list(dados=list(),links=list())))
    ok(list(dados=list(id="77",siglaTipo="PL",codTipo="139",descricaoTipo="Projeto de Lei",
      numero=2L,ano=2024L,dataApresentacao="2024-02-01",ementa="Detalhe API",
      uri="https://dadosabertos.camara.leg.br/api/v2/proposicoes/77",
      urlInteiroTeor="https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=987"),links=list()))
  }
  first<-run_camara_enrichment(props,out,"https://dadosabertos.camara.leg.br/api/v2",mock,5L)
  expect_equal(first$requests_used,5L)
  expect_equal(first$queue$status[match(camara_enrichment_endpoints,first$queue$endpoint_kind)],
    c("success_nonempty","success_nonempty","success_empty","success_nonempty","success_empty"))
  expect_equal(first$propositions$summary,"Detalhe API")
  expect_equal(nrow(first$authors),1L)
  expect_equal(nrow(first$themes),0L)
  expect_equal(nrow(first$process_phases),1L)
  expect_equal(nrow(first$documents),1L)
  expect_equal(first$documents$normalized_kind,"unknown")
  expect_equal(nrow(first$proposition_documents),1L)
  expect_equal(first$proposition_documents$role_status,"unknown")
  expect_true(all(first$source_snapshots$payload_sha256!=""))
  expect_equal(nrow(first$metadata_checks),6L)

  second<-run_camara_enrichment(first$propositions,out,"https://dadosabertos.camara.leg.br/api/v2",mock,5L)
  expect_equal(second$requests_used,0L)
  expect_equal(nrow(second$authors),1L)
  expect_equal(nrow(second$documents),1L)
  coverage<-data.frame(segment_id="camara:col:api_v2:proposicoes:presentation:2024:Q1",
    year=2024L,period_start=as.Date("2024-01-01"),period_end=as.Date("2024-03-31"),
    inventory_status="exhausted",coverage_status="complete_discovered",retrieved_count=0L,gap_reason=NA_character_)
  updated<-camara_update_enrichment_coverage(coverage,second$propositions,second$queue)
  expect_equal(updated$retrieved_count,1L)
  expect_equal(updated$inventory_status,"exhausted")
  expect_equal(updated$coverage_status,"closed_with_gaps")
  expect_match(updated$gap_reason,"portal/arquivos")
})

test_that("429 deixa tarefa retomável e erro/empty ficam explícitos", {
  out<-tempfile("camara-enrichment-retry-"); props<-make_prop("88")
  rate_limit<-function(url,page) list(status="retryable_error_exhausted",http_status=429L,
    attempts=6L,error_message="rate limited",finished_at=Sys.time())
  first<-run_camara_enrichment(props,out,"https://mock.api/v2",rate_limit,1L)
  expect_equal(first$queue$status[1],"retryable_error")
  expect_equal(first$queue$attempts[1],6L)
  expect_equal(first$metadata_checks$status[1],"retryable_error")
  recovered<-run_camara_enrichment(props,out,"https://mock.api/v2",function(url,page)
    ok(list(dados=list(id="88",siglaTipo="PL",codTipo="139",numero=1L,ano=2024L),links=list())),1L)
  expect_equal(recovered$queue$status[1],"success_nonempty")
  expect_equal(recovered$queue$attempts[1],7L)
  expect_equal(sum(recovered$source_snapshots$http_status==429L),1L)
  expect_equal(sum(recovered$source_snapshots$http_status==200L),1L)
})
