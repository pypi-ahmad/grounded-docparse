# Graph Report - .  (2026-08-12)

## Corpus Check
- Large corpus: 356 files · ~904,216 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 2110 nodes · 7584 edges · 173 communities (113 shown, 60 thin omitted)
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 2127 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- OpenAIDocumentGateway
- PageEvidence
- pipeline.py
- ParserConfig
- quality.py
- Runtime
- PageAnalyzer
- Document
- init .py
- RunUsage
- ingest.py
- config.py
- PageInspection
- properties
- DocumentExtractor
- Block
- RegionDraft
- regression-policy-v1.schema.json
- ParseResult
- extraction.py
- docling native.py
- streamlit app.py
- WorkspaceStore
- models.py
- Document Processing Pipeline
- ValueError
- Quarterly Table
- DocumentAgent
- ClassifierProfile
- NativeDocument
- Native Document Model
- build docs site.py
- benchmark.py
- Install-GroundedDocParse.ps1
- refresh knowledge wiki.py
- Any
- test evaluation metrics.py
- AgenticAnalysis
- load corpus manifest()
- test schema store.py
- test docling native parser.py
- cli.py
- Synthetic Native Text Fixture
- live report()
- evaluate live document()
- enhancement.py
- schema store.py
- properties 2
- LangExtractNativeExtractor
- SchemaStore
- ua-assemble-final.cjs
- manifest-v1.1.schema.json
- manage-ocr-stack.sh
- Synthetic Options
- source
- source 2
- Native PDF Pipeline
- Document Parse Studio
- launch-stack.sh
- required
- enum
- Manual Document Routing
- generate corpus()
- prepare()
- properties 3
- properties 4
- properties 5
- Explicit Processing Type Routing
- prepare paddleocr runtime.py
- run-app.sh
- evaluate regression policy()
- test paddle runtime config.py
- Processing Types and Manual Routing
- SourceAnchor API
- RuntimeError
- test knowledge wiki.py
- manifest-v1.schema.json
- items
- External Integrations
- main()
- setup-ollama.sh
- Unicode Identifier Register
- manifest.json
- required 2
- required 3
- Immutable Evidence Spine
- Supported Local Setup
- serve-ollama.sh
- setup-paddleocr.sh
- .extract forms()
- features
- type
- SourceAnchor
- Agentic Document Extraction Comparison
- Routing Contract Tests
- SourceAnchor Evidence
- main() 2
- serve-glmocr.sh
- setup-glmocr.sh
- Source Anchors and Character Spans
- Codebase Concerns
- Mixed PDF Review
- Layout-Aware Large Field Extraction Workflow
- main() 3
- Ingest CLI
- sanitize markdown preview()
- simple pdf()
- ua-fingerprint-input.cjs
- ua-tour-analyze.js
- Office and Native Formats
- Native Parser Constraints
- Human Control
- Public Contract Tests
- Technology Stack
- UniversalDocumentParser Boundary
- PaddleOCR-VL Runtime
- UniversalDocumentParser
- Bug Report Template Site Page
- Feature Request Template Site Page
- Local PaddleOCR-VL Runtime
- OCR Evidence Geometry
- Evaluation Corpus Manifest Query Rationale
- ua-arch-analyze.js
- ua-finalize.cjs
- ua-inline-validate.cjs
- Native Source Manifest
- Security Privacy and Trust Boundaries
- Graph Merge Report
- GLM-OCR Configuration
- Paddle vLLM Configuration
- Azure Bulk Fax Deployment
- Business User Workflow
- Complete User Guide
- Extraction Quality Research
- IDP versus ADE Classification
- Layout-Aware Large Field Workflow
- GLM-OCR Runtime
- Calibration and Holdout Evaluation
- Python API
- Documentation Site Favicon
- Azure Bulk Fax Deployment Site
- Business User Workflow Site Page
- Changelog Site Page
- Codebase Architecture Site Page
- Codebase Concerns Site Page
- Codebase Conventions Site Page
- Codebase Integrations Site Page
- Codebase Stack Site Page
- Codebase Structure Site Page
- Codebase Testing Site Page
- Contributing Site Page
- Extraction Quality Research Site Page
- Agentic Design Site Page
- Documentation Site Index
- Security Content Exclusion
- Wiki Operation Log
- Zero-to-Hero Tutorial Site Page
- grounded-docparse
- Trusted Local Workstation Boundary
- Wiki Authoring Contract
- Evaluation Corpus and Metrics
- Repository Architecture
- Native Document Model 2
- Installation and Local Runtimes
- Grounded DocParse Knowledge Wiki
- Native Ingestion Knowledge Snapshot

## God Nodes (most connected - your core abstractions)
1. `ParserConfig` - 192 edges
2. `Block` - 151 edges
3. `DocumentParser` - 147 edges
4. `Document` - 125 edges
5. `RegionDraft` - 115 edges
6. `RunUsage` - 109 edges
7. `PageEvidence` - 100 edges
8. `BoundingBox` - 99 edges
9. `PageDraft` - 96 edges
10. `PageInspection` - 94 edges

