# Enrichment da API v2 por proposição. Checkpoints e payloads ficam em DATA_ROOT.

camara_enrichment_endpoints <- c("detail", "autores", "temas", "tramitacoes", "relacionadas")

camara_enrichment_empty_queue <- function() data.frame(
  proposition_id=character(), source_id=character(), endpoint_kind=character(),
  status=character(), next_url=character(), pages_completed=integer(), attempts=integer(),
  last_snapshot_id=character(), last_checked_at=as.POSIXct(character(),tz="UTC"),
  reason=character(), stringsAsFactors=FALSE)

camara_add_enrichment_queue_rows <- function(queue, proposition_rows) {
  if (is.null(proposition_rows) || !nrow(proposition_rows)) return(queue)
  new_rows <- list()
  for (i in seq_len(nrow(proposition_rows))) {
    pid <- as.character(proposition_rows$proposition_id[i])
    sid <- as.character(proposition_rows$source_id[i])
    for (endpoint in camara_enrichment_endpoints) {
      exists <- nrow(queue) && any(queue$proposition_id == pid & queue$endpoint_kind == endpoint)
      if (!exists) new_rows[[length(new_rows)+1L]] <- data.frame(
        proposition_id=pid, source_id=sid, endpoint_kind=endpoint, status="pending",
        next_url=NA_character_, pages_completed=0L, attempts=0L, last_snapshot_id=NA_character_,
        last_checked_at=as.POSIXct(NA,tz="UTC"), reason="Aguardando consulta API v2.", stringsAsFactors=FALSE)
    }
  }
  if (length(new_rows)) queue <- dplyr::bind_rows(queue, dplyr::bind_rows(new_rows))
  queue
}

camara_enrichment_url <- function(api_base, source_id, endpoint) {
  base <- paste0(sub("/+$", "", api_base), "/proposicoes/", utils::URLencode(source_id, reserved=TRUE))
  suffix <- switch(endpoint, detail="", autores="/autores", temas="/temas",
    tramitacoes="/tramitacoes", relacionadas="/relacionadas")
  paste0(base, suffix)
}

camara_enrichment_snapshot <- function(url, body, response, endpoint, page) {
  payload <- if (!is.null(body)) as.character(jsonlite::toJSON(body, auto_unbox=TRUE)) else ""
  status <- as.integer(response$http_status %||% NA_integer_)
  stamp <- response$finished_at %||% Sys.time()
  sid <- paste0("camara:snap:enrichment:", hash_string(paste(url, status, payload, format(stamp, "%Y%m%d%H%M%OS6",tz="UTC"))))
  data.frame(snapshot_id=sid, house="camara", source_kind="api", request_url=url,
    query_json=as.character(jsonlite::toJSON(list(endpoint=endpoint,page=page),auto_unbox=TRUE)),
    collected_at=as.POSIXct(stamp,tz="UTC"), http_status=status,
    payload_sha256=if (is.null(body)) NA_character_ else hash_string(payload), raw_path=NA_character_,
    pagination_complete=FALSE, source_schema_version="0.4.344",
    license_evidence_id="camara:use:dados_abertos_politica", stringsAsFactors=FALSE)
}

camara_enrichment_items <- function(body, endpoint) {
  if (is.null(body) || !length(body)) return(list())
  if (endpoint == "detail") {
    value <- body$dados
    if (is.null(value) || !length(value)) return(list())
    if (is.list(value) && !is.null(names(value))) return(list(value))
    return(value)
  }
  value <- body$dados
  if (is.null(value)) list() else value
}

camara_enrichment_next <- function(body) {
  links <- body$links
  if (is.null(links) || !length(links)) return(NULL)
  for (link in links) if (identical(as.character(link$rel), "next")) return(as.character(link$href))
  NULL
}

