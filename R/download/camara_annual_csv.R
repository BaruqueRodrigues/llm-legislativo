# Downloads anuais da API aberta da Câmara. Cada tabela/ano tem estado próprio.

camara_annual_csv_datasets <- c("proposicoes", "proposicoesTemas", "proposicoesAutores")

camara_annual_file_url <- function(dataset, year) {
  if (length(dataset) != 1L || !dataset %in% camara_annual_csv_datasets) {
    stop("Dataset anual da Câmara não suportado: ", dataset)
  }
  if (length(year) != 1L || is.na(year) || year < 1800L || year > 9999L) {
    stop("Ano inválido para arquivo anual da Câmara: ", year)
  }
  sprintf(
    "https://dadosabertos.camara.leg.br/arquivos/%s/csv/%s-%04d.csv",
    dataset, dataset, as.integer(year)
  )
}

read_camara_annual_years <- function(annual_index = NULL,
                                     from_year = NULL,
                                     through_year = NULL) {
  if (!is.null(annual_index)) {
    if (!file.exists(annual_index)) stop("Índice anual não encontrado: ", annual_index)
    index <- if (grepl("\\.parquet$", annual_index, ignore.case = TRUE)) {
      as.data.frame(arrow::read_parquet(annual_index))
    } else utils::read.csv(annual_index, stringsAsFactors = FALSE, check.names = FALSE)
    year_col <- intersect(c("year", "ano", "segment_year"), names(index))
    if (length(year_col) == 0L) stop("Índice anual precisa de uma coluna year (ou ano/segment_year).")
    years <- suppressWarnings(as.integer(index[[year_col[[1]]]]))
    if (anyNA(years)) stop("Índice anual contém ano ausente ou inválido.")
    if (any(years < 1800L | years > 9999L)) stop("Índice anual contém ano fora da faixa válida.")
    return(sort(unique(years)))
  }
  if (is.null(from_year) || is.null(through_year)) {
    stop("Informe --annual-index ou ambos --from-year e --through-year.")
  }
  from_year <- as.integer(from_year)
  through_year <- as.integer(through_year)
  if (is.na(from_year) || is.na(through_year) || from_year < 1800L || through_year > 9999L || from_year > through_year) {
    stop("Intervalo de anos inválido.")
  }
  seq.int(from_year, through_year)
}

camara_document_status_path <- function(output_dir, year) file.path(output_dir, sprintf("annual_document_status_%04d", year))
camara_null_coalesce <- function(x, fallback) if (is.null(x)) fallback else x
camara_header_value <- function(headers, name) {
  if (is.null(headers) || !length(headers)) return(NA_character_)
  if (is.raw(headers) || (is.character(headers) && is.null(names(headers)))) {
    headers <- curl::parse_headers_list(headers)
  }
  header_names <- names(headers)
  if (is.null(header_names) || !length(header_names)) return(NA_character_)
  idx <- which(tolower(header_names) == tolower(name))
  if (!length(idx)) return(NA_character_)
  value <- headers[[idx[[1]]]]
  if (is.null(value) || !length(value)) NA_character_ else as.character(value[[1]])
}
camara_new_http11_handle <- function(...) curl::new_handle(..., connecttimeout=30L, http_version=2L)

verify_camara_document_file <- function(path, content_type = "") {
  size <- if (file.exists(path)) file.info(path)$size else 0
  if (is.na(size) || size == 0) return(list(ok=FALSE,error="empty_file"))
  con <- file(path,"rb")
  on.exit(close(con))
  bytes <- readBin(con,"raw",n=min(size,65536))
  media <- detect_media_type(bytes)
  if (identical(media,"text/html") ||
      (length(content_type)==1L && !is.na(content_type) && grepl("html",content_type,ignore.case=TRUE))) {
    return(list(ok=FALSE,error="html_error"))
  }
  list(ok=TRUE,error=NA_character_)
}

