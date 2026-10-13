# Offline tests for the Câmara's annual open-data CSV route.
suppressPackageStartupMessages(library(testthat))
repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) repo_root <- dirname(repo_root)
source(file.path(repo_root, "R/download/validator.R"))
source(file.path(repo_root, "R/inventory/common/hashing.R"))
source(file.path(repo_root, "R/inventory/common/storage.R"))
source(file.path(repo_root, "R/download/blob_store.R"))
source(file.path(repo_root, "R/download/camara_annual_csv.R"))

fixture_csv <- charToRaw("id;sigla;numero\n1;PL;10\n")

test_that("URLs anuais usam os três conjuntos oficiais e não introduzem filtros", {
  expect_equal(camara_annual_file_url("proposicoes", 2024),
    "https://dadosabertos.camara.leg.br/arquivos/proposicoes/csv/proposicoes-2024.csv")
  expect_equal(camara_annual_file_url("proposicoesTemas", 1934),
    "https://dadosabertos.camara.leg.br/arquivos/proposicoesTemas/csv/proposicoesTemas-1934.csv")
  expect_equal(camara_annual_file_url("proposicoesAutores", 2026),
    "https://dadosabertos.camara.leg.br/arquivos/proposicoesAutores/csv/proposicoesAutores-2026.csv")
  expect_error(camara_annual_file_url("proposicoesTemas?codTema=2", 2024), "não suportado")
 })

test_that("índice anual e intervalo explícito constroem trio de arquivos por ano", {
  index_path <- tempfile(fileext = ".csv")
  write.csv(data.frame(year = c(2024, 2025, 2024)), index_path, row.names = FALSE)
  expect_equal(read_camara_annual_years(index_path), c(2024L, 2025L))
  expect_equal(read_camara_annual_years(from_year = 2024, through_year = 2025), 2024:2025)
  expect_equal(nrow(expand.grid(year = read_camara_annual_years(index_path), dataset = camara_annual_csv_datasets)), 6L)
  expect_error(read_camara_annual_years(from_year = 2025, through_year = 2024), "inválido")
  unlink(index_path)
})

test_that("extração de cabeçalhos HTTP tolera casing variável e campos ausentes", {
  expect_equal(camara_header_value(c("Content-Type"="text/csv", "Content-Length"="21"), "content-type"), "text/csv")
  expect_equal(camara_header_value(c("CONTENT-LENGTH"="21"), "content-length"), "21")
  expect_true(is.na(camara_header_value(c("Date"="hoje"), "content-type")))
  expect_true(is.na(camara_header_value(NULL, "content-type")))
  expect_true(is.na(camara_header_value(character(), "content-length")))
})

test_that("handle da Câmara aceita opção HTTP/1.1 do pacote curl", {
  handle <- camara_new_http11_handle(timeout=5L)
  expect_true(inherits(handle,"curl_handle"))
  expect_no_error(curl::handle_setopt(handle,http_version=2L))
})

test_that("lotes concorrentes mantêm limite por host e URLs únicas", {
  urls <- c("https://docs.example/a", "https://docs.example/b", "https://docs.example/a",
            "https://other.example/c", "https://docs.example/d", "https://docs.example/e")
  batches <- camara_url_batches(urls, 25L)
  parallel_batches <- camara_parallel_batches(urls, 2L)
  expect_equal(length(unique(unlist(batches))), 5L)
  expect_true(all(lengths(batches) <= 25L))
  expect_true(all(lengths(parallel_batches) <= 2L))
  expect_true(all(vapply(batches, function(batch) length(unique(camara_url_host(batch))) == 1L, logical(1))))
  expect_true(all(camara_is_terminal_failure(c("unavailable_404","reused_html_error","http_404"))))
  expect_false(any(camara_is_terminal_failure(c("http_429","http_503","empty_file","truncated_file"))))
  expect_false(camara_is_terminal_failure("network_error"))
  expect_error(run_camara_annual_csv(data_root=tempfile(), from_year=2024, through_year=2024, dry_run=TRUE, max_concurrency=0L), "inteiro positivo")
})