## Surprising Connections (you probably didn't know these)
- `Manual Document Routing` --semantically_similar_to--> `Explicit Document Routing`  [INFERRED] [semantically similar]
  README.md → docs/architecture.md
- `Immutable Base Text` --semantically_similar_to--> `SourceAnchor API`  [INFERRED] [semantically similar]
  README.md → docs/api.md
- `Grounded LangExtract` --semantically_similar_to--> `Exact Character Interval Validation`  [INFERRED] [semantically similar]
  README.md → docs/how-it-works.md
- `Architecture` --semantically_similar_to--> `Native PDF Pipeline`  [INFERRED] [semantically similar]
  docs-site/architecture.html → docs/spec.md
- `Complete User Guide` --semantically_similar_to--> `Mixed PDF Review`  [INFERRED] [semantically similar]
  docs-site/complete-user-guide.html → docs/tutorial.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Native Document Grounding Contract** — readme_manual_document_routing, readme_immutable_base_text, readme_grounded_langextract, docs_api_source_anchor [INFERRED 0.95]
- **Explicit Native Processing Routes** — readme_native_pdf_pipeline, readme_docling_native_conversion, readme_mixed_pdf_review, docs_architecture_explicit_document_routing [INFERRED 0.95]
- **Native Ingestion Evidence Contract** — docs_site_how_it_works_immutable_base_text, docs_site_how_it_works_source_anchor_evidence, docs_site_how_it_works_langextract_interval_validation [EXTRACTED 1.00]
- **Manual Native Route Workflow** — docs_site_how_it_works_explicit_processing_type_routing, docs_site_how_it_works_native_pdf_pipeline, docs_site_how_it_works_mixed_pdf_review, docs_site_how_it_works_docling_native_conversion [EXTRACTED 1.00]
- **Native Grounding Contract** — docs_site_wiki_articles_grounding_immutable_base_text_immutable_base_text, docs_site_wiki_articles_grounding_source_anchors_and_character_spans_source_anchors_and_character_spans, docs_site_wiki_articles_grounding_langextract_grounded_extraction_langextract_grounded_extraction, docs_site_wiki_articles_product_grounding_and_evidence_contract_grounding_and_evidence_contract [EXTRACTED 1.00]
- **Manual Routing Workflow** — docs_site_wiki_articles_product_processing_types_and_manual_routing_processing_types_and_manual_routing, docs_site_wiki_articles_interfaces_streamlit_workflow_streamlit_workflow, docs_site_wiki_articles_interfaces_cli_and_python_api_cli_and_python_api, docs_site_wiki_articles_pipelines_mixed_pdf_pipeline_mixed_pdf_pipeline [EXTRACTED 1.00]
- **Native and OCR Pipeline Boundaries** — docs_site_wiki_articles_pipelines_native_pdf_pipeline_native_pdf_pipeline, docs_site_wiki_articles_pipelines_docling_native_conversion_docling_native_conversion, docs_site_wiki_articles_pipelines_scanned_pdf_and_image_pipeline_scanned_pdf_and_image_pipeline, docs_site_wiki_articles_pipelines_ocr_quality_and_recovery_ocr_quality_and_recovery [EXTRACTED 1.00]
- **Native Document Assurance** — docs_codebase_explicit_routing, docs_codebase_immutable_evidence_spine, docs_codebase_native_contract_tests, wiki_articles_engineering_native_trust_boundary [INFERRED 0.95]
- **Grounded Native Extraction Pipeline** — docs_spec_manual_processing_type, docs_spec_native_pdf_pipeline, docs_spec_docling_native_conversion, docs_spec_immutable_base_text, docs_spec_source_anchor, docs_spec_langextract_grounding [EXTRACTED 1.00]
- **Native Extraction Grounding** — docs_codebase_langextract, wiki_articles_grounding_immutable_base_text, wiki_articles_grounding_exact_interval_acceptance, wiki_articles_grounding_native_document_model [INFERRED 0.95]
- **Native Evidence Model** — wiki_articles_grounding_source_anchors_and_character_spans_source_anchors, wiki_articles_product_grounding_and_evidence_contract_grounding_contract, wiki_articles_grounding_schema_translation_and_value_validation_schema_translation, wiki_articles_interfaces_workspace_persistence_and_exports_workspace_exports [EXTRACTED 1.00]
- **Manual Routing System** — wiki_articles_product_processing_types_and_manual_routing_manual_routing, wiki_articles_interfaces_cli_and_python_api_cli_api, wiki_articles_interfaces_streamlit_workflow_streamlit_workflow, wiki_articles_pipelines_mixed_pdf_pipeline_mixed_pdf [EXTRACTED 1.00]
- **Quantitative Fixture Representations** — benchmarks_corpus_v1_documents_cross_page_table_quarterly_table, benchmarks_corpus_v1_documents_figure_chart_units_by_period, benchmarks_corpus_v1_documents_tables_synthetic_inventory_table [INFERRED 0.75]
- **Document Parse Studio Workflow** — docs_site_assets_content_docs_images_document_parse_studio_full_document_upload, docs_site_assets_content_docs_images_document_parse_studio_full_parse_configuration, docs_site_assets_content_docs_images_document_parse_studio_full_document_parsing_pipeline, docs_site_assets_content_docs_images_document_parse_studio_full_parse_results [INFERRED 0.85]
- **Document Parse Studio Processing Stages** — docs_images_document_parse_studio_full_layout_detection, docs_images_document_parse_studio_full_region_recognition, docs_images_document_parse_studio_full_luna_visual_recovery, docs_images_document_parse_studio_full_base_markdown, docs_images_document_parse_studio_full_annotated_pdf, docs_images_document_parse_studio_full_luna_markdown_refinement, docs_images_document_parse_studio_full_document_classification, docs_images_document_parse_studio_full_table_of_contents [EXTRACTED 1.00]
- **Document Parse Studio Configurable Capabilities** — docs_images_document_parse_studio_full_reading_order, docs_images_document_parse_studio_full_ade_fast_mode, docs_images_document_parse_studio_full_hard_region_visual_recovery, docs_images_document_parse_studio_full_document_classification, docs_images_document_parse_studio_full_table_of_contents, docs_images_document_parse_studio_full_document_chat [EXTRACTED 1.00]
- **Document Parse Studio Result Views** — docs_images_document_parse_studio_full_markdown_output, docs_images_document_parse_studio_full_annotated_pdf, docs_images_document_parse_studio_full_layout_tree_output [EXTRACTED 1.00]
- **Agentic Document Control** — docs_agentic_controlled_document_workflow, docs_agentic_deterministic_validation, docs_site_how_grounded_docparse_is_agentic, docs_site_extraction_quality_research [INFERRED 0.85]
- **Local Runtime Installation Flow** — docs_site_onboarding_project_onboarding, docs_site_setup_supported_local_setup, docs_site_run_local_runtime_launch, docs_site_local_glmocr_glm_ocr_runtime, docs_site_local_paddleocr_vl_paddleocr_vl_runtime, docs_site_wiki_articles_interfaces_installation_and_local_runtimes [INFERRED 0.85]

