# Download concorrente a partir do inventário CSV consolidado do Senado.
# Não segue páginas HTML de visualização/desafio: somente redirecionamentos HTTP
# automáticos e conteúdo binário validado pelo contrato comum são aceitos.

senado_csv_host <- function(url) tolower(sub("^https?://([^/:?#]+).*$", "\\1", url, ignore.case=TRUE))
senado_null_coalesce <- function(x, fallback) if (is.null(x)) fallback else x
senado_header_value <- function(headers, name) {
  if (is.null(headers) || !length(headers)) return(NA_character_)
  if (is.raw(headers) || (is.character(headers) && is.null(names(headers)))) headers <- curl::parse_headers_list(headers)
  nms <- names(headers)
  if (is.null(nms)) return(NA_character_)
  idx <- which(tolower(nms)==tolower(name))
  if (!length(idx) || is.null(headers[[idx[[1L]]]]) || !length(headers[[idx[[1L]]]])) NA_character_ else as.character(headers[[idx[[1L]]]][[1L]])
}
senado_retry_delay <- function(headers, attempt) {
  value <- senado_header_value(headers,"retry-after")
  seconds <- suppressWarnings(as.numeric(value))
  if (!is.na(seconds)) return(max(0,seconds))
  date <- suppressWarnings(as.POSIXct(value,format="%a, %d %b %Y %H:%M:%S",tz="GMT"))
  if (!is.na(date)) return(max(0,as.numeric(difftime(date,Sys.time(),units="secs"))))
  min(60,2^(attempt-1L))+stats::runif(1,0,0.25)
}

senado_links_read_csv <- function(path) {
  if (!file.exists(path)) stop("Inventário CSV do Senado não encontrado: ", path)
  dat <- utils::read.csv(path, stringsAsFactors=FALSE, check.names=FALSE, colClasses="character",
                         na.strings=character(), fileEncoding="UTF-8")
  required <- c("document_url", "process_id", "source")
  missing <- setdiff(required, names(dat))
  if (length(missing)) stop("Inventário precisa das colunas: ", paste(required, collapse=", "),
                            "; ausentes: ", paste(missing, collapse=", "))
  dat$document_url <- trimws(dat$document_url)
  dat <- dat[!is.na(dat$document_url) & nzchar(dat$document_url), , drop=FALSE]
  dat
}

senado_write_checkpoint <- function(state, path) {
  tmp <- paste0(path, ".part")
  utils::write.csv(state, tmp, row.names=FALSE, na="", fileEncoding="UTF-8")
  if (!file.rename(tmp, path)) stop("Falha ao publicar checkpoint: ", path)
}