test_that("validação CSV verifica BOM e delimitador em bytes sem decodificar acentos", {
  path <- tempfile(fileext=".csv")
  bom_accent_csv <- c(as.raw(c(0xef,0xbb,0xbf)), charToRaw("id;ementa (descrição)\n1;ação legislativa\n"))
  writeBin(bom_accent_csv,path)
  expect_true(verify_camara_annual_csv(path, NA_character_)$ok)
  invalid <- tempfile(fileext=".csv"); writeBin(c(as.raw(c(0xef,0xbb,0xbf)),charToRaw("resposta inválida\n")),invalid)
  expect_equal(verify_camara_annual_csv(invalid)$error,"invalid_csv_header")
  unlink(c(path,invalid))
})

test_that("dry-run não chama transporte e publica status planned por ano/arquivo", {
  data_root <- tempfile("camara_annual_dry_")
  dir.create(data_root)
  on.exit(unlink(data_root, recursive = TRUE))
  called <- FALSE
  res <- run_camara_annual_csv(data_root = data_root, from_year = 2024, through_year = 2024,
    dry_run = TRUE, mock_transport = function(...) { called <<- TRUE; stop("não deve chamar") })
  expect_false(called)
  expect_equal(nrow(res$files), 3L)
  expect_true(all(res$files$status == "planned"))
  expect_true(file.exists(res$status_path))
  expect_true(all(startsWith(res$files$requested_url, "https://dadosabertos.camara.leg.br/arquivos/")))
})

test_that("download valida CSV, registra 404 e HTML 200, preserva/hash e retoma", {
  data_root <- tempfile("camara_annual_fetch_")
  dir.create(data_root)
  on.exit(unlink(data_root, recursive = TRUE))
  requests <- character()
  transport <- function(url, year, dataset, probe_only) {
    requests <<- c(requests, dataset)
    if (dataset == "proposicoes") return(list(http_status = 200L, content_type = "text/csv; charset=utf-8",
      content_length = length(fixture_csv), final_url = url, body = fixture_csv))
    if (dataset == "proposicoesTemas") return(list(http_status = 404L, content_type = "text/html",
      content_length = 0, final_url = url, body = raw(0)))
    if (dataset == "proposicoesAutores") return(list(http_status = 200L, content_type = "text/html", content_length = 25,
      final_url = url, body = charToRaw("<html>bloqueado</html>")))
    list(http_status = 200L, content_type = "text/html", content_length = 25,
      final_url = url, body = charToRaw("<html>bloqueado</html>"))
  }
  res <- run_camara_annual_csv(data_root = data_root, from_year = 2024, through_year = 2024,
    mock_transport = transport)
  expect_equal(res$files$status, c("verified", "unavailable_404", "html_error"))
  expect_equal(res$files$http_status, c(200L, 404L, 200L))
  expect_equal(res$files$sha256[[1]], digest::digest(fixture_csv, algo = "sha256", serialize = FALSE))
  saved <- file.path(data_root, res$files$raw_path[[1]])
  expect_true(file.exists(saved))
  expect_identical(tolower(hash_file(saved)), tolower(res$files$sha256[[1]]))
  resumed_requests <- character()
  resumed <- run_camara_annual_csv(data_root = data_root, from_year = 2024, through_year = 2024,
    mock_transport = function(url, year, dataset, probe_only) {
      resumed_requests <<- c(resumed_requests, dataset)
      transport(url, year, dataset, probe_only)
    })
  expect_equal(resumed$files$status, c("resumed_verified", "unavailable_404", "html_error"))
  expect_length(resumed_requests, 0L)
  retry_requests <- character()
  retry <- run_camara_annual_csv(data_root = data_root, from_year = 2024, through_year = 2024,
    retry_failures = TRUE, mock_transport = function(url, year, dataset, probe_only) {
      retry_requests <<- c(retry_requests,dataset); transport(url, year, dataset, probe_only)
    })
  expect_equal(retry$files$status, c("resumed_verified", "unavailable_404", "html_error"))
  expect_equal(retry_requests,c("proposicoesTemas","proposicoesAutores"))
})

