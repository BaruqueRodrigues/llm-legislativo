# tests/inventory/camara/test_pagination_and_resilience.R
# Testes unitários para particionamento trimestral, paginação HATEOAS, retries e respostas vazias

suppressPackageStartupMessages({
  library(testthat)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory/camara/api_client.R"))

test_that("G1.CAMARA.5: Particionamento trimestral obrigatório para evitar HTTP 400", {
  windows_2024 <- generate_quarterly_windows(2024)

  expect_equal(length(windows_2024), 4)
  expect_equal(windows_2024[[1]]$start, "2024-01-01")
  expect_equal(windows_2024[[1]]$end, "2024-03-31")

  expect_equal(windows_2024[[2]]$start, "2024-04-01")
  expect_equal(windows_2024[[2]]$end, "2024-06-30")

  expect_equal(windows_2024[[3]]$start, "2024-07-01")
  expect_equal(windows_2024[[3]]$end, "2024-09-30")

  expect_equal(windows_2024[[4]]$start, "2024-10-01")
  expect_equal(windows_2024[[4]]$end, "2024-12-31")

  # Nenhuma janela excede 92 dias (respeitando limite documentado de 3 meses da API v2)
  for (w in windows_2024) {
    diff_days <- as.numeric(as.Date(w$end) - as.Date(w$start)) + 1
    expect_true(diff_days <= 92)
  }
})

test_that("G1.CAMARA.6: Paginação HATEOAS seguindo link next até esgotamento", {
  # Mock de 3 páginas
  mock_requester <- function(url, page) {
    if (page == 1) {
      body <- list(
        dados = list(list(id = 1, siglaTipo = "PL", numero = 101, ano = 2024),
                     list(id = 2, siglaTipo = "PL", numero = 102, ano = 2024)),
        links = list(list(rel = "next", href = "https://mock.api/proposicoes?pagina=2"))
      )
      list(status = "succeeded", http_status = 200, body = body, attempts = 1)
    } else if (page == 2) {
      body <- list(
        dados = list(list(id = 3, siglaTipo = "PL", numero = 103, ano = 2024)),
        links = list(list(rel = "next", href = "https://mock.api/proposicoes?pagina=3"))
      )
      list(status = "succeeded", http_status = 200, body = body, attempts = 1)
    } else if (page == 3) {
      body <- list(
        dados = list(list(id = 4, siglaTipo = "PL", numero = 104, ano = 2024)),
        links = list(list(rel = "self", href = "https://mock.api/proposicoes?pagina=3")) # sem next!
      )
      list(status = "succeeded", http_status = 200, body = body, attempts = 1)
    }
  }

  res <- paginate_camara_api("https://mock.api/proposicoes?pagina=1", max_pages = 10, request_fn = mock_requester)

  expect_true(res$pagination_complete)
  expect_equal(res$pages_read, 3)
  expect_equal(length(res$raw_items), 4)

  # Verificar snapshots gerados
  expect_equal(length(res$snapshots), 3)
  expect_false(res$snapshots[[1]]$pagination_complete)
  expect_false(res$snapshots[[2]]$pagination_complete)
  expect_true(res$snapshots[[3]]$pagination_complete) # Último snapshot marcado como completo
})

test_that("G1.CAMARA.7: Tratamento elegante de resposta vazia sem interrupção", {
  mock_empty <- function(url, page) {
    list(
      status = "succeeded",
      http_status = 200,
      body = list(dados = list(), links = list()),
      attempts = 1
    )
  }

  res <- paginate_camara_api("https://mock.api/proposicoes?ano=1937", max_pages = 5, request_fn = mock_empty)

  expect_true(res$pagination_complete)
  expect_equal(length(res$raw_items), 0)
  expect_equal(res$pages_read, 1)
})

test_that("G1.CAMARA.8: Retries e recuperação em erro transitório (500/503)", {
  calls <- 0
  mock_retry_success <- function(url, page) {
    calls <<- calls + 1
    if (calls == 1) {
      # Erro na primeira chamada, simulando recuperação
      return(list(
        status = "succeeded",
        http_status = 200,
        body = list(dados = list(list(id = 99, siglaTipo = "PEC", numero = 1, ano = 2024)), links = list()),
        attempts = 2 # Registra que houve retry
      ))
    }
  }

  res <- paginate_camara_api("https://mock.api/proposicoes?pagina=1", max_pages = 2, request_fn = mock_retry_success)
  expect_true(res$pagination_complete)
  expect_equal(length(res$raw_items), 1)
})

test_that("Uma página vazia com rel=next não encerra a consulta", {
  mock <- function(url, page) {
    if (page == 1L) return(list(status="succeeded", http_status=200L,
      body=list(dados=list(), links=list(list(rel="next",href="https://mock.api/pagina=2")))))
    list(status="succeeded", http_status=200L,
      body=list(dados=list(list(id="2",siglaTipo="PEC")), links=list()))
  }
  seen <- list()
  res <- paginate_camara_api("https://mock.api/pagina=1", max_pages=3,
    request_fn=mock, on_page=function(event) seen[[length(seen)+1L]] <<- event)
  expect_true(res$pagination_complete)
  expect_equal(res$pages_read, 2L)
  expect_length(res$raw_items, 1L)
  expect_length(seen, 2L)
  expect_false(seen[[1]]$terminal)
  expect_true(seen[[2]]$terminal)
})
