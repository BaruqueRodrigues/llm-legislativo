# Fila contínua curl: conclusões, META refresh e retries sem barreiras por onda.
camara_meta_target <- function(path, base_url) {
  if (!file.exists(path)) return(NULL)
  con <- file(path,"rb"); on.exit(close(con))
  bytes <- readBin(con,"raw",n=min(file.info(path)$size,65536))
  if (!length(bytes)) return(NULL)
  if (!identical(detect_media_type(bytes),"text/html")) return(NULL)
  bytes[bytes==as.raw(0)] <- as.raw(32)
  html <- rawToChar(bytes)
  tag <- regmatches(html,regexpr("(?is)<meta[^>]+http-equiv\\s*=\\s*['\"]?refresh['\"]?[^>]+>",html,perl=TRUE,useBytes=TRUE))
  if (!length(tag) || !nzchar(tag)) return(NULL)
  target <- regmatches(tag,regexpr("(?is)url\\s*=\\s*['\"]?[^'\";>]+",tag,perl=TRUE,useBytes=TRUE))
  if (!length(target) || !nzchar(target)) return(NULL)
  target <- sub("(?is)^.*?url\\s*=\\s*['\"]?", "",target,perl=TRUE)
  target <- gsub("&amp;","&",sub("['\";>\\s]+$","",target),fixed=TRUE)
  if (requireNamespace("xml2",quietly=TRUE)) target <- xml2::url_absolute(target,base_url)
  else if (grepl("^//",target)) target <- paste0("https:",target)
  else if (startsWith(target,"/")) target <- paste0(sub("^(https?://[^/]+).*$","\\1",base_url),target)
  else if (!grepl("^https?://",target,ignore.case=TRUE)) target <- paste0(sub("/[^/]*$","/",sub("[?#].*$","",base_url)),target)
  target <- sub("#.*$","",target)
  if (grepl("^http://([^/]+\\.)?camara\\.leg\\.br([/:]|$)",target,ignore.case=TRUE)) {
    target <- sub("^http://","https://",target,ignore.case=TRUE)
  }
  if (!grepl("^https?://",target,ignore.case=TRUE)) return(NULL)
  target
}

camara_retry_delay <- function(headers, attempt) {
  value <- camara_header_value(headers,"retry-after")
  seconds <- suppressWarnings(as.numeric(value))
  if (!is.na(seconds)) return(max(0,seconds))
  date <- suppressWarnings(as.POSIXct(value,format="%a, %d %b %Y %H:%M:%S",tz="GMT"))
  if (!is.na(date)) return(max(0,as.numeric(difftime(date,Sys.time(),units="secs"))))
  min(60,2^(attempt-1L)) + stats::runif(1,0,0.25)
}

camara_host_slot <- function(data_root, host, limit) {
  directory <- file.path(data_root,"staging","download_host_slots",hash_string(host))
  dir.create(directory,recursive=TRUE,showWarnings=FALSE)
  for (i in seq_len(limit)) {
    slot <- file.path(directory,sprintf("slot_%03d",i))
    if (dir.exists(slot) && as.numeric(difftime(Sys.time(),file.info(slot)$mtime,units="secs")) > 600) unlink(slot,recursive=TRUE)
    if (dir.create(slot,showWarnings=FALSE)) return(slot)
  }
  NULL
}

camara_document_result <- function(fetched, data_root) {
  if (!is.null(fetched$cached_result)) return(fetched$cached_result)
  response <- fetched$response; part <- fetched$part_path
  result <- list(http_status=camara_null_coalesce(response$http_status,NA_integer_),
    content_type=camara_null_coalesce(response$content_type,NA_character_),file_size_bytes=NA_real_,
    sha256=NA_character_,raw_path=NA_character_,resolved_url=fetched$resolved_url,
    attempt_count=camara_null_coalesce(response$attempt_count,1L),range_fallback=isTRUE(response$range_fallback),
    status="network_error",error_message=camara_null_coalesce(response$error,NA_character_))
  if (is.null(response$error)) {
    code <- result$http_status
    if (code == 404L) result$status <- "unavailable_404"
    else if (code < 200L || code >= 300L) result$status <- paste0("http_",code)
    else {
      validation <- verify_camara_document_file(part,result$content_type)
      size <- if (file.exists(part)) file.info(part)$size else 0
      declared <- camara_null_coalesce(response$content_length,NA_real_)
      if (!validation$ok) result$status <- validation$error
      else if (!is.na(declared) && declared > size) result$status <- "truncated_file"
      else {
        sha <- tolower(hash_file(part))
        blob <- assert_data_path(file.path(data_root,"raw","sha256",substr(sha,1,2),paste0(sha,".bin")),data_root,"document blob")
        dir.create(dirname(blob),recursive=TRUE,showWarnings=FALSE)
        if (file.exists(blob) && identical(tolower(hash_file(blob)),sha)) unlink(part)
        else if (!file.rename(part,blob)) stop("Falha ao persistir blob: ",blob)
        result$status <- "verified"; result$file_size_bytes <- size; result$sha256 <- sha
        result$raw_path <- substring(blob,nchar(data_root)+2L)
      }
    }
  }
  if (file.exists(part) && !result$status %in% c("network_error","truncated_file")) unlink(part)
  result
}

