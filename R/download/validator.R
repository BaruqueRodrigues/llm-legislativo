# R/download/validator.R
# Validador de integridade binária, magic numbers, parsers e detecção de falsos positivos (HTML 200)
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0)

suppressPackageStartupMessages({
  library(digest)
})

#' Detecta o tipo de mídia (MIME) a partir dos magic bytes do buffer binário
#'
#' @param raw_bytes Vetor raw contendo o conteúdo do arquivo.
#' @return String com o MIME type detectado ou "application/octet-stream".
detect_media_type <- function(raw_bytes) {
  if (is.null(raw_bytes) || length(raw_bytes) == 0) {
    return("application/x-empty")
  }

  n <- length(raw_bytes)

  # 1. PDF: %PDF-
  if (n >= 4 && rawToChar(raw_bytes[1:4]) == "%PDF") {
    return("application/pdf")
  }

  # 2. RTF: {\rtf
  if (n >= 5 && rawToChar(raw_bytes[1:5]) == "{\\rtf") {
    return("application/rtf")
  }

  # 3. ZIP / OpenXML (DOCX, etc.): PK\x03\x04
  if (n >= 4 && raw_bytes[1] == as.raw(0x50) && raw_bytes[2] == as.raw(0x4b) &&
      raw_bytes[3] == as.raw(0x03) && raw_bytes[4] == as.raw(0x04)) {
    return("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
  }

  # 4. DOC legado (OLE2 / Compound File): \xd0\xcf\x11\xe0
  if (n >= 4 && raw_bytes[1] == as.raw(0xd0) && raw_bytes[2] == as.raw(0xcf) &&
      raw_bytes[3] == as.raw(0x11) && raw_bytes[4] == as.raw(0xe0)) {
    return("application/msword")
  }

  # 5. HTML: portais legados podem iniciar diretamente em <head><meta ...>
  prefix_len <- min(n, 1024L)
  prefix_bytes <- raw_bytes[1:prefix_len]
  prefix_bytes[prefix_bytes < as.raw(0x09) | prefix_bytes > as.raw(0x7e)] <- as.raw(0x20)
  prefix_str <- tryCatch(tolower(rawToChar(prefix_bytes)), error = function(e) "")

  if (grepl("<!doctype[[:space:]]+html|<html|<head([[:space:]>])|<meta([[:space:]>])|<body([[:space:]>])", prefix_str)) {
    return("text/html")
  }

  # 6. XML: <?xml
  if (grepl("^[[:space:]]*<\\?xml", prefix_str)) {
    return("application/xml")
  }

  # 7. Plain text se for decodificável como texto legível
  if (n > 0 && n <= 5000000) {
    # Amostra de até 4096 bytes
    sample_len <- min(n, 4096L)
    sample_bytes <- raw_bytes[1:sample_len]
    # Se maioria são caracteres ASCII/UTF-8 imprimíveis ou whitespace
    non_printable <- sum(sample_bytes < as.raw(0x09) | (sample_bytes > as.raw(0x0d) & sample_bytes < as.raw(0x20)))
    if (non_printable == 0) {
      return("text/plain")
    }
  }

  return("application/octet-stream")
}

#' Extrai a contagem de páginas de um arquivo ou buffer PDF
#'
#' @param raw_bytes Vetor raw do PDF.
#' @param file_path Caminho opcional do arquivo temporário no disco.
#' @return Inteiro com número de páginas (ou NA_integer_ se não for PDF ou falhar).
extract_pdf_page_count <- function(raw_bytes = NULL, file_path = NULL) {
  # Se recebemos bytes mas não arquivo, ou se precisamos de arquivo para mdls
  created_temp <- FALSE
  if (is.null(file_path) && !is.null(raw_bytes)) {
    file_path <- tempfile(fileext = ".pdf")
    writeBin(raw_bytes, file_path)
    created_temp <- TRUE
  }
  on.exit({
    if (created_temp && file.exists(file_path)) {
      unlink(file_path)
    }
  })

  # Estratégia 1: No macOS (Darwin), usar mdls se o arquivo existir
  if (!is.null(file_path) && file.exists(file_path) && Sys.info()["sysname"] == "Darwin") {
    mdls_count <- tryCatch({
      out <- system2("mdls", c("-name", "kMDItemNumberOfPages", shQuote(file_path)), stdout = TRUE, stderr = FALSE)
      if (length(out) > 0) {
        line <- grep("kMDItemNumberOfPages", out, value = TRUE)
        if (length(line) > 0 && grepl("[0-9]+", line[1])) {
          cnt <- suppressWarnings(as.integer(sub(".*?=[[:space:]]*([0-9]+).*", "\\1", line[1])))
          if (!is.na(cnt) && cnt > 0) cnt else NULL
        } else NULL
      } else NULL
    }, error = function(e) NULL)

    if (!is.null(mdls_count)) {
      return(mdls_count)
    }
  }

  # Estratégia 2: Parser binário nativo inspecionando a árvore /Type /Pages /Count
  if (is.null(raw_bytes) && !is.null(file_path) && file.exists(file_path)) {
    raw_bytes <- readBin(file_path, "raw", file.info(file_path)$size)
  }

  if (is.null(raw_bytes) || length(raw_bytes) < 4) {
    return(NA_integer_)
  }

  # Sanitizar bytes brutos para ASCII puro para evitar erros de multibyte em streams comprimidos
  chars <- raw_bytes
  chars[chars < as.raw(0x09) | chars > as.raw(0x7e)] <- as.raw(0x20)
  txt <- tryCatch(rawToChar(chars), error = function(e) "")

  if (nchar(txt) == 0) {
    return(1L)
  }

  # Busca 1: /Type /Pages ... /Count N
  m1 <- regmatches(txt, gregexpr("/Type[[:space:]]*/Pages[^>]*?/Count[[:space:]]+([0-9]+)", txt, perl = TRUE))[[1]]
  if (length(m1) > 0) {
    counts <- suppressWarnings(as.integer(sub(".*?/Count[[:space:]]+([0-9]+).*", "\\1", m1)))
    counts <- counts[!is.na(counts) & counts > 0]
    if (length(counts) > 0) {
      return(max(counts))
    }
  }

  # Busca 2: /Count N ... /Type /Pages
  m2 <- regmatches(txt, gregexpr("/Count[[:space:]]+([0-9]+)[^>]*?/Type[[:space:]]*/Pages", txt, perl = TRUE))[[1]]
  if (length(m2) > 0) {
    counts <- suppressWarnings(as.integer(sub(".*?/Count[[:space:]]+([0-9]+).*", "\\1", m2)))
    counts <- counts[!is.na(counts) & counts > 0]
    if (length(counts) > 0) {
      return(max(counts))
    }
  }

  # Busca 3: Ocorrências de /Type /Page (sem o s de Pages)
  m3 <- gregexpr("/Type[[:space:]]*/Page[^sA-Za-z0-9]", txt, perl = TRUE)[[1]]
  if (m3[1] != -1) {
    return(as.integer(length(m3)))
  }

  # Se tem magic %PDF mas não achou árvore explícita (ex: linearizado ou streams comprimidos)
  if (length(raw_bytes) >= 4 && rawToChar(raw_bytes[1:4]) == "%PDF") {
    return(1L)
  }

  return(NA_integer_)
}

#' Valida integralmente o conteúdo capturado, aplicando regras anti-HTML200, truncamento e magic numbers
#'
#' @param raw_bytes Vetor raw com o conteúdo recebido.
#' @param declared_media_type Tipo MIME declarado pelo servidor (Content-Type).
#' @param declared_size_bytes Tamanho declarado pelo servidor (Content-Length).
#' @param is_binary_expected Indicador se era esperado documento binário (default TRUE).
#' @return Lista com validação: valid (logical), detected_media_type, page_count, integrity_status, error_code, error_message.
validate_download_content <- function(raw_bytes,
                                      declared_media_type = NULL,
                                      declared_size_bytes = NULL,
                                      is_binary_expected = TRUE) {
  received_len <- length(raw_bytes)

  # Regra 1: Rejeitar arquivo vazio (zero bytes)
  if (is.null(raw_bytes) || received_len == 0) {
    return(list(
      valid = FALSE,
      detected_media_type = "application/x-empty",
      page_count = NA_integer_,
      integrity_status = "quarantined",
      error_code = "EMPTY_FILE",
      error_message = "Arquivo baixado possui zero bytes"
    ))
  }

  # Regra 2: Rejeitar arquivo truncado em relação ao Content-Length declarado
  if (!is.null(declared_size_bytes) && !is.na(declared_size_bytes) && declared_size_bytes > 0) {
    if (received_len < declared_size_bytes) {
      return(list(
        valid = FALSE,
        detected_media_type = detect_media_type(raw_bytes),
        page_count = NA_integer_,
        integrity_status = "quarantined",
        error_code = "TRUNCATED_FILE",
        error_message = sprintf("Arquivo truncado: recebido %d bytes, esperado %d bytes", received_len, as.integer(declared_size_bytes))
      ))
    }
  }

  # Detectar MIME type real
  real_mime <- detect_media_type(raw_bytes)

  # Regra 3: Rejeição de Falso Positivo HTML 200 (HTTP 200 com página HTML de erro / aviso)
  if (real_mime == "text/html") {
    # Se era esperado binário (ex.: PDF, RTF, DOCX), qualquer HTML recebido é falso positivo
    # Inspeciona também mensagens de erro comuns em portais legislativos
    prefix_len <- min(received_len, 4096L)
    prefix_sample <- raw_bytes[1:prefix_len]
    prefix_sample[prefix_sample < as.raw(0x09) | prefix_sample > as.raw(0x7e)] <- as.raw(0x20)
    prefix_str <- tryCatch(tolower(rawToChar(prefix_sample)), error = function(e) "")

    is_security_challenge <- grepl("<title>", prefix_str) &&
      grepl("verifica", prefix_str) && grepl("seguran", prefix_str) &&
      grepl("senado federal", prefix_str)
    is_error_html <- grepl("erro[[:space:]]+404|p[aá]gina[[:space:]]+n[aã]o[[:space:]]+encontrada|indispon[ií]vel|acesso[[:space:]]+negado|proposicoesweb/erro|sistema[[:space:]]+em[[:space:]]+manuten", prefix_str)

    error_detail <- if (is_security_challenge) {
      "Servidor retornou página de verificação de segurança do Senado Federal (HTTP 200 HTML)"
    } else if (is_error_html) {
      "Servidor retornou pagina HTML de erro legislativo com status HTTP 200"
    } else {
      "Servidor retornou documento HTML quando era esperado documento binario legislativo"
    }

    return(list(
      valid = FALSE,
      detected_media_type = "text/html",
      page_count = NA_integer_,
      integrity_status = "quarantined",
      error_code = "HTML_200_FALSE_POSITIVE",
      error_message = error_detail
    ))
  }

  # Regra 4: Validação específica de PDF
  page_count <- NA_integer_
  if (real_mime == "application/pdf") {
    # Validar magic header
    if (received_len < 4 || rawToChar(raw_bytes[1:4]) != "%PDF") {
      return(list(
        valid = FALSE,
        detected_media_type = "application/pdf",
        page_count = NA_integer_,
        integrity_status = "quarantined",
        error_code = "INVALID_PDF_MAGIC",
        error_message = "Arquivo alegado PDF nao inicia com assinatura %PDF"
      ))
    }

    # Extrair contagem de páginas (> 0)
    pages <- extract_pdf_page_count(raw_bytes = raw_bytes)
    if (is.na(pages) || pages <= 0) {
      return(list(
        valid = FALSE,
        detected_media_type = "application/pdf",
        page_count = NA_integer_,
        integrity_status = "quarantined",
        error_code = "PDF_ZERO_PAGES",
        error_message = "PDF valido nao possui paginas legiveis detectadas"
      ))
    }
    page_count <- as.integer(pages)
  }

  # Sucesso: conteúdo aceito e verificado
  list(
    valid = TRUE,
    detected_media_type = real_mime,
    page_count = page_count,
    integrity_status = "verified",
    error_code = NA_character_,
    error_message = NA_character_
  )
}
