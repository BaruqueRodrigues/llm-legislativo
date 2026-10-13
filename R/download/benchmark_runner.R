# Worker isolado do benchmark; a janela é controlada pelo supervisor Python.
args <- commandArgs(trailingOnly=TRUE)
root <- args[[1]]; source_path <- args[[2]]; queue_path <- args[[3]]; workers <- as.integer(args[[4]])
Sys.setenv(DATA_ROOT=root,LLM_DO_ZERO_MIN_FREE_GIB="10",LLM_DOWNLOAD_CACHE="0")
source("R/download/validator.R")
source("R/inventory/common/hashing.R")
source("R/inventory/common/storage.R")
source("R/download/blob_store.R")
source(source_path)
dir.create(root,recursive=TRUE,showWarnings=FALSE)
writeLines("ready",file.path(root,"READY"))
while (!file.exists(file.path(root,"START"))) Sys.sleep(0.05)
tryCatch(download_camara_documents_for_year(queue_path,2026L,root,file.path(root,"stage"),max_concurrency=workers),
  interrupt=function(e) cat("Benchmark interrompido ao fim da janela.\n"))