camara_url_index <- function(data_root) {
  if (identical(Sys.getenv("LLM_DOWNLOAD_CACHE"),"0")) return(NULL)
  cutoff <- Sys.getenv("LLM_DOWNLOAD_SNAPSHOT_ID",unset="")
  if (!nzchar(cutoff)) cutoff <- yaml::read_yaml(file.path(repo_root,"configs","data","history.yaml"))$snapshot_cutoff_utc
  scope <- hash_string(as.character(cutoff))
  directory <- file.path(data_root,"staging","download_url_cache",scope)
  dir.create(directory,recursive=TRUE,showWarnings=FALSE)
  directory
}
camara_index_get <- function(directory,url,data_root) {
  if (is.null(directory)) return(NULL)
  path <- file.path(directory,paste0(hash_string(url),".rds"))
  if (!file.exists(path)) return(NULL)
  value <- tryCatch(readRDS(path),error=function(e) NULL)
  if (is.null(value) || !identical(value$status,"verified")) return(NULL)
  blob <- tryCatch(assert_data_path(file.path(data_root,value$raw_path),data_root,"cached blob"),error=function(e) NULL)
  if (is.null(blob)) return(NULL)
  if (!file.exists(blob)) {
    if (!cloud_blob_archived(value$raw_path, value$sha256, data_root)) return(NULL)
  } else if (!identical(tolower(hash_file(blob)),value$sha256)) return(NULL)
  value
}
camara_index_put <- function(directory,url,result) {
  if (is.null(directory) || !identical(result$status,"verified")) return(invisible(NULL))
  path <- file.path(directory,paste0(hash_string(url),".rds"))
  part <- tempfile("index_",tmpdir=directory)
  saveRDS(result,part)
  if (!file.rename(part,path)) { unlink(part); stop("Falha ao publicar índice URL: ",path) }
  invisible(NULL)
}

