# R/inventory/camara/historical_collections.R
# Inventário de objetos digitais em coleções históricas oficiais (Diários, Anais, Arquivo)
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/01_INVENTARIO.md

suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))

#' Inventaria edições de publicações históricas (Diários da Câmara e Anais)
#'
#' @param collection_id ID canônico da coleção (ex: camara:col:portal_publicacoes).
#' @param publications_list Lista com metadados de edições/volumes históricos.
#' @param snapshot_id Snapshot dos metadados.
#' @return Lista com data.frame documents e data.frame collection_documents.
inventory_historical_publications <- function(collection_id = "camara:col:portal_publicacoes",
                                               publications_list = list(),
                                               snapshot_id = "camara:snap:pub:2026-10-07") {
  n <- length(publications_list)
  if (n == 0) {
    return(list(
      documents = data.frame(
        document_id = character(), house = character(), source_document_id = character(),
        source_namespace = character(), identity_url = character(), document_type = character(),
        document_type_source_id = character(), legislative_type_id = character(),
        legislative_body = character(), normalized_kind = character(), publication_date = as.Date(character()),
        date_range_start = as.Date(character()), date_range_end = as.Date(character()),
        date_status = character(), source_uri = character(), snapshot_id = character(),
        stringsAsFactors = FALSE
      ),
      collection_documents = data.frame(
        collection_id = character(), document_id = character(), source_catalog_id = character(),
        reference_code = character(), volume_label = character(), issue_label = character(),
        source_order = integer(), snapshot_id = character(), stringsAsFactors = FALSE
      )
    ))
  }

  doc_id_vec <- character(n)
  source_doc_id_vec <- character(n)
  ident_url_vec <- character(n)
  doc_type_vec <- character(n)
  norm_kind_vec <- character(n)
  pub_date_vec <- as.Date(rep(NA, n))
  date_stat_vec <- character(n)
  source_uri_vec <- character(n)

  cat_id_vec <- character(n)
  ref_code_vec <- character(n)
  vol_label_vec <- character(n)
  iss_label_vec <- character(n)
  order_vec <- integer(n)

  for (i in seq_len(n)) {
    pub <- publications_list[[i]]
    sid <- as.character(pub$id)
    source_doc_id_vec[i] <- sid

    url <- if (!is.null(pub$url) && !is.na(pub$url)) as.character(pub$url) else paste0("https://imagem.camara.leg.br/diarios.asp?id=", sid)
    ident_url_vec[i] <- url
    source_uri_vec[i] <- url

    doc_id <- build_document_id("camara", "diarios_anais", id_oficial = sid)
    doc_id_vec[i] <- doc_id

    dtype <- if (!is.null(pub$tipo)) as.character(pub$tipo) else "DIARIO"
    doc_type_vec[i] <- dtype

    nkind <- if (grepl("ANAIS", toupper(dtype))) "annals" else "diary"
    norm_kind_vec[i] <- nkind

    dpub <- if (!is.null(pub$data_publicacao) && !is.na(pub$data_publicacao)) as.Date(pub$data_publicacao) else as.Date(NA)
    pub_date_vec[i] <- dpub
    date_stat_vec[i] <- if (!is.na(dpub)) "verified" else "unknown"

    cat_id_vec[i] <- sid
    ref_code_vec[i] <- if (!is.null(pub$codigo_referencia)) as.character(pub$codigo_referencia) else NA_character_
    vol_label_vec[i] <- if (!is.null(pub$volume)) as.character(pub$volume) else NA_character_
    iss_label_vec[i] <- if (!is.null(pub$edicao)) as.character(pub$edicao) else NA_character_
    order_vec[i] <- as.integer(i)
  }

  docs_df <- data.frame(
    document_id = doc_id_vec,
    house = rep("camara", n),
    source_document_id = source_doc_id_vec,
    source_namespace = rep("diarios_anais", n),
    identity_url = ident_url_vec,
    document_type = doc_type_vec,
    document_type_source_id = rep(NA_character_, n),
    legislative_type_id = rep(NA_character_, n),
    legislative_body = rep("Câmara dos Deputados", n),
    normalized_kind = norm_kind_vec,
    publication_date = pub_date_vec,
    date_range_start = as.Date(NA),
    date_range_end = as.Date(NA),
    date_status = date_stat_vec,
    source_uri = source_uri_vec,
    snapshot_id = rep(as.character(snapshot_id), n),
    stringsAsFactors = FALSE
  )

  col_docs_df <- data.frame(
    collection_id = rep(as.character(collection_id), n),
    document_id = doc_id_vec,
    source_catalog_id = cat_id_vec,
    reference_code = ref_code_vec,
    volume_label = vol_label_vec,
    issue_label = iss_label_vec,
    source_order = order_vec,
    snapshot_id = rep(as.character(snapshot_id), n),
    stringsAsFactors = FALSE
  )

  list(documents = docs_df, collection_documents = col_docs_df)
}

#' Processa itens do Arquivo Histórico diferenciando objetos digitais de descrições puras
#'
#' Descrições sem arquivo digital NÃO geram linhas em documents (são tratadas como lacunas).
#'
#' @param archival_items Lista de itens arquivísticos com has_digital_file (TRUE/FALSE).
#' @param snapshot_id Snapshot dos metadados.
#' @return Lista com documents (apenas os digitalizados), collection_documents e gaps_summary.
inventory_archival_units <- function(archival_items = list(),
                                     snapshot_id = "camara:snap:arq:2026-10-07") {
  col_id <- "camara:col:arquivo_historico"

  digitized_items <- list()
  gaps_count <- 0L

  for (it in archival_items) {
    has_file <- isTRUE(it$has_digital_file)
    if (has_file) {
      digitized_items[[length(digitized_items) + 1]] <- it
    } else {
      # Descrição sem arquivo: contabilizada como lacuna, nunca como documento de treino
      gaps_count <- gaps_count + 1L
    }
  }

  res <- inventory_historical_publications(
    collection_id = col_id,
    publications_list = digitized_items,
    snapshot_id = snapshot_id
  )

  list(
    documents = res$documents,
    collection_documents = res$collection_documents,
    non_digitized_gaps_count = gaps_count
  )
}
