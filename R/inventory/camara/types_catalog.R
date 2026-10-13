# R/inventory/camara/types_catalog.R
# Descoberta, catalogação e mapeamento da taxonomia de tipos legislativos da Câmara dos Deputados
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/01_INVENTARIO.md

suppressPackageStartupMessages({
  library(jsonlite)
  library(dplyr)
  library(httr2)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))

#' Carrega os tipos brutos da referência da Câmara
#'
#' @param reference_path Caminho opcional para arquivo JSON local.
#' @param base_api_url URL base opcional da API v2.
#' @return Lista com os registros brutos do endpoint /referencias/proposicoes/siglaTipo.
load_camara_raw_types <- function(reference_path = NULL, base_api_url = NULL) {
  # 1. Se caminho informado existe, carrega
  if (!is.null(reference_path) && file.exists(reference_path)) {
    content <- jsonlite::fromJSON(reference_path, simplifyVector = FALSE)
    if ("dados" %in% names(content)) {
      return(content$dados)
    }
    return(content)
  }

  # 2. Caminho padrão local do projeto
  default_local <- file.path(repo_root, "R", "inventory", "camara", "types_reference.json")
  if (file.exists(default_local)) {
    content <- jsonlite::fromJSON(default_local, simplifyVector = FALSE)
    if ("dados" %in% names(content)) {
      return(content$dados)
    }
    return(content)
  }

  # 3. Fallback online se URL base configurada
  if (!is.null(base_api_url)) {
    endpoint <- paste0(sub("/+$", "", base_api_url), "/referencias/proposicoes/siglaTipo")
    tryCatch({
      req <- request(endpoint) %>%
        req_headers("Accept" = "application/json") %>%
        req_user_agent("LLM-Legislativo/2.0") %>%
        req_timeout(15)
      resp <- req_perform(req)
      if (resp_status(resp) == 200) {
        body <- resp_body_json(resp)
        if ("dados" %in% names(body)) {
          return(body$dados)
        }
        return(body)
      }
    }, error = function(e) {
      warning("Falha ao consultar API online para tipos: ", conditionMessage(e))
    })
  }

  stop("Não foi possível carregar o catálogo de tipos legislativos da Câmara.")
}