fetch_camara_document_url <- function(url, year, output_dir, mock_transport = NULL, url_cache = NULL) {
  cache_key <- digest::digest(url, algo="sha256", serialize=FALSE)
  part <- file.path(output_dir, "document_parts", paste0(cache_key, ".part"))
  tryCatch({
    request <- function(target, destination) {
      response <- camara_annual_download_with_retries(
        target,destination,year,"document",mock_transport,
        validator=verify_camara_document_file,preserve_partial_on_failure=TRUE
      )
      response
    }
    response <- request(url, part)
    resolved_url <- camara_null_coalesce(response$final_url, url)
    for (redirect_depth in seq_len(5L)) {
      if (!is.null(response$error) || !file.exists(part)) break
      size <- file.info(part)$size
      bytes <- if (size > 0) { con<-file(part,"rb"); value<-readBin(con,"raw",n=min(size,65536)); close(con); value } else raw()
      media <- if (length(bytes)) detect_media_type(bytes) else "application/x-empty"
      is_html <- (!is.null(response$content_type) && !is.na(response$content_type) && grepl("html",response$content_type,ignore.case=TRUE)) || media == "text/html"
      # Alguns links históricos passam por mais de uma página visualizadora.
      # Só seguimos META refresh explícito; HTML comum segue rejeitado.
      if (!is_html) break
      # Trate o HTML como bytes: páginas legadas podem conter texto em
      # encoding inválido para a locale, embora os atributos META sejam ASCII.
      html <- rawToChar(bytes)
      refresh <- regmatches(html, regexpr("(?is)<meta[^>]+http-equiv\\s*=\\s*['\"]?refresh['\"]?[^>]+>", html, perl=TRUE, useBytes=TRUE))
      if (!length(refresh) || !nzchar(refresh)) break
      target <- regmatches(refresh, regexpr("(?is)url\\s*=\\s*['\"]?[^'\";>]+", refresh, perl=TRUE, useBytes=TRUE))
      if (!length(target) || !nzchar(target)) break
      target <- sub("(?is)^.*?url\\s*=\\s*['\"]?", "", target, perl=TRUE)
      target <- sub("['\";>\\s]+$", "", target)
      target <- gsub("&amp;", "&", target, fixed=TRUE)
      if (grepl("^//",target)) target <- paste0("https:",target)
      else if (!grepl("^https?://",target,ignore.case=TRUE)) {
        base <- sub("[?#].*$", "", resolved_url)
        target <- paste0(sub("/[^/]*$", "/", base), target)
      }
      target <- sub("^http://", "https://", target, ignore.case=TRUE)
      canonical <- sub("#.*$", "", target)
      canonical_key <- digest::digest(canonical,algo="sha256",serialize=FALSE)
      if (!is.null(url_cache) && exists(canonical_key,envir=url_cache,inherits=FALSE)) {
        unlink(part)
        return(list(response=list(cached_document=TRUE),part_path=part,
                    resolved_url=canonical,cached_result=get(canonical_key,envir=url_cache,inherits=FALSE)))
      }
      unlink(part)
      response <- request(target, part)
      resolved_url <- camara_null_coalesce(response$final_url, target)
      resolved_url <- sub("#.*$", "", resolved_url)
    }
    list(response=response, part_path=part, resolved_url=resolved_url)
  }, error=function(e) {
    list(response=list(error=conditionMessage(e)), part_path=part, resolved_url=NA_character_)
  })
}

# Fila contínua com o mesmo pool entre checkpoints e chunks.
fetch_camara_document_urls_parallel <- function(urls, year, output_dir, max_concurrency,
                                                pool, url_cache = NULL, on_result = NULL) {
  camara_schedule_urls(urls,year,output_dir,max_concurrency,pool,url_cache,on_result)
}

camara_url_host <- function(url) tolower(sub("^https?://([^/:?#]+).*$", "\\1", url, ignore.case=TRUE))
camara_url_batches <- function(urls, checkpoint_every=25L) {
  urls <- unique(urls)
  groups <- split(urls, camara_url_host(urls))
  unlist(lapply(groups, function(host_urls) split(host_urls, ceiling(seq_along(host_urls)/checkpoint_every))), recursive=FALSE)
}
camara_parallel_batches <- function(urls, max_concurrency=40L) split(urls, ceiling(seq_along(urls)/max_concurrency))
camara_is_terminal_failure <- function(status) {
  status <- sub("^reused_", "", status)
  status %in% c("unavailable_404", "html_error") |
    (grepl("^http_[0-9]{3}$",status) & !grepl("^http_(429|5[0-9]{2})$",status))
}