test_that("CSV anual canônico de outro run é reutilizado após validar hash e conteúdo", {
  data_root <- tempfile("camara_reuse_raw_"); dir.create(data_root); on.exit(unlink(data_root, recursive=TRUE))
  target <- file.path(data_root,"raw","camara","annual_csv","proposicoes","2024")
  dir.create(target,recursive=TRUE)
  sha <- digest::digest(fixture_csv,algo="sha256",serialize=FALSE)
  writeBin(fixture_csv,file.path(target,paste0(sha,".csv")))
  requested <- character()
  transport <- function(url,year,dataset,probe_only) {
    requested <<- c(requested,dataset)
    list(http_status=200L,content_type="text/csv",content_length=length(fixture_csv),final_url=url,body=fixture_csv)
  }
  result <- run_camara_annual_csv(data_root=data_root,from_year=2024,through_year=2024,mock_transport=transport)
  expect_equal(result$files$status[[1]],"resumed_verified")
  expect_identical(tolower(result$files$sha256[[1]]),tolower(sha))
  expect_false("proposicoes" %in% requested)
  expect_true(all(file.exists(file.path(data_root,result$files$raw_path))))
})

test_that("CSV anual parcial é tentado novamente e só promove conteúdo validado", {
  data_root <- tempfile("camara_partial_csv_"); dir.create(data_root); on.exit(unlink(data_root,recursive=TRUE))
  attempts <- setNames(integer(3),camara_annual_csv_datasets)
  transport <- function(url,year,dataset,probe_only,range_start=NULL) {
    attempts[[dataset]] <<- attempts[[dataset]] + 1L
    if (dataset == "proposicoes" && !is.null(range_start)) {
      suffix <- fixture_csv[(range_start+1L):length(fixture_csv)]
      return(list(http_status=206L,content_type="text/csv",content_length=length(suffix),
        content_range=sprintf("bytes %d-%d/%d",range_start,length(fixture_csv)-1L,length(fixture_csv)),final_url=url,body=suffix))
    }
    if (dataset == "proposicoes" && attempts[[dataset]] == 1L) {
      return(list(error="unexpected EOF",partial_body=fixture_csv[1:8]))
    }
    list(http_status=200L,content_type="text/csv",content_length=length(fixture_csv),final_url=url,body=fixture_csv)
  }
  result <- run_camara_annual_csv(data_root=data_root,from_year=2024,through_year=2024,mock_transport=transport)
  expect_equal(attempts[["proposicoes"]],2L)
  expect_equal(result$files$attempt_count,c(2L,1L,1L))
  expect_true(all(result$files$status=="verified"))
  part <- tempfile(fileext=".part"); failed_attempts <- 0L
  exhausted <- camara_annual_download_with_retries("https://example.test/file.csv",part,2024,"proposicoes",
    mock_transport=function(url,year,dataset,probe_only,range_start=NULL) {
      failed_attempts <<- failed_attempts+1L
      if (is.null(range_start)) return(list(http_status=200L,content_type="text/csv",content_length=length(fixture_csv),body=fixture_csv[1:(length(fixture_csv)-3L)]))
      byte <- fixture_csv[range_start+1L]
      list(http_status=206L,content_type="text/csv",content_length=1L,
        content_range=sprintf("bytes %d-%d/%d",range_start,range_start,length(fixture_csv)),body=byte)
    },backoff_seconds=c(0,0))
  expect_equal(failed_attempts,3L)
  expect_equal(exhausted$validation$error,"truncated_file")
  expect_false(file.exists(part))

  full_calls <- 0L
  fallback <- camara_annual_download_with_retries("https://example.test/ignore-range.csv",part,2024,"proposicoes",
    mock_transport=function(url,year,dataset,probe_only,range_start=NULL) {
      if (!is.null(range_start)) return(list(http_status=200L,content_type="text/csv",content_length=length(fixture_csv),body=fixture_csv))
      full_calls <<- full_calls+1L
      if (full_calls==1L) return(list(error="unexpected EOF",partial_body=fixture_csv[1:8]))
      list(http_status=200L,content_type="text/csv",content_length=length(fixture_csv),body=fixture_csv)
    },backoff_seconds=c(0,0))
  expect_true(fallback$validation$ok)
  expect_equal(fallback$attempt_count,2L)
  expect_true(fallback$range_fallback)
  expect_equal(full_calls,2L)
})

