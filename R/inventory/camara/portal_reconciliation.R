# R/inventory/camara/portal_reconciliation.R
# Reconciliação entre Portal Web (proposicoesWeb), API v2 e acervo documental
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

#' Registra um documento oficial do portal com reconciliação e proteção de integridade
#'
#' Cria as entidades normativas em documents, proposition_documents, entity_aliases
#' e metadata_checks quando um documento existe no portal mas dá 404 na API REST.
#'
#' @param portal_doc_id ID oficial no portal (ex: 2422083).
#' @param main_proposition_id ID canônico da proposição principal (ex: camara:prop:2416804).
#' @param doc_type Sigla ou tipo do documento (ex: DVT, Parecer, Emenda).
#' @param doc_role Papel legislativo (ex: vote, opinion, amendment, substitute, initial).
#' @param identity_url URL de acesso/identidade do inteiro teor.
#' @param source_portal_url URL da ficha ou página no portal.
#' @param doc_date Data oficial do documento (Date ou string YYYY-MM-DD).
#' @param api_http_status Status retornado pela API REST (ex: 404).
#' @param snapshot_id Identificador do snapshot.
#' @return Lista com documents, proposition_documents, entity_aliases e metadata_checks.
reconcile_portal_document <- function(portal_doc_id,
                                      main_proposition_id,
                                      doc_type = "DVT",
                                      doc_role = "vote",
                                      identity_url = NULL,
                                      source_portal_url = NULL,
                                      doc_date = NULL,
                                      api_http_status = 404L,
                                      snapshot_id = "camara:snap:portal:2026-10-07") {
  sid <- as.character(portal_doc_id)
  prop_id <- as.character(main_proposition_id)

  if (is.null(identity_url) || nchar(identity_url) == 0) {
    identity_url <- paste0("https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=", sid)
  }
  if (is.null(source_portal_url) || nchar(source_portal_url) == 0) {
    source_portal_url <- paste0("https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=", sid)
  }

  doc_id <- build_document_id("camara", "portal_proposicoes", id_oficial = sid)

  d_date <- if (!is.null(doc_date) && !is.na(doc_date)) as.Date(doc_date) else as.Date(NA)
  date_status <- if (!is.na(d_date)) "verified" else "unknown"

  # Mapeamento do normalized_kind
  norm_kind <- switch(
    tolower(doc_role),
    "vote" = "vote",
    "opinion" = "opinion",
    "report" = "report",
    "amendment" = "amendment",
    "substitute" = "substitute",
    "final_text" = "final_text",
    "initial" = "initial",
    "justification" = "justification",
    "other_legislative"
  )

  # 1. Tabela documents
  doc_df <- data.frame(
    document_id = doc_id,
    house = "camara",
    source_document_id = sid,
    source_namespace = "portal_proposicoes",
    identity_url = identity_url,
    document_type = doc_type,
    document_type_source_id = NA_character_,
    legislative_type_id = NA_character_,
    legislative_body = "Câmara dos Deputados",
    normalized_kind = norm_kind,
    publication_date = d_date,
    date_range_start = as.Date(NA),
    date_range_end = as.Date(NA),
    date_status = date_status,
    source_uri = source_portal_url,
    snapshot_id = as.character(snapshot_id),
    stringsAsFactors = FALSE
  )

  # 2. Tabela proposition_documents
  prop_doc_df <- data.frame(
    proposition_id = prop_id,
    document_id = doc_id,
    document_role = doc_role,
    role_status = "verified",
    role_evidence = paste0("Documento oficial ", doc_type, " registrado no Portal Web da Câmara"),
    document_date = d_date,
    source_order = 1L,
    snapshot_id = as.character(snapshot_id),
    stringsAsFactors = FALSE
  )

  # 3. Tabela entity_aliases
  alias_id <- paste0("camara:alias:portal:", sid)
  aliases_df <- data.frame(
    alias_id = alias_id,
    entity_kind = "document",
    alias_namespace = "portal_proposicoes",
    alias_source_id = sid,
    canonical_entity_id = doc_id,
    evidence_uri = source_portal_url,
    snapshot_id = as.character(snapshot_id),
    status = "verified",
    stringsAsFactors = FALSE
  )

  # 4. Tabela metadata_checks
  check_status <- if (api_http_status == 404L) "terminal_error" else if (api_http_status < 400L) "success_nonempty" else "retryable_error"
  reason_text <- if (api_http_status == 404L) {
    "HTTP 404 na API v2 para peca existente e verificada no portal Web"
  } else {
    paste0("Status HTTP ", api_http_status, " na API v2")
  }

  checks_df <- data.frame(
    entity_kind = "document",
    entity_id = doc_id,
    endpoint_kind = "api_v2_proposicoes_detalhe",
    status = check_status,
    snapshot_id = as.character(snapshot_id),
    last_checked_at = as.POSIXct("2026-10-07 12:00:00", tz = "UTC"),
    reason = reason_text,
    stringsAsFactors = FALSE
  )

  list(
    documents = doc_df,
    proposition_documents = prop_doc_df,
    entity_aliases = aliases_df,
    metadata_checks = checks_df
  )
}

#' Constrói documento para o inteiro teor inicial da proposição
#'
#' @param prop_row Linha da tabela propositions ou lista com dados da proposição.
#' @param snapshot_id Snapshot dos metadados.
#' @return Lista contendo documents e proposition_documents.
create_initial_document <- function(prop_row, snapshot_id) {
  prop_id <- as.character(prop_row$proposition_id)
  whole_url <- as.character(prop_row$whole_text_url)

  if (is.null(whole_url) || is.na(whole_url) || nchar(trimws(whole_url)) == 0) {
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
      proposition_documents = data.frame(
        proposition_id = character(), document_id = character(), document_role = character(),
        role_status = character(), role_evidence = character(), document_date = as.Date(character()),
        source_order = integer(), snapshot_id = character(), stringsAsFactors = FALSE
      )
    ))
  }

  doc_id <- build_document_id("camara", "api_v2_inteiro_teor", identity_url = whole_url)
  pres_date <- if (!is.null(prop_row$presentation_date) && !is.na(prop_row$presentation_date)) as.Date(prop_row$presentation_date) else as.Date(NA)
  date_status <- if (!is.na(pres_date)) "verified" else "unknown"

  doc_df <- data.frame(
    document_id = doc_id,
    house = "camara",
    source_document_id = as.character(prop_row$source_id),
    source_namespace = "api_v2_inteiro_teor",
    identity_url = whole_url,
    document_type = as.character(prop_row$type_code),
    document_type_source_id = as.character(prop_row$type_source_id),
    legislative_type_id = as.character(prop_row$legislative_type_id),
    legislative_body = as.character(prop_row$legislative_body),
    normalized_kind = "initial",
    publication_date = pres_date,
    date_range_start = as.Date(NA),
    date_range_end = as.Date(NA),
    date_status = date_status,
    source_uri = as.character(prop_row$source_uri),
    snapshot_id = as.character(snapshot_id),
    stringsAsFactors = FALSE
  )

  prop_doc_df <- data.frame(
    proposition_id = prop_id,
    document_id = doc_id,
    document_role = "initial",
    role_status = "verified",
    role_evidence = "URL de inteiro teor oficial vinculada à proposição",
    document_date = pres_date,
    source_order = 1L,
    snapshot_id = as.character(snapshot_id),
    stringsAsFactors = FALSE
  )

  list(documents = doc_df, proposition_documents = prop_doc_df)
}
