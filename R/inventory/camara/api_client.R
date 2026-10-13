# R/inventory/camara/api_client.R
# Cliente e adaptadores de paginação e extração de entidades para a API v2 da Câmara
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/01_INVENTARIO.md

suppressPackageStartupMessages({
  library(httr2)
  library(jsonlite)
  library(dplyr)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))
source(file.path(repo_root, "R", "inventory", "common", "http_client.R"))

#' Gera janelas trimestrais de pesquisa para evitar HTTP 400 na API v2
#'
#' @param year Ano inteiro para geração das 4 janelas.
#' @return Lista de 4 listas com start_date e end_date.
generate_quarterly_windows <- function(year) {
  yr <- as.integer(year)
  list(
    list(quarter = "Q1", start = sprintf("%04d-01-01", yr), end = sprintf("%04d-03-31", yr)),
    list(quarter = "Q2", start = sprintf("%04d-04-01", yr), end = sprintf("%04d-06-30", yr)),
    list(quarter = "Q3", start = sprintf("%04d-07-01", yr), end = sprintf("%04d-09-30", yr)),
    list(quarter = "Q4", start = sprintf("%04d-10-01", yr), end = sprintf("%04d-12-31", yr))
  )
}

#' Realiza paginação resiliente na API da Câmara seguindo os links HATEOAS rel="next"
#'
#' @param initial_url URL completa inicial com query params.
#' @param max_pages Número máximo de páginas a seguir.
#' @param request_fn Função opcional para mockar chamadas HTTP (usada em testes).
#' @return Lista com raw_items (todos os dados concatenados), snapshots e pagination_complete.
paginate_camara_api <- function(initial_url, max_pages = 50, request_fn = NULL,
                                on_page = NULL) {
  current_url <- initial_url
  page_count <- 0
  all_items <- list()
  snapshots <- list()
  complete <- FALSE

  while (!is.null(current_url) && page_count < max_pages) {
    page_count <- page_count + 1

    # Executar requisição real ou mock
    if (!is.null(request_fn)) {
      req_result <- request_fn(current_url, page_count)
    } else {
      req_result <- perform_resilient_request(current_url)
    }

    if (req_result$status != "succeeded") {
      # Falha na requisição: registrar e parar
      break
    }

    # Extrair corpo JSON
    body <- if (!is.null(req_result$body)) {
      req_result$body
    } else if (!is.null(req_result$response)) {
      resp_body_json(req_result$response)
    } else {
      list(dados = list(), links = list())
    }

    items <- if ("dados" %in% names(body)) body$dados else list()
    links <- if ("links" %in% names(body)) body$links else list()

    payload_str <- jsonlite::toJSON(body, auto_unbox = TRUE)
    snap_id <- paste0("camara:snap:", hash_string(paste0(current_url, payload_str)))

    snapshots[[length(snapshots) + 1]] <- list(
      snapshot_id = snap_id,
      house = "camara",
      source_kind = "api",
      request_url = current_url,
      query_json = as.character(jsonlite::toJSON(list(page = page_count), auto_unbox = TRUE)),
      collected_at = if (!is.null(req_result$finished_at)) req_result$finished_at else Sys.time(),
      http_status = as.integer(req_result$http_status),
      payload_sha256 = hash_string(payload_str),
      raw_path = NA_character_,
      pagination_complete = FALSE,
      source_schema_version = "0.4.344",
      license_evidence_id = "camara:use:dados_abertos_politica"
    )

    if (length(items) > 0) {
      all_items <- c(all_items, items)
    }

    # Buscar link rel="next"
    next_url <- NULL
    if (length(links) > 0) {
      for (lk in links) {
        if (!is.null(lk$rel) && lk$rel == "next") {
          next_url <- lk$href
          break
        }
      }
    }

    # A page with zero records is not evidence that a query is exhausted when
    # the server still advertises a next page.
    terminal_page <- is.null(next_url)
    if (is.function(on_page)) {
      on_page(list(
        page = page_count, request_url = current_url, body = body,
        snapshot = snapshots[[length(snapshots)]], next_url = next_url,
        terminal = terminal_page
      ))
    }

    if (terminal_page) {
      complete <- TRUE
      break
    }

    current_url <- next_url
  }

  if (length(snapshots) > 0 && complete) {
    snapshots[[length(snapshots)]]$pagination_complete <- TRUE
  }

  list(
    raw_items = all_items,
    snapshots = snapshots,
    pagination_complete = complete,
    pages_read = page_count
  )
}

