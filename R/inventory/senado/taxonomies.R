# R/inventory/senado/taxonomies.R
# Descoberta, taxonomia e mapeamento normativo de tipos legislativos do Senado
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0) e docs/subagents/10_SENADO.md

suppressPackageStartupMessages({
  library(dplyr)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))

# Mapeamento determinístico de siglas para famílias normativas normalizadas
map_sigla_to_family <- function(sigla, descricao = "") {
  s <- toupper(trimws(sigla))
  d <- tolower(trimws(descricao))

  if (s %in% c("PL", "PLS", "PLC")) return("initial_bill")
  if (s %in% c("PLP", "PLPN", "PLPV")) return("complementary_bill")
  if (s %in% c("PEC")) return("constitutional_amendment")
  if (s %in% c("PDL", "PDS", "PDC", "PDN", "PDR")) return("legislative_decree")
  if (s %in% c("PRS", "PRN", "PDA", "PRC")) return("resolution")
  if (s %in% c("MPV")) return("provisional_measure")
  if (s %in% c("EMC", "EMS", "EMENDA")) return("amendment")
  if (s %in% c("SCD", "SLS", "SUB")) return("substitute")
  if (s %in% c("PAR", "P.S", "REL", "PARECER")) return("opinion")
  if (s %in% c("RQS", "REQ", "R.C", "R.S", "REQUERIMENTO")) return("request")
  if (s %in% c("MSG", "MCN", "MSF")) return("message")
  if (s %in% c("OF", "OFS", "OF.", "OFI")) return("official_letter")
  if (s %in% c("INS", "INC")) return("indication")
  if (s %in% c("REP")) return("representation")
  if (s %in% c("CON")) return("consultation")
  if (s %in% c("ADF", "PDF")) return("df_bill")
  if (s %in% c("VET")) return("veto")
  if (s %in% c("PFS")) return("fiscal_control_proposal")
  if (grepl("projeto de lei complementar", d)) return("complementary_bill")
  if (grepl("projeto de lei", d)) return("initial_bill")
  if (grepl("emenda à constituição", d)) return("constitutional_amendment")
  if (grepl("decreto legislativo", d)) return("legislative_decree")
  if (grepl("resolução", d)) return("resolution")
  if (grepl("medida provisória", d)) return("provisional_measure")
  if (grepl("requerimento", d)) return("request")
  if (grepl("parecer", d)) return("opinion")
  if (grepl("aviso", d)) return("notice")
  if (grepl("ato", d)) return("administrative_act")

  "other_legislative"
}

# Mapeamento determinístico de tipo de documento para normalized_kind do contrato
map_doc_type_to_normalized_kind <- function(sigla_tipo, descricao_tipo = "") {
  st <- toupper(trimws(sigla_tipo))
  dt <- tolower(trimws(descricao_tipo))

  if (grepl("PROJETO_LEI|AVULSO_INICIAL|TEXTO_INICIAL|PROPOSICAO", st) || grepl("projeto de lei|inicial", dt)) {
    return("initial")
  }
  if (grepl("EMENDA|SUBEMENDA", st) || grepl("emenda", dt)) {
    return("amendment")
  }
  if (grepl("RELATORIO", st) || grepl("relatório", dt)) {
    return("report")
  }
  if (grepl("PARECER", st) || grepl("parecer", dt)) {
    return("opinion")
  }
  if (grepl("VOTO", st) || grepl("voto", dt)) {
    return("vote")
  }
  if (grepl("SUBSTITUTIVO", st) || grepl("substitutivo", dt)) {
    return("substitute")
  }
  if (grepl("REDACAO_FINAL", st) || grepl("redação final", dt)) {
    return("final_text")
  }
  if (grepl("JUSTIFICATIVA|EXPOSICAO_MOTIVOS", st) || grepl("justificativa|exposição de motivos", dt)) {
    return("justification")
  }
  if (grepl("NOTA_TAQUIGRAFICA|DISCURSO|PRONUNCIAMENTO", st) || grepl("taquigráfica|discurso|pronunciamento", dt)) {
    return("session_record")
  }
  if (grepl("DIARIO|BOLETIM", st) || grepl("diário", dt)) {
    return("diary")
  }
  if (grepl("ANAIS", st) || grepl("anais", dt)) {
    return("annals")
  }
  if (grepl("ANEXO", st) || grepl("anexo", dt)) {
    return("annex")
  }

  "other_legislative"
}

# Mapeamento determinístico para document_role de proposition_documents
map_doc_type_to_document_role <- function(sigla_tipo, descricao_tipo = "", is_initial = FALSE) {
  if (is_initial) return("initial")
  kind <- map_doc_type_to_normalized_kind(sigla_tipo, descricao_tipo)
  if (kind == "initial") return("initial")
  if (kind == "amendment") return("amendment")
  if (kind == "report") return("report")
  if (kind == "opinion") return("opinion")
  if (kind == "vote") return("vote")
  if (kind == "substitute") return("substitute")
  if (kind == "final_text") return("final_text")
  if (kind == "justification") return("justification")
  if (kind == "annex") return("associated")

  "associated"
}

