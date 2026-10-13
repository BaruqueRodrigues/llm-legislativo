# R/inventory/senado/collections.R
# Registro de coleções, acervos históricos (Anais, Diários, API) e segmentos de cobertura do Senado
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

# Registrar evidências de uso e licença do Senado
build_senado_use_evidence <- function(snapshot_id) {
  data.frame(
    evidence_id = "senado:lic:politica_uso_dados_abertos",
    source_uri = "https://www12.senado.leg.br/institucional/documentos/politica-de-uso-do-portal-do-senado-federal",
    accessed_at = as.POSIXct(Sys.time(), tz = "UTC"),
    snapshot_id = snapshot_id,
    applies_to = "official_legislative_text",
    permission_status = "allowed",
    attribution_rule = "Citar fonte oficial: Senado Federal",
    redistribution_rule = "Livre utilizacao institucional conforme Politica de Uso e Lei 12.527/2011 (LAI)",
    review_note = "Termos e Politica de Uso de Dados Abertos verificados em 2026-10-07",
    stringsAsFactors = FALSE
  )
}

# Registrar coleções oficiais do Senado
register_senado_collections <- function(snapshot_id) {
  cols <- list(
    list(
      collection_id = "senado:collection:api:processo",
      house = "senado",
      source_namespace = "senado_api_processo",
      name = "API de Processos e Matérias Legislativas do Senado",
      collection_kind = "api",
      catalog_uri = "https://legis.senado.leg.br/dadosabertos/v3/api-docs",
      snapshot_id = snapshot_id,
      inventory_unit = "process",
      digital_availability_note = "Disponivel via REST API v3. O limite historico da cobertura de processos nao foi comprovado; consultar a listagem por estados e reconciliar com as colecoes historicas."
    ),
    list(
      collection_id = "senado:collection:catalogo:dadosabertos",
      house = "senado",
      source_namespace = "senado_catalogo_csv",
      name = "Catálogo de Arquivos Abertos do Senado (Processos e Emendas)",
      collection_kind = "annual_files",
      catalog_uri = "https://www12.senado.leg.br/dados-abertos/conjuntos?grupo=projetos-e-materias&portal=Legislativo",
      snapshot_id = snapshot_id,
      inventory_unit = "process",
      digital_availability_note = "Arquivos CSV consolidados de processos e emendas atualmente em tramitacao."
    ),
    list(
      collection_id = "senado:collection:arquivo:anais",
      house = "senado",
      source_namespace = "senado_arquivo_anais",
      name = "Livros de Anais do Senado Federal (1826–2013)",
      collection_kind = "annals",
      catalog_uri = "https://www25.senado.leg.br/web/atividade/anais",
      snapshot_id = snapshot_id,
      inventory_unit = "volume",
      digital_availability_note = "Registro oficial historico das sessoes plenarias do Senado (Imperio 1826-1889, Republica 1889-2013, Constituinte 1988). Migrado para Diarios em 2014."
    ),
    list(
      collection_id = "senado:collection:publicacoes:diarios",
      house = "senado",
      source_namespace = "senado_publicacoes_diarios",
      name = "Diários do Senado Federal e do Congresso Nacional (DSF/DCN 2014–presente)",
      collection_kind = "diary",
      catalog_uri = "https://legis.senado.leg.br/diarios/",
      snapshot_id = snapshot_id,
      inventory_unit = "issue",
      digital_availability_note = "Publicacoes periodicas oficiais digitais do DSF e DCN a partir de 2014 consolidando a producao plenaria e documental."
    )
  )

  do.call(rbind, lapply(cols, as.data.frame, stringsAsFactors = FALSE))
}

# Construir segmentos de cobertura histórica reconciliados (Gates G1 e GH)
build_senado_coverage_segments <- function(collections_df, snapshot_id, cutoff_utc = as.character(Sys.time())) {
  cutoff_ts <- as.POSIXct(cutoff_utc, tz = "UTC")
  segments <- list()

  # Segmentos anuais são criados pelo motor somente após fixar o cutoff e
  # respeitar o limite operacional. Evita deixar dois segmentos all-years que
  # poderiam parecer cobertura suficiente após uma consulta S/N.

  # Acervos: os intervalos descritos nos catálogos orientam a descoberta, mas
  # não provam que cada volume/edição foi enumerado ou recuperado.
  archive_segments <- list(
    list(id = "senado:collection:arquivo:anais:all_volumes", collection = "senado:collection:arquivo:anais",
         start = as.Date("1826-05-06"), end = as.Date("2013-12-31"), axis = "catalog_period", unit = "volume",
         query = list(catalog = "anais", period = "1826-2013"), gap = "Índice oficial e unidades digitais precisam ser enumerados e reconciliados; a faixa publicada não prova continuidade."),
    list(id = "senado:collection:publicacoes:diarios:all_issues", collection = "senado:collection:publicacoes:diarios",
         start = as.Date("2014-01-01"), end = as.Date(NA), axis = "publication", unit = "issue",
         query = list(catalog = "diarios", period_start = "2014-01-01", cutoff = as.character(cutoff_ts)), gap = "Edições do DSF/DCN não foram enumeradas nesta execução.")
  )
  for (item in archive_segments) {
    segments[[length(segments) + 1]] <- list(
      segment_id = item$id,
      collection_id = item$collection,
      house = "senado",
      legislative_type_id = NA_character_,
      year = NA_integer_,
      period_start = item$start,
      period_end = item$end,
      date_axis = item$axis,
      snapshot_cutoff_utc = cutoff_ts,
      query_json = toJSON(item$query, auto_unbox = TRUE),
      inventory_status = "pending",
      coverage_status = "pending",
      expected_count = NA_integer_,
      discovered_count = 0L,
      retrieved_count = 0L,
      accepted_count = 0L,
      count_unit = item$unit,
      exhaustion_evidence = NA_character_,
      gap_reason = item$gap,
      snapshot_id = snapshot_id
    )
  }

  # Converter para data frame
  df <- do.call(rbind, lapply(segments, as.data.frame, stringsAsFactors = FALSE))
  df
}