## Communities (173 total, 60 thin omitted)

### Community 0 - "OpenAIDocumentGateway"
Cohesion: 0.07
Nodes (54): computed_field, build_enhancement_chunks(), Document, render_chunk_plan(), _is_schema_failure(), OpenAIDocumentGateway, Any, Exception (+46 more)

### Community 1 - "PageEvidence"
Cohesion: 0.17
Nodes (70): OcrEngine, StrEnum, IngestedDocument, PageEvidence, render_region_crop(), OcrPageResult, OcrRegion, AgentRole (+62 more)

### Community 2 - "pipeline.py"
Cohesion: 0.07
Nodes (70): GlmPageResult, ProgressCallback, RecoveryBoxKey, AtomicDraft, SpanRepairDecision, SpanRepairTarget, _aggregated_confidence(), _apply_correction() (+62 more)

### Community 3 - "ParserConfig"
Cohesion: 0.09
Nodes (48): ParserConfig, DocumentParser, test_parallel_page_config_defaults_and_environment(), test_runtime_config_defaults_environment_and_validation(), test_runtime_releases_permit_after_base_exception_and_callback_failure(), _account_pdf(), OrderedRejectedAdditionGateway, RejectedAdditionGateway (+40 more)

### Community 4 - "quality.py"
Cohesion: 0.11
Nodes (56): _area(), _box_overlap(), _clipped(), _covered_fraction(), _critical_values(), _duplicate(), find_missing_source_regions(), _fingerprint() (+48 more)

### Community 5 - "Runtime"
Cohesion: 0.09
Nodes (47): cache_resource, AnalysisThresholds, Deterministic image-analysis thresholds; ratios use rendered page pixels., _bbox(), clear_glmocr_runtimes(), _form_recovery_config_path(), get_glmocr_form_recovery_runtime(), get_glmocr_runtime() (+39 more)

### Community 6 - "PageAnalyzer"
Cohesion: 0.10
Nodes (34): HTMLParser, glmocr_version(), AnalysisEngineEvidence, BoundingBoxProvenance, CoordinateBox, DetectedPageFeatures, LayoutRegionEvidence, PageAnalysis (+26 more)

### Community 7 - "Document"
Cohesion: 0.12
Nodes (54): combine_page_markdown(), AtomicEvidence, Document, Page, TableCell, TableData, Render canonical Markdown together with its grounded v4 envelope., render_agentic_document() (+46 more)

### Community 8 - "init .py"
Cohesion: 0.13
Nodes (37): Grounded document parsing pipeline., PageRoute, DoclingNativeParser, _native_type(), PdfInspectorParser, _subset_pdf(), ProcessingType, StrEnum (+29 more)

### Community 9 - "RunUsage"
Cohesion: 0.17
Nodes (43): AgentTraceEvent, RunUsage, StoredSchema, CharacterInterval, _Accepted, _assemble_values(), _build_extraction_contract(), _coerce() (+35 more)

