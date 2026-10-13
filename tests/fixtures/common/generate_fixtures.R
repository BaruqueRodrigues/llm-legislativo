# tests/fixtures/common/generate_fixtures.R
# Gerador de fixtures sintéticas canônicas (SYN001–SYN006, cross-house, cross-year)
# Conforme docs/CONTRATOS_DADOS.md (Seção 10) e docs/VALIDACAO.md

suppressPackageStartupMessages({
  library(arrow)
  library(dplyr)
  library(digest)
})

repo_root <- getwd()
while (!file.exists(file.path(repo_root, "AGENTS.md")) && repo_root != dirname(repo_root)) {
  repo_root <- dirname(repo_root)
}

source(file.path(repo_root, "schemas", "arrow_schemas.R"))

source(file.path(repo_root, "R", "inventory", "common", "hashing.R"))
source(file.path(repo_root, "R", "inventory", "common", "id_builders.R"))
source(file.path(repo_root, "R", "inventory", "common", "storage.R"))

output_dir <- file.path(repo_root, "tests", "fixtures", "common")

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

cat("Gerando fixtures sintéticas normativas em:", output_dir, "\n")

# 1. source_snapshots
snapshots_df <- tibble(
  snapshot_id = c("SYN-SNAPSHOT-1", "SYN-SNAPSHOT-SENADO-1"),
  house = c("camara", "senado"),
  source_kind = c("api", "api"),
  request_url = c("https://dadosabertos.camara.leg.br/api/v2/proposicoes", "https://legis.senado.leg.br/dadosabertos/v3/processo"),
  query_json = c("{\"siglaTipo\": \"PL\"}", "{\"ano\": 2023}"),
  collected_at = as.POSIXct(c("2026-10-07 10:00:00", "2026-10-07 10:00:00"), tz = "UTC"),
  http_status = c(200L, 200L),
  payload_sha256 = c(hash_string("payload_camara_mock"), hash_string("payload_senado_mock")),
  raw_path = c("sources/camara/SYN-SNAPSHOT-1/data.json", "sources/senado/SYN-SNAPSHOT-SENADO-1/data.json"),
  pagination_complete = c(TRUE, TRUE),
  source_schema_version = c("0.4.344", "4.1.3.99"),
  license_evidence_id = c("EVID-001", "EVID-002")
)

# 2. propositions
propositions_df <- tibble(
  proposition_id = c(
    "camara:prop:SYN001",
    "camara:prop:SYN002",
    "camara:prop:SYN003",
    "camara:prop:SYN004",
    "camara:prop:SYN005",
    "camara:prop:SYN006",
    "camara:prop:100",           # Teste de colisão entre casas
    "senado:prop:processo:100"    # Mesmo número no Senado
  ),
  house = c("camara", "camara", "camara", "camara", "camara", "camara", "camara", "senado"),
  source_id = c("SYN001", "SYN002", "SYN003", "SYN004", "SYN005", "SYN006", "100", "100"),
  type_code = c("PL", "PL", "PL", "PL", "PL", "PL", "PL", "PL"),
  type_source_id = rep(NA_character_, 8),
  type_label = c(rep("Projeto de Lei", 7), "Projeto de Lei"),
  legislative_type_id = rep(NA_character_, 8),
  source_namespace = c(rep("api", 7), "processo"),
  number = c(1L, 2L, 3L, 4L, 5L, 6L, 100L, 100L),
  numbering_year = c(2023L, 2023L, 2023L, 2023L, 2021L, 2024L, 2023L, 2023L),
  number_raw = c("1", "2", "3", "4", "5", "6", "100", "100"),
  identifier_label = c("PL 1/2023", "PL 2/2023", "PL 3/2023", "PL 4/2023", "PL 5/2021", "PL 6/2024", "PL 100/2023 (CD)", "PL 100/2023 (SF)"),
  presentation_date = as.Date(c("2023-03-15", "2023-03-15", "2023-03-16", "2023-03-17", "2021-05-10", "2024-02-01", "2023-01-10", "2023-01-10")),
  presentation_raw = c("2023-03-15", "2023-03-15", "2023-03-16", "2023-03-17", "2021-05-10", "2024-02-01", "2023-01-10", "2023-01-10"),
  origin_house = rep(NA_character_, 8),
  legislative_body = c(rep("Câmara dos Deputados", 7), "Senado Federal"),
  title = rep(NA_character_, 8),
  summary = c(
    "Ementa sintética 1", "Ementa sintética 2 (dup)", "Ementa sintética 3 (variante)",
    "Ementa sintética 4 (invalida)", "Ementa sintética 5 (antiga)", "Ementa sintética 6 (recente)",
    "Ementa CD 100", "Ementa SF 100"
  ),
  source_uri = c(
    "https://camara.leg.br/proposicoes/SYN001", "https://camara.leg.br/proposicoes/SYN002",
    "https://camara.leg.br/proposicoes/SYN003", "https://camara.leg.br/proposicoes/SYN004",
    "https://camara.leg.br/proposicoes/SYN005", "https://camara.leg.br/proposicoes/SYN006",
    "https://camara.leg.br/proposicoes/100", "https://senado.leg.br/processo/100"
  ),
  whole_text_url = rep(NA_character_, 8),
  snapshot_id = c(rep("SYN-SNAPSHOT-1", 7), "SYN-SNAPSHOT-SENADO-1"),
  cohort_status = c("included", "included", "included", "included", "included", "included", "included", "included"),
  cohort_reason = rep("fixture sintética canônica", 8)
)

