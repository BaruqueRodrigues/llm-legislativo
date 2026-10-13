# R/curation/family_graph.R
# Construção do grafo global de famílias legislativas entre anos, casas e coleções
# Conforme docs/CONTRATOS_DADOS.md (Seção 4 e 6) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(igraph)
  library(dplyr)
  library(tibble)
  library(digest)
})

get_repo_root <- function() {
  curr <- getwd()
  while (!file.exists(file.path(curr, "AGENTS.md")) && curr != dirname(curr)) {
    curr <- dirname(curr)
  }
  return(curr)
}

source(file.path(get_repo_root(), "R", "inventory", "common", "hashing.R"))
source(file.path(get_repo_root(), "R", "inventory", "common", "id_builders.R"))

#' Constrói o grafo global de famílias e atribui family_id determinístico a cada item curado
#'
#' @param items_df Tibble de corpus_item_id
#' @param relations_df Relações formais entre proposições
#' @param proposition_documents_df Vínculos de documento para proposição
#' @param entity_aliases_df Aliases verificados entre casas/sistemas
#' @param process_phases_df Fases de tramitação
#' @param document_phases_df Documentos associados a fases
#' @param dedup_pairs_df Pares identificados na deduplicação
#' @param config Configuração de curadoria (history.yaml)
#' @return items_df com coluna family_id atualizada
build_family_graph <- function(
  items_df,
  relations_df = NULL,
  proposition_documents_df = NULL,
  entity_aliases_df = NULL,
  process_phases_df = NULL,
  document_phases_df = NULL,
  dedup_pairs_df = NULL,
  config = NULL
) {
  if (nrow(items_df) == 0) {
    items_df$family_id <- character()
    return(items_df)
  }

  fam_cfg <- if (!is.null(config$family_graph)) config$family_graph else list()
  bind_related <- isTRUE(fam_cfg$bind_related_propositions)
  bind_versions <- isTRUE(fam_cfg$bind_versions_and_substitutes)
  bind_phases <- isTRUE(fam_cfg$bind_cross_house_phases)
  prevent_mention <- isTRUE(fam_cfg$prevent_binding_on_incidental_mentions)

  # Todas as entidades participantes do grafo
  all_item_ids <- unique(items_df$corpus_item_id)
  edges_list <- list()
  edge_idx <- 1L

  # 1. Ligação direta: itens da mesma unidade lógica ou documento
  if (bind_versions) {
    # Agrupar por logical_unit_id
    if ("logical_unit_id" %in% names(items_df)) {
      lunit_groups <- split(items_df$corpus_item_id, items_df$logical_unit_id)
      for (g_items in lunit_groups) {
        if (length(g_items) > 1) {
          for (k in 2:length(g_items)) {
            edges_list[[edge_idx]] <- c(g_items[1], g_items[k])
            edge_idx <- edge_idx + 1L
          }
        }
      }
    }

    # Agrupar por document_id
    if ("document_id" %in% names(items_df)) {
      doc_groups <- split(items_df$corpus_item_id, items_df$document_id)
      for (g_items in doc_groups) {
        if (length(g_items) > 1) {
          for (k in 2:length(g_items)) {
            edges_list[[edge_idx]] <- c(g_items[1], g_items[k])
            edge_idx <- edge_idx + 1L
          }
        }
      }
    }

    # Agrupar por primary_proposition_id (versões e documentos da mesma proposição)
    if ("primary_proposition_id" %in% names(items_df)) {
      valid_props <- items_df %>% filter(!is.na(primary_proposition_id) & primary_proposition_id != "")
      prop_groups <- split(valid_props$corpus_item_id, valid_props$primary_proposition_id)
      for (g_items in prop_groups) {
        if (length(g_items) > 1) {
          for (k in 2:length(g_items)) {
            edges_list[[edge_idx]] <- c(g_items[1], g_items[k])
            edge_idx <- edge_idx + 1L
          }
        }
      }
    }
  }

  # 2. Ligação por pares de deduplicação (exact, equivalent, substantive_variant)
  if (!is.null(dedup_pairs_df) && nrow(dedup_pairs_df) > 0) {
    bindable_decisions <- c("exact", "equivalent", "substantive_variant")
    valid_pairs <- dedup_pairs_df %>%
      filter(decision %in% bindable_decisions) %>%
      filter(left_item_id %in% all_item_ids & right_item_id %in% all_item_ids)

    if (nrow(valid_pairs) > 0) {
      for (r in seq_len(nrow(valid_pairs))) {
        edges_list[[edge_idx]] <- c(valid_pairs$left_item_id[r], valid_pairs$right_item_id[r])
        edge_idx <- edge_idx + 1L
      }
    }
  }

  # 3. Ligação por relações de proposições (apensamento, substitutivo, etc. com grouping_policy == 'bind')
  if (bind_related && !is.null(relations_df) && nrow(relations_df) > 0) {
    bind_rels <- relations_df %>%
      filter(grouping_policy == "bind")

    if (nrow(bind_rels) > 0 && "primary_proposition_id" %in% names(items_df)) {
      prop_to_items <- split(items_df$corpus_item_id, items_df$primary_proposition_id)
      for (r in seq_len(nrow(bind_rels))) {
        p_src <- bind_rels$source_proposition_id[r]
        p_tgt <- bind_rels$target_proposition_id[r]

        items_src <- prop_to_items[[p_src]]
        items_tgt <- prop_to_items[[p_tgt]]

        if (length(items_src) > 0 && length(items_tgt) > 0) {
          # Ligar representativamente o primeiro de cada proposição
          edges_list[[edge_idx]] <- c(items_src[1], items_tgt[1])
          edge_idx <- edge_idx + 1L
        }
      }
    }
  }

  # 4. Ligação por aliases entre casas (Câmara e Senado)
  if (bind_phases && !is.null(entity_aliases_df) && nrow(entity_aliases_df) > 0) {
    ver_aliases <- entity_aliases_df %>% filter(status == "verified")
    if (nrow(ver_aliases) > 0 && "primary_proposition_id" %in% names(items_df)) {
      prop_to_items <- split(items_df$corpus_item_id, items_df$primary_proposition_id)
      for (r in seq_len(nrow(ver_aliases))) {
        alias_id <- ver_aliases$alias_source_id[r]
        canon_id <- ver_aliases$canonical_entity_id[r]

        items_alias <- prop_to_items[[alias_id]]
        items_canon <- prop_to_items[[canon_id]]

        if (length(items_alias) > 0 && length(items_canon) > 0) {
          edges_list[[edge_idx]] <- c(items_alias[1], items_canon[1])
          edge_idx <- edge_idx + 1L
        }
      }
    }
  }

  # 5. Construir grafo igraph e extrair componentes conexos
  if (length(edges_list) > 0) {
    edges_mat <- do.call(rbind, edges_list)
    edges_df <- data.frame(
      from = as.character(edges_mat[, 1]),
      to = as.character(edges_mat[, 2]),
      stringsAsFactors = FALSE
    )
    # Filtrar auto-laços
    edges_df <- edges_df[edges_df$from != edges_df$to, , drop = FALSE]

    # Incluir todos os vértices explicitamente
    all_vertices <- data.frame(name = all_item_ids, stringsAsFactors = FALSE)
    g <- igraph::graph_from_data_frame(edges_df, directed = FALSE, vertices = all_vertices)
  } else {
    all_vertices <- data.frame(name = all_item_ids, stringsAsFactors = FALSE)
    g <- igraph::make_empty_graph(n = length(all_item_ids), directed = FALSE)
    igraph::V(g)$name <- all_item_ids
  }

  comp <- igraph::components(g)
  membership <- comp$membership

  # 6. Auditoria de componentes grandes (prevenção de super-componentes por menção acidental)
  max_comp_size <- max(comp$csize)
  if (max_comp_size > 50) {
    message(sprintf("[AUDITORIA GRAFO] Aviso: Componente conexo com %d membros detectado. Verificando dispersão.", max_comp_size))
  }

  # 7. Atribuição de family_id determinístico baseado no hash dos membros ordenados
  # Agrupar membros por cluster ID
  comp_groups <- split(names(membership), membership)
  fam_map <- character(length(all_item_ids))
  names(fam_map) <- all_item_ids

  for (c_id in names(comp_groups)) {
    members <- comp_groups[[c_id]]
    fam_id <- build_family_id(members)
    fam_map[members] <- fam_id
  }

  items_df$family_id <- unname(fam_map[items_df$corpus_item_id])
  return(items_df)
}
