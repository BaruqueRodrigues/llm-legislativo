# R/extraction/section_parser.R
# Segmentação de seções estruturadas legislativas com offsets Unicode [start, end)
# Conforme docs/CONTRATOS_DADOS.md (Seção 3, linha 138) e schemas/arrow_schemas.R

suppressPackageStartupMessages({
  library(tibble)
  library(dplyr)
  library(stringr)
  library(bit64)
})

# Padrões regex para detecção de seções legislativas canônicas
SECTION_PATTERNS <- list(
  exposition_of_motives = "(?i)(?:^|\\n)\\s*(?:EXPOSIÇÃO DE MOTIVOS|E\\.?\\s*M\\.?\\s*I\\.?|MENSAGEM\\s+N[ºo\\.]?\\s*\\d+|AVISO\\s+N[ºo\\.]?\\s*\\d+)\\b",
  justification = "(?i)(?:^|\\n)\\s*(?:JUSTIFICAÇÃO|JUSTIFICATIVA|DA JUSTIFICAÇÃO|RAZÕES DO PROJETO|MOTIVAÇÃO|RAZÕES DA PROPOSIÇÃO)\\b",
  amendment_text = "(?i)(?:^|\\n)\\s*(?:EMENDA\\s+(?:MODIFICATIVA|ADITIVA|SUPRESSIVA|SUBSTITUTIVA|DE PLENÁRIO|DE REDAÇÃO|DE RELATOR|N[ºo\\.]?\\s*\\d+)|SUBEMENDA|TEXTO DA EMENDA)\\b",
  substitute_text = "(?i)(?:^|\\n)\\s*(?:SUBSTITUTIVO(?:\\s+AO\\s+PROJETO)?|EMENDA SUBSTITUTIVA)\\b",
  final_text = "(?i)(?:^|\\n)\\s*(?:REDAÇÃO FINAL|TEXTO FINAL|AUTÓGRAFO)\\b",
  report = "(?i)(?:^|\\n)\\s*(?:(?:I\\s*[-–—]\\s*)?RELATÓRIO|DO RELATÓRIO|RELATÓRIO DA COMISSÃO)\\b",
  opinion = "(?i)(?:^|\\n)\\s*(?:PARECER(?:\\s+N[ºo\\.]?\\s*\\d+)?|DA FUNDAMENTAÇÃO|DO MÉRITO|DA ADMISSIBILIDADE|PARECER DA COMISSÃO|DO PARECER)\\b",
  vote = "(?i)(?:^|\\n)\\s*(?:(?:(?:II|III)\\s*[-–—]\\s*)?VOTO(?:\\s+DO\\s+RELATOR)?|VOTO EM SEPARADO|VOTO VENCIDO|CONCLUSÃO DO RELATOR)\\b",
  session_record = "(?i)(?:^|\\n)\\s*(?:ATA DA\\s+\\d+.*SESSÃO|SESSÃO DELIBERATIVA|DIÁRIO DA CÂMARA|DIÁRIO DO SENADO|ANAIS DO SENADO|SUMÁRIO DA SESSÃO)\\b",
  speech = "(?i)(?:^|\\n)\\s*(?:O SR\\.|A SRA\\.|DISCURSO DO|PRONUNCIAMENTO)\\b",
  annex = "(?i)(?:^|\\n)\\s*(?:ANEXO(?:\\s+[IVXLCDM\\d]+|\\s+ÚNICO)?|TABELA COMPARATIVA)\\b",
  signatures = "(?i)(?:^|\\n)\\s*(?:Sala das Sessões|Sala da Comissão|Brasília,\\s+\\d+\\s+de\\s+[a-zç]+\\s+de\\s+\\d{4})\\b",
  initial_text = "(?i)(?:^|\\n)\\s*(?:PROJETO DE LEI|PROPOSTA DE EMENDA|PROJETO DE DECRETO|MEDIDA PROVISÓRIA|O Congresso Nacional decreta:|A Câmara dos Deputados decreta:|O Senado Federal resolve:|Art\\.\\s*1[ºo\\.]?)\\b"
)