#' Converte registros brutos da API v2 em data.frame no schema propositions
#'
#' @param raw_items Lista de itens brutos da API v2 /proposicoes.
#' @param snapshot_id Snapshot pai dos metadados.
#' @return data.frame estritamente compatível com o schema Arrow propositions.
parse_camara_propositions <- function(raw_items, snapshot_id) {
  n <- length(raw_items)
  if (n == 0) {
    # Retorna data.frame vazio com tipos corretos
    return(data.frame(
      proposition_id = character(),
      house = character(),
      source_id = character(),
      type_code = character(),
      type_source_id = character(),
      type_label = character(),
      legislative_type_id = character(),
      source_namespace = character(),
      number = integer(),
      numbering_year = integer(),
      number_raw = character(),
      identifier_label = character(),
      presentation_date = as.Date(character()),
      presentation_raw = character(),
      origin_house = character(),
      legislative_body = character(),
      title = character(),
      summary = character(),
      source_uri = character(),
      whole_text_url = character(),
      snapshot_id = character(),
      cohort_status = character(),
      cohort_reason = character(),
      stringsAsFactors = FALSE
    ))
  }

  prop_id_vec <- character(n)
  source_id_vec <- character(n)
  type_code_vec <- character(n)
  type_source_id_vec <- character(n)
  type_label_vec <- character(n)
  leg_type_id_vec <- character(n)
  source_ns_vec <- vapply(raw_items, function(it) {
    ns <- it$source_namespace
    if (is.null(ns) || length(ns) == 0L || is.na(ns[1]) || !nzchar(as.character(ns[1]))) "api_v2" else as.character(ns[1])
  }, character(1))
  num_vec <- integer(n)
  num_yr_vec <- integer(n)
  num_raw_vec <- character(n)
  ident_label_vec <- character(n)
  pres_date_vec <- as.Date(rep(NA, n))
  pres_raw_vec <- character(n)
  origin_house_vec <- rep(NA_character_, n)
  leg_body_vec <- rep("Câmara dos Deputados", n)
  title_vec <- rep(NA_character_, n)
  summary_vec <- character(n)
  source_uri_vec <- character(n)
  whole_text_vec <- character(n)
  snapshot_id_vec <- rep(as.character(snapshot_id), n)
  cohort_status_vec <- rep("candidate", n)
  cohort_reason_vec <- rep("Captura oficial API v2 Câmara", n)

  for (i in seq_len(n)) {
    it <- raw_items[[i]]
    sid <- as.character(it$id)
    source_id_vec[i] <- sid
    prop_id_vec[i] <- paste0("camara:prop:", sid)

    tcode <- if (!is.null(it$siglaTipo) && !is.na(it$siglaTipo)) trimws(as.character(it$siglaTipo)) else NA_character_
    type_code_vec[i] <- tcode

    tsid <- if (!is.null(it$codTipo) && !is.na(it$codTipo)) as.character(it$codTipo) else NA_character_
    type_source_id_vec[i] <- tsid
    leg_type_id_vec[i] <- if (!is.na(tsid) && nchar(tsid) > 0) paste0("camara:type:", tsid) else NA_character_

    tlabel <- if (!is.null(it$descricaoTipo) && !is.na(it$descricaoTipo)) trimws(as.character(it$descricaoTipo)) else tcode
    type_label_vec[i] <- if (!is.na(tlabel) && nchar(tlabel) > 0) tlabel else "Tipo desconhecido"

    num <- if (!is.null(it$numero) && !is.na(it$numero)) as.integer(it$numero) else NA_integer_
    num_vec[i] <- num
    num_raw_vec[i] <- if (!is.na(num)) as.character(num) else NA_character_

    yr <- if (!is.null(it$ano) && !is.na(it$ano)) as.integer(it$ano) else NA_integer_
    num_yr_vec[i] <- yr

    ident_label_vec[i] <- if (!is.na(tcode) && !is.na(num) && !is.na(yr)) {
      paste0(tcode, " ", num, "/", yr)
    } else {
      paste0("Prop ", sid)
    }

    # Data de apresentação
    raw_date <- if (!is.null(it$dataApresentacao) && !is.na(it$dataApresentacao)) as.character(it$dataApresentacao) else NA_character_
    pres_raw_vec[i] <- raw_date
    if (!is.na(raw_date) && nchar(raw_date) >= 10) {
      pres_date_vec[i] <- as.Date(substr(raw_date, 1, 10))
    }

    summary_vec[i] <- if (!is.null(it$ementa) && !is.na(it$ementa)) as.character(it$ementa) else NA_character_
    source_uri_vec[i] <- if (!is.null(it$uri) && !is.na(it$uri)) as.character(it$uri) else paste0("https://dadosabertos.camara.leg.br/api/v2/proposicoes/", sid)
    whole_text_vec[i] <- if (!is.null(it$urlInteiroTeor) && !is.na(it$urlInteiroTeor)) as.character(it$urlInteiroTeor) else NA_character_
  }

  data.frame(
    proposition_id = prop_id_vec,
    house = rep("camara", n),
    source_id = source_id_vec,
    type_code = type_code_vec,
    type_source_id = type_source_id_vec,
    type_label = type_label_vec,
    legislative_type_id = leg_type_id_vec,
    source_namespace = source_ns_vec,
    number = num_vec,
    numbering_year = num_yr_vec,
    number_raw = num_raw_vec,
    identifier_label = ident_label_vec,
    presentation_date = pres_date_vec,
    presentation_raw = pres_raw_vec,
    origin_house = origin_house_vec,
    legislative_body = leg_body_vec,
    title = title_vec,
    summary = summary_vec,
    source_uri = source_uri_vec,
    whole_text_url = whole_text_vec,
    snapshot_id = snapshot_id_vec,
    cohort_status = cohort_status_vec,
    cohort_reason = cohort_reason_vec,
    stringsAsFactors = FALSE
  )
}