test_that("probe-only mede disponibilidade com HEAD sem persistir blobs", {
  data_root <- tempfile("camara_annual_probe_")
  dir.create(data_root)
  on.exit(unlink(data_root, recursive = TRUE))
  res <- run_camara_annual_csv(data_root = data_root, from_year = 2024, through_year = 2024,
    probe_only = TRUE, mock_transport = function(url, year, dataset, probe_only) {
      expect_true(probe_only)
      list(http_status = if (dataset == "proposicoesTemas") 404L else 200L,
        content_type = "text/csv", content_length = 100L, final_url = url)
    })
  expect_equal(res$files$status, c("available", "unavailable_404", "available"))
  expect_true(all(is.na(res$files$sha256)))
  expect_false(dir.exists(file.path(data_root, "raw")))
})

test_that("proposições baixam todas as URLs documentais com estado e retomada", {
  data_root <- tempfile("camara_docs_"); dir.create(data_root); on.exit(unlink(data_root, recursive=TRUE))
  csv <- charToRaw(paste0("id;urlInteiroTeor;urlArquivo\n", "123;https://example.org/a.pdf;https://example.org/a.doc\n", "124;;https://example.org/a.doc\n"))
  calls <- character()
  transport <- function(url, year, dataset, probe_only) {
    if (dataset %in% c("proposicoes", "proposicoesTemas", "proposicoesAutores")) return(list(http_status=200L, content_type="text/csv", content_length=length(csv), final_url=url, body=csv))
    calls <<- c(calls,url)
    list(http_status=200L, content_type="application/pdf", content_length=length(charToRaw("%PDF-1.7 mock")), final_url=url, body=charToRaw("%PDF-1.7 mock"))
  }
  result <- run_camara_annual_csv(data_root=data_root, from_year=2024, through_year=2024, mock_transport=transport, max_concurrency=1L)
  ledger <- utils::read.csv(file.path(camara_document_status_path(result$output_dir, 2024), "ledger.csv"), stringsAsFactors=FALSE)
  expect_length(calls, 2L)
  expect_true(all(ledger$status[ledger$status != "url_missing"] %in% c("verified", "reused_verified")))
  expect_equal(sum(ledger$status == "url_missing"), 1L)
  expect_true(all(!is.na(ledger$proposition_id)))
  expect_true(all(file.exists(file.path(data_root, ledger$raw_path[ledger$status == "verified"]))))
  calls <- character()
  run_camara_annual_csv(data_root=data_root, from_year=2024, through_year=2024, mock_transport=transport, max_concurrency=1L)
  expect_length(calls, 0L)
})

test_that("limite documental não altera a faixa anual nem inicia documentos acima do corte", {
  data_root <- tempfile("camara_doc_cutoff_"); dir.create(data_root); on.exit(unlink(data_root,recursive=TRUE))
  csv <- charToRaw("id;urlInteiroTeor\n1;https://files.example/one.pdf\n")
  doc_requests <- character()
  transport <- function(url,year,dataset,probe_only) {
    if (dataset %in% camara_annual_csv_datasets) return(list(http_status=200L,content_type="text/csv",content_length=length(csv),final_url=url,body=csv))
    doc_requests <<- c(doc_requests,paste(year,url,sep=":"))
    list(http_status=200L,content_type="application/pdf",content_length=length(charToRaw("%PDF-1.7")),final_url=url,body=charToRaw("%PDF-1.7"))
  }
  result <- run_camara_annual_csv(data_root=data_root,from_year=2024,through_year=2025,
    documents_through_year=2024,mock_transport=transport,max_concurrency=1L)
  expect_equal(sort(unique(result$files$year)),2024:2025)
  expect_true(all(startsWith(doc_requests,"2024:")))
  expect_true(file.exists(file.path(camara_document_status_path(result$output_dir,2024),"ledger.csv")))
  expect_false(file.exists(file.path(camara_document_status_path(result$output_dir,2025),"ledger.csv")))
})