### Community 10 - "ingest.py"
Cohesion: 0.09
Nodes (35): validate_paddleocr_service_url(), ingest_document(), _ingest_image(), _ingest_pdf(), Path, _validate_input(), _bbox(), _find_blocks() (+27 more)

### Community 11 - "config.py"
Cohesion: 0.07
Nodes (28): APIStatusError, Return normalized Levenshtein similarity over OCR word tokens., token_edit_similarity(), _tokens(), BudgetExceeded, Exception, T, test_cross_check_sends_only_budgeted_crops_and_restores_primary() (+20 more)

### Community 12 - "PageInspection"
Cohesion: 0.09
Nodes (10): InspectionDecision, PageInspection, _decision_issue(), _validated_crop_decisions(), ConflictingScanProbeGateway, GeometryOnlyQualityGateway, ScanProbeRecoveryGateway, SecondRoundStructuredRepairGateway (+2 more)

### Community 13 - "properties"
Cohesion: 0.05
Nodes (44): additionalProperties, type, type, type, minLength, type, type, type (+36 more)

### Community 14 - "DocumentExtractor"
Cohesion: 0.13
Nodes (28): DocumentExtractor, AgentUsage, CheckboxState, DisjointStringEvidenceGateway, EnvelopePointerGateway, ExtractionGateway, InferredExtractionGateway, LaunderingEvidenceGateway (+20 more)

### Community 15 - "Block"
Cohesion: 0.14
Nodes (39): Counter, CorpusDocument, CorpusSource, Block, _agentic_atoms(), _atom_values(), _bbox_key(), _body() (+31 more)

### Community 16 - "RegionDraft"
Cohesion: 0.08
Nodes (7): PageDraft, RegionDraft, _scan_candidate(), ConcurrencyTracker, ParallelGateway, OverflowingScanProbeGateway, PlannedQualityCropGateway

### Community 17 - "regression-policy-v1.schema.json"
Cohesion: 0.05
Nodes (40): additionalProperties, enum, $id, additionalProperties, anyOf, properties, required, type (+32 more)

### Community 18 - "ParseResult"
Cohesion: 0.15
Nodes (28): _active_elements(), AgenticContext, _category_map(), _fallback_toc(), _feature_error(), _flatten_sections(), _nest_sections(), _page_markdown() (+20 more)

### Community 19 - "extraction.py"
Cohesion: 0.15
Nodes (31): _active_blocks(), _bbox_tuple(), _boolean_token(), _canonical_evidence_pointer(), _citations_contain_value(), _evidence_contains_boolean(), _extracted_fields(), _extraction_payload() (+23 more)

### Community 20 - "docling native.py"
Cohesion: 0.26
Nodes (29): build_source_manifest(), claim_record(), _csv_manifest(), _docx(), _epub(), _html(), _html_records(), _local() (+21 more)

### Community 21 - "streamlit app.py"
Cohesion: 0.09
Nodes (18): cache_data, annotation_variant(), append_session_usage(), cached_pdf_inspection(), capture_document_state(), default_document_state(), document_selection_key(), load_workspace() (+10 more)

### Community 22 - "WorkspaceStore"
Cohesion: 0.18
Nodes (13): BatchDocument, build_batch_documents(), _now(), Connection, Path, WorkspaceStore, test_completed_batch_round_trips_across_store_instances(), test_corrupt_result_isolated_as_document_failure() (+5 more)

### Community 23 - "models.py"
Cohesion: 0.24
Nodes (18): ChartPoint, Element, ExtractionResult, FormSegmentWire, OcrComparisonResult, PageQuality, ParseMetadata, BaseModel (+10 more)

### Community 24 - "Document Processing Pipeline"
Cohesion: 0.12
Nodes (22): ADE Fast Mode, Annotated PDF, Base Markdown, Document Chat, Document Classification, Document Parse Studio, Document Parse Studio Interface, Document Processing Pipeline (+14 more)

### Community 25 - "ValueError"
Cohesion: 0.15
Nodes (4): model_validator, model_validator, model_validator, ValueError

### Community 26 - "Quarterly Table"
Cohesion: 0.10
Nodes (21): Cross-Page Table Document, Q1 Units: 10, Q2 Units: 14, Q3 Units: 16, Quarterly Table, Figure Chart Document, P1 Units: 4, P2 Units: 7 (+13 more)

### Community 27 - "DocumentAgent"
Cohesion: 0.22
Nodes (17): DocumentAgent, ExtractedField, Flatten optional agentic results into the canonical v4.5 envelope., render_combined_result(), _result(), test_agentic_context_contains_compact_text_layout(), test_analysis_classifies_first_two_pages_and_builds_grounded_toc(), test_chat_maps_only_element_ids_to_grounded_citations() (+9 more)

### Community 28 - "ClassifierProfile"
Cohesion: 0.18
Nodes (19): BatchArchiveEntry, build_output_archive(), build_split_archive(), _pdf_range(), _safe_name(), ClassifierCategory, ClassifierProfile, FormClassificationResult (+11 more)

