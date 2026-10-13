# R/inventory/common/id_builders.R
# Construtores determinísticos de identificadores normativos (docs/CONTRATOS_DADOS.md)

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))




build_proposition_id <- function(house, source_id, is_processo = FALSE, is_legado = FALSE) {
  house <- tolower(trimws(house))
  source_id <- as.character(source_id)
  if (house == "camara") {
    paste0("camara:prop:", source_id)
  } else if (house == "senado") {
    if (is_legado) {
      paste0("senado:prop:materia:", source_id)
    } else {
      paste0("senado:prop:processo:", source_id)
    }
  } else {
    paste0(house, ":prop:", source_id)
  }
}

build_document_id <- function(house, source_namespace, id_oficial = NULL, identity_url = NULL) {
  house <- tolower(trimws(house))
  source_namespace <- tolower(trimws(source_namespace))
  if (!is.null(id_oficial) && !is.na(id_oficial) && nchar(trimws(as.character(id_oficial))) > 0) {
    paste0(house, ":doc:", source_namespace, ":", trimws(as.character(id_oficial)))
  } else if (!is.null(identity_url) && !is.na(identity_url) && nchar(trimws(identity_url)) > 0) {
    url_hash <- hash_string(trimws(identity_url))
    paste0(house, ":doc:", source_namespace, ":url:", url_hash)
  } else {
    stop("build_document_id exige id_oficial ou identity_url")
  }
}

build_version_id <- function(document_id, file_sha256) {
  if (is.null(document_id) || is.null(file_sha256)) {
    stop("build_version_id exige document_id e file_sha256")
  }
  paste0(document_id, ":v:", tolower(trimws(file_sha256)))
}

build_author_id <- function(house, source_id = NULL, name = NULL) {
  house <- tolower(trimws(house))
  if (!is.null(source_id) && !is.na(source_id) && nchar(trimws(as.character(source_id))) > 0) {
    paste0(house, ":author:", trimws(as.character(source_id)))
  } else if (!is.null(name) && !is.na(name) && nchar(trimws(name)) > 0) {
    name_hash <- hash_string(trimws(name))
    paste0(house, ":author:local:", name_hash)
  } else {
    stop("build_author_id exige source_id ou name")
  }
}

build_theme_id <- function(house, source_id) {
  house <- tolower(trimws(house))
  paste0(house, ":theme:", trimws(as.character(source_id)))
}

build_phase_id <- function(house, source_namespace, process_proposition_id, source_phase_id = NULL, phase_identity = NULL) {
  house <- tolower(trimws(house))
  if (!is.null(source_phase_id) && !is.na(source_phase_id) && nchar(trimws(as.character(source_phase_id))) > 0) {
    paste0(house, ":phase:", source_namespace, ":", trimws(as.character(source_phase_id)))
  } else if (!is.null(phase_identity) && !is.na(phase_identity)) {
    h <- hash_string(paste0(process_proposition_id, ":", phase_identity))
    paste0(house, ":phase:", source_namespace, ":local:", h)
  } else {
    stop("build_phase_id exige source_phase_id ou phase_identity")
  }
}

build_segment_id <- function(collection_id, house, legislative_type_code = "ALL", year = NULL) {
  yr_str <- if (is.null(year) || is.na(year)) "undated" else as.character(year)
  paste0(collection_id, ":", tolower(house), ":", tolower(legislative_type_code), ":", yr_str)
}

build_logical_unit_id <- function(document_id, source_locator = NULL) {
  if (is.null(source_locator) || is.na(source_locator) || nchar(trimws(source_locator)) == 0) {
    document_id
  } else {
    paste0(document_id, ":unit:", hash_string(trimws(source_locator)))
  }
}

build_family_id <- function(sorted_member_ids) {
  if (is.null(sorted_member_ids) || length(sorted_member_ids) == 0) {
    stop("build_family_id exige lista de identificadores")
  }
  sorted_ids <- sort(unique(as.character(sorted_member_ids)))
  paste0("fam:", hash_string(paste(sorted_ids, collapse = "|")))
}