#' Converte autores de uma proposição em tabelas authors e proposition_authors
#'
#' @param raw_authors Lista de autores retornados por /proposicoes/{id}/autores.
#' @param proposition_id Identificador canônico da proposição (ex: camara:prop:123).
#' @param snapshot_id Snapshot dos metadados.
#' @return Lista contendo data.frame authors e data.frame proposition_authors.
parse_camara_authors <- function(raw_authors, proposition_id, snapshot_id) {
  n <- length(raw_authors)
  if (n == 0) {
    return(list(
      authors = data.frame(
        author_id = character(), house = character(), source_id = character(),
        name = character(), author_type = character(), source_uri = character(),
        snapshot_id = character(), stringsAsFactors = FALSE
      ),
      proposition_authors = data.frame(
        proposition_id = character(), author_id = character(), role = character(),
        is_proponent = logical(), signature_order = integer(), snapshot_id = character(),
        stringsAsFactors = FALSE
      )
    ))
  }

  author_id_vec <- character(n)
  house_vec <- rep("camara", n)
  source_id_vec <- character(n)
  name_vec <- character(n)
  author_type_vec <- character(n)
  source_uri_vec <- character(n)

  prop_id_vec <- rep(as.character(proposition_id), n)
  role_vec <- character(n)
  is_prop_vec <- logical(n)
  sig_order_vec <- integer(n)

  for (i in seq_len(n)) {
    aut <- raw_authors[[i]]
    nm <- if (!is.null(aut$nome) && !is.na(aut$nome)) trimws(as.character(aut$nome)) else "Autor não identificado"
    name_vec[i] <- nm

    atype <- if (!is.null(aut$tipo) && !is.na(aut$tipo)) trimws(as.character(aut$tipo)) else "unknown"
    author_type_vec[i] <- atype

    s_uri <- if (!is.null(aut$uri) && !is.na(aut$uri)) as.character(aut$uri) else NA_character_
    source_uri_vec[i] <- s_uri

    # Extrair source_id numérico de /deputados/{id} ou usar codTipoAutor
    sid <- NA_character_
    if (!is.na(s_uri) && grepl("/deputados/(\\d+)", s_uri)) {
      sid <- sub(".*/deputados/(\\d+).*", "\\1", s_uri)
    } else if (!is.null(aut$codTipoAutor) && !is.na(aut$codTipoAutor)) {
      sid <- as.character(aut$codTipoAutor)
    }
    source_id_vec[i] <- sid

    aid <- if (!is.na(sid) && nchar(sid) > 0) {
      paste0("camara:author:", sid)
    } else {
      paste0("camara:author:local:", hash_string(paste0("camara:", nm)))
    }
    author_id_vec[i] <- aid

    is_prop <- if (!is.null(aut$proponente) && !is.na(aut$proponente)) (as.integer(aut$proponente) == 1) else TRUE
    is_prop_vec[i] <- is_prop
    role_vec[i] <- if (is_prop) "proponent" else "signatory"

    sorder <- if (!is.null(aut$ordemAssinatura) && !is.na(aut$ordemAssinatura)) as.integer(aut$ordemAssinatura) else as.integer(i)
    sig_order_vec[i] <- sorder
  }

  authors_df <- data.frame(
    author_id = author_id_vec,
    house = house_vec,
    source_id = source_id_vec,
    name = name_vec,
    author_type = author_type_vec,
    source_uri = source_uri_vec,
    snapshot_id = rep(as.character(snapshot_id), n),
    stringsAsFactors = FALSE
  ) %>% distinct(author_id, .keep_all = TRUE)

  prop_authors_df <- data.frame(
    proposition_id = prop_id_vec,
    author_id = author_id_vec,
    role = role_vec,
    is_proponent = is_prop_vec,
    signature_order = sig_order_vec,
    snapshot_id = rep(as.character(snapshot_id), n),
    stringsAsFactors = FALSE
  ) %>% distinct(proposition_id, author_id, role, .keep_all = TRUE)

  list(authors = authors_df, proposition_authors = prop_authors_df)
}