### Community 29 - "NativeDocument"
Cohesion: 0.19
Nodes (18): NativeDocument, PdfSourceAnchor, render_native_document(), SourceSpan, _document(), parametrize, test_annotated_pdf_is_optional_for_native_results(), test_base_text_is_immutable() (+10 more)

### Community 30 - "Native Document Model"
Cohesion: 0.21
Nodes (20): Testing Strategy, Immutable Base Text, LangExtract Grounded Extraction, Native Document Model, Schema Translation and Value Validation, Source Anchors and Character Spans, CLI and Python API, Streamlit Workflow (+12 more)

### Community 31 - "build docs site.py"
Cohesion: 0.25
Nodes (19): copy_local_images(), discover_markdown(), Document, document_cards(), excluded_page(), extract_document(), grouped_documents(), is_security_document() (+11 more)

### Community 32 - "benchmark.py"
Cohesion: 0.22
Nodes (18): _aggregate_sequence_metrics(), CorpusAnnotation, CorpusManifest, _edit_distance(), EvaluationAnchor, EvaluationNativeExtraction, EvaluationTable, EvaluationTableCell (+10 more)

### Community 33 - "Install-GroundedDocParse.ps1"
Cohesion: 0.32
Nodes (18): Ensure-LinuxUser(), Ensure-Wsl(), Get-HardwareMode(), Get-WslProjectRoot(), Install-LinuxPrerequisites(), Install-PaddleRuntime(), Install-Runtime(), Invoke-External() (+10 more)

### Community 34 - "refresh knowledge wiki.py"
Cohesion: 0.30
Nodes (18): NamedTuple, article_paths(), build_snapshot(), classify_path(), _dirty_paths(), excluded(), _frontmatter(), _git() (+10 more)

### Community 35 - "Any"
Cohesion: 0.16
Nodes (17): build_live_report(), _classification_summary(), _group_metrics(), _json_leaves(), _json_pointer(), _json_type(), live_telemetry_record(), _macro_metrics() (+9 more)

### Community 36 - "test evaluation metrics.py"
Cohesion: 0.16
Nodes (18): continuity_metrics(), hallucination_metrics(), _semantic_normalize(), semantic_text_metrics(), semantic_text_metrics_by_page(), semantic_text_metrics_for_reference_pages(), _semantic_words(), summarize_telemetry() (+10 more)

### Community 37 - "AgenticAnalysis"
Cohesion: 0.16
Nodes (12): AppTest, AgenticAnalysis, isolated_studio_database(), fixture, _select_scanned(), test_batch_continues_after_failure_and_retry_skips_completed_document(), test_completed_batch_restores_after_app_restart_without_reparsing(), test_mixed_pdf_prefills_routes_and_requires_confirmation() (+4 more)

### Community 38 - "load corpus manifest()"
Cohesion: 0.33
Nodes (17): load_corpus_manifest(), Path, _repository_path(), parametrize, Path, test_generator_builds_twelve_local_documents_and_external_public_water(), test_load_manifest_accepts_expected_document_type(), test_load_manifest_accepts_reference_provenance() (+9 more)

### Community 39 - "test schema store.py"
Cohesion: 0.19
Nodes (17): parse_markdown_schema(), parse_tabular_schema(), parametrize, _schema(), test_classifier_profile_markdown_rejects_invalid_profiles(), test_date_compiles_to_nullable_iso_string(), test_parse_markdown_schema_bullets_uses_filename_fallback(), test_parse_markdown_schema_rejects_invalid_fields() (+9 more)

### Community 40 - "test docling native parser.py"
Cohesion: 0.21
Nodes (17): _docx(), _epub(), _odf(), _parse(), _pptx(), parametrize, test_converter_allowlist_excludes_pdf_and_images_and_disables_models(), test_csv_maps_cells_to_one_based_rows_and_columns() (+9 more)

### Community 41 - "cli.py"
Cohesion: 0.33
Nodes (14): ArgumentParser, _discover(), _ingest(), _load_schema(), main(), _page_routes(), _parse(), _parser() (+6 more)

### Community 42 - "Synthetic Native Text Fixture"
Cohesion: 0.13
Nodes (15): Degraded Scan Document, Archived for Evaluation Only, Public Test Data, Batch ID SCAN-042, Synthetic Degraded Scan, Form Document, Approved: Yes, Record ID FORM-204 (+7 more)

### Community 43 - "live report()"
Cohesion: 0.28
Nodes (14): _glm_only_proof(), _live_report(), main(), _page_subset_mappings(), _path_mappings(), Any, Namespace, Path (+6 more)

### Community 44 - "evaluate live document()"
Cohesion: 0.23
Nodes (13): _candidate_anchor_ids(), _candidate_tables(), _canonical_block_text(), canonical_document_pages(), evaluate_live_document(), _flatten(), _markdown_reference_text(), Document (+5 more)