# Executa no máximo max_requests páginas/endpoints. Cada linha da fila recebe
# até uma página por execução para garantir justiça e retomada limitada.
run_camara_enrichment <- function(propositions, output_dir, api_base,
                                  request_fn=NULL, max_requests=100L) {
  root <- file.path(output_dir,"enrichment")
  raw_root <- file.path(root,"responses")
  dir.create(raw_root,recursive=TRUE,showWarnings=FALSE)
  queue_path <- file.path(root,"queue.rds")
  queue <- if (file.exists(queue_path)) readRDS(queue_path) else camara_enrichment_empty_queue()
  queue <- camara_add_enrichment_queue_rows(queue, propositions)
  used <- 0L; attempts_used <- 0L; newly_discovered <- list()
  ready <- which(queue$status %in% c("pending","running","retryable_error"))
  for (idx in head(ready, max_requests)) {
    row <- queue[idx,,drop=FALSE]
    url <- if (!is.na(row$next_url[1]) && nzchar(row$next_url[1])) row$next_url[1] else
      camara_enrichment_url(api_base,row$source_id[1],row$endpoint_kind[1])
    started <- Sys.time()
    result <- tryCatch(if (is.function(request_fn)) request_fn(url, row$pages_completed[1]+1L) else
      perform_resilient_request(url), error=function(e) list(status="retryable_error_exhausted",
        http_status=NA_integer_,attempts=1L,error_message=conditionMessage(e),finished_at=Sys.time()))
    used <- used+1L
    attempts_used <- attempts_used+as.integer(result$attempts %||% 1L)
    body <- NULL
    if (identical(result$status,"succeeded")) {
      body <- if (!is.null(result$body)) result$body else if (!is.null(result$response))
        httr2::resp_body_json(result$response,simplifyVector=FALSE) else list(dados=list(),links=list())
    }
    snap <- camara_enrichment_snapshot(url,body,result,row$endpoint_kind[1],row$pages_completed[1]+1L)
    if (identical(result$status,"succeeded")) snap$pagination_complete <- is.null(camara_enrichment_next(body))
    item_count <- length(camara_enrichment_items(body,row$endpoint_kind[1]))
    next_url <- if (identical(result$status,"succeeded")) camara_enrichment_next(body) else NULL
    snap$pagination_complete <- identical(result$status,"succeeded") && is.null(next_url)
    queue$pages_completed[idx] <- queue$pages_completed[idx]+1L
    queue$attempts[idx] <- queue$attempts[idx]+as.integer(result$attempts %||% 1L)
    queue$last_snapshot_id[idx] <- snap$snapshot_id
    queue$last_checked_at[idx] <- as.POSIXct(result$finished_at %||% Sys.time(),tz="UTC")
    if (identical(result$status,"succeeded")) {
      queue$next_url[idx] <- if (is.null(next_url)) NA_character_ else next_url
      queue$status[idx] <- if (!is.null(next_url)) "running" else if (item_count==0L) "success_empty" else "success_nonempty"
      queue$reason[idx] <- if (!is.null(next_url)) "Página capturada; próxima página pendente." else
        if (item_count==0L) "HTTP bem-sucedido sem registros; ausência não inferida fora deste endpoint." else "Resposta oficial capturada."
    } else {
      queue$next_url[idx] <- url
      status_code <- as.integer(result$http_status %||% NA_integer_)
      queue$status[idx] <- if (!is.na(status_code) && status_code %in% c(400L,401L,403L,404L,410L)) "terminal_error" else "retryable_error"
      queue$reason[idx] <- result$error_message %||% paste("Falha HTTP",status_code)
    }
    folder <- file.path(raw_root,gsub("[^A-Za-z0-9_-]","_",row$source_id[1]),row$endpoint_kind[1])
    page_path <- file.path(folder,sprintf("page-%05d.json",queue$pages_completed[idx]))
    camara_write_json_atomic(list(request_url=url,started_at=format(started,"%Y-%m-%dT%H:%M:%OSZ",tz="UTC"),
      body=body,response_status=result$status,http_status=result$http_status %||% NA_integer_,
      attempts=result$attempts %||% 1L,error=result$error_message %||% NULL,
      snapshot=as.list(snap[1,,drop=FALSE]),terminal=identical(result$status,"succeeded") && is.null(next_url)),page_path)
    if (identical(result$status,"succeeded") && row$endpoint_kind[1]=="relacionadas") {
      related <- camara_enrichment_items(body,"relacionadas")
      if (length(related)) newly_discovered[[length(newly_discovered)+1L]] <-
        parse_camara_propositions(related,snap$snapshot_id)
    }
  }
  if (length(newly_discovered)) {
    propositions <- dplyr::bind_rows(propositions,dplyr::bind_rows(newly_discovered)) |>
      dplyr::distinct(proposition_id,.keep_all=TRUE)
    queue <- camara_add_enrichment_queue_rows(queue,dplyr::bind_rows(newly_discovered))
  }
  saveRDS(queue,queue_path)

  files <- list.files(raw_root,pattern="^page-[0-9]+[.]json$",recursive=TRUE,full.names=TRUE)
  records <- lapply(files,function(f) jsonlite::fromJSON(f,simplifyVector=FALSE))
  records <- Filter(function(x) !is.null(x$snapshot),records)
  snapshot_objects <- lapply(records,function(x) {
    s <- x$snapshot
    if (is.list(s) && is.null(names(s)) && length(s)==1L) s[[1]] else s
  })
  snapshots <- if(length(snapshot_objects)) dplyr::bind_rows(lapply(snapshot_objects,camara_snapshot_row)) |>
    dplyr::distinct(snapshot_id,.keep_all=TRUE) else camara_empty_contract_table("source_snapshots")
  checks <- if(nrow(queue)) data.frame(entity_kind="proposition",entity_id=queue$proposition_id,
    endpoint_kind=queue$endpoint_kind,status=ifelse(queue$status=="running","pending",queue$status),
    snapshot_id=queue$last_snapshot_id,last_checked_at=queue$last_checked_at,reason=queue$reason,
    stringsAsFactors=FALSE) else camara_empty_contract_table("metadata_checks")

  authors <- list(); prop_authors <- list(); themes <- list(); prop_themes <- list(); linked_props <- list()
  phases <- list(); relations <- list(); docs <- list(); prop_docs <- list(); merged_details <- list()
  for (rec in records) {
    request_url <- rec$request_url
    if (!identical(rec$response_status,"succeeded") || is.null(rec$body)) next
    snap_obj <- rec$snapshot
    if (is.list(snap_obj) && is.null(names(snap_obj)) && length(snap_obj)==1L) snap_obj <- snap_obj[[1]]
    snap_id <- snap_obj$snapshot_id
    endpoint <- sub("^.*/proposicoes/[^/]+/?","",sub("[?].*$","",request_url))
    source_id <- sub("^.*?/proposicoes/([^/?]+).*$","\\1",request_url)
    pid <- paste0("camara:prop:",source_id)
    items <- camara_enrichment_items(rec$body,if(nzchar(endpoint)) endpoint else "detail")
    if (!nzchar(endpoint)) {
      if(length(items)) merged_details[[length(merged_details)+1L]] <- parse_camara_propositions(items,snap_id)
      if(length(items) && !is.null(items[[1]]$urlInteiroTeor) && length(items[[1]]$urlInteiroTeor)>0L &&
          !is.na(items[[1]]$urlInteiroTeor[1]) && nzchar(as.character(items[[1]]$urlInteiroTeor[1]))) {
        url <- as.character(items[[1]]$urlInteiroTeor)
        did <- build_document_id("camara","api_v2_inteiro_teor",identity_url=url)
        docs[[length(docs)+1L]] <- data.frame(document_id=did,house="camara",source_document_id=NA_character_,
          source_namespace="api_v2_inteiro_teor",identity_url=url,document_type=as.character(items[[1]]$siglaTipo %||% "unknown"),
          document_type_source_id=as.character(items[[1]]$codTipo %||% NA_character_),legislative_type_id=NA_character_,
          legislative_body="Câmara dos Deputados",normalized_kind="unknown",publication_date=as.Date(NA),
          date_range_start=as.Date(NA),date_range_end=as.Date(NA),date_status="unknown",source_uri=url,
          snapshot_id=snap_id,stringsAsFactors=FALSE)
        prop_docs[[length(prop_docs)+1L]] <- data.frame(proposition_id=pid,document_id=did,document_role="unknown",
          role_status="unknown",role_evidence="urlInteiroTeor da resposta detalhe; papel documental não determinado",
          document_date=as.Date(NA),source_order=NA_integer_,snapshot_id=snap_id,stringsAsFactors=FALSE)
      }
    } else if(endpoint=="autores") {
      x<-parse_camara_authors(items,pid,snap_id); authors[[length(authors)+1L]]<-x$authors; prop_authors[[length(prop_authors)+1L]]<-x$proposition_authors
    } else if(endpoint=="temas") {
      x<-parse_camara_themes(items,pid,snap_id); themes[[length(themes)+1L]]<-x$themes; prop_themes[[length(prop_themes)+1L]]<-x$proposition_themes
    } else if(endpoint=="tramitacoes") {
      phases[[length(phases)+1L]]<-parse_camara_tramitacoes(items,pid,snap_id)
    } else if(endpoint=="relacionadas" && length(items)) {
      related_props<-parse_camara_propositions(items,snap_id)
      linked_props[[length(linked_props)+1L]]<-related_props
      for (i in seq_len(nrow(related_props))) {
        target<-related_props$proposition_id[i]
        relations[[length(relations)+1L]]<-data.frame(relation_id=paste0("camara:rel:",hash_string(paste(pid,target,"related"))),
          source_proposition_id=pid,target_proposition_id=target,relation_type="related",snapshot_id=snap_id,
          source_uri=request_url,grouping_policy="review",stringsAsFactors=FALSE)
      }
    }
  }
  if(length(linked_props)) propositions<-dplyr::bind_rows(propositions,dplyr::bind_rows(linked_props)) |>
    dplyr::distinct(proposition_id,.keep_all=TRUE)
  detail_checks <- list()
  for (rec_index in seq_along(records)) {
    rec <- records[[rec_index]]
    if (!identical(rec$response_status,"succeeded") || is.null(rec$body) ||
        !grepl("/detail/page-[0-9]+[.]json$",gsub("\\\\","/",files[rec_index]))) next
    detail <- rec$body$dados
    snap_obj <- rec$snapshot
    if (is.list(snap_obj) && is.null(names(snap_obj)) && length(snap_obj)==1L) snap_obj <- snap_obj[[1]]
    source_id <- sub("^.*/proposicoes/([^/?]+).*$","\\1",rec$request_url)
    has_link <- !is.null(detail$urlInteiroTeor) && length(detail$urlInteiroTeor)>0L &&
      !is.na(detail$urlInteiroTeor[1]) && nzchar(as.character(detail$urlInteiroTeor[1]))
    detail_checks[[length(detail_checks)+1L]] <- data.frame(
      entity_kind="proposition",entity_id=paste0("camara:prop:",source_id),endpoint_kind="whole_text_link",
      status=if(has_link) "success_nonempty" else "success_empty",snapshot_id=snap_obj$snapshot_id,
      last_checked_at=as.POSIXct(snap_obj$collected_at,tz="UTC"),
      reason=if(has_link) "Campo urlInteiroTeor observado; papel documental ainda não determinado." else
        "Detalhe não forneceu urlInteiroTeor; isso não prova inexistência de documentos no portal ou noutras fontes.",
      stringsAsFactors=FALSE)
  }
  if(length(detail_checks)) checks <- dplyr::bind_rows(checks,dplyr::bind_rows(detail_checks)) |>
    dplyr::distinct(entity_kind,entity_id,endpoint_kind,.keep_all=TRUE)
  if(length(merged_details)) {
    detail_df<-dplyr::bind_rows(merged_details)
    for(i in seq_len(nrow(detail_df))) {
      idx<-match(detail_df$proposition_id[i],propositions$proposition_id)
      if(!is.na(idx)) for(nm in names(detail_df)) if(!is.na(detail_df[[nm]][i]) && !(is.character(detail_df[[nm]][i]) && !nzchar(detail_df[[nm]][i]))) propositions[[nm]][idx]<-detail_df[[nm]][i]
    }
  }
  combine <- function(xs,name) if(length(xs)) dplyr::bind_rows(xs) |> dplyr::distinct(.data[[name]],.keep_all=TRUE) else camara_empty_contract_table(name)
  list(propositions=propositions, queue=queue, source_snapshots=snapshots, metadata_checks=checks,
    authors=combine(authors,"author_id"), proposition_authors=if(length(prop_authors)) dplyr::bind_rows(prop_authors)|>dplyr::distinct(proposition_id,author_id,role,.keep_all=TRUE) else camara_empty_contract_table("proposition_authors"),
    themes=combine(themes,"theme_id"), proposition_themes=if(length(prop_themes)) dplyr::bind_rows(prop_themes)|>dplyr::distinct(proposition_id,theme_id,.keep_all=TRUE) else camara_empty_contract_table("proposition_themes"),
    process_phases=if(length(phases)) dplyr::bind_rows(phases)|>dplyr::distinct(phase_id,.keep_all=TRUE) else camara_empty_contract_table("process_phases"),
    relations=if(length(relations)) dplyr::bind_rows(relations)|>dplyr::distinct(relation_id,.keep_all=TRUE) else camara_empty_contract_table("relations"),
    documents=if(length(docs)) dplyr::bind_rows(docs)|>dplyr::distinct(document_id,.keep_all=TRUE) else camara_empty_contract_table("documents"),
    proposition_documents=if(length(prop_docs)) dplyr::bind_rows(prop_docs)|>dplyr::distinct(proposition_id,document_id,.keep_all=TRUE) else camara_empty_contract_table("proposition_documents"),
    requests_used=used, http_attempts=attempts_used)
}