#' Converte temas de uma proposição em tabelas themes e proposition_themes
#'
#' @param raw_themes Lista de temas retornados por /proposicoes/{id}/temas.
#' @param proposition_id Identificador da proposição.
#' @param snapshot_id Snapshot dos metadados.
#' @return Lista contendo data.frame themes e data.frame proposition_themes.
parse_camara_themes <- function(raw_themes, proposition_id, snapshot_id) {
  n <- length(raw_themes)
  if (n == 0) {
    return(list(
      themes = data.frame(
        theme_id = character(), house = character(), source_id = character(),
        name = character(), snapshot_id = character(), stringsAsFactors = FALSE
      ),
      proposition_themes = data.frame(
        proposition_id = character(), theme_id = character(), relevance = character(),
        snapshot_id = character(), stringsAsFactors = FALSE
      )
    ))
  }

  theme_id_vec <- character(n)
  source_id_vec <- character(n)
  name_vec <- character(n)
  relevance_vec <- character(n)

  for (i in seq_len(n)) {
    th <- raw_themes[[i]]
    sid <- if (!is.null(th$codTema) && !is.na(th$codTema)) as.character(th$codTema) else as.character(i)
    source_id_vec[i] <- sid
    theme_id_vec[i] <- paste0("camara:theme:", sid)

    nm <- if (!is.null(th$tema) && !is.na(th$tema)) trimws(as.character(th$tema)) else paste0("Tema ", sid)
    name_vec[i] <- nm

    rel <- if (!is.null(th$relevancia) && !is.na(th$relevancia)) as.character(th$relevancia) else NA_character_
    relevance_vec[i] <- rel
  }

  themes_df <- data.frame(
    theme_id = theme_id_vec,
    house = rep("camara", n),
    source_id = source_id_vec,
    name = name_vec,
    snapshot_id = rep(as.character(snapshot_id), n),
    stringsAsFactors = FALSE
  ) %>% distinct(theme_id, .keep_all = TRUE)

  prop_themes_df <- data.frame(
    proposition_id = rep(as.character(proposition_id), n),
    theme_id = theme_id_vec,
    relevance = relevance_vec,
    snapshot_id = rep(as.character(snapshot_id), n),
    stringsAsFactors = FALSE
  ) %>% distinct(proposition_id, theme_id, .keep_all = TRUE)

  list(themes = themes_df, proposition_themes = prop_themes_df)
}