#' Classifica um tipo legislativo em família normalizada, entidade e status
#'
#' @param cod Código numérico oficial (string).
#' @param sigla Sigla oficial ou vazia.
#' @param nome Nome textual descritivo.
#' @param descricao Descrição opcional.
#' @return Lista contendo normalized_family, entity_kind e mapping_status.
classify_camara_type <- function(cod, sigla, nome, descricao = "") {
  sigla_clean <- toupper(trimws(ifelse(is.null(sigla) || is.na(sigla), "", as.character(sigla))))
  nome_clean <- toupper(trimws(ifelse(is.null(nome) || is.na(nome), "", as.character(nome))))
  desc_clean <- toupper(trimws(ifelse(is.null(descricao) || is.na(descricao), "", as.character(descricao))))

  # Casos com sigla vazia (agrupamentos de catálogo / títulos de seção)
  if (nchar(sigla_clean) == 0) {
    if (grepl("PARECER|MANIFESTA|REDAÇÃO FINAL", nome_clean)) {
      return(list(normalized_family = "AGRUPAMENTO_PARECERES", entity_kind = "collection", mapping_status = "proposed"))
    } else if (grepl("EMENDA", nome_clean)) {
      return(list(normalized_family = "AGRUPAMENTO_EMENDAS", entity_kind = "collection", mapping_status = "proposed"))
    } else if (grepl("REQUERIMENTO", nome_clean)) {
      return(list(normalized_family = "AGRUPAMENTO_REQUERIMENTOS", entity_kind = "collection", mapping_status = "proposed"))
    } else if (grepl("PROPOSIÇÕES", nome_clean)) {
      return(list(normalized_family = "AGRUPAMENTO_PROPOSICOES", entity_kind = "collection", mapping_status = "proposed"))
    } else {
      return(list(normalized_family = "AGRUPAMENTO_LEGADO", entity_kind = "collection", mapping_status = "proposed"))
    }
  }

  # Proposições Principais Normativas
  if (sigla_clean == "PL") {
    return(list(normalized_family = "PL", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "PLP") {
    return(list(normalized_family = "PLP", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "PEC") {
    return(list(normalized_family = "PEC", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean %in% c("PDC", "PDL")) {
    return(list(normalized_family = "PDL", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "MPV") {
    return(list(normalized_family = "MPV", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "PRC") {
    return(list(normalized_family = "PRC", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "VET") {
    return(list(normalized_family = "VET", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "INC") {
    return(list(normalized_family = "INC", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "RIC") {
    return(list(normalized_family = "RIC", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "CON") {
    return(list(normalized_family = "CON", entity_kind = "proposition", mapping_status = "verified"))
  } else if (grepl("^REQ", sigla_clean)) {
    return(list(normalized_family = "REQ", entity_kind = "proposition", mapping_status = "verified"))
  }

  # Peças Documentais e Acessórias
  if (sigla_clean %in% c("SBE", "SUB", "SSP", "SBE-A", "SBR") || grepl("SUBEMENDA", nome_clean)) {
    return(list(normalized_family = "SUBEMENDA", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean %in% c("EMC", "EMP", "EMS", "EMV", "EMR", "EMD", "EAP") || grepl("EMENDA", nome_clean)) {
    return(list(normalized_family = "EMENDA", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean %in% c("SBT") || grepl("SUBSTITUTIVO", nome_clean)) {
    return(list(normalized_family = "SUBSTITUTIVO", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean %in% c("PRL", "PRR", "PAR") || grepl("PARECER|RELATÓRIO", nome_clean)) {
    return(list(normalized_family = "PARECER", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean %in% c("RDF", "RED") || grepl("REDAÇÃO FINAL", nome_clean)) {
    return(list(normalized_family = "REDACAO_FINAL", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean %in% c("DVT", "VTV", "VTP") || grepl("DECLARAÇÃO DE VOTO|VOTO", nome_clean)) {
    return(list(normalized_family = "VOTO", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean %in% c("DSP", "DES") || grepl("DESPACHO", nome_clean)) {
    return(list(normalized_family = "DESPACHO", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean == "OF" || grepl("OFÍCIO", nome_clean)) {
    return(list(normalized_family = "OFICIO", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean %in% c("MSC", "MSG") || grepl("MENSAGEM", nome_clean)) {
    return(list(normalized_family = "MENSAGEM", entity_kind = "document", mapping_status = "verified"))
  } else if (sigla_clean %in% c("REC", "RCP") || grepl("RECURSO", nome_clean)) {
    return(list(normalized_family = "RECURSO", entity_kind = "proposition", mapping_status = "verified"))
  } else if (sigla_clean == "DOC" || grepl("DOCUMENTO", nome_clean)) {
    return(list(normalized_family = "DOC", entity_kind = "document", mapping_status = "verified"))
  }

  # Fallback preservando identidade
  list(
    normalized_family = sigla_clean,
    entity_kind = "proposition",
    mapping_status = "proposed"
  )
}

#' Constrói a tabela legislative_types em estrita conformidade com o esquema Arrow
#'
#' @param raw_items Lista opcional com registros brutos de siglaTipo.
#' @param snapshot_id Snapshot de captura dos metadados.
#' @return data.frame com o esquema legislative_types normativo.
build_legislative_types <- function(raw_items = NULL, snapshot_id = "camara:snap:types:2026-10-07") {
  if (is.null(raw_items)) {
    raw_items <- load_camara_raw_types()
  }

  n <- length(raw_items)
  if (n == 0) {
    stop("Lista de tipos brutos da Câmara está vazia.")
  }

  legislative_type_id_vec <- character(n)
  house_vec <- rep("camara", n)
  source_namespace_vec <- rep("api_v2_referencias", n)
  type_source_id_vec <- character(n)
  type_code_vec <- character(n)
  type_label_vec <- character(n)
  entity_kind_vec <- character(n)
  normalized_family_vec <- character(n)
  mapping_status_vec <- character(n)
  snapshot_id_vec <- rep(as.character(snapshot_id), n)

  for (i in seq_len(n)) {
    item <- raw_items[[i]]
    cod <- as.character(item$cod)
    sigla <- if (is.null(item$sigla) || is.na(item$sigla)) "" else trimws(as.character(item$sigla))
    nome <- if (is.null(item$nome) || is.na(item$nome)) "" else trimws(as.character(item$nome))
    desc <- if (is.null(item$descricao) || is.na(item$descricao)) "" else trimws(as.character(item$descricao))

    # Identificador determinístico: namespace camara:type:<cod>
    legislative_type_id_vec[i] <- paste0("camara:type:", cod)
    type_source_id_vec[i] <- cod
    type_code_vec[i] <- if (nchar(sigla) > 0) sigla else NA_character_
    type_label_vec[i] <- if (nchar(nome) > 0) nome else paste0("Tipo oficial cod ", cod)

    classification <- classify_camara_type(cod, sigla, nome, desc)
    entity_kind_vec[i] <- classification$entity_kind
    normalized_family_vec[i] <- classification$normalized_family
    mapping_status_vec[i] <- classification$mapping_status
  }

  data.frame(
    legislative_type_id = legislative_type_id_vec,
    house = house_vec,
    source_namespace = source_namespace_vec,
    type_source_id = type_source_id_vec,
    type_code = type_code_vec,
    type_label = type_label_vec,
    entity_kind = entity_kind_vec,
    normalized_family = normalized_family_vec,
    mapping_status = mapping_status_vec,
    snapshot_id = snapshot_id_vec,
    stringsAsFactors = FALSE
  )
}