# 3. authors e proposition_authors (demonstrando que 2 autores e 2 temas NÃO multiplicam textos)
authors_df <- tibble(
  author_id = c("camara:author:A001", "camara:author:A002", "senado:author:S001"),
  house = c("camara", "camara", "senado"),
  source_id = c("A001", "A002", "S001"),
  name = c("Deputado Alfa", "Deputado Beta", "Senador Gama"),
  author_type = c("deputado", "deputado", "senador"),
  source_uri = rep(NA_character_, 3),
  snapshot_id = c("SYN-SNAPSHOT-1", "SYN-SNAPSHOT-1", "SYN-SNAPSHOT-SENADO-1")
)

prop_authors_df <- tibble(
  proposition_id = c("camara:prop:SYN001", "camara:prop:SYN001"),
  author_id = c("camara:author:A001", "camara:author:A002"),
  role = c("autor", "coautor"),
  is_proponent = c(TRUE, FALSE),
  signature_order = c(1L, 2L),
  snapshot_id = c("SYN-SNAPSHOT-1", "SYN-SNAPSHOT-1")
)

# 4. themes e proposition_themes
themes_df <- tibble(
  theme_id = c("camara:theme:T10", "camara:theme:T20"),
  house = c("camara", "camara"),
  source_id = c("T10", "T20"),
  name = c("Direito Penal", "Administração Pública"),
  snapshot_id = c("SYN-SNAPSHOT-1", "SYN-SNAPSHOT-1")
)

prop_themes_df <- tibble(
  proposition_id = c("camara:prop:SYN001", "camara:prop:SYN001"),
  theme_id = c("camara:theme:T10", "camara:theme:T20"),
  relevance = c("principal", "secundario"),
  snapshot_id = c("SYN-SNAPSHOT-1", "SYN-SNAPSHOT-1")
)

# 5. documents
documents_df <- tibble(
  document_id = c(
    "camara:doc:api:D001",
    "camara:doc:api:D002",
    "camara:doc:api:D003",
    "camara:doc:api:D004",
    "camara:doc:api:D005",
    "camara:doc:api:D006"
  ),
  house = rep("camara", 6),
  source_document_id = c("D001", "D002", "D003", "D004", "D005", "D006"),
  source_namespace = rep("api", 6),
  identity_url = paste0("https://example.invalid/docs/D00", 1:6, ".pdf"),
  document_type = rep("inteiro_teor", 6),
  document_type_source_id = rep(NA_character_, 6),
  legislative_type_id = rep(NA_character_, 6),
  legislative_body = rep("Câmara dos Deputados", 6),
  normalized_kind = c("initial", "initial", "initial", "initial", "initial", "initial"),
  publication_date = as.Date(c("2023-03-15", "2023-03-15", "2023-03-16", "2023-03-17", "2021-05-10", "2024-02-01")),
  date_range_start = rep(as.Date(NA), 6),
  date_range_end = rep(as.Date(NA), 6),
  date_status = rep("verified", 6),
  source_uri = paste0("https://example.invalid/docs/D00", 1:6),
  snapshot_id = rep("SYN-SNAPSHOT-1", 6)
)

