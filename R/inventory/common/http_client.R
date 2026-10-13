# R/inventory/common/http_client.R
# Cliente HTTP resiliente com retries, backoff exponencial, jitter e registro de tentativas

suppressPackageStartupMessages({
  library(httr2)
  library(jsonlite)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}
source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))




perform_resilient_request <- function(url,
                                      method = "GET",
                                      headers = list(),
                                      query = list(),
                                      max_retries = 5,
                                      backoff_base = 1.5,
                                      timeout_seconds = 60,
                                      user_agent = "LLM-Legislativo/2.0") {
  attempt <- 1
  resp <- NULL
  err <- NULL

  req <- request(url) %>%
    req_method(method) %>%
    req_user_agent(user_agent) %>%
    req_timeout(timeout_seconds)

  if (length(headers) > 0) {
    req <- do.call(req_headers, c(list(req), headers))
  }
  if (length(query) > 0) {
    req <- req_url_query(req, !!!query)
  }

  started_at <- Sys.time()

  while (attempt <= max_retries) {
    res <- tryCatch({
      resp <- req_perform(req)
      list(success = TRUE, response = resp, error = NULL)
    }, error = function(e) {
      list(success = FALSE, response = NULL, error = e)
    })

    if (res$success) {
      status <- resp_status(res$response)
      if (status < 400) {
        return(list(
          status = "succeeded",
          http_status = status,
          response = res$response,
          attempts = attempt,
          started_at = started_at,
          finished_at = Sys.time()
        ))
      } else if (status %in% c(429, 500, 502, 503, 504)) {
        # Retryable HTTP status
        retry_after <- resp_header(res$response, "retry-after")
        wait_sec <- if (!is.null(retry_after) && !is.na(as.numeric(retry_after))) {
          as.numeric(retry_after)
        } else {
          (backoff_base ^ attempt) + stats::runif(1, 0.1, 0.5)
        }
        Sys.sleep(min(wait_sec, 30))
      } else {
        # Terminal error (e.g. 404, 401, 403, 410)
        return(list(
          status = "terminal_error",
          http_status = status,
          response = res$response,
          attempts = attempt,
          error_message = paste("HTTP terminal error:", status),
          started_at = started_at,
          finished_at = Sys.time()
        ))
      }
    } else {
      # Connection / network error
      wait_sec <- (backoff_base ^ attempt) + stats::runif(1, 0.1, 0.5)
      Sys.sleep(min(wait_sec, 30))
    }
    attempt <- attempt + 1
  }

  list(
    status = "retryable_error_exhausted",
    http_status = if (!is.null(resp)) resp_status(resp) else NA_integer_,
    response = resp,
    attempts = attempt - 1,
    error_message = if (!is.null(res$error)) conditionMessage(res$error) else "Retries exhausted",
    started_at = started_at,
    finished_at = Sys.time()
  )
}

validate_pdf_magic <- function(raw_bytes) {
  if (length(raw_bytes) < 4) return(FALSE)
  header <- rawToChar(raw_bytes[1:4])
  return(header == "%PDF")
}