camara_update_enrichment_coverage <- function(coverage, propositions, queue, listed_propositions=NULL) {
  if (!nrow(coverage) || !nrow(propositions) || !nrow(queue)) return(coverage)
  endpoints <- camara_enrichment_endpoints
  settled <- c("success_nonempty","success_empty","terminal_error")
  for (i in seq_len(nrow(coverage))) {
    yr<-coverage$year[i]; q<-as.integer(sub("^Q","",sub(".*:Q","Q",coverage$segment_id[i])))
    if(is.na(yr)||is.na(q)||!grepl(":Q[1-4]$",coverage$segment_id[i])) next
    w<-generate_quarterly_windows(yr)[[q]]
    ids<-if(!is.null(listed_propositions)) listed_propositions$proposition_id[
      listed_propositions$segment_id==coverage$segment_id[i]] else propositions$proposition_id[
      !is.na(propositions$presentation_date) & propositions$presentation_date>=as.Date(w$start) &
      propositions$presentation_date<=as.Date(w$end)]
    if(!length(ids)) next
    subq<-queue[queue$proposition_id%in%ids & queue$endpoint_kind%in%endpoints,,drop=FALSE]
    done<-sum(vapply(ids,function(pid) {
      mine<-subq[subq$proposition_id==pid,,drop=FALSE]
      states<-setNames(mine$status,mine$endpoint_kind)
      all(endpoints%in%names(states)) && all(states[endpoints]%in%settled)
    },logical(1)))
    coverage$retrieved_count[i]<-as.integer(done)
    if(done<length(ids)) {coverage$inventory_status[i]<-"running";coverage$coverage_status[i]<-"partial";coverage$gap_reason[i]<-"Enriquecimento de endpoints por proposição pendente ou com erro retomável."}
    else {coverage$inventory_status[i]<-"exhausted";coverage$coverage_status[i]<-"closed_with_gaps";coverage$gap_reason[i]<-"Endpoints API suportados processados; reconciliação portal/arquivos e documentos fora da API ainda pendente."}
  }
  coverage
}

camara_listing_ids_by_segment <- function(output_dir, coverage) {
  rows <- list()
  for (i in seq_len(nrow(coverage))) {
    id <- coverage$segment_id[i]
    if (!grepl(":Q[1-4]$",id) || is.na(coverage$year[i])) next
    q <- as.integer(sub(".*:Q","",id)); folder <- file.path(output_dir,"pages",paste0(coverage$year[i],"-Q",q))
    files <- list.files(folder,pattern="^page-[0-9]+[.]json$",full.names=TRUE)
    for (f in files) {
      page <- jsonlite::fromJSON(f,simplifyVector=FALSE)
      items <- page$body$dados %||% list()
      for (item in items) if (!is.null(item$id)) rows[[length(rows)+1L]] <- data.frame(
        segment_id=id,proposition_id=paste0("camara:prop:",as.character(item$id)),stringsAsFactors=FALSE)
    }
  }
  if(length(rows)) dplyr::bind_rows(rows)|>dplyr::distinct(segment_id,proposition_id) else
    data.frame(segment_id=character(),proposition_id=character(),stringsAsFactors=FALSE)
}