# 6. proposition_documents
prop_documents_df <- tibble(
  proposition_id = paste0("camara:prop:SYN00", 1:6),
  document_id = paste0("camara:doc:api:D00", 1:6),
  document_role = rep("initial_with_justification", 6),
  role_status = rep("verified", 6),
  role_evidence = rep("apresentação oficial", 6),
  document_date = as.Date(c("2023-03-15", "2023-03-15", "2023-03-16", "2023-03-17", "2021-05-10", "2024-02-01")),
  source_order = rep(1L, 6),
  snapshot_id = rep("SYN-SNAPSHOT-1", 6)
)

# 7. Textos substantivos
text_syn001 <- "PROJETO DE LEI\nArt. 1º Fica instituído o programa exemplo.\n\nJUSTIFICAÇÃO\nEsta é uma justificativa sintética."
text_syn002 <- text_syn001 # Duplicata exata
text_syn003 <- "PROJETO DE LEI\nArt. 1º Fica revogado o programa exemplo.\n\nJUSTIFICAÇÃO\nEsta é uma justificativa sintética." # Variante substantiva
text_syn005 <- "PROJETO DE LEI\nArt. 1º Norma antiga de 2021.\n\nJUSTIFICAÇÃO\nJustificativa 2021."
text_syn006 <- "PROJETO DE LEI\nArt. 1º Norma recente de 2024.\n\nJUSTIFICAÇÃO\nJustificativa 2024."

hash_syn001 <- hash_string(text_syn001)
hash_syn002 <- hash_string(text_syn002)
hash_syn003 <- hash_string(text_syn003)
hash_syn005 <- hash_string(text_syn005)
hash_syn006 <- hash_string(text_syn006)

# 8. curated_documents (SYN001-SYN006)
# SYN001: representante elegível
# SYN002: duplicate de SYN001 (auditável, include_in_dataset = FALSE, representative = SYN001)
# SYN003: variante substantiva (include_in_dataset = TRUE, representative = SYN003, mesma família de SYN001 se relacionados)
# SYN004: não tem curated_document pois PDF falhou (quarantined em extraction/curation)
# SYN005 e SYN006: versões antes e depois do corte temporal
curated_docs_df <- tibble(
  corpus_item_id = c(
    paste0("item:syn001:", substr(hash_syn001, 1, 12)),
    paste0("item:syn002:", substr(hash_syn002, 1, 12)),
    paste0("item:syn003:", substr(hash_syn003, 1, 12)),
    paste0("item:syn005:", substr(hash_syn005, 1, 12)),
    paste0("item:syn006:", substr(hash_syn006, 1, 12))
  ),
  primary_proposition_id = c("camara:prop:SYN001", "camara:prop:SYN002", "camara:prop:SYN003", "camara:prop:SYN005", "camara:prop:SYN006"),
  document_id = c("camara:doc:api:D001", "camara:doc:api:D002", "camara:doc:api:D003", "camara:doc:api:D005", "camara:doc:api:D006"),
  house = rep("camara", 5),
  normalized_kind = rep("initial", 5),
  content_date = as.Date(c("2023-03-15", "2023-03-15", "2023-03-16", "2021-05-10", "2024-02-01")),
  content_date_start = as.Date(rep(NA, 5)),
  content_date_end = as.Date(rep(NA, 5)),
  temporal_date_evidence = rep("document_date", 5),
  temporal_date_status = rep("verified", 5),
  version_id = c(
    build_version_id("camara:doc:api:D001", hash_string("bin1")),
    build_version_id("camara:doc:api:D002", hash_string("bin2")),
    build_version_id("camara:doc:api:D003", hash_string("bin3")),
    build_version_id("camara:doc:api:D005", hash_string("bin5")),
    build_version_id("camara:doc:api:D006", hash_string("bin6"))
  ),
  extraction_id = paste0("ext:run:00", c(1, 2, 3, 5, 6)),
  composition_id = rep("comp_standard_v1", 5),
  logical_unit_id = c("camara:doc:api:D001", "camara:doc:api:D002", "camara:doc:api:D003", "camara:doc:api:D005", "camara:doc:api:D006"),
  source_span_start = rep(0L, 5),
  source_span_end = as.integer(c(nchar(text_syn001), nchar(text_syn002), nchar(text_syn003), nchar(text_syn005), nchar(text_syn006))),
  text = c(text_syn001, text_syn002, text_syn003, text_syn005, text_syn006),
  text_sha256 = c(hash_syn001, hash_syn002, hash_syn003, hash_syn005, hash_syn006),
  comparison_sha256 = c(hash_syn001, hash_syn002, hash_syn003, hash_syn005, hash_syn006),
  utf8_bytes = as.integer(c(nchar(text_syn001, type="bytes"), nchar(text_syn002, type="bytes"), nchar(text_syn003, type="bytes"), nchar(text_syn005, type="bytes"), nchar(text_syn006, type="bytes"))),
  character_count = as.integer(c(nchar(text_syn001), nchar(text_syn002), nchar(text_syn003), nchar(text_syn005), nchar(text_syn006))),
  cleaning_version = rep("clean_v1", 5),
  presentation_date = as.Date(c("2023-03-15", "2023-03-15", "2023-03-16", "2021-05-10", "2024-02-01")),
  quality_status = rep("accepted", 5),
  eligibility_reason = c("representante original", "duplicata exata de SYN001", "variante substantiva", "elegivel", "elegivel"),
  exact_cluster_id = c("cl_exact_1", "cl_exact_1", "cl_exact_3", "cl_exact_5", "cl_exact_6"),
  family_id = c("fam_001", "fam_001", "fam_001", "fam_005_cross", "fam_005_cross"),
  near_cluster_id = rep(NA_character_, 5),
  representative_item_id = c(
    paste0("item:syn001:", substr(hash_syn001, 1, 12)),
    paste0("item:syn001:", substr(hash_syn001, 1, 12)),  # SYN002 aponta para SYN001
    paste0("item:syn003:", substr(hash_syn003, 1, 12)),
    paste0("item:syn005:", substr(hash_syn005, 1, 12)),
    paste0("item:syn006:", substr(hash_syn006, 1, 12))
  ),
  include_in_dataset = c(TRUE, FALSE, TRUE, TRUE, TRUE),
  permission_status = rep("allowed", 5)
)

