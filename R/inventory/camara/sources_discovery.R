# R/inventory/camara/sources_discovery.R
# Descoberta de fontes, coleções oficiais, termos de uso e segmentos de cobertura da Câmara
# Conforme docs/CONTRATOS_DADOS.md e docs/subagents/01_INVENTARIO.md

suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))

#' Constrói a tabela source_collections para a Câmara dos Deputados
#'
#' @param snapshot_id Identificador do snapshot de metadados.
#' @return data.frame compatível com o esquema Arrow source_collections.
build_source_collections <- function(snapshot_id = "camara:snap:collections:2026-10-07") {
  data.frame(
    collection_id = c(
      "camara:col:api_v2",
      "camara:col:arquivos_anuais",
      "camara:col:portal_proposicoes",
      "camara:col:portal_publicacoes",
      "camara:col:arquivo_historico",
      "camara:col:discursos_notas"
    ),
    house = rep("camara", 6),
    source_namespace = c(
      "api_v2",
      "arquivos_anuais",
      "portal_web",
      "diarios_anais",
      "arquivo_historico",
      "discursos_notas"
    ),
    name = c(
      "API de Dados Abertos v2 da Câmara dos Deputados",
      "Arquivos Anuais em Lote de Dados Abertos (CSV/JSON)",
      "Portal Web Proposições, Ficha de Tramitação e Inteiro Teor",
      "Diários da Câmara dos Deputados, Anais e Boletins",
      "Acervo do Arquivo Histórico da Câmara dos Deputados",
      "Discursos e Notas Taquigráficas da Câmara dos Deputados"
    ),
    collection_kind = c(
      "api",
      "annual_files",
      "dossier",
      "diary",
      "archive",
      "transcripts"
    ),
    catalog_uri = c(
      "https://dadosabertos.camara.leg.br/api/v2",
      "https://dadosabertos.camara.leg.br/arquivos",
      "https://www.camara.leg.br/proposicoesWeb",
      "https://imagem.camara.leg.br/diarios.asp",
      "https://www2.camara.leg.br/a-camara/documentos-e-pesquisa/arquivo",
      "https://www2.camara.leg.br/atividade-legislativa/discursos-e-notas-taquigraficas"
    ),
    snapshot_id = rep(as.character(snapshot_id), 6),
    inventory_unit = c(
      "proposition",
      "proposition",
      "document",
      "issue",
      "archival_unit",
      "issue"
    ),
    digital_availability_note = c(
      "API RESTful oficial v2 com metadados de proposições, autores, temas, tramitações e referências",
      "Catálogo/arquivos anuais oficiais; intervalos precisam ser descobertos e reconciliados por consulta",
      "Fichas completas de tramitação, dossiês, avulsos, peças acessórias (DVT, pareceres de comissão) e PDFs por codteor",
      "Portal oficial de publicações legislativas históricas (edições e digitalização a inventariar)",
      "Catálogo oficial do Arquivo Histórico; unidades e objetos digitais a inventariar",
      "Transcrições oficiais de discursos em plenário e notas taquigráficas de comissões e audiências"
    ),
    stringsAsFactors = FALSE
  )
}

#' Constrói a tabela use_evidence para os termos e licenças aplicáveis à Câmara
#'
#' @param snapshot_id Identificador do snapshot.
#' @return data.frame compatível com o esquema Arrow use_evidence.
build_use_evidence <- function(snapshot_id = "camara:snap:collections:2026-10-07") {
  ts_utc <- as.POSIXct("2026-10-07 12:00:00", tz = "UTC")

  data.frame(
    evidence_id = c(
      "camara:use:termos_portal",
      "camara:use:lei_9610_art8",
      "camara:use:dados_abertos_politica"
    ),
    source_uri = c(
      "https://www2.camara.leg.br/termo-de-uso-e-politica-de-privacidade",
      "https://www.planalto.gov.br/ccivil_03/leis/l9610.htm",
      "https://dadosabertos.camara.leg.br/howtouse/sobre-dados-abertos.html"
    ),
    accessed_at = rep(ts_utc, 3),
    snapshot_id = rep(as.character(snapshot_id), 3),
    applies_to = c(
      "official_legislative_text",
      "official_legislative_text",
      "metadata"
    ),
    permission_status = c(
      "allowed",
      "allowed",
      "allowed"
    ),
    attribution_rule = c(
      "Indicação da Câmara dos Deputados como fonte e do autor institucional/parlamentar",
      "Art. 8º, IV da Lei Federal nº 9.610/1998",
      "Citação da fonte Dados Abertos da Câmara dos Deputados"
    ),
    redistribution_rule = c(
      "Permitida reprodução e redistribuição sem ônus para fins informativos e de pesquisa",
      "Livre circulação e reprodução de atos normativos oficiais e decisões públicas",
      "Livre reutilização de metadados sem restrição de acesso"
    ),
    review_note = c(
      "Termos de Uso do Portal da Câmara (itens 7 e 29) autorizam reprodução com citação de fonte e declaram informações de domínio público",
      "Textos de atos oficiais, projetos legislativos e relatórios públicos não são objeto de proteção de direitos autorais de terceiros",
      "Política de Dados Abertos da Câmara em conformidade com a LAI (Lei 12.527/2011) e Decreto 8.777/2016"
    ),
    stringsAsFactors = FALSE
  )
}

