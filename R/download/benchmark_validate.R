# Verificação independente, posterior à janela cronometrada.
args <- commandArgs(trailingOnly=TRUE)
base <- normalizePath(args[[1]])
suppressPackageStartupMessages(library(pdftools))
for (variant in c("base_4","optimized_20","optimized_40")) {
  root <- file.path(base,variant)
  paths <- list.files(file.path(root,"raw","sha256"),pattern="\\.bin$",recursive=TRUE,full.names=TRUE)
  results <- vector("list",length(paths))
  for (i in seq_along(paths)) {
    path <- paths[[i]]; con <- file(path,"rb"); header <- readBin(con,"raw",n=5L); close(con)
    is_pdf <- length(header)==5L && identical(header,charToRaw("%PDF-"))
    info <- if (is_pdf) tryCatch(suppressWarnings(suppressMessages(pdf_info(path))),error=function(e)e) else NULL
    valid <- is_pdf && !inherits(info,"error") && !is.null(info$pages) && info$pages>0
    results[[i]] <- data.frame(sha256=sub("\\.bin$","",basename(path)),is_pdf=is_pdf,
      pdf_parser_valid=valid,page_count=if (valid) info$pages else NA_integer_,
      parser_error=if (inherits(info,"error")) conditionMessage(info) else NA_character_)
    if (i%%500L==0L) cat(variant,":",i,"/",length(paths),"\n")
  }
  if (length(results)) write.csv(do.call(rbind,results),file.path(root,"pdf_parser_checks.csv"),row.names=FALSE,na="")
  cat(variant,": parser concluído;",length(paths),"blobs\n")
}