# 9. split_assignments
split_assignments_df <- tibble(
  split_version = rep("split_v1", 5),
  corpus_item_id = curated_docs_df$corpus_item_id,
  family_id = curated_docs_df$family_id,
  split = c("train", "train", "train", "quarantine", "quarantine"),
  policy = c("group_hash", "group_hash", "group_hash", "temporal_purged", "temporal_purged"),
  assignment_reason = c(
    "fam_001 sorteada para train",
    "fam_001 sorteada para train",
    "fam_001 sorteada para train",
    "fam_005_cross cruza corte temporal 2022/2023",
    "fam_005_cross cruza corte temporal 2022/2023"
  ),
  seed = rep(42L, 5),
  temporal_cut_train = rep(as.Date("2022-12-31"), 5),
  temporal_cut_validation = rep(as.Date("2023-12-31"), 5)
)

# Gravar todas as tabelas em Parquet usando write_contract_parquet
write_contract_parquet(snapshots_df, "source_snapshots", file.path(output_dir, "source_snapshots.parquet"))
write_contract_parquet(propositions_df, "propositions", file.path(output_dir, "propositions.parquet"))
write_contract_parquet(authors_df, "authors", file.path(output_dir, "authors.parquet"))
write_contract_parquet(prop_authors_df, "proposition_authors", file.path(output_dir, "proposition_authors.parquet"))
write_contract_parquet(themes_df, "themes", file.path(output_dir, "themes.parquet"))
write_contract_parquet(prop_themes_df, "proposition_themes", file.path(output_dir, "proposition_themes.parquet"))
write_contract_parquet(documents_df, "documents", file.path(output_dir, "documents.parquet"))
write_contract_parquet(prop_documents_df, "proposition_documents", file.path(output_dir, "proposition_documents.parquet"))
write_contract_parquet(curated_docs_df, "curated_documents", file.path(output_dir, "curated_documents.parquet"))
write_contract_parquet(split_assignments_df, "split_assignments", file.path(output_dir, "split_assignments.parquet"))

cat("Fixtures sintéticas geradas com sucesso em Parquet!\n")