#' Converte tramitações da API em fases de processo (process_phases)
#'
#' @param raw_tramitacoes Lista retornada por /proposicoes/{id}/tramitacoes.
#' @param process_prop_id Identificador da proposição principal (ex: camara:prop:123).
#' @param snapshot_id Snapshot dos metadados.
#' @return data.frame compatível com process_phases.
parse_camara_tramitacoes <- function(raw_tramitacoes, process_prop_id, snapshot_id) {
  n <- length(raw_tramitacoes)
  if (n == 0) {
    return(data.frame(
      phase_id = character(), process_proposition_id = character(), house = character(),
      source_namespace = character(), source_phase_id = character(), phase_kind = character(),
      legislative_body = character(), committee_source_id = character(), number_raw = character(),
      type_code = character(), numbering_year = integer(), date_start = as.Date(character()),
      date_end = as.Date(character()), source_uri = character(), snapshot_id = character(),
      stringsAsFactors = FALSE
    ))
  }

  phase_id_vec <- character(n)
  source_phase_id_vec <- character(n)
  phase_kind_vec <- character(n)
  leg_body_vec <- character(n)
  date_start_vec <- as.Date(rep(NA, n))
  num_year_vec <- integer(n)
  source_uri_vec <- character(n)

  for (i in seq_len(n)) {
    tr <- raw_tramitacoes[[i]]
    seq_id <- if (!is.null(tr$sequencia) && !is.na(tr$sequencia)) as.character(tr$sequencia) else as.character(i)
    source_phase_id_vec[i] <- seq_id
    phase_id_vec[i] <- paste0("camara:phase:tramitacao:", sub("camara:prop:", "", process_prop_id), ":", seq_id)

    org <- if (!is.null(tr$siglaOrgao) && !is.na(tr$siglaOrgao)) trimws(as.character(tr$siglaOrgao)) else "Mesa Diretora"
    leg_body_vec[i] <- org

    dhora <- if (!is.null(tr$dataHora) && !is.na(tr$dataHora)) as.character(tr$dataHora) else NA_character_
    if (!is.na(dhora) && nchar(dhora) >= 10) {
      date_start_vec[i] <- as.Date(substr(dhora, 1, 10))
      num_year_vec[i] <- as.integer(substr(dhora, 1, 4))
    } else {
      num_year_vec[i] <- NA_integer_
    }

    desc <- if (!is.null(tr$descricaoTramitacao)) toupper(as.character(tr$descricaoTramitacao)) else ""
    phase_kind_vec[i] <- if (grepl("APRESENTAÇÃO|INICIAL", desc)) {
      "initiating"
    } else if (grepl("PARECER|RELATOR", desc)) {
      "reviewing"
    } else if (grepl("EMENDA", desc)) {
      "amendments"
    } else if (grepl("SUBSTITUTIVO", desc)) {
      "substitute"
    } else {
      "other"
    }

    source_uri_vec[i] <- if (!is.null(tr$url) && !is.na(tr$url)) as.character(tr$url) else paste0("https://dadosabertos.camara.leg.br/api/v2/proposicoes/", sub("camara:prop:", "", process_prop_id))
  }

  data.frame(
    phase_id = phase_id_vec,
    process_proposition_id = rep(as.character(process_prop_id), n),
    house = rep("camara", n),
    source_namespace = rep("api_v2_tramitacoes", n),
    source_phase_id = source_phase_id_vec,
    phase_kind = phase_kind_vec,
    legislative_body = leg_body_vec,
    committee_source_id = rep(NA_character_, n),
    number_raw = rep(NA_character_, n),
    type_code = rep(NA_character_, n),
    numbering_year = num_year_vec,
    date_start = date_start_vec,
    date_end = rep(as.Date(NA), n),
    source_uri = source_uri_vec,
    snapshot_id = rep(as.character(snapshot_id), n),
    stringsAsFactors = FALSE
  )
}
