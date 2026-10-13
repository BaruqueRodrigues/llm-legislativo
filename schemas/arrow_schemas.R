# schemas/arrow_schemas.R
# Definição normativa dos esquemas Arrow para todas as tabelas do projeto legislm
# Conforme docs/CONTRATOS_DADOS.md (Proposta 2.0.0)

suppressPackageStartupMessages({
  library(arrow)
})

get_arrow_schemas <- function() {
  list(
    source_snapshots = schema(
      snapshot_id = string(),
      house = string(),
      source_kind = string(),
      request_url = string(),
      query_json = string(),
      collected_at = timestamp(unit = "us", timezone = "UTC"),
      http_status = int32(),
      payload_sha256 = string(),
      raw_path = string(),
      pagination_complete = boolean(),
      source_schema_version = string(),
      license_evidence_id = string()
    ),

    propositions = schema(
      proposition_id = string(),
      house = string(),
      source_id = string(),
      type_code = string(),
      type_source_id = string(),
      type_label = string(),
      legislative_type_id = string(),
      source_namespace = string(),
      number = int32(),
      numbering_year = int32(),
      number_raw = string(),
      identifier_label = string(),
      presentation_date = date32(),
      presentation_raw = string(),
      origin_house = string(),
      legislative_body = string(),
      title = string(),
      summary = string(),
      source_uri = string(),
      whole_text_url = string(),
      snapshot_id = string(),
      cohort_status = string(),
      cohort_reason = string()
    ),

    authors = schema(
      author_id = string(),
      house = string(),
      source_id = string(),
      name = string(),
      author_type = string(),
      source_uri = string(),
      snapshot_id = string()
    ),

    proposition_authors = schema(
      proposition_id = string(),
      author_id = string(),
      role = string(),
      is_proponent = boolean(),
      signature_order = int32(),
      snapshot_id = string()
    ),

    document_authors = schema(
      document_id = string(),
      author_id = string(),
      role = string(),
      signature_order = int32(),
      source_uri = string(),
      snapshot_id = string()
    ),

    themes = schema(
      theme_id = string(),
      house = string(),
      source_id = string(),
      name = string(),
      snapshot_id = string()
    ),

    proposition_themes = schema(
      proposition_id = string(),
      theme_id = string(),
      relevance = string(),
      snapshot_id = string()
    ),

    metadata_checks = schema(
      entity_kind = string(),
      entity_id = string(),
      endpoint_kind = string(),
      status = string(),
      snapshot_id = string(),
      last_checked_at = timestamp(unit = "us", timezone = "UTC"),
      reason = string()
    ),

    relations = schema(
      relation_id = string(),
      source_proposition_id = string(),
      target_proposition_id = string(),
      relation_type = string(),
      snapshot_id = string(),
      source_uri = string(),
      grouping_policy = string()
    ),

    process_phases = schema(
      phase_id = string(),
      process_proposition_id = string(),
      house = string(),
      source_namespace = string(),
      source_phase_id = string(),
      phase_kind = string(),
      legislative_body = string(),
      committee_source_id = string(),
      number_raw = string(),
      type_code = string(),
      numbering_year = int32(),
      date_start = date32(),
      date_end = date32(),
      source_uri = string(),
      snapshot_id = string()
    ),

    document_phases = schema(
      document_id = string(),
      phase_id = string(),
      role = string(),
      evidence = string(),
      snapshot_id = string()
    ),

    documents = schema(
      document_id = string(),
      house = string(),
      source_document_id = string(),
      source_namespace = string(),
      identity_url = string(),
      document_type = string(),
      document_type_source_id = string(),
      legislative_type_id = string(),
      legislative_body = string(),
      normalized_kind = string(),
      publication_date = date32(),
      date_range_start = date32(),
      date_range_end = date32(),
      date_status = string(),
      source_uri = string(),
      snapshot_id = string()
    ),

    proposition_documents = schema(
      proposition_id = string(),
      document_id = string(),
      document_role = string(),
      role_status = string(),
      role_evidence = string(),
      document_date = date32(),
      source_order = int32(),
      snapshot_id = string()
    ),

    document_versions = schema(
      version_id = string(),
      document_id = string(),
      file_sha256 = string(),
      raw_path = string(),
      file_size_bytes = int64(),
      detected_media_type = string(),
      page_count = int32(),
      version_kind = string(),
      source_version_label = string(),
      source_content_date = date32(),
      availability_date = date32(),
      version_date_status = string(),
      predecessor_version_id = string(),
      first_capture_id = string(),
      integrity_status = string()
    ),

    fetch_attempts = schema(
      capture_id = string(),
      document_id = string(),
      requested_url = string(),
      final_url = string(),
      started_at = timestamp(unit = "us", timezone = "UTC"),
      finished_at = timestamp(unit = "us", timezone = "UTC"),
      attempt_no = int32(),
      http_status = int32(),
      declared_media_type = string(),
      declared_size_bytes = int64(),
      received_size_bytes = int64(),
      file_sha256 = string(),
      version_id = string(),
      status = string(),
      error_code = string(),
      error_message = string(),
      next_retry_at = timestamp(unit = "us", timezone = "UTC")
    ),

    use_evidence = schema(
      evidence_id = string(),
      source_uri = string(),
      accessed_at = timestamp(unit = "us", timezone = "UTC"),
      snapshot_id = string(),
      applies_to = string(),
      permission_status = string(),
      attribution_rule = string(),
      redistribution_rule = string(),
      review_note = string()
    ),

    source_collections = schema(
      collection_id = string(),
      house = string(),
      source_namespace = string(),
      name = string(),
      collection_kind = string(),
      catalog_uri = string(),
      snapshot_id = string(),
      inventory_unit = string(),
      digital_availability_note = string()
    ),

    legislative_types = schema(
      legislative_type_id = string(),
      house = string(),
      source_namespace = string(),
      type_source_id = string(),
      type_code = string(),
      type_label = string(),
      entity_kind = string(),
      normalized_family = string(),
      mapping_status = string(),
      snapshot_id = string()
    ),

    coverage_segments = schema(
      segment_id = string(),
      collection_id = string(),
      house = string(),
      legislative_type_id = string(),
      year = int32(),
      period_start = date32(),
      period_end = date32(),
      date_axis = string(),
      snapshot_cutoff_utc = timestamp(unit = "us", timezone = "UTC"),
      query_json = string(),
      inventory_status = string(),
      coverage_status = string(),
      expected_count = int64(),
      discovered_count = int64(),
      retrieved_count = int64(),
      accepted_count = int64(),
      count_unit = string(),
      exhaustion_evidence = string(),
      gap_reason = string(),
      snapshot_id = string()
    ),

    collection_documents = schema(
      collection_id = string(),
      document_id = string(),
      source_catalog_id = string(),
      reference_code = string(),
      volume_label = string(),
      issue_label = string(),
      source_order = int32(),
      snapshot_id = string()
    ),

    entity_aliases = schema(
      alias_id = string(),
      entity_kind = string(),
      alias_namespace = string(),
      alias_source_id = string(),
      canonical_entity_id = string(),
      evidence_uri = string(),
      snapshot_id = string(),
      status = string()
    ),

    extraction_runs = schema(
      extraction_id = string(),
      version_id = string(),
      extraction_config_hash = string(),
      tool_versions_json = string(),
      host_os_build = string(),
      helper_source_sha256 = string(),
      started_at = timestamp(unit = "us", timezone = "UTC"),
      status = string(),
      error_code = string()
    ),

    pages = schema(
      extraction_id = string(),
      page_index = int32(),
      method = string(),
      engine = string(),
      engine_revision = string(),
      recognition_level = string(),
      recognition_languages_json = string(),
      uses_language_correction = boolean(),
      render_width = int32(),
      render_height = int32(),
      elapsed_ms = float64(),
      raw_text = string(),
      raw_text_sha256 = string(),
      character_count = int64(),
      replacement_char_ratio = float64(),
      printable_ratio = float64(),
      image_area_ratio = float64(),
      ocr_confidence = float64(),
      layout_path = string(),
      layout_sha256 = string(),
      quality_status = string(),
      quality_reasons_json = string()
    ),

    sections = schema(
      section_id = string(),
      extraction_id = string(),
      ordinal = int32(),
      section_type = string(),
      page_start = int32(),
      page_end = int32(),
      start_char = int64(),
      end_char = int64(),
      detection_method = string(),
      confidence = float64(),
      review_status = string(),
      text = string()
    ),

    curated_documents = schema(
      corpus_item_id = string(),
      primary_proposition_id = string(),
      document_id = string(),
      house = string(),
      normalized_kind = string(),
      content_date = date32(),
      content_date_start = date32(),
      content_date_end = date32(),
      temporal_date_evidence = string(),
      temporal_date_status = string(),
      version_id = string(),
      extraction_id = string(),
      composition_id = string(),
      logical_unit_id = string(),
      source_span_start = int64(),
      source_span_end = int64(),
      text = string(),
      text_sha256 = string(),
      comparison_sha256 = string(),
      utf8_bytes = int64(),
      character_count = int64(),
      cleaning_version = string(),
      presentation_date = date32(),
      quality_status = string(),
      eligibility_reason = string(),
      exact_cluster_id = string(),
      family_id = string(),
      near_cluster_id = string(),
      representative_item_id = string(),
      include_in_dataset = boolean(),
      permission_status = string()
    ),

    corpus_item_propositions = schema(
      corpus_item_id = string(),
      proposition_id = string(),
      link_type = string(),
      grouping_policy = string(),
      evidence = string()
    ),

    curated_document_sections = schema(
      corpus_item_id = string(),
      section_id = string(),
      output_order = int32(),
      included = boolean(),
      reason = string()
    ),

    dedup_pairs = schema(
      left_item_id = string(),
      right_item_id = string(),
      method = string(),
      similarity = float64(),
      decision = string(),
      evidence = string(),
      policy_version = string()
    ),

    cleaning_events = schema(
      event_id = string(),
      corpus_item_id = string(),
      rule_id = string(),
      before_sha256 = string(),
      after_sha256 = string(),
      affected_spans_json = string(),
      reason = string()
    ),

    quality_reviews = schema(
      review_id = string(),
      extraction_id = string(),
      corpus_item_id = string(),
      page_index = int32(),
      reviewer = string(),
      sample_seed = int64(),
      stratum = string(),
      result = string(),
      cer = float64(),
      wer = float64(),
      reviewed_at = timestamp(unit = "us", timezone = "UTC"),
      notes = string()
    ),

    split_assignments = schema(
      split_version = string(),
      corpus_item_id = string(),
      family_id = string(),
      split = string(),
      policy = string(),
      assignment_reason = string(),
      seed = int64(),
      temporal_cut_train = date32(),
      temporal_cut_validation = date32()
    )
  )
}