### Community 45 - "enhancement.py"
Cohesion: 0.19
Nodes (12): _compatible(), EnhancementChunk, _page_input(), _walk(), _annotation_group(), _annotation_label(), _as_pdf(), materialize_document_quality() (+4 more)

### Community 46 - "schema store.py"
Cohesion: 0.23
Nodes (10): SchemaField, _field(), _markdown_text(), parse_markdown_classifier_profile(), Path, _routing_category(), _table_cells(), _tabular_schema() (+2 more)

### Community 47 - "properties 2"
Cohesion: 0.20
Nodes (12): type, type, minLength, type, properties, null, string, annotation_path (+4 more)

### Community 48 - "LangExtractNativeExtractor"
Cohesion: 0.42
Nodes (11): LangExtractNativeExtractor, _extraction(), parametrize, _result(), _schema(), test_combined_native_export_contains_grounded_extraction(), test_native_extraction_rejects_partially_unanchored_interval(), test_native_extraction_rejects_ungrounded_values() (+3 more)

### Community 49 - "SchemaStore"
Cohesion: 0.29
Nodes (4): ClassifierProfileStore, Connection, SchemaStore, _stored_schema()

### Community 50 - "ua-assemble-final.cjs"
Cohesion: 0.17
Nodes (9): base, fs, graph, layers, nodeIds, rawLayers, rawTour, scan (+1 more)

### Community 51 - "manifest-v1.1.schema.json"
Cohesion: 0.18
Nodes (10): additionalProperties, $id, annotation_schema_version, corpus_id, documents, schema_version, required, $schema (+2 more)

### Community 52 - "manage-ocr-stack.sh"
Cohesion: 0.53
Nodes (9): ensure_glm(), ensure_paddle(), pid_matches(), port_is_listening(), manage-ocr-stack.sh script, stop_glm(), stop_managed(), stop_paddle() (+1 more)

### Community 54 - "Synthetic Options"
Cohesion: 0.20
Nodes (10): Checkboxes Document, Alpha Option (Selected), Beta Option (Not Selected), Gamma Option (Selected), Synthetic Options, Lists Document, Open the Public Fixture, Record the Result (+2 more)

### Community 55 - "source"
Cohesion: 0.20
Nodes (10): kind, path, kind, path, sha256, source, additionalProperties, properties (+2 more)

### Community 56 - "source 2"
Cohesion: 0.20
Nodes (10): kind, path, kind, path, sha256, source, additionalProperties, properties (+2 more)

### Community 57 - "Native PDF Pipeline"
Cohesion: 0.22
Nodes (10): Grounded Native Document Ingestion, Parse-Then-Reason Split, Architecture, OCR-Disabled Docling Conversion, Immutable Base Text, LangExtract Grounding, Manual Processing Type, Mixed PDF Page Routing (+2 more)

### Community 58 - "Document Parse Studio"
Cohesion: 0.29
Nodes (10): Annotated PDF, Document Parse Studio, Document Parsing Pipeline, Document Upload, GLM-OCR, gpt-5.6-luna, Layout Tree, Markdown Output (+2 more)

### Community 59 - "launch-stack.sh"
Cohesion: 0.36
Nodes (8): DOCPARSE_PADDLEOCR_SERVICE_URL, pid_matches(), port_is_listening(), launch-stack.sh script, start_streamlit(), stop_managed(), streamlit_environment_matches(), wait_for_url()

### Community 61 - "required"
Cohesion: 0.22
Nodes (9): items, type, additionalProperties, required, features, id, source, synthetic (+1 more)

### Community 62 - "enum"
Cohesion: 0.22
Nodes (9): enum, Bank Statement, Certificate, Contract, Form, Invoice, Letter, Other (+1 more)

### Community 63 - "Manual Document Routing"
Cohesion: 0.22
Nodes (9): Docling Adapter, Explicit Document Routing, Native Extraction Adapter, pdf-inspector Adapter, Docling Native Conversion, Grounded Document Parser, Manual Document Routing, Mixed PDF Review (+1 more)

### Community 64 - "generate corpus()"
Cohesion: 0.47
Nodes (8): _annotation(), generate_corpus(), main(), Any, Path, _save_degraded_scan(), _save_pdf(), _write_schemas()

### Community 65 - "prepare()"
Cohesion: 0.42
Nodes (8): _atomic_write(), main(), _positive_int(), prepare(), Any, Path, _resolve_snapshot(), _runtime_config()

### Community 66 - "properties 3"
Cohesion: 0.25
Nodes (8): const, minLength, type, properties, annotation_schema_version, corpus_id, schema_version, const

### Community 67 - "properties 4"
Cohesion: 0.25
Nodes (8): const, minLength, type, properties, annotation_schema_version, corpus_id, schema_version, const

### Community 68 - "properties 5"
Cohesion: 0.25
Nodes (8): type, minLength, type, properties, features, id, synthetic, type