#' Constrói os segmentos de cobertura histórica para a Câmara dos Deputados
#'
#' @param snapshot_id Identificador do snapshot de descoberta.
#' @param start_year Primeiro ano histórico catalogado (padrão 1934).
#' @param end_year Último ano histórico (padrão 2026).
#' @param snapshot_cutoff_utc Timestamp limite do snapshot.
#' @return data.frame estritamente compatível com o esquema coverage_segments.
build_coverage_segments <- function(snapshot_id = "camara:snap:coverage:pending",
                                    start_year = 1934,
                                    end_year = as.integer(format(Sys.Date(), "%Y")),
                                    snapshot_cutoff_utc = NULL) {
  if (is.null(snapshot_cutoff_utc)) snapshot_cutoff_utc <- as.POSIXct(Sys.time(), tz = "UTC")
  if (length(start_year) != 1L || length(end_year) != 1L || start_year > end_year) stop("Intervalo anual inválido.")
  rows <- list()
  add <- function(id, collection, year=NA_integer_, start=as.Date(NA), end=as.Date(NA), axis="catalog_period",
                  query=list(), unit="propositions", reason="Segmento planejado; ainda não consultado.") {
    rows[[length(rows)+1L]] <<- data.frame(
      segment_id=id, collection_id=collection, house="camara", legislative_type_id=NA_character_,
      year=as.integer(year), period_start=as.Date(start), period_end=as.Date(end), date_axis=axis,
      snapshot_cutoff_utc=as.POSIXct(snapshot_cutoff_utc, tz="UTC"),
      query_json=as.character(jsonlite::toJSON(query, auto_unbox=TRUE)),
      inventory_status="pending", coverage_status="pending", expected_count=NA_integer_,
      discovered_count=0L, retrieved_count=0L, accepted_count=0L, count_unit=unit,
      exhaustion_evidence=NA_character_, gap_reason=reason, snapshot_id=snapshot_id,
      stringsAsFactors=FALSE)
  }
  for (yr in seq.int(start_year, end_year)) {
    windows <- list(
      list(start=sprintf("%04d-01-01",yr), end=sprintf("%04d-03-31",yr)),
      list(start=sprintf("%04d-04-01",yr), end=sprintf("%04d-06-30",yr)),
      list(start=sprintf("%04d-07-01",yr), end=sprintf("%04d-09-30",yr)),
      list(start=sprintf("%04d-10-01",yr), end=sprintf("%04d-12-31",yr)))
    for (q in seq_along(windows)) {
      w <- windows[[q]]
      add(paste0("camara:col:api_v2:proposicoes:presentation:",yr,":Q",q), "camara:col:api_v2",
        yr, as.Date(w$start), as.Date(w$end), "presentation",
        list(endpoint="/proposicoes", dataApresentacaoInicio=w$start, dataApresentacaoFim=w$end))
    }
  }
  add("camara:col:api_v2:proposicoes:undated", "camara:col:api_v2", axis="undated",
      query=list(endpoint="/proposicoes", note="estratégia de itens sem data ainda pendente"))
  add("camara:col:api_v2:tramitacoes:events", "camara:col:api_v2", year=end_year,
      start=as.Date(sprintf("%04d-01-01",end_year)), end=as.Date(sprintf("%04d-12-31",end_year)), axis="event",
      query=list(endpoint="/proposicoesTramitacoes", note="reconciliação por evento pendente"), unit="events")
  add("camara:col:portal_proposicoes:attachments", "camara:col:portal_proposicoes", axis="attachment",
      query=list(collection="fichas,árvores,dossiês,avulsos,emendas,pareceres,substitutivos,votos,redações"), unit="documents")
  add("camara:col:portal_publicacoes:historical", "camara:col:portal_publicacoes", axis="publication",
      query=list(collection="diários,anais,boletins"), unit="issues")
  add("camara:col:arquivo_historico:catalog", "camara:col:arquivo_historico", axis="catalog_period",
      query=list(collection="arquivo histórico"), unit="archival_unit")
  add("camara:col:discursos_notas:catalog", "camara:col:discursos_notas", axis="publication",
      query=list(collection="discursos e notas taquigráficas"), unit="issues")
  dplyr::bind_rows(rows)
}
