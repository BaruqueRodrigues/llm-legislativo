testthat::test_that("recibo remoto verificado preserva identidade sem blob local", {
  repo_root <- normalizePath(if (file.exists("AGENTS.md")) "." else "..")
  source(file.path(repo_root, "R/inventory/common/cloud_storage.R"), local = TRUE)
  root <- tempfile("cloud_receipt_")
  on.exit(unlink(root, recursive = TRUE), add = TRUE)
  sha <- paste(rep("a", 64), collapse = "")
  relative <- paste0("raw/sha256/aa/", sha, ".bin")
  path <- file.path(root, "staging/cloud_storage/objects", paste0(relative, ".json"))
  dir.create(dirname(path), recursive = TRUE)
  config <- jsonlite::fromJSON(file.path(repo_root, "configs/storage/drive.json"))
  value <- list(status = "verified", sha256 = sha, raw_path = relative, size_bytes = 15,
                folder_id = config$folder_id, remote = config$remote, offset_bytes = 0,
                storage_kind = "pack_v1", verification = "sha256_remote_stream",
                remote_path = paste0(config$remote, ":", config$remote_data_dir, "/packs/", sha, ".pack"))
  jsonlite::write_json(value, path, auto_unbox = TRUE)
  testthat::expect_true(cloud_blob_archived(relative, sha, root))
  testthat::expect_false(file.exists(file.path(root, relative)))
  testthat::expect_false(cloud_blob_archived(relative, paste(rep("b", 64), collapse = ""), root))
  testthat::expect_false(cloud_blob_archived("../escape", sha, root))
  value$folder_id <- "another_folder"
  jsonlite::write_json(value, path, auto_unbox = TRUE)
  testthat::expect_false(cloud_blob_archived(relative, sha, root))
  writeLines("{broken", path)
  testthat::expect_false(cloud_blob_archived(relative, sha, root))
})