senado_download_links_csv <- function(csv_path, data_root=NULL, output_dir=NULL,
                                      max_concurrency=40L, per_host_concurrency=4L,
                                      min_host_interval=0.2, max_retries=3L,
                                      retry_failures=FALSE, dry_run=FALSE) {
  source(file.path(repo_root,"R","download","publisher.R"), local=TRUE)
  source(file.path(repo_root,"R","download","reconciliation.R"), local=TRUE)
  source(file.path(repo_root,"R","download","validator.R"), local=TRUE)
  source(file.path(repo_root,"R","download","blob_store.R"), local=TRUE)
  data_root <- resolve_download_data_root(data_root)
  max_concurrency <- as.integer(max_concurrency); per_host_concurrency <- as.integer(per_host_concurrency)
  max_retries <- as.integer(max_retries); min_host_interval <- as.numeric(min_host_interval)
  if (is.na(max_concurrency) || max_concurrency < 1L || is.na(per_host_concurrency) || per_host_concurrency < 1L ||
      is.na(max_retries) || max_retries < 1L || is.na(min_host_interval) || min_host_interval < 0)
    stop("Concorrência, retries e intervalo por host precisam ser valores válidos e não negativos.")
  input <- senado_links_read_csv(csv_path)
  input$document_id <- paste0("senado:doc:senado_api_url:",vapply(input$document_url,hash_string,character(1)))
  # Um fetch por URL distinta; a publicação mantém a identidade por URL como chave
  # quando a mesma captura atende a mais de um processo do catálogo.
  docs <- unique(input[c("document_url","document_id")])
  docs$key <- vapply(docs$document_url, hash_string, character(1))
  input_sha <- tolower(hash_file(csv_path))
  batch_id <- paste0("senado_links_csv_",substr(input_sha,1,16))
  if (is.null(output_dir)) output_dir <- file.path(data_root,"staging","downloads","senado_links_csv",batch_id)
  output_dir <- assert_data_path(output_dir,data_root,"output_dir")
  dir.create(output_dir,recursive=TRUE,showWarnings=FALSE)
  utils::write.csv(input,file.path(output_dir,"source_links.csv"),row.names=FALSE,na="",fileEncoding="UTF-8")
  checkpoint_path <- file.path(output_dir,"document_status.csv")
  journal_path <- file.path(output_dir,"fetch_attempts.jsonl")
  if (dry_run) return(list(status="dry_run",batch_id=batch_id,input_rows=nrow(input),unique_urls=nrow(docs),
    output_dir=output_dir,max_concurrency=max_concurrency,per_host_concurrency=per_host_concurrency,
    min_host_interval=min_host_interval))

  prior <- if (file.exists(checkpoint_path)) utils::read.csv(checkpoint_path,stringsAsFactors=FALSE,check.names=FALSE) else NULL
  journal_lines <- if (file.exists(journal_path)) readLines(journal_path,warn=FALSE) else character()
  journal_events <- Filter(Negate(is.null),lapply(journal_lines,function(line) tryCatch(jsonlite::fromJSON(line,simplifyVector=TRUE),error=function(e) NULL)))
  status <- data.frame(key=docs$key,document_id=docs$document_id,requested_url=docs$document_url,
    status="pending",attempt_count=0L,http_status=NA_integer_,content_type=NA_character_,final_url=NA_character_,
    declared_size_bytes=NA_real_,received_size_bytes=NA_real_,sha256=NA_character_,raw_path=NA_character_,capture_id=NA_character_,
    error_code=NA_character_,error_message=NA_character_,stringsAsFactors=FALSE)
  if (!is.null(prior) && all(c("key","status") %in% names(prior))) for (i in seq_len(nrow(status))) {
    old <- which(prior$key==status$key[[i]])
    if (length(old)) for (nm in intersect(names(status),names(prior))) status[[nm]][[i]] <- prior[[nm]][tail(old,1)]
    if (status$status[[i]] %in% c("verified","resumed_verified")) {
      p <- tryCatch(assert_data_path(file.path(data_root,status$raw_path[[i]]),data_root,"resumed blob"),error=function(e) NA_character_)
      capture <- NULL
      if (!is.na(p) && file.exists(p) && identical(tolower(hash_file(p)),tolower(status$sha256[[i]]))) {
        matched <- Filter(function(e) identical(as.character(e$document_id),status$document_id[[i]]) &&
          identical(tolower(as.character(e$file_sha256)),tolower(status$sha256[[i]])) &&
          identical(as.character(e$status),"succeeded") && !is.null(e$capture_id),journal_events)
        if (length(matched)) capture <- as.character(tail(matched,1L)[[1L]]$capture_id)
      }
      if (is.null(capture)) {
        # Um blob válido sem tentativa de sucesso verificável não satisfaz first_capture_id.
        status$status[[i]] <- "pending"
        status$sha256[[i]] <- NA_character_
        status$raw_path[[i]] <- NA_character_
        status$capture_id[[i]] <- NA_character_
      } else {
        status$status[[i]] <- "resumed_verified"
        status$capture_id[[i]] <- capture
      }
    }
  }
  pending <- which(status$status %in% c("pending","retry_pending") |
    (retry_failures & !status$status %in% c("verified","resumed_verified")))
  if (length(pending)) {
    dir.create(file.path(output_dir,"parts"),recursive=TRUE,showWarnings=FALSE)
    pool <- curl::new_pool(total_con=max_concurrency,host_con=max_concurrency,max_streams=max_concurrency,multiplex=FALSE)
    jobs <- lapply(pending,function(i) {
      previous_attempts <- suppressWarnings(as.integer(status$attempt_count[[i]]))
      if (is.na(previous_attempts) || previous_attempts < 0L) previous_attempts <- 0L
      retry_events <- Filter(function(e) identical(as.character(e$document_id),status$document_id[[i]]) &&
        identical(as.character(e$requested_url),status$requested_url[[i]]) &&
        identical(as.character(e$status),"retry_pending") && !is.null(e$next_retry_at),journal_events)
      due <- 0
      if (length(retry_events)) {
        retry_at <- tail(retry_events,1L)[[1L]]$next_retry_at
        retry_at <- suppressWarnings(as.POSIXct(as.character(retry_at),tz="UTC"))
        if (length(retry_at)==1L && !is.na(retry_at)) due <- as.numeric(retry_at)
      }
      list(row=i,attempt=previous_attempts,active=FALSE,due=due,handle=NULL,host=senado_csv_host(status$requested_url[[i]]))
    })
    names(jobs) <- as.character(pending)
    inbox <- list(); active <- 0L; host_active <- new.env(parent=emptyenv()); host_last <- new.env(parent=emptyenv())
    host_cooldown <- new.env(parent=emptyenv()); host_limits <- new.env(parent=emptyenv())
    journal <- file(journal_path,"a"); on.exit(close(journal),add=TRUE)
    record_attempt <- function(i, attempt, started, code, mime, declared, received, final, result_status, err,
                               sha=NA_character_, version_id=NA_character_, next_retry_at=as.POSIXct(NA,tz="UTC")) {
      capture <- paste0("cap:",hash_string(paste(status$document_id[[i]],status$requested_url[[i]],attempt,format(started,tz="UTC",usetz=TRUE))))
      rec <- list(capture_id=capture,document_id=status$document_id[[i]],requested_url=status$requested_url[[i]],final_url=final,
        started_at=started,finished_at=Sys.time(),attempt_no=as.integer(attempt),http_status=as.integer(code),declared_media_type=mime,
        declared_size_bytes=as.numeric(declared),received_size_bytes=as.numeric(received),file_sha256=sha,version_id=version_id,
        status=result_status,error_code=err,error_message=err,next_retry_at=next_retry_at)
      cat(jsonlite::toJSON(rec,auto_unbox=TRUE,na="null"),"\n",file=journal,sep=""); flush(journal)
      status$capture_id[[i]] <<- capture
      rec
    }
    done_count <- 0L
    while (done_count < length(jobs)) {
      if (length(inbox)) {
        events <- inbox; inbox <- list()
        for (event in events) {
          j <- jobs[[as.character(event$i)]]; active <- active-1L; host_active[[j$host]] <- max(0L,host_active[[j$host]]-1L)
          j$active <- FALSE
          res <- event$response; code <- if (is.null(res$status_code)) 0L else as.integer(res$status_code)
          mime <- senado_header_value(res$headers,"content-type"); decl <- suppressWarnings(as.numeric(senado_header_value(res$headers,"content-length")))
          part <- file.path(output_dir,"parts",paste0(status$key[[event$i]],".part")); size <- if (file.exists(part)) file.info(part)$size else 0
          final <- if (is.null(res$url)) status$requested_url[[event$i]] else res$url
          err <- if (!is.null(res$error)) as.character(res$error) else NA_character_
          result <- NULL; version_id <- NA_character_; sha <- NA_character_
          if (is.na(err) && code>=200L && code<300L) {
            bytes <- if (size>0) readBin(part,"raw",n=size) else raw()
            validation <- validate_download_content(bytes,mime,decl,TRUE)
            if (!validation$valid) err <- validation$error_code
            else {
              blob <- store_raw_blob(bytes,data_root)
              sha <- blob$sha256; status$raw_path[[event$i]] <- blob$raw_path; status$sha256[[event$i]] <- sha
              version_id <- paste0(status$document_id[[event$i]],":v:",sha); result <- "verified"
            }
          } else if (is.na(err)) err <- if (code==404L) "HTTP_404" else paste0("HTTP_",code)
          retryable <- !is.na(err) && (code==0L || code==429L || code>=500L || identical(err,"TRUNCATED_FILE"))
          next_retry_at <- as.POSIXct(NA,tz="UTC")
          if (!is.null(result)) status$status[[event$i]] <- result
          else if (retryable && j$attempt < max_retries) {
            delay <- senado_retry_delay(res$headers,j$attempt)
            j$due <- as.numeric(Sys.time()) + delay
            next_retry_at <- as.POSIXct(j$due,origin="1970-01-01",tz="UTC")
            if (code %in% c(429L,503L)) {
              host_cooldown[[j$host]] <- j$due
              current_limit <- senado_null_coalesce(host_limits[[j$host]],per_host_concurrency)
              host_limits[[j$host]] <- max(1L,as.integer(ceiling(current_limit/2)))
            }
            status$status[[event$i]] <- "retry_pending"
          } else {
            status$status[[event$i]] <- if (identical(err,"HTML_200_FALSE_POSITIVE")) "html_error" else "terminal_error"
            unlink(part)
          }
          status$attempt_count[[event$i]] <- j$attempt; status$http_status[[event$i]] <- if (code>0) code else NA_integer_
          status$content_type[[event$i]] <- mime; status$final_url[[event$i]] <- final; status$declared_size_bytes[[event$i]] <- decl
          status$received_size_bytes[[event$i]] <- size; status$error_code[[event$i]] <- if (is.null(result)) err else NA_character_
          status$error_message[[event$i]] <- status$error_code[[event$i]]
          record_attempt(event$i,j$attempt,event$started,code,mime,decl,size,final,
            if (is.null(result)) status$status[[event$i]] else "succeeded",if (is.null(result)) err else NA_character_,sha,version_id,next_retry_at)
          if (!identical(status$status[[event$i]],"retry_pending")) done_count <- done_count+1L
          jobs[[as.character(event$i)]] <- j
          senado_write_checkpoint(status,checkpoint_path)
        }
      }
      for (nm in names(jobs)) {
        j <- jobs[[nm]]; i <- j$row
        if (j$active || !status$status[[i]] %in% c("pending","retry_pending") || j$due>as.numeric(Sys.time()) || active>=max_concurrency) next
        host <- j$host
        if (senado_null_coalesce(host_cooldown[[host]],0)>as.numeric(Sys.time())) next
        if (senado_null_coalesce(host_active[[host]],0L)>=senado_null_coalesce(host_limits[[host]],per_host_concurrency)) next
        last <- host_last[[host]]; now <- as.numeric(Sys.time())
        if (!is.null(last) && now-last<min_host_interval) next
        part <- file.path(output_dir,"parts",paste0(status$key[[i]],".part")); started <- Sys.time(); j$attempt <- j$attempt+1L
        handle <- curl::new_handle(url=status$requested_url[[i]],followlocation=TRUE,timeout=180L,connecttimeout=30L,
          accept_encoding="identity",useragent="LLM-Legislativo/2.0 (pesquisa educacional)")
        callback_done <- local({idx<-i; st<-started; function(response) inbox[[length(inbox)+1L]] <<- list(i=idx,started=st,response=response)})
        callback_fail <- local({idx<-i; st<-started; function(message) inbox[[length(inbox)+1L]] <<- list(i=idx,started=st,response=list(error=as.character(message),status_code=0L,headers=list()))})
        j$handle<-handle; j$active<-TRUE; jobs[[nm]]<-j; active<-active+1L; host_active[[host]]<-senado_null_coalesce(host_active[[host]],0L)+1L; host_last[[host]]<-now
        curl::multi_add(handle,done=callback_done,fail=callback_fail,data=part,pool=pool)
      }
      if (length(curl::multi_list(pool))) curl::multi_run(timeout=0.2,poll=TRUE,pool=pool) else if (!length(inbox)) Sys.sleep(0.05)
    }
  }
  senado_write_checkpoint(status,checkpoint_path)

  # Reconstrói as tabelas normativas a partir do journal append-only.
  events <- if (file.exists(journal_path)) lapply(readLines(journal_path,warn=FALSE),function(x) tryCatch(jsonlite::fromJSON(x,simplifyVector=TRUE),error=function(e) NULL)) else list()
  events <- Filter(Negate(is.null),events)
  attempt_fields <- c("capture_id","document_id","requested_url","final_url","started_at","finished_at","attempt_no",
    "http_status","declared_media_type","declared_size_bytes","received_size_bytes","file_sha256","version_id",
    "status","error_code","error_message","next_retry_at")
  attempts <- if (length(events)) dplyr::bind_rows(lapply(events,function(x) {
    row <- lapply(attempt_fields,function(nm) if (is.null(x[[nm]]) || !length(x[[nm]])) NA else x[[nm]])
    names(row) <- attempt_fields
    as.data.frame(row,stringsAsFactors=FALSE)
  })) else data.frame()
  verified <- which(status$status %in% c("verified","resumed_verified"))
  versions <- lapply(verified,function(i) {
    path <- assert_data_path(file.path(data_root,status$raw_path[[i]]),data_root,"Senado document blob")
    bytes <- readBin(path,"raw",n=min(file.info(path)$size,16L)); media <- detect_media_type(bytes)
    list(version_id=paste0(status$document_id[[i]],":v:",status$sha256[[i]]),document_id=status$document_id[[i]],
      file_sha256=status$sha256[[i]],raw_path=status$raw_path[[i]],file_size_bytes=as.numeric(file.info(path)$size),
      detected_media_type=media,page_count=NA_integer_,version_kind="observed_capture",source_version_label=NA_character_,
      source_content_date=as.Date(NA),availability_date=as.Date(Sys.Date()),version_date_status="unknown",
      predecessor_version_id=NA_character_,first_capture_id=status$capture_id[[i]],integrity_status="verified")
  })
  versions_df <- if (length(versions)) dplyr::bind_rows(versions) else data.frame()
  queue <- data.frame(document_id=docs$document_id,house="senado",requested_url=docs$document_url,
    normalized_kind="unknown",publication_date=as.Date(NA),stringsAsFactors=FALSE)
  retrieved <- sum(status$status %in% c("verified","resumed_verified")); failed <- sum(status$status %in% c("terminal_error","html_error"))
  pending_total <- sum(status$status %in% c("pending","retry_pending"))
  coverage_status <- if (!nrow(queue)) "empty_verified" else if (retrieved==nrow(queue)) "complete_discovered" else if (retrieved>0L && (failed>0L || pending_total>0L)) "closed_with_gaps" else if (retrieved>0L) "partial" else "pending"
  summary <- list(discovered_total=nrow(queue),retrieved_total=retrieved,failed_total=failed,
    pending_total=pending_total,coverage_status=coverage_status,
    storage_metrics=list(unique_blobs_count=length(unique(status$sha256[!is.na(status$sha256)])),storage_reuse_count=0L,
      total_bytes_received=sum(status$received_size_bytes,na.rm=TRUE)))
  pub <- publish_download_batch(attempts,versions_df,output_dir,batch_id,summary)
  list(status="completed",batch_id=batch_id,input_rows=nrow(input),unique_urls=nrow(docs),document_status=status,
    publication=pub,checkpoint_path=checkpoint_path,output_dir=output_dir)
}