download_camara_documents_for_year <- function(csv_path, year, data_root, output_dir, mock_transport = NULL,
                                               url_cache = new.env(parent=emptyenv()), max_concurrency = 40L,
                                               retry_failures = FALSE) {
  max_concurrency <- as.integer(max_concurrency)
  if (is.na(max_concurrency) || max_concurrency < 1L) stop("max_concurrency deve ser inteiro positivo.")
  header <- names(readr::read_delim(csv_path, delim = ";", n_max = 0, show_col_types = FALSE,
                                    name_repair = "minimal", progress = FALSE))
  # Campos com URL de API/identidade (uri, urlProposicao etc.) não são documentos.
  url_cols <- header[grepl("^(urlInteiroTeor|urlDocumento|urlArquivo|urlTexto|urlDocumentoTexto)$", header, ignore.case = TRUE)]
  id_col <- intersect(c("id", "idProposicao", "uri", "uriProposicao"), header)
  status_dir <- camara_document_status_path(output_dir, year)
  dir.create(status_dir, recursive=TRUE, showWarnings=FALSE)
  ledger_path <- file.path(status_dir, "ledger.csv")
  if (file.exists(ledger_path)) unlink(ledger_path)
  if (!length(url_cols)) {
    status <- data.frame(year=year, proposition_id=NA_character_, source_row=NA_integer_, url_column="urlInteiroTeor",
      requested_url=NA_character_, resolved_url=NA_character_, http_status=NA_integer_, content_type=NA_character_, file_size_bytes=NA_real_, sha256=NA_character_, raw_path=NA_character_, status="url_column_absent", error_message=NA_character_, record_key=digest::digest(paste(year,"url_column_absent",sep="\n"),algo="sha256",serialize=FALSE), stringsAsFactors=FALSE)
    write_camara_annual_status(status, file.path(status_dir,"chunk_000000.csv"))
    utils::write.csv(status,ledger_path,row.names=FALSE,na="",fileEncoding="UTF-8")
    return(status)
  }
  selected <- unique(c(id_col, url_cols))
  download_pool <- curl::new_pool(total_con=max_concurrency,host_con=max_concurrency,
                                  max_streams=max_concurrency,multiplex=FALSE)
  chunk_callback <- readr::SideEffectChunkCallback$new(function(dat, pos) {
    chunk_no <- as.integer(pos %/% 5000L) + 1L
    chunk_path <- file.path(status_dir, sprintf("chunk_%06d.csv", chunk_no))
    prior <- if (file.exists(chunk_path)) utils::read.csv(chunk_path, stringsAsFactors=FALSE, check.names=FALSE) else data.frame()
    journal <- paste0(chunk_path,".events.jsonl")
    replay <- new.env(parent=emptyenv())
    if (file.exists(journal)) {
      for (line in readLines(journal,warn=FALSE)) {
        event <- tryCatch(jsonlite::fromJSON(line),error=function(e) NULL)
        if (!is.null(event) && !is.null(event$url)) assign(hash_string(event$url),event$result,envir=replay)
      }
    }
    records <- vector("list", nrow(dat) * length(url_cols)); k <- 0L
    for (r in seq_len(nrow(dat))) for (column in url_cols) {
      url <- dat[[column]][[r]]; if (is.na(url)) url <- "" else url <- trimws(url)
      prop_id <- if (length(id_col)) dat[[id_col[[1]]]][[r]] else NA_character_
      source_row <- as.integer(pos + r)
      key <- digest::digest(paste(year, source_row, column, url, sep="\n"), algo="sha256", serialize=FALSE)
      rec <- data.frame(year=year, proposition_id=prop_id, source_row=source_row, url_column=column,
        requested_url=if (nzchar(url)) url else NA_character_, resolved_url=NA_character_, http_status=NA_integer_, content_type=NA_character_,
        file_size_bytes=NA_real_, sha256=NA_character_, raw_path=NA_character_, attempt_count=0L,
        range_fallback=FALSE, status="pending", error_message=NA_character_, record_key=key, stringsAsFactors=FALSE)
      if (!nzchar(url)) rec$status <- "url_missing" else if (!grepl("^https?://",url,ignore.case=TRUE)) rec$status <- "invalid_url"
      old <- if (nrow(prior)) which(prior$record_key == key) else integer()
      if (length(old)) {
        old_rec <- prior[tail(old,1),,drop=FALSE]
        for (field in setdiff(names(rec),names(old_rec))) old_rec[[field]] <- rec[[field]]
        rec <- old_rec[,names(rec),drop=FALSE]
      }
      if (nzchar(url) && exists(hash_string(url),envir=replay,inherits=FALSE)) {
        result <- get(hash_string(url),envir=replay,inherits=FALSE)
        for (field in intersect(names(result),names(rec))) rec[[field]] <- if (is.null(result[[field]])) NA else result[[field]]
      }
      k <- k + 1L; records[[k]] <- rec
    }
    status <- do.call(rbind,records); rownames(status) <- NULL
    # Revalidate per-proposition checkpoints before scheduling unique URLs.
    verified_hashes <- new.env(parent=emptyenv())
    for (i in seq_len(nrow(status))) {
      if (status$status[[i]] %in% c("verified", "resumed_verified", "reused_verified") && !is.na(status$raw_path[[i]])) {
        cached_path <- assert_data_path(file.path(data_root,status$raw_path[[i]]),data_root,"document blob")
        actual_hash <- if (!file.exists(cached_path)) {
          if (cloud_blob_archived(status$raw_path[[i]], status$sha256[[i]], data_root)) tolower(status$sha256[[i]]) else NA_character_
        } else
          if (exists(cached_path,envir=verified_hashes,inherits=FALSE)) get(cached_path,envir=verified_hashes,inherits=FALSE) else tolower(hash_file(cached_path))
        assign(cached_path,actual_hash,envir=verified_hashes)
        if (!is.na(actual_hash) && identical(actual_hash,tolower(status$sha256[[i]]))) {
          status$status[[i]] <- "resumed_verified"
          assign(digest::digest(status$requested_url[[i]],algo="sha256",serialize=FALSE),
            list(http_status=status$http_status[[i]],content_type=status$content_type[[i]],file_size_bytes=status$file_size_bytes[[i]],resolved_url=status$resolved_url[[i]],
              sha256=status$sha256[[i]],raw_path=status$raw_path[[i]],status="verified",error_message=NA_character_),envir=url_cache)
        }
        else status$status[[i]] <- "pending"
      }
    }
    terminal <- c("url_missing", "url_column_absent", "invalid_url", "resumed_verified")
    terminal_status <- camara_is_terminal_failure(status$status)
    pending <- which(!is.na(status$requested_url) & !status$status %in% terminal & (retry_failures | !terminal_status))
    status$status[pending] <- "pending"
    unique_pending <- unique(status$requested_url[pending])
    # Um pool duradouro; checkpoint e eventos independem do tamanho da fila.
    rows_by_url <- split(pending,status$requested_url[pending])
    index_dir <- camara_url_index(data_root)
    completed_since_checkpoint <- 0L
    last_checkpoint <- as.numeric(Sys.time())
    event_path <- paste0(chunk_path,".events.jsonl")
    event_con <- file(event_path,"a")
    on.exit(close(event_con),add=TRUE)
    store_result <- function(url,fetched) {
      result <- camara_document_result(fetched,data_root)
      assign(hash_string(url),result,envir=url_cache)
      if (!is.na(result$resolved_url) && identical(result$status,"verified")) {
        assign(hash_string(sub("#.*$","",result$resolved_url)),result,envir=url_cache)
        camara_index_put(index_dir,result$resolved_url,result)
      }
      camara_index_put(index_dir,url,result)
      rows <- rows_by_url[[url]]
      if (length(rows)) {
        for (field in intersect(names(result),names(status))) status[[field]][rows] <<- result[[field]]
        status$status[rows] <<- c(result$status,rep(paste0("reused_",result$status),length(rows)-1L))
      }
      cat(jsonlite::toJSON(list(url=url,result=result),auto_unbox=TRUE,na="null"),"\n",file=event_con,sep="")
      flush(event_con)
      completed_since_checkpoint <<- completed_since_checkpoint+1L
      if (completed_since_checkpoint>=250L || as.numeric(Sys.time())-last_checkpoint>=5) {
        write_camara_annual_status(status,chunk_path)
        completed_since_checkpoint <<- 0L; last_checkpoint <<- as.numeric(Sys.time())
      }
    }
    # Reutiliza versões somente no namespace do snapshot e após conferir o hash.
    uncached <- character()
    for (url in unique_pending) {
      key <- hash_string(url)
      cached <- if (exists(key,envir=url_cache,inherits=FALSE)) get(key,envir=url_cache,inherits=FALSE) else camara_index_get(index_dir,url,data_root)
      if (is.null(cached)) uncached <- c(uncached,url)
      else store_result(url,list(cached_result=cached))
    }
    camara_assert_download_disk_space(file.path(output_dir,"document_parts"))
    if (!is.null(mock_transport)) {
      for (url in uncached) store_result(url,fetch_camara_document_url(url,year,output_dir,mock_transport,url_cache))
    } else {
      fetch_camara_document_urls_parallel(uncached,year,output_dir,max_concurrency,
        download_pool,url_cache,on_result=store_result)
    }
    write_camara_annual_status(status,chunk_path)
    # O ledger agregado é reconstruível a partir dos checkpoints por chunk.
    utils::write.table(status, ledger_path, sep=",", row.names=FALSE, col.names=!file.exists(ledger_path), append=file.exists(ledger_path), na="", qmethod="double", fileEncoding="UTF-8")
  })
  readr::read_delim_chunked(csv_path, delim=";",
    col_types=readr::cols(.default=readr::col_character()), progress=FALSE,
    na=c("", "NA"), chunk_size=5000L, callback=chunk_callback)
  invisible(ledger_path)
}