parse_document_sections <- function(extraction_id, pages_df) {
  if (is.null(pages_df) || nrow(pages_df) == 0) {
    return(tibble(
      section_id = character(0),
      extraction_id = character(0),
      ordinal = integer(0),
      section_type = character(0),
      page_start = integer(0),
      page_end = integer(0),
      start_char = bit64::integer64(0),
      end_char = bit64::integer64(0),
      detection_method = character(0),
      confidence = numeric(0),
      review_status = character(0),
      text = character(0)
    ))
  }

  pages_sorted <- pages_df %>% dplyr::arrange(page_index)

  # 1. Mapeamento de offsets por página na concatenação com \n\f\n
  delimiter <- "\n\f\n"
  delim_len <- nchar(delimiter, type = "chars")

  page_ranges <- list()
  full_text <- ""
  current_offset <- 0

  for (i in seq_len(nrow(pages_sorted))) {
    p_idx <- pages_sorted$page_index[i]
    p_text <- pages_sorted$raw_text[i] %||% ""
    p_len <- nchar(p_text, type = "chars")

    if (i > 1) {
      full_text <- paste0(full_text, delimiter)
      current_offset <- current_offset + delim_len
    }

    start_p <- current_offset
    end_p <- current_offset + p_len
    full_text <- paste0(full_text, p_text)
    current_offset <- end_p

    page_ranges[[i]] <- list(
      page_index = p_idx,
      start_char = start_p,
      end_char = end_p
    )
  }

  total_chars <- nchar(full_text, type = "chars")
  if (total_chars == 0) {
    return(tibble(
      section_id = paste0(extraction_id, ":sec:1"),
      extraction_id = extraction_id,
      ordinal = 1L,
      section_type = "unknown",
      page_start = 1L,
      page_end = 1L,
      start_char = bit64::as.integer64(0),
      end_char = bit64::as.integer64(0),
      detection_method = "empty_document",
      confidence = 1.0,
      review_status = "review",
      text = ""
    ))
  }

  # Função auxiliar para mapear offset para página (1-based)
  offset_to_page <- function(char_offset) {
    for (pr in page_ranges) {
      if (char_offset >= pr$start_char && char_offset <= pr$end_char) {
        return(pr$page_index)
      }
    }
    return(pages_sorted$page_index[length(pages_sorted$page_index)])
  }

  # 2. Busca de limites de seções usando regex
  candidates <- list()
  for (sec_type in names(SECTION_PATTERNS)) {
    pattern <- SECTION_PATTERNS[[sec_type]]
    matches <- stringr::str_locate_all(full_text, pattern)[[1]]
    if (nrow(matches) > 0) {
      for (m in seq_len(nrow(matches))) {
        pos <- matches[m, 1]
        # Se começou com \n, avança 1 para o início real da palavra
        if (substr(full_text, pos, pos) == "\n") {
          pos <- pos + 1
        }
        candidates[[length(candidates) + 1]] <- list(
          pos = pos,
          type = sec_type
        )
      }
    }
  }

  # Se nenhum cabeçalho foi detectado
  if (length(candidates) == 0) {
    # Tenta verificar se é articulado
    sec_type <- if (grepl("(?i)Art\\.\\s*1", full_text)) "initial_text" else "unknown"
    method <- if (sec_type == "initial_text") "heuristic_article" else "fallback_unknown"
    conf <- if (sec_type == "initial_text") 0.8 else 0.5
    status <- if (sec_type == "initial_text") "pass" else "review"

    return(tibble(
      section_id = paste0(extraction_id, ":sec:1"),
      extraction_id = extraction_id,
      ordinal = 1L,
      section_type = sec_type,
      page_start = 1L,
      page_end = max(pages_sorted$page_index),
      start_char = bit64::as.integer64(0),
      end_char = bit64::as.integer64(total_chars),
      detection_method = method,
      confidence = conf,
      review_status = status,
      text = full_text
    ))
  }

  # Ordenar candidatos por posição
  candidates_df <- do.call(rbind, lapply(candidates, as.data.frame))
  candidates_df <- candidates_df %>%
    dplyr::arrange(pos) %>%
    dplyr::distinct(pos, .keep_all = TRUE)

  # Filtrar candidatos excessivamente próximos (< 10 caracteres) para evitar colisões
  filtered_candidates <- list()
  last_pos <- -100
  for (c_idx in seq_len(nrow(candidates_df))) {
    cur_pos <- candidates_df$pos[c_idx]
    if (cur_pos - last_pos >= 10) {
      filtered_candidates[[length(filtered_candidates) + 1]] <- list(
        pos = cur_pos,
        type = as.character(candidates_df$type[c_idx])
      )
      last_pos <- cur_pos
    }
  }

  # Construção dos blocos de seções
  sections_list <- list()
  ord <- 1L

  # Bloco inicial antes do primeiro cabeçalho se houver texto
  first_pos <- filtered_candidates[[1]]$pos
  if (first_pos > 1) {
    prefix_text <- substr(full_text, 1, first_pos - 1)
    prefix_clean <- trimws(prefix_text)
    if (nchar(prefix_clean) > 0) {
      p_start <- 1L
      p_end <- offset_to_page(first_pos - 1)
      p_type <- if (grepl("(?i)Art\\.\\s*1|Congresso Nacional|Câmara dos Deputados|Senado Federal", prefix_clean)) "initial_text" else "unknown"

      sections_list[[ord]] <- tibble(
        section_id = paste0(extraction_id, ":sec:", ord),
        extraction_id = extraction_id,
        ordinal = ord,
        section_type = p_type,
        page_start = p_start,
        page_end = p_end,
        start_char = bit64::as.integer64(0),
        end_char = bit64::as.integer64(first_pos - 1),
        detection_method = "pre_heading_prefix",
        confidence = 0.85,
        review_status = if (p_type == "unknown") "review" else "pass",
        text = prefix_text
      )
      ord <- ord + 1L
    }
  }

  # Blocos delimitados por cabeçalhos
  num_cands <- length(filtered_candidates)
  for (i in seq_len(num_cands)) {
    s_start_1b <- filtered_candidates[[i]]$pos
    s_end_1b <- if (i < num_cands) (filtered_candidates[[i + 1]]$pos - 1) else total_chars
    s_type <- filtered_candidates[[i]]$type

    s_text <- substr(full_text, s_start_1b, s_end_1b)
    # 0-based code points: [s_start_1b - 1, s_end_1b)
    start_cp <- s_start_1b - 1
    end_cp <- s_end_1b

    p_start <- offset_to_page(s_start_1b)
    p_end <- offset_to_page(s_end_1b)

    sections_list[[ord]] <- tibble(
      section_id = paste0(extraction_id, ":sec:", ord),
      extraction_id = extraction_id,
      ordinal = ord,
      section_type = s_type,
      page_start = p_start,
      page_end = p_end,
      start_char = bit64::as.integer64(start_cp),
      end_char = bit64::as.integer64(end_cp),
      detection_method = "regex_heading",
      confidence = 0.95,
      review_status = "pass",
      text = s_text
    )
    ord <- ord + 1L
  }

  dplyr::bind_rows(sections_list)
}