test_that("inteiro teor histórico resolve META refresh para PDF e reutiliza o original", {
  data_root <- tempfile("camara_meta_"); dir.create(data_root); data_root <- normalizePath(data_root); on.exit(unlink(data_root, recursive=TRUE))
  csv <- charToRaw(paste0("id;urlInteiroTeor\n", "1;https://example.org/prop/1\n", "2;https://example.org/prop/2\n"))
  calls <- character()
  transport <- function(url, year, dataset, probe_only) {
    if (dataset %in% c("proposicoes", "proposicoesTemas", "proposicoesAutores")) return(list(http_status=200L,content_type="text/csv",content_length=length(csv),final_url=url,body=csv))
    calls <<- c(calls,url)
    if (grepl("example.org/prop/",url)) {
      page <- if (grepl("/1$",url)) 2 else 3
      return(list(http_status=200L,content_type="text/html",final_url=url,
                  body=charToRaw(sprintf("<head><meta http-equiv=\"refresh\" content=\"0; URL=http://files.example.org/viewer.asp?page=%s\"></head>",page))))
    }
    if (grepl("viewer.asp",url)) {
      page <- sub(".*page=", "", url)
      return(list(http_status=200L,content_type="text/html",final_url=url,
                  body=charToRaw(sprintf("<head><META HTTP-EQUIV=\"Refresh\" CONTENT=\"1; URL=http://files.example.org/daily.pdf#page=%s\" /></head>",page))))
    }
    list(http_status=200L,content_type="application/pdf",content_length=length(charToRaw("%PDF-1.7 mock")),final_url=url,body=charToRaw("%PDF-1.7 mock"))
  }
  result <- run_camara_annual_csv(data_root=data_root,from_year=2024,through_year=2024,mock_transport=transport,max_concurrency=1L)
  ledger <- utils::read.csv(file.path(camara_document_status_path(result$output_dir,2024),"ledger.csv"),stringsAsFactors=FALSE)
  expect_equal(sum(ledger$status %in% c("verified","reused_verified")),2L)
  expect_true(all(grepl("files.example.org/daily.pdf",ledger$resolved_url)))
  expect_equal(sum(grepl("daily.pdf",calls,fixed=TRUE)),1L)
})

test_that("META refresh é reconhecido com bytes HTML que não são UTF-8 válido", {
  data_root <- tempfile("camara_meta_bytes_"); dir.create(data_root); data_root <- normalizePath(data_root); on.exit(unlink(data_root,recursive=TRUE))
  out <- file.path(data_root,"staging"); dir.create(out)
  calls <- character()
  transport <- function(url,year,dataset,probe_only) {
    calls <<- c(calls,url)
    if (length(calls)==1L) return(list(http_status=200L,content_type="text/html",final_url=url,
      body=c(as.raw(0xff),charToRaw('<html><head><meta http-equiv="refresh" content="0; url=https://files.example/good.pdf"></head></html>'))))
    list(http_status=200L,content_type="application/pdf",final_url=url,body=charToRaw("%PDF-1.7"))
  }
  result <- fetch_camara_document_url("https://portal.example/view",2001L,out,transport)
  expect_null(result$response$error)
  expect_match(result$resolved_url,"good.pdf")
  expect_length(calls,2L)
})

test_that("ledger distingue URL ausente, 404, HTML e coluna documental ausente", {
  data_root <- tempfile("camara_doc_status_"); dir.create(data_root); data_root <- normalizePath(data_root); on.exit(unlink(data_root, recursive=TRUE))
  root <- file.path(data_root, "raw", "camara", "annual_csv", "proposicoes", "2024"); dir.create(root, recursive=TRUE)
  csv <- file.path(root, "proposicoes-2024.csv")
  writeBin(charToRaw("id;urlInteiroTeor\n5;https://example.org/missing\n6;https://example.org/html\n7;\n"), csv)
  out <- file.path(data_root, "staging"); dir.create(out)
  t <- function(url, year, dataset, probe_only) if (grepl("missing",url)) list(http_status=404L) else list(http_status=200L,content_type="text/html",body=charToRaw("<html>no</html>"))
  download_camara_documents_for_year(csv,2024,data_root,out,t)
  st <- utils::read.csv(file.path(camara_document_status_path(out,2024),"ledger.csv"),stringsAsFactors=FALSE)
  expect_equal(st$status,c("unavailable_404","html_error","url_missing"))
  no_col <- file.path(root,"no-column.csv"); writeBin(charToRaw("id;sigla\n1;PL\n"),no_col)
  download_camara_documents_for_year(no_col,2024,data_root,out,t)
  absent <- utils::read.csv(file.path(camara_document_status_path(out,2024),"ledger.csv"),stringsAsFactors=FALSE)
  expect_equal(absent$status,"url_column_absent")
})