camara_schedule_urls <- function(urls,year,output_dir,max_concurrency,pool,url_cache=NULL,
                                 on_result=NULL,max_attempts=3L,deadline=Inf) {
  if (!length(urls)) return(list())
  data_root <- resolve_download_data_root()
  dir.create(file.path(output_dir,"document_parts"),recursive=TRUE,showWarnings=FALSE)
  jobs <- lapply(urls,function(u) list(url=u,current=u,part=file.path(output_dir,"document_parts",paste0(hash_string(u),".part")),
    attempt=0L,requests=0L,depth=0L,due=0,active=FALSE,done=FALSE,handle=NULL,slot=NULL,range_fallback=FALSE))
  results <- vector("list",length(urls)); inbox <- list(); active <- 0L; done_count <- 0L
  pending <- seq_along(urls); host_active <- new.env(parent=emptyenv())
  last_disk_check <- 0
  host_limits <- new.env(parent=emptyenv()); host_cooldown <- new.env(parent=emptyenv())
  attempts <- file(file.path(output_dir,"fetch_attempts.jsonl"),"a")
  on.exit({
    for (job in jobs) {
      if (!is.null(job$handle) && job$active) curl::multi_cancel(job$handle)
      if (!is.null(job$slot)) unlink(job$slot,recursive=TRUE)
    }
    close(attempts)
  },add=TRUE)
  finish <- function(i,fetched) {
    results[[i]] <<- fetched
    jobs[[i]]$done <<- TRUE
    done_count <<- done_count+1L
    if (!is.null(on_result)) on_result(urls[[i]],fetched)
  }
  while (done_count < length(jobs)) {
    now <- as.numeric(Sys.time())
    if (now >= deadline) break
    if (now-last_disk_check>=5) {
      camara_assert_download_disk_space(file.path(output_dir,"document_parts"))
      last_disk_check <- now
    }
    if (length(inbox)) {
      completed <- inbox; inbox <- list()
      for (event in completed) {
        i <- event$i; job <- jobs[[i]]; job$active <- FALSE; active <- active-1L
        if (!is.null(job$slot)) unlink(job$slot,recursive=TRUE)
        job$slot <- NULL
        host <- camara_url_host(job$current)
        host_active[[host]] <- max(0L,camara_null_coalesce(host_active[[host]],0L)-1L)
        res <- event$response; res$attempt_count <- job$requests
        headers <- res$headers
        code <- camara_null_coalesce(res$status_code,0L)
        content_type <- camara_header_value(headers,"content-type")
        declared <- suppressWarnings(as.numeric(camara_header_value(headers,"content-length")))
        if (is.null(res$error) && job$offset > 0) {
          range <- camara_header_value(headers,"content-range")
          fields <- regmatches(range,regexec("^bytes ([0-9]+)-([0-9]+)/([0-9]+)$",range))[[1]]
          segment_size <- if (file.exists(job$destination)) file.info(job$destination)$size else 0
          if (code == 206L && length(fields)==4L && as.numeric(fields[[2]])==job$offset &&
              as.numeric(fields[[3]])-job$offset+1==segment_size) {
            camara_append_file(job$destination,job$part); unlink(job$destination)
            declared <- as.numeric(fields[[4]])
          } else if (code==200L) {
            unlink(job$part); file.rename(job$destination,job$part); job$range_fallback <- TRUE
          } else {
            unlink(c(job$destination,job$part)); res$error <- "invalid_range_response"; job$range_fallback <- TRUE
          }
        }
        size <- if (file.exists(job$part)) file.info(job$part)$size else 0
        cat(jsonlite::toJSON(list(requested_url=job$url,final_url=camara_null_coalesce(res$url,job$current),
          attempt_no=job$requests,http_status=code,received_size_bytes=camara_null_coalesce(res$content_length,size),
          elapsed_seconds=as.numeric(Sys.time())-job$started_at,error=camara_null_coalesce(res$error,NA_character_),
          finished_at_utc=strftime(Sys.time(),"%Y-%m-%dT%H:%M:%OS3Z",tz="UTC")),auto_unbox=TRUE,na="null"),"\n",file=attempts,sep="")
        flush(attempts)
        response <- list(http_status=as.integer(code),final_url=camara_null_coalesce(res$url,job$current),
          content_type=content_type,content_length=declared,attempt_count=job$requests,range_fallback=job$range_fallback,error=res$error)
        retryable <- !is.null(res$error) || code==429L || code>=500L ||
          (code>=200L && code<300L && (size==0 || (!is.na(declared) && declared>size)))
        if (retryable && job$attempt < max_attempts) {
          delay <- camara_retry_delay(headers,job$attempt)
          job$due <- as.numeric(Sys.time())+delay
          if (code==429L || code==503L) {
            host <- camara_url_host(job$current)
            host_limits[[host]] <- max(1L,as.integer(camara_null_coalesce(host_limits[[host]],max_concurrency)/2L))
            host_cooldown[[host]] <- job$due
          }
          if (code>=400L || size==0) unlink(job$part)
        } else {
          target <- if (is.null(res$error) && code>=200L && code<300L) camara_meta_target(job$part,response$final_url) else NULL
          if (!is.null(target) && job$depth < 5L) {
            job$current <- target; job$depth <- job$depth+1L; job$attempt <- 0L; job$due <- 0
            unlink(job$part)
          } else {
            jobs[[i]] <- job
            finish(i,list(response=response,part_path=job$part,resolved_url=response$final_url))
            next
          }
        }
        jobs[[i]] <- job
        pending <- c(pending,i)
      }
    }
    admitted <- integer()
    for (i in pending) {
      if (active>=max_concurrency) break
      job <- jobs[[i]]
      if (job$done || job$active || job$due>as.numeric(Sys.time())) next
      key <- hash_string(sub("#.*$","",job$current))
      if (!is.null(url_cache) && exists(key,envir=url_cache,inherits=FALSE)) {
        admitted <- c(admitted,i)
        finish(i,list(response=list(cached_document=TRUE),part_path=job$part,resolved_url=job$current,
                      cached_result=get(key,envir=url_cache,inherits=FALSE)))
        next
      }
      host <- camara_url_host(job$current)
      limit <- camara_null_coalesce(host_limits[[host]],max_concurrency)
      if (camara_null_coalesce(host_cooldown[[host]],0)>as.numeric(Sys.time())) next
      occupied <- camara_null_coalesce(host_active[[host]],0L)
      if (occupied>=limit) next
      slot <- camara_host_slot(data_root,host,limit)
      if (is.null(slot)) next
      job$slot <- slot
      job$offset <- if (file.exists(job$part)) file.info(job$part)$size else 0
      job$destination <- if (job$offset>0) paste0(job$part,".range") else job$part
      job$attempt <- job$attempt+1L; job$requests <- job$requests+1L
      job$started_at <- as.numeric(Sys.time())
      handle <- curl::new_handle(url=job$current,followlocation=TRUE,timeout=180L,connecttimeout=30L,
        http_version=2L,accept_encoding="identity",useragent="LLM-Legislativo/2.0 (pesquisa educacional)")
      if (job$offset>0) curl::handle_setheaders(handle,Range=paste0("bytes=",format(job$offset,scientific=FALSE),"-"))
      done <- local({ index <- i; function(response) inbox[[length(inbox)+1L]] <<- list(i=index,response=response) })
      fail <- local({ index <- i; function(message) inbox[[length(inbox)+1L]] <<- list(i=index,response=list(error=as.character(message))) })
      job$handle <- handle; job$active <- TRUE; jobs[[i]] <- job; active <- active+1L
      host_active[[host]] <- occupied+1L; admitted <- c(admitted,i)
      tryCatch(curl::multi_add(handle,done=done,fail=fail,data=job$destination,pool=pool),
        error=function(e) fail(conditionMessage(e)))
    }
    pending <- pending[!pending %in% admitted]
    if (length(curl::multi_list(pool))) curl::multi_run(timeout=0.2,poll=TRUE,pool=pool)
    else if (!length(inbox)) Sys.sleep(0.05)
  }
  results
}