### Community 69 - "Explicit Processing Type Routing"
Cohesion: 0.25
Nodes (8): OCR-disabled Docling Conversion, Explicit Processing Type Routing, Mixed PDF Route Review, Native PDF Pipeline, Manual Native Ingestion Contract, Native Ingestion User Workflow, Native Format Extension, Additive Native Ingestion Architecture

### Community 70 - "prepare paddleocr runtime.py"
Cohesion: 0.61
Nodes (7): configure_pipeline(), ensure_cached_assets(), find_submodule(), main(), paddle_cache_root(), Path, validate_cached_assets()

### Community 71 - "run-app.sh"
Cohesion: 0.25
Nodes (7): DOCPARSE_GLMOCR_CONFIG_PATH, DOCPARSE_LOCAL_OCR_ENABLED, DOCPARSE_OCR_ENGINE, DOCPARSE_PADDLEOCR_SERVICE_URL, DOCPARSE_PRELOAD_LOCAL_OCR, HF_HOME, run-app.sh script

### Community 72 - "evaluate regression policy()"
Cohesion: 0.57
Nodes (7): evaluate_regression_policy(), _report(), test_regression_policy_fails_closed_for_missing_metric(), test_regression_policy_passes_absolute_and_baseline_limits(), test_regression_policy_rejects_incompatible_baseline(), test_regression_policy_reports_each_failed_constraint(), test_regression_policy_requires_matching_baseline_review_threshold()

### Community 73 - "test paddle runtime config.py"
Cohesion: 0.43
Nodes (7): _config(), MonkeyPatch, Path, test_configure_pipeline_preserves_full_v1_6_layout_and_uses_vllm(), test_configure_pipeline_rejects_non_v1_6_layout(), test_main_defaults_an_empty_forwarded_port(), test_validate_cached_assets_requires_all_runtime_downloads()

### Community 74 - "Processing Types and Manual Routing"
Cohesion: 0.29
Nodes (8): CLI and Python API, Streamlit Workflow, Mixed PDF Pipeline, Native PDF Pipeline, OCR Quality and Recovery, Scanned PDF and Image Pipeline, Processing Types and Manual Routing, System Overview

### Community 75 - "SourceAnchor API"
Cohesion: 0.29
Nodes (7): NativeParseResult, ProcessingType API, SourceAnchor API, Exact Character Interval Validation, Native Routing Workflow, Grounded LangExtract, Immutable Base Text

### Community 76 - "RuntimeError"
Cohesion: 0.33
Nodes (3): ModuleType, RuntimeError, _pdf_inspector()

### Community 77 - "test knowledge wiki.py"
Cohesion: 0.57
Nodes (6): init_repository(), load_refresh_module(), Path, test_repository_wiki_contract(), test_snapshot_is_deterministic_and_excludes_generated_or_secret_files(), test_validation_reports_stale_snapshot_and_unresolved_wikilink()

### Community 78 - "manifest-v1.schema.json"
Cohesion: 0.33
Nodes (5): additionalProperties, $id, $schema, title, type

### Community 79 - "items"
Cohesion: 0.33
Nodes (6): items, type, items, additionalProperties, type, documents

### Community 80 - "External Integrations"
Cohesion: 0.33
Nodes (6): Docling Integration, External Integrations, LangExtract Integration, pdf-inspector Integration, Exact Interval Acceptance, LangExtract Grounded Extraction

### Community 81 - "main()"
Cohesion: 0.53
Nodes (5): _content(), main(), _page_image(), Any, Path

### Community 82 - "setup-ollama.sh"
Cohesion: 0.40
Nodes (5): download_and_extract(), OLLAMA_CONTEXT_LENGTH, OLLAMA_HOST, OLLAMA_MODELS, setup-ollama.sh script

### Community 83 - "Unicode Identifier Register"
Cohesion: 0.40
Nodes (5): Unicode Identifiers Document, Cafe-Å42, Naive-Ü18, Unicode Identifier Register, Resume-É74

### Community 84 - "manifest.json"
Cohesion: 0.40
Nodes (4): annotation_schema_version, corpus_id, documents, schema_version

### Community 85 - "required 2"
Cohesion: 0.40
Nodes (5): required, features, id, source, synthetic

### Community 86 - "required 3"
Cohesion: 0.40
Nodes (5): annotation_schema_version, corpus_id, documents, schema_version, required

### Community 87 - "Immutable Evidence Spine"
Cohesion: 0.40
Nodes (5): Codebase Architecture, Explicit Routing Architecture, Immutable Evidence Spine, Immutable Base Text, Source Span Coordinate System

### Community 88 - "Supported Local Setup"
Cohesion: 0.40
Nodes (5): Project Onboarding, Run Locally, Supported Local Setup, Knowledge Wiki Authoring Contract, Installation and Local Runtimes

### Community 89 - "serve-ollama.sh"
Cohesion: 0.40
Nodes (4): OLLAMA_CONTEXT_LENGTH, OLLAMA_HOST, OLLAMA_MODELS, serve-ollama.sh script