test_that("detector identifica HTML de portal iniciado em head/meta", {
  expect_equal(detect_media_type(charToRaw("<head><META HTTP-EQUIV=\"Refresh\" CONTENT=\"1; URL=/arquivo.pdf\" /></head>")),"text/html")
})

test_that("cabeçalhos curl brutos usam a última resposta HTTP", {
  headers <- charToRaw("HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\nHTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nContent-Length: 123\r\n\r\n")
  expect_equal(camara_header_value(headers,"Content-Type"),"application/pdf")
  expect_equal(camara_header_value(headers,"content-length"),"123")
})

test_that("journal recupera conclusão ainda não consolidada e cache cruza runs", {
  data_root <- tempfile("camara_journal_"); dir.create(data_root); data_root <- normalizePath(data_root); on.exit(unlink(data_root,recursive=TRUE))
  csv_path <- file.path(data_root,"source.csv")
  writeLines("id;urlInteiroTeor\n1;https://files.example/a.pdf",csv_path)
  out <- file.path(data_root,"one"); out2 <- file.path(data_root,"two")
  calls <- 0L
  transport <- function(url,year,dataset,probe_only) {
    calls <<- calls+1L
    list(http_status=200L,content_type="application/pdf",body=charToRaw("%PDF-1.7 mock"),final_url=url)
  }
  download_camara_documents_for_year(csv_path,2024,data_root,out,mock_transport=transport)
  chunks <- list.files(camara_document_status_path(out,2024),pattern="^chunk_[0-9]+\\.csv$",full.names=TRUE)
  unlink(chunks)
  download_camara_documents_for_year(csv_path,2024,data_root,out,mock_transport=transport)
  download_camara_documents_for_year(csv_path,2024,data_root,out2,mock_transport=transport)
  expect_equal(calls,1L)
  ledger <- read.csv(file.path(camara_document_status_path(out,2024),"ledger.csv"))
  expect_equal(ledger$status,"resumed_verified")
  # Um índice adulterado não pode dispensar a verificação de integridade.
  blob <- file.path(data_root,ledger$raw_path)
  writeBin(charToRaw("corrompido"),blob)
  download_camara_documents_for_year(csv_path,2024,data_root,file.path(data_root,"three"),mock_transport=transport)
  expect_equal(calls,2L)
})

test_that("reuso do hash calculado não aceita SHA divergente em outra associação", {
  data_root <- tempfile("camara_hash_refs_"); dir.create(data_root); data_root <- normalizePath(data_root)
  on.exit(unlink(data_root,recursive=TRUE))
  csv_path <- file.path(data_root,"source.csv")
  writeLines("id;urlInteiroTeor\n1;https://files.example/a.pdf\n2;https://files.example/b.pdf",csv_path)
  out <- file.path(data_root,"stage")
  transport <- function(url,year,dataset,probe_only) list(http_status=200L,content_type="application/pdf",
    body=charToRaw("%PDF-1.7 same"),final_url=url)
  download_camara_documents_for_year(csv_path,2024,data_root,out,mock_transport=transport)
  folder <- camara_document_status_path(out,2024)
  chunk <- list.files(folder,pattern="^chunk_[0-9]+\\.csv$",full.names=TRUE)[[1]]
  d <- read.csv(chunk,stringsAsFactors=FALSE)
  d$sha256[[2]] <- paste(rep("0",64),collapse="")
  write.csv(d,chunk,row.names=FALSE,na="")
  unlink(paste0(chunk,".events.jsonl"))
  download_camara_documents_for_year(csv_path,2024,data_root,out,mock_transport=transport)
  ledger <- read.csv(file.path(folder,"ledger.csv"),stringsAsFactors=FALSE)
  expect_equal(ledger$sha256[[1]],ledger$sha256[[2]])
  expect_true(all(ledger$status %in% c("verified","resumed_verified")))
})