new_camara_annual_status <- function(year, dataset, requested_url) {
  data.frame(
    year = as.integer(year),
    dataset = as.character(dataset),
    requested_url = as.character(requested_url),
    final_url = NA_character_,
    http_status = NA_integer_,
    content_type = NA_character_,
    file_size_bytes = NA_real_,
    sha256 = NA_character_,
    raw_path = NA_character_,
    attempt_count = 0L,
    range_fallback = FALSE,
    status = "pending",
    error_message = NA_character_,
    updated_at_utc = strftime(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    stringsAsFactors = FALSE
  )
}

write_camara_annual_status <- function(status, path) {
  part <- paste0(path, ".part")
  utils::write.csv(status, part, row.names = FALSE, na = "", fileEncoding = "UTF-8")
  if (!file.rename(part, path)) {
    if (!file.copy(part, path, overwrite = TRUE)) stop("Falha ao publicar status anual: ", path)
    unlink(part)
  }
  invisible(path)
}

verify_camara_annual_csv <- function(path, content_type = "") {
  size <- file.info(path)$size
  if (is.na(size) || size == 0) return(list(ok = FALSE, error = "empty_file"))
  con <- file(path, open = "rb")
  on.exit(close(con))
  bytes <- readBin(con, what = "raw", n = min(size, 65536))
  if (length(bytes) >= 3L && identical(bytes[1:3], as.raw(c(0xef, 0xbb, 0xbf)))) {
    bytes <- bytes[-(1:3)]
  }
  if (detect_media_type(bytes) == "text/html") return(list(ok = FALSE, error = "html_error"))
  line_end <- which(bytes == as.raw(0x0a))
  first_line <- if (length(line_end)) bytes[seq_len(line_end[[1]] - 1L)] else bytes
  first_line <- first_line[first_line != as.raw(0x0d)]
  if (!length(first_line) || !any(first_line == as.raw(0x3b))) {
    return(list(ok = FALSE, error = "invalid_csv_header"))
  }
  if (length(content_type) == 1L && !is.na(content_type) && nzchar(content_type) &&
      grepl("html", content_type, ignore.case = TRUE)) {
    return(list(ok = FALSE, error = "html_error"))
  }
  list(ok = TRUE, error = NA_character_)
}

camara_annual_head <- function(url, timeout_seconds = 60L) {
  handle <- camara_new_http11_handle(nobody = TRUE, followlocation = TRUE,
                             timeout = timeout_seconds,
                             useragent = "LLM-Legislativo/2.0 (pesquisa educacional)")
  response <- curl::curl_fetch_memory(url, handle = handle)
  headers <- response$headers
  list(
    http_status = as.integer(response$status_code),
    final_url = response$url,
    content_type = camara_header_value(headers, "content-type"),
    content_length = suppressWarnings(as.numeric(camara_header_value(headers, "content-length")))
  )
}

camara_annual_download <- function(url, part_path, timeout_seconds = 180L) {
  camara_assert_download_disk_space(dirname(part_path))
  dir.create(dirname(part_path), recursive = TRUE, showWarnings = FALSE)
  if (file.exists(part_path)) unlink(part_path)
  handle <- camara_new_http11_handle(followlocation = TRUE, timeout = timeout_seconds,
                             accept_encoding = "identity",
                             useragent = "LLM-Legislativo/2.0 (pesquisa educacional)")
  response <- curl::curl_fetch_disk(url, path = part_path, handle = handle)
  headers <- response$headers
  list(
    http_status = as.integer(response$status_code),
    final_url = response$url,
    content_type = camara_header_value(headers, "content-type"),
    content_length = suppressWarnings(as.numeric(camara_header_value(headers, "content-length"))),
    response_headers = headers
  )
}

camara_append_file <- function(source, destination) {
  src <- file(source,"rb"); dst <- file(destination,"ab")
  on.exit({close(src); close(dst)})
  repeat {
    bytes <- readBin(src,"raw",n=1024L*1024L)
    if (!length(bytes)) break
    writeBin(bytes,dst)
  }
  invisible(destination)
}

camara_annual_download_range <- function(url, part_path, offset, year, dataset, mock_transport=NULL,
                                         timeout_seconds=600L) {
  segment_path <- paste0(part_path,".range")
  camara_assert_download_disk_space(dirname(segment_path))
  if (file.exists(segment_path)) unlink(segment_path)
  response <- tryCatch({
    if (is.null(mock_transport)) {
      handle <- camara_new_http11_handle(followlocation=TRUE,timeout=timeout_seconds,
        useragent="LLM-Legislativo/2.0 (pesquisa educacional)",accept_encoding="identity",
        httpheader=sprintf("Range: bytes=%s-",format(offset,scientific=FALSE)))
      res <- curl::curl_fetch_disk(url,path=segment_path,handle=handle)
      list(http_status=as.integer(res$status_code),final_url=res$url,content_type=camara_header_value(res$headers,"content-type"),
        content_length=suppressWarnings(as.numeric(camara_header_value(res$headers,"content-length"))),
        content_range=camara_header_value(res$headers,"content-range"))
    } else {
      res <- mock_transport(url=url,year=year,dataset=dataset,probe_only=FALSE,range_start=offset)
      if (!is.null(res$body)) { dir.create(dirname(segment_path),recursive=TRUE,showWarnings=FALSE); writeBin(res$body,segment_path) }
      res
    }
  },error=function(e) list(error=conditionMessage(e)))
  response$range_start <- offset
  response$segment_path <- segment_path
  if (!is.null(response$error)) {
    if (file.exists(segment_path)) unlink(segment_path)
    return(response)
  }
  code <- as.integer(response$http_status)
  if (code != 206L) { response$range_unsupported <- TRUE; return(response) }
  content_range <- camara_null_coalesce(response$content_range,NA_character_)
  match <- if (!is.na(content_range)) regexec("^bytes ([0-9]+)-([0-9]+)/([0-9]+|\\*)$",content_range,ignore.case=TRUE) else -1L
  fields <- if (length(match)==1L && length(match[[1]])==1L && match[[1]][[1]]==-1L) character() else regmatches(content_range,match)[[1]]
  segment_size <- if (file.exists(segment_path)) file.info(segment_path)$size else 0
  declared_length <- suppressWarnings(as.numeric(camara_null_coalesce(response$content_length,NA_real_)))
  if (length(fields)!=4L || as.numeric(fields[[2]])!=offset ||
      as.numeric(fields[[3]])-as.numeric(fields[[2]])+1!=segment_size ||
      (!is.na(declared_length) && declared_length!=segment_size)) {
    response$range_unsupported <- TRUE
    if (file.exists(segment_path)) unlink(segment_path)
    return(response)
  }
  total <- suppressWarnings(as.numeric(fields[[4]]))
  if (is.na(total)) {
    response$range_unsupported <- TRUE
    if (file.exists(segment_path)) unlink(segment_path)
    return(response)
  }
  if (!file.exists(part_path)) file.create(part_path)
  camara_append_file(segment_path,part_path)
  if (file.exists(segment_path)) unlink(segment_path)
  response$content_length <- if (is.na(total)) NA_real_ else total
  response$range_partial <- !is.na(total) && file.info(part_path)$size < total
  response
}

camara_annual_download_with_retries <- function(url, part_path, year, dataset, mock_transport=NULL,
                                                max_attempts=3L, backoff_seconds=c(1,2,4),
                                                validator=verify_camara_annual_csv,
                                                preserve_partial_on_failure=FALSE) {
  max_attempts <- as.integer(max_attempts)
  if (is.na(max_attempts) || max_attempts < 1L) stop("max_attempts deve ser positivo.")
  last_response <- list(error="download_failed")
  range_fallback_used <- FALSE
  for (attempt in seq_len(max_attempts)) {
    camara_assert_download_disk_space(dirname(part_path))
    response <- tryCatch({
      offset <- if (file.exists(part_path)) file.info(part_path)$size else 0
      if (offset > 0) camara_annual_download_range(url,part_path,offset,year,dataset,mock_transport)
      else {
        if (file.exists(part_path)) unlink(part_path)
        if (is.null(mock_transport)) camara_annual_download(url,part_path) else {
          z <- mock_transport(url=url,year=year,dataset=dataset,probe_only=FALSE)
          if (!is.null(z$body) || !is.null(z$partial_body)) {
            dir.create(dirname(part_path),recursive=TRUE,showWarnings=FALSE); writeBin(camara_null_coalesce(z$body,z$partial_body),part_path)
          }
          z
        }
      }
    }, error=function(e) list(error=conditionMessage(e)))
    response$attempt_count <- attempt
    if (isTRUE(response$range_unsupported)) {
      range_fallback_used <- TRUE
      if (file.exists(response$segment_path)) unlink(response$segment_path)
      if (file.exists(part_path)) unlink(part_path)
      fallback <- tryCatch({
        if (is.null(mock_transport)) camara_annual_download(url,part_path) else {
          z <- mock_transport(url=url,year=year,dataset=dataset,probe_only=FALSE)
          if (!is.null(z$body) || !is.null(z$partial_body)) {
            dir.create(dirname(part_path),recursive=TRUE,showWarnings=FALSE); writeBin(camara_null_coalesce(z$body,z$partial_body),part_path)
          }
          z
        }
      },error=function(e) list(error=conditionMessage(e)))
      if (!is.null(fallback$error)) fallback$error <- paste("Range não aceito; fallback para download integral falhou:",fallback$error)
      fallback$attempt_count <- attempt
      response <- fallback
    }
    should_retry <- FALSE
    if (!is.null(response$error)) should_retry <- TRUE
    else {
      code <- as.integer(response$http_status)
      if (code >= 500L && code < 600L) should_retry <- TRUE
      else if (code >= 200L && code < 300L) {
        validation <- if (file.exists(part_path)) validator(part_path,response$content_type) else list(ok=FALSE,error="empty_file")
        size <- if (file.exists(part_path)) file.info(part_path)$size else 0
        declared <- suppressWarnings(as.numeric(camara_null_coalesce(response$content_length,NA_real_)))
        if (validation$ok && !is.na(declared) && declared > 0 && size < declared) validation <- list(ok=FALSE,error="truncated_file")
        response$validation <- validation
        should_retry <- identical(validation$error,"truncated_file") || identical(validation$error,"empty_file") || isTRUE(response$range_partial)
        if (!should_retry) { last_response <- response; break }
      } else { last_response <- response; break }
    }
    last_response <- response
    preserve_partial <- (!is.null(response$error) && file.exists(part_path) && file.info(part_path)$size > 0) ||
      isTRUE(response$range_partial) || identical(response$validation$error,"truncated_file")
    if (file.exists(part_path) && !preserve_partial) unlink(part_path)
    if (attempt < max_attempts && should_retry) {
      delay_idx <- min(attempt,length(backoff_seconds))
      if (length(backoff_seconds) && backoff_seconds[[delay_idx]] > 0) Sys.sleep(backoff_seconds[[delay_idx]])
    } else break
  }
  validation_error <- if (!is.null(last_response$validation)) last_response$validation$error else NA_character_
  resumable_failure <- !is.null(last_response$error) || identical(validation_error,"truncated_file") ||
    isTRUE(last_response$range_partial)
  verified_download <- is.null(last_response$error) && !is.null(last_response$validation) &&
    isTRUE(last_response$validation$ok) && !isTRUE(last_response$range_partial)
  # O resolvedor documental ainda precisa ler HTML/META e classificar a falha.
  keep_part <- verified_download || (isTRUE(preserve_partial_on_failure) &&
    (resumable_failure || identical(validation_error,"html_error")))
  if (file.exists(part_path) && !keep_part) unlink(part_path)
  last_response$range_fallback <- range_fallback_used
  last_response
}

run_camara_annual_csv <- function(data_root = NULL,
                                  annual_index = NULL,
                                  from_year = NULL,
                                  through_year = NULL,
                                  probe_only = FALSE,
                                  dry_run = FALSE,
                                  mock_transport = NULL,
                                  max_concurrency = 40L,
                                  retry_failures = FALSE,
                                  documents_through_year = NULL) {
  max_concurrency <- as.integer(max_concurrency)
  if (is.na(max_concurrency) || max_concurrency < 1L) stop("max_concurrency deve ser inteiro positivo.")
  if (!is.null(documents_through_year)) {
    documents_through_year <- as.integer(documents_through_year)
    if (length(documents_through_year) != 1L || is.na(documents_through_year)) stop("documents_through_year deve ser um ano inteiro.")
  }
  data_root <- resolve_download_data_root(data_root)
  years <- read_camara_annual_years(annual_index, from_year, through_year)
  requests <- expand.grid(year = years, dataset = camara_annual_csv_datasets,
                          stringsAsFactors = FALSE)
  requests <- requests[order(requests$year, match(requests$dataset, camara_annual_csv_datasets)), ]
  requests$requested_url <- mapply(camara_annual_file_url, requests$dataset, requests$year,
                                   USE.NAMES = FALSE)
  request_fingerprint <- digest::digest(paste(requests$year, requests$dataset, requests$requested_url,
                                              collapse = "\n"), algo = "sha256", serialize = FALSE)
  run_id <- paste0("camara_annual_csv_", substr(request_fingerprint, 1L, 16L))
  output_dir <- file.path(data_root, "staging", "downloads", "camara_annual_csv", run_id)
  output_dir <- assert_data_path(output_dir, data_root, "annual CSV output")
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
  status_path <- file.path(output_dir, "annual_file_status.csv")

  prior <- if (file.exists(status_path)) {
    utils::read.csv(status_path, stringsAsFactors = FALSE, check.names = FALSE)
  } else data.frame()
  status <- do.call(rbind, lapply(seq_len(nrow(requests)), function(i) {
    row <- new_camara_annual_status(requests$year[[i]], requests$dataset[[i]], requests$requested_url[[i]])
    match_idx <- if (nrow(prior)) which(prior$year == row$year & prior$dataset == row$dataset) else integer()
    if (length(match_idx)) {
      prior_row <- prior[tail(match_idx, 1L), , drop=FALSE]
      for (column in intersect(names(row),names(prior_row))) row[[column]] <- prior_row[[column]][[1]]
    }
    row
  }))
  rownames(status) <- NULL

  if (dry_run) {
    status$status <- "planned"
    write_camara_annual_status(status, status_path)
    return(list(status = "dry_run", run_id = run_id, output_dir = output_dir,
                status_path = status_path, files = status))
  }

  for (i in seq_len(nrow(status))) {
    url <- status$requested_url[[i]]
    dataset <- status$dataset[[i]]
    year <- status$year[[i]]
    target_dir <- file.path(data_root, "raw", "camara", "annual_csv", dataset, sprintf("%04d", year))
    target_dir <- assert_data_path(target_dir, data_root, "annual CSV raw directory")
    if (!probe_only) dir.create(target_dir, recursive = TRUE, showWarnings = FALSE)

    # Reutilize CSV canônico de outra execução somente após conferir o hash
    # embutido no nome do blob e validar cabeçalho/conteúdo CSV.
    if (!probe_only && status$status[[i]] %in% c("network_error", "planned", "pending", "")) {
      candidates <- list.files(target_dir, pattern="^[0-9a-fA-F]{64}\\.csv$", full.names=TRUE)
      reusable <- NULL
      for (candidate in candidates) {
        candidate_hash <- tryCatch(tolower(hash_file(candidate)), error=function(e) NA_character_)
        expected_hash <- tolower(sub("\\.csv$", "", basename(candidate)))
        validation <- tryCatch(verify_camara_annual_csv(candidate, NA_character_), error=function(e) list(ok=FALSE))
        if (!is.na(candidate_hash) && identical(candidate_hash, expected_hash) && isTRUE(validation$ok)) {
          reusable <- list(path=candidate, sha256=candidate_hash)
          break
        }
      }
      if (!is.null(reusable)) {
        status$status[[i]] <- "resumed_verified"
        status$http_status[[i]] <- ifelse(is.na(status$http_status[[i]]), 200L, status$http_status[[i]])
        status$content_type[[i]] <- "text/csv (reused after hash+validation)"
        status$file_size_bytes[[i]] <- as.numeric(file.info(reusable$path)$size)
        status$sha256[[i]] <- reusable$sha256
        status$raw_path[[i]] <- substring(reusable$path, nchar(data_root) + 2L)
        status$error_message[[i]] <- NA_character_
        status$updated_at_utc[[i]] <- strftime(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz="UTC")
        write_camara_annual_status(status, status_path)
        next
      }
    }

    if (!probe_only && status$status[[i]] %in% c("verified", "resumed_verified") &&
        !is.na(status$raw_path[[i]]) && nzchar(status$raw_path[[i]])) {
      existing <- assert_data_path(file.path(data_root, status$raw_path[[i]]), data_root, "annual CSV cached file")
      if (file.exists(existing) && !is.na(status$sha256[[i]]) &&
          identical(tolower(hash_file(existing)), tolower(status$sha256[[i]]))) {
        status$status[[i]] <- "resumed_verified"
        status$updated_at_utc[[i]] <- strftime(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
        write_camara_annual_status(status, status_path)
        next
      }
    }
    if (!probe_only && !retry_failures && camara_is_terminal_failure(status$status[[i]])) next

    if (probe_only) {
      response <- if (is.null(mock_transport)) {
        tryCatch(camara_annual_head(url), error=function(e) list(error=conditionMessage(e)))
      } else tryCatch(mock_transport(url=url,year=year,dataset=dataset,probe_only=TRUE),error=function(e) list(error=conditionMessage(e)))
      response$attempt_count <- 1L
    } else {
      part_path <- file.path(target_dir,paste0(".",run_id,".part"))
      response <- camara_annual_download_with_retries(url,part_path,year,dataset,mock_transport)
    }

    status$updated_at_utc[[i]] <- strftime(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
    status$attempt_count[[i]] <- if (!is.null(response$attempt_count)) as.integer(response$attempt_count) else 1L
    status$range_fallback[[i]] <- isTRUE(response$range_fallback)
    if (!is.null(response$error)) {
      status$status[[i]] <- "network_error"
      status$error_message[[i]] <- as.character(response$error)
    } else {
      code <- as.integer(response$http_status)
      status$http_status[[i]] <- code
      status$final_url[[i]] <- if (!is.null(response$final_url)) as.character(response$final_url) else url
      status$content_type[[i]] <- if (!is.null(response$content_type)) as.character(response$content_type) else NA_character_
      if (probe_only) {
        status$status[[i]] <- if (code >= 200L && code < 300L) "available" else if (code == 404L) "unavailable_404" else paste0("http_", code)
        status$file_size_bytes[[i]] <- if (!is.null(response$content_length)) as.numeric(response$content_length) else NA_real_
      } else if (code == 404L) {
        status$status[[i]] <- "unavailable_404"
        if (file.exists(part_path)) unlink(part_path)
      } else if (code < 200L || code >= 300L) {
        status$status[[i]] <- paste0("http_", code)
        if (file.exists(part_path)) unlink(part_path)
      } else {
        validation <- camara_null_coalesce(response$validation, verify_camara_annual_csv(part_path, status$content_type[[i]]))
        size <- if (file.exists(part_path)) file.info(part_path)$size else 0
        declared <- if (!is.null(response$content_length)) suppressWarnings(as.numeric(response$content_length)) else NA_real_
        if (validation$ok && !is.na(declared) && declared > 0 && size < declared) {
          validation <- list(ok = FALSE, error = "truncated_file")
        }
        if (!validation$ok) {
          status$status[[i]] <- validation$error
          status$error_message[[i]] <- validation$error
          if (file.exists(part_path)) unlink(part_path)
        } else {
          sha <- tolower(hash_file(part_path))
          blob_path <- file.path(target_dir, paste0(sha, ".csv"))
          if (file.exists(blob_path)) {
            if (identical(tolower(hash_file(blob_path)), sha)) unlink(part_path) else file.rename(part_path, blob_path)
          } else if (!file.rename(part_path, blob_path)) {
            if (!file.copy(part_path, blob_path, overwrite = FALSE)) stop("Falha ao promover arquivo CSV verificado: ", blob_path)
            unlink(part_path)
          }
          status$status[[i]] <- "verified"
          status$file_size_bytes[[i]] <- as.numeric(file.info(blob_path)$size)
          status$sha256[[i]] <- sha
          status$raw_path[[i]] <- substring(blob_path, nchar(data_root) + 2L)
          status$error_message[[i]] <- NA_character_
        }
      }
    }
    write_camara_annual_status(status, status_path)
  }

  # Após a tabela de proposições estar validada, baixar todos os campos URL
  # documentais encontrados, mantendo ledger separado e sem limitar quantidade.
  if (!probe_only) {
    eligible <- which(status$dataset == "proposicoes" & status$status %in% c("verified", "resumed_verified"))
    if (!is.null(documents_through_year)) eligible <- eligible[status$year[eligible] <= documents_through_year]
    document_url_cache <- new.env(parent=emptyenv())
    for (i in eligible) {
      csv_path <- assert_data_path(file.path(data_root, status$raw_path[[i]]), data_root, "propositions CSV")
      download_camara_documents_for_year(csv_path, status$year[[i]], data_root, output_dir, mock_transport, document_url_cache, max_concurrency, retry_failures)
    }
  }

  list(status = if (probe_only) "probed" else "completed", run_id = run_id,
       output_dir = output_dir, status_path = status_path, files = status)
}

source(file.path(repo_root,"R","download","camara_scheduler.R"))