# Função principal de descoberta e estruturação de taxonomias
discover_senado_taxonomies <- function(client) {
  # 1. Siglas de Processos (/processo/siglas)
  resp_siglas <- client$request("/processo/siglas", accept = "application/json")
  siglas_data <- resp_siglas$data
  snap_siglas_id <- resp_siglas$snapshot$snapshot_id
  # Preserve o payload original do catálogo para planejar fatias temporais sem
  # perder campos de vigência que não fazem parte da taxonomia normalizada.
  client$process_siglas_catalog <- siglas_data
  client$process_siglas_catalog_status <- if (identical(as.integer(resp_siglas$http_status), 200L) && is.list(siglas_data)) "available" else "unavailable"
  client$process_siglas_catalog_snapshot_id <- snap_siglas_id

  types_list <- list()

  if (is.list(siglas_data) && length(siglas_data) > 0) {
    for (item in siglas_data) {
      sigla <- if (!is.null(item$sigla)) as.character(item$sigla) else ""
      desc <- if (!is.null(item$descricao)) as.character(item$descricao) else ""
      type_id <- paste0("senado:type:sigla:", tolower(sigla))
      fam <- map_sigla_to_family(sigla, desc)

      types_list[[length(types_list) + 1]] <- list(
        legislative_type_id = type_id,
        house = "senado",
        source_namespace = "senado_api_processo",
        type_source_id = sigla,
        type_code = sigla,
        type_label = if (nchar(desc) > 0) desc else sigla,
        entity_kind = "process",
        normalized_family = fam,
        mapping_status = "verified",
        snapshot_id = snap_siglas_id
      )
    }
  }

  # 2. Tipos de Documentos (/processo/documento/tipos)
  resp_doctypes <- client$request("/processo/documento/tipos", accept = "application/json")
  doctypes_data <- resp_doctypes$data
  snap_doctypes_id <- resp_doctypes$snapshot$snapshot_id

  if (is.list(doctypes_data) && length(doctypes_data) > 0) {
    for (item in doctypes_data) {
      src_id <- if (!is.null(item$id)) as.character(item$id) else ""
      sigla <- if (!is.null(item$sigla)) as.character(item$sigla) else ""
      desc <- if (!is.null(item$descricao)) as.character(item$descricao) else ""
      type_id <- paste0("senado:type:doc:", src_id)
      fam <- map_doc_type_to_normalized_kind(sigla, desc)

      types_list[[length(types_list) + 1]] <- list(
        legislative_type_id = type_id,
        house = "senado",
        source_namespace = "senado_processo_documento",
        type_source_id = src_id,
        type_code = sigla,
        type_label = if (nchar(desc) > 0) desc else sigla,
        entity_kind = "document",
        normalized_family = fam,
        mapping_status = "verified",
        snapshot_id = snap_doctypes_id
      )
    }
  }

  # 3. Tipos de Conteúdo (/processo/documento/tipos-conteudo)
  resp_conteudo <- client$request("/processo/documento/tipos-conteudo", accept = "application/json")
  conteudo_data <- resp_conteudo$data
  snap_conteudo_id <- resp_conteudo$snapshot$snapshot_id

  if (is.list(conteudo_data) && length(conteudo_data) > 0) {
    for (item in conteudo_data) {
      src_id <- if (!is.null(item$id)) as.character(item$id) else ""
      sigla <- if (!is.null(item$sigla)) as.character(item$sigla) else ""
      desc <- if (!is.null(item$descricao)) as.character(item$descricao) else ""
      type_id <- paste0("senado:type:conteudo:", src_id)
      fam <- map_doc_type_to_normalized_kind(sigla, desc)

      types_list[[length(types_list) + 1]] <- list(
        legislative_type_id = type_id,
        house = "senado",
        source_namespace = "senado_processo_conteudo",
        type_source_id = src_id,
        type_code = sigla,
        type_label = if (nchar(desc) > 0) desc else sigla,
        entity_kind = "content",
        normalized_family = fam,
        mapping_status = "verified",
        snapshot_id = snap_conteudo_id
      )
    }
  }

  # Converter lista para data.frame Arrow tipado
  if (length(types_list) == 0) {
    return(data.frame(
      legislative_type_id = character(),
      house = character(),
      source_namespace = character(),
      type_source_id = character(),
      type_code = character(),
      type_label = character(),
      entity_kind = character(),
      normalized_family = character(),
      mapping_status = character(),
      snapshot_id = character(),
      stringsAsFactors = FALSE
    ))
  }

  df <- do.call(rbind, lapply(types_list, as.data.frame, stringsAsFactors = FALSE))
  # Deduplicar por legislative_type_id (PK)
  df <- df[!duplicated(df$legislative_type_id), ]
  df
}