### Community 90 - "setup-paddleocr.sh"
Cohesion: 0.40
Nodes (4): PADDLE_PDX_CACHE_HOME, PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK, setup-paddleocr.sh script, UV_PROJECT_ENVIRONMENT

### Community 91 - ".extract forms()"
Cohesion: 0.70
Nodes (3): Any, _segment_extraction_payload(), SegmentExtraction

### Community 93 - "features"
Cohesion: 0.50
Nodes (4): items, type, type, features

### Community 94 - "type"
Cohesion: 0.50
Nodes (4): type, null, string, annotation_path

### Community 95 - "SourceAnchor"
Cohesion: 0.50
Nodes (4): LangExtract Grounding, Native Document Ingestion, ProcessingType, SourceAnchor

### Community 96 - "Agentic Document Extraction Comparison"
Cohesion: 0.67
Nodes (4): Controlled Document Workflow, Deterministic Validation, Agentic Document Extraction Comparison, Agentic Comparison Site Page

### Community 97 - "Routing Contract Tests"
Cohesion: 0.50
Nodes (4): Native Contract Tests, Testing Patterns, Routing Contract Tests, Testing Strategy

### Community 98 - "SourceAnchor Evidence"
Cohesion: 0.67
Nodes (4): Immutable Base Text, LangExtract Interval Validation, SourceAnchor Evidence, Native Evaluation Corpus

### Community 99 - "main() 2"
Cohesion: 0.83
Nodes (3): digital_report(), fax_document(), main()

### Community 100 - "serve-glmocr.sh"
Cohesion: 0.50
Nodes (3): HF_HUB_OFFLINE, serve-glmocr.sh script, TRANSFORMERS_OFFLINE

### Community 101 - "setup-glmocr.sh"
Cohesion: 0.50
Nodes (3): HF_HOME, setup-glmocr.sh script, UV_PROJECT_ENVIRONMENT

### Community 102 - "Source Anchors and Character Spans"
Cohesion: 0.50
Nodes (4): Schema Translation and Value Validation, Source Anchors and Character Spans, Workspace Persistence and Exports, Grounding and Evidence Contract

### Community 103 - "Codebase Concerns"
Cohesion: 0.67
Nodes (3): Codebase Concerns, Canonical Contract Drift, Workspace Retention Risk

### Community 104 - "Mixed PDF Review"
Cohesion: 0.67
Nodes (3): Complete User Guide, Mixed PDF Review, Source Structure View

### Community 105 - "Layout-Aware Large Field Extraction Workflow"
Cohesion: 0.67
Nodes (3): Layout-Aware Large Field Extraction Workflow, Confidence Calibration and Regression Evaluation, Design Basis

### Community 107 - "Ingest CLI"
Cohesion: 0.67
Nodes (3): Ingest CLI, Confirmed Mixed PDF Routes, Native Dependency Extra

### Community 108 - "sanitize markdown preview()"
Cohesion: 0.67
Nodes (3): Allow safe table and figure HTML without changing surrounding Markdown., sanitize_markdown_preview(), test_markdown_preview_preserves_markdown_and_sanitizes_supported_html()

### Community 112 - "Office and Native Formats"
Cohesion: 0.67
Nodes (3): Docling Native Conversion, Office and Native Formats, Product Capabilities and Boundaries

## Knowledge Gaps
- **320 isolated node(s):** `fs`, `fs`, `base`, `scan`, `rawLayers` (+315 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **60 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ParserConfig` connect `ParserConfig` to `OpenAIDocumentGateway`, `PageEvidence`, `pipeline.py`, `Runtime`, `PageAnalyzer`, `init .py`, `cli.py`, `ingest.py`, `config.py`, `RunUsage`, `RuntimeError`, `DocumentExtractor`, `PageInspection`, `LangExtractNativeExtractor`, `RegionDraft`, `ParseResult`, `extraction.py`, `DocumentAgent`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Why does `Block` connect `Block` to `benchmark.py`, `PageEvidence`, `pipeline.py`, `ParserConfig`, `quality.py`, `OpenAIDocumentGateway`, `Document`, `init .py`, `evaluate live document()`, `enhancement.py`, `DocumentExtractor`, `ParseResult`, `models.py`, `DocumentAgent`, `ClassifierProfile`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Why does `DocumentParser` connect `ParserConfig` to `OpenAIDocumentGateway`, `PageEvidence`, `pipeline.py`, `PageAnalyzer`, `Document`, `init .py`, `cli.py`, `RunUsage`, `live report()`, `RuntimeError`, `PageInspection`, `DocumentExtractor`, `Block`, `RegionDraft`, `ParseResult`, `models.py`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Are the 77 inferred relationships involving `ParserConfig` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`ParserConfig` has 77 INFERRED edges - model-reasoned connections that need verification._
- **Are the 44 inferred relationships involving `Block` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`Block` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 92 inferred relationships involving `DocumentParser` (e.g. with `DoclingNativeParser` and `PdfInspectorParser`) actually correct?**
  _`DocumentParser` has 92 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `Document` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`Document` has 48 INFERRED edges - model-reasoned connections that need verification._