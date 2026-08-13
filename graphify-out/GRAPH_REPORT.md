# Graph Report - .  (2026-08-12)

## Corpus Check
- Large corpus: 323 files · ~790,799 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 2143 nodes · 7619 edges · 173 communities (113 shown, 60 thin omitted)
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 2130 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Pipeline
- Openai Vision Gateway
- Agentic Contract
- Simple Pipeline
- Agentic
- Quality
- Render
- Page Analysis
- Page Analysis
- Simple Pipeline
- Workspace Store
- Provider Runtime
- Annotation V1 1 Schema
- Agentic Extraction
- Universal
- Regression Policy V1 Schema
- Docling Native Parser
- Streamlit App
- Paddle Ocr
- Simple Pipeline
- Native Extraction
- Extraction
- Schema Store
- Simple Pipeline
- Docling Native
- Native Models
- Document Parse Studio Full
- Benchmark
- Models
- Figure Chart
- Technical
- Build
- Install Groundeddocparse
- Refresh Knowledge
- Corpus Manifest
- Simple Streamlit
- Benchmark
- Benchmark
- Benchmark
- Cli
- Degraded Scan
- Evaluate Corpus
- Launch Stack
- Manage Ocr Stack
- Native Extraction
- Manifest V1 1 Schema
- Batch
- Schema Store
- Native Pdf Parser
- Manifest V1 1 Schema
- Runtime Control
- Checkboxes
- Manifest V1 1 Schema
- Manifest V1 Schema
- Document Parse Studio Full
- Manifest V1 1 Schema
- Manifest V1 1 Schema
- Spec
- Generate Evaluation Corpus
- Prepare Glmocr Runtime
- Run App
- Manifest V1 1 Schema
- Manifest V1 Schema
- Manifest V1 Schema
- Complete User Guide
- Prepare Paddleocr Runtime
- Regression Policy
- Paddle Runtime Config
- Cli And Python Api
- Knowledge
- Manifest V1 Schema
- Manifest V1 Schema
- Integrations
- Benchmark Glmocr
- Setup Ollama
- Unicode Identifiers
- Manifest
- Manifest V1 Schema
- Manifest V1 Schema
- Architecture
- Serve Ollama
- Setup Paddleocr
- Stop Stack
- Manifest V1 1 Schema
- Manifest V1 Schema
- Architecture
- Testing
- Codebase Structure
- Extraction Quality Research
- Grounding Immutable Base Text
- Grounding Langextract Extraction
- Grounding Native Document Model
- Pipelines Mixed Pdf Pipeline
- Pipelines Native Pdf Pipeline
- Product Grounding And Evidence
- Zero To Hero Tutorial
- Generate Examples
- Serve Glmocr
- Setup Glmocr
- Render
- Schema Translation And Value
- Agentic Document Extraction Comparison
- Api
- Concerns
- Check Paddleocr Api
- Conftest
- Docling Native Conversion
- Changelog
- Code Of Conduct
- How Is Agentic
- Azure Bulk Fax Deployment
- Conventions
- Stack
- Structure
- Complete User Guide
- How It Works
- Local Paddleocr Vl
- Onboarding
- Run
- Spec
- Technical
- Tutorial
- Usage
- Agents
- Engineering Adding A Native
- Engineering Evaluation Corpus And
- Engineering Repository Architecture
- Engineering Testing Strategy
- Interfaces Cli And Python
- Interfaces Installation And Local
- Interfaces Streamlit Workflow
- Interfaces Workspace Persistence And
- Pipelines Ocr Quality And
- Pipelines Scanned Pdf And
- Product Product Capabilities And
- Index
- Tutorial
- Query 20260730 154807 Why
- Adding A Native Format
- Security Privacy And Trust
- Merge Report
- Glmocr
- Paddle Vllm
- Business User Extraction Workflow
- Extraction Quality Research
- Idp Vs Ade Classification
- Layout Aware Large Field
- Local Glmocr
- Private Evaluation
- Favicon
- Issue Template Bug Report
- Issue Template Feature Request
- Security Content Excluded
- Log
- Bug Report
- Feature Request
- Pyproject
- Pyproject
- Agents
- Evaluation Corpus And Metrics
- Repository Architecture
- Native Document Model
- Installation And Local Runtimes
- Index
- Log

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
- `Architecture Guide` --semantically_similar_to--> `Technical Overview`  [INFERRED] [semantically similar]
  docs-site/architecture.html → TECHNICAL.md
- `Documentation Site Release History` --semantically_similar_to--> `Release History`  [INFERRED] [semantically similar]
  docs-site/changelog.html → CHANGELOG.md
- `Documentation Site Conduct Policy` --semantically_similar_to--> `Community Conduct Policy`  [INFERRED] [semantically similar]
  docs-site/code-of-conduct.html → CODE_OF_CONDUCT.md
- `Business Extraction Workflow` --semantically_similar_to--> `User Workflow`  [INFERRED] [semantically similar]
  docs-site/business-user-extraction-workflow.html → USAGE.md
- `Grounded Parsing Tutorial` --semantically_similar_to--> `Grounded Parsing Tutorial`  [INFERRED] [semantically similar]
  docs-site/zero-to-hero-tutorial.html → docs/zero-to-hero-tutorial.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Local OCR Runtime Operating Model** — docs_site_setup_setup_guide, docs_site_run_local_runtime, docs_site_local_glmocr_glmocr_runtime, docs_site_local_paddleocr_vl_paddleocr_runtime [INFERRED 0.85]
- **Agentic Document Control** — docs_agentic_controlled_document_workflow, docs_agentic_deterministic_validation [INFERRED 0.85]
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

## Communities (173 total, 60 thin omitted)

### Community 0 - "Pipeline"
Cohesion: 0.07
Nodes (90): GlmPageResult, ProgressCallback, RecoveryBoxKey, render_region_crop(), get_glmocr_form_recovery_runtime(), AtomicDraft, Citation, ConfidenceSpan (+82 more)

### Community 1 - "Openai Vision Gateway"
Cohesion: 0.07
Nodes (58): computed_field, _is_schema_failure(), OpenAIDocumentGateway, Any, Exception, Path, T, Return presentation-only instructions; document text is never accepted. (+50 more)

### Community 2 - "Agentic Contract"
Cohesion: 0.24
Nodes (52): OcrEngine, StrEnum, IngestedDocument, PageEvidence, OcrPageResult, OcrRegion, AgentRole, AnalysisRegionType (+44 more)

### Community 3 - "Simple Pipeline"
Cohesion: 0.12
Nodes (63): CorpusDocument, CorpusSource, AtomicEvidence, Block, Document, Page, TableCell, TableData (+55 more)

### Community 4 - "Agentic"
Cohesion: 0.10
Nodes (50): _active_elements(), AgenticContext, _category_map(), DocumentAgent, _fallback_toc(), _feature_error(), _flatten_sections(), _nest_sections() (+42 more)

### Community 5 - "Quality"
Cohesion: 0.10
Nodes (59): _build_recovery_log(), Document, _area(), _box_overlap(), _clipped(), _covered_fraction(), _critical_values(), _duplicate() (+51 more)

### Community 6 - "Render"
Cohesion: 0.09
Nodes (49): Counter, build_enhancement_chunks(), combine_page_markdown(), _compatible(), EnhancementChunk, _page_input(), Document, render_chunk_plan() (+41 more)

### Community 7 - "Page Analysis"
Cohesion: 0.09
Nodes (46): cache_resource, AnalysisThresholds, Deterministic image-analysis thresholds; ratios use rendered page pixels., _bbox(), clear_glmocr_runtimes(), _form_recovery_config_path(), get_glmocr_runtime(), GlmOcrRuntime (+38 more)

### Community 8 - "Page Analysis"
Cohesion: 0.09
Nodes (33): HTMLParser, glmocr_version(), AnalysisEngineEvidence, BoundingBoxProvenance, CoordinateBox, DetectedPageFeatures, LayoutRegionEvidence, PageComplexity (+25 more)

### Community 9 - "Simple Pipeline"
Cohesion: 0.10
Nodes (47): ParserConfig, DocumentParser, _account_pdf(), test_all_visuals_are_enriched_in_bounded_batches(), test_clipped_critical_literal_remains_visible_with_review_warning(), test_crop_decision_for_wrong_region_remains_unresolved(), test_crop_render_error_preserves_draft_text(), test_crop_requests_cover_all_risky_regions_in_one_batch() (+39 more)

### Community 10 - "Workspace Store"
Cohesion: 0.12
Nodes (32): BatchDocument, build_batch_documents(), AgenticAnalysis, Element, OcrComparisonResult, PageQuality, ParseMetadata, Engine-neutral, layout-aware document element. (+24 more)

### Community 11 - "Provider Runtime"
Cohesion: 0.07
Nodes (28): APIStatusError, Return normalized Levenshtein similarity over OCR word tokens., token_edit_similarity(), _tokens(), BudgetExceeded, Exception, T, test_cross_check_sends_only_budgeted_crops_and_restores_primary() (+20 more)

### Community 12 - "Annotation V1 1 Schema"
Cohesion: 0.05
Nodes (44): additionalProperties, type, type, type, minLength, type, type, type (+36 more)

### Community 13 - "Agentic Extraction"
Cohesion: 0.14
Nodes (29): DocumentExtractor, AgentUsage, CheckboxState, ParseResult, DisjointStringEvidenceGateway, EnvelopePointerGateway, ExtractionGateway, InferredExtractionGateway (+21 more)

### Community 14 - "Universal"
Cohesion: 0.17
Nodes (32): Grounded document parsing pipeline., NativeParseResult, PageRoute, DoclingNativeParser, _native_type(), PdfInspectorParser, _subset_pdf(), ProcessingType (+24 more)

### Community 15 - "Regression Policy V1 Schema"
Cohesion: 0.05
Nodes (40): additionalProperties, enum, $id, additionalProperties, anyOf, properties, required, type (+32 more)

### Community 16 - "Docling Native Parser"
Cohesion: 0.09
Nodes (30): _docx(), _epub(), _multi_paragraph_pptx(), _odf(), _parse(), _pptx(), parametrize, test_converter_allowlist_excludes_pdf_and_images_and_disables_models() (+22 more)

### Community 17 - "Streamlit App"
Cohesion: 0.08
Nodes (26): cache_data, dialog, ClassifierCategory, append_session_usage(), cached_pdf_inspection(), capture_document_state(), _classification_rows(), confirm_managed_shutdown() (+18 more)

### Community 18 - "Paddle Ocr"
Cohesion: 0.11
Nodes (28): validate_paddleocr_service_url(), ingest_document(), _ingest_image(), _ingest_pdf(), Path, _validate_input(), _bbox(), _find_blocks() (+20 more)

### Community 19 - "Simple Pipeline"
Cohesion: 0.10
Nodes (3): InspectionDecision, PageInspection, test_geometry_only_rejection_flag_is_additive_and_fail_closed()

### Community 20 - "Native Extraction"
Cohesion: 0.20
Nodes (34): AgentTraceEvent, StoredSchema, CharacterInterval, _Accepted, _assemble_values(), _build_extraction_contract(), _coerce(), _collect_extraction_groups() (+26 more)

### Community 21 - "Extraction"
Cohesion: 0.15
Nodes (31): _active_blocks(), _bbox_tuple(), _boolean_token(), _canonical_evidence_pointer(), _citations_contain_value(), _evidence_contains_boolean(), _extracted_fields(), _extraction_payload() (+23 more)

### Community 22 - "Schema Store"
Cohesion: 0.13
Nodes (27): SchemaField, _field(), _markdown_text(), parse_markdown_classifier_profile(), parse_markdown_schema(), parse_tabular_schema(), Path, _routing_category() (+19 more)

### Community 23 - "Simple Pipeline"
Cohesion: 0.12
Nodes (3): PageDraft, RegionDraft, _scan_candidate()

### Community 24 - "Docling Native"
Cohesion: 0.28
Nodes (26): build_source_manifest(), claim_record(), _csv_manifest(), _docx(), _epub(), _html(), _html_records(), _local() (+18 more)

### Community 25 - "Native Models"
Cohesion: 0.17
Nodes (24): NativeDocument, NativeElement, PdfSourceAnchor, BaseModel, render_native_document(), RenderedNativeDocument, SourceSpan, SourceUnit (+16 more)

### Community 26 - "Document Parse Studio Full"
Cohesion: 0.12
Nodes (22): ADE Fast Mode, Annotated PDF, Base Markdown, Document Chat, Document Classification, Document Parse Studio, Document Parse Studio Interface, Document Processing Pipeline (+14 more)

### Community 27 - "Benchmark"
Cohesion: 0.14
Nodes (20): build_live_report(), _classification_summary(), _group_metrics(), _json_leaves(), _json_pointer(), _json_type(), live_telemetry_record(), _macro_metrics() (+12 more)

### Community 28 - "Models"
Cohesion: 0.15
Nodes (4): model_validator, model_validator, model_validator, ValueError

### Community 29 - "Figure Chart"
Cohesion: 0.10
Nodes (21): Cross-Page Table Document, Q1 Units: 10, Q2 Units: 14, Q3 Units: 16, Quarterly Table, Figure Chart Document, P1 Units: 4, P2 Units: 7 (+13 more)

### Community 30 - "Technical"
Cohesion: 0.12
Nodes (20): Contributor Workflow, Agentic Document Extraction Comparison, Python API Reference, Architecture Guide, Azure Bulk Fax Deployment, Business Extraction Workflow, Codebase Architecture Analysis, Codebase Concerns Analysis (+12 more)

### Community 31 - "Build"
Cohesion: 0.25
Nodes (19): copy_local_images(), discover_markdown(), Document, document_cards(), excluded_page(), extract_document(), grouped_documents(), is_security_document() (+11 more)

### Community 32 - "Install Groundeddocparse"
Cohesion: 0.32
Nodes (18): Ensure-LinuxUser(), Ensure-Wsl(), Get-HardwareMode(), Get-WslProjectRoot(), Install-LinuxPrerequisites(), Install-PaddleRuntime(), Install-Runtime(), Invoke-External() (+10 more)

### Community 33 - "Refresh Knowledge"
Cohesion: 0.30
Nodes (18): NamedTuple, article_paths(), build_snapshot(), classify_path(), _dirty_paths(), excluded(), _frontmatter(), _git() (+10 more)

### Community 34 - "Corpus Manifest"
Cohesion: 0.33
Nodes (17): load_corpus_manifest(), Path, _repository_path(), parametrize, Path, test_generator_builds_twelve_local_documents_and_external_public_water(), test_load_manifest_accepts_expected_document_type(), test_load_manifest_accepts_reference_provenance() (+9 more)

### Community 35 - "Simple Streamlit"
Cohesion: 0.15
Nodes (10): AppTest, isolated_studio_database(), fixture, _select_scanned(), test_batch_continues_after_failure_and_retry_skips_completed_document(), test_completed_batch_restores_after_app_restart_without_reparsing(), test_mixed_pdf_prefills_routes_and_requires_confirmation(), test_multiple_uploads_process_sequentially_and_only_process_new_files() (+2 more)

### Community 36 - "Benchmark"
Cohesion: 0.26
Nodes (15): CorpusAnnotation, CorpusManifest, EvaluationAnchor, EvaluationNativeExtraction, EvaluationTable, EvaluationTableCell, grounding_metrics(), _intersection_over_union() (+7 more)

### Community 38 - "Benchmark"
Cohesion: 0.17
Nodes (16): _aggregate_sequence_metrics(), _edit_distance(), hallucination_metrics(), _semantic_normalize(), semantic_text_metrics(), semantic_text_metrics_by_page(), semantic_text_metrics_for_reference_pages(), _semantic_words() (+8 more)

### Community 39 - "Benchmark"
Cohesion: 0.19
Nodes (15): _candidate_anchor_ids(), _candidate_tables(), _canonical_block_text(), canonical_document_pages(), continuity_metrics(), evaluate_live_document(), _flatten(), _markdown_reference_text() (+7 more)

### Community 40 - "Cli"
Cohesion: 0.33
Nodes (14): ArgumentParser, _discover(), _ingest(), _load_schema(), main(), _page_routes(), _parse(), _parser() (+6 more)

### Community 41 - "Degraded Scan"
Cohesion: 0.13
Nodes (15): Degraded Scan Document, Archived for Evaluation Only, Public Test Data, Batch ID SCAN-042, Synthetic Degraded Scan, Form Document, Approved: Yes, Record ID FORM-204 (+7 more)

### Community 42 - "Evaluate Corpus"
Cohesion: 0.28
Nodes (14): _glm_only_proof(), _live_report(), main(), _page_subset_mappings(), _path_mappings(), Any, Namespace, Path (+6 more)

### Community 43 - "Launch Stack"
Cohesion: 0.29
Nodes (10): DOCPARSE_PADDLEOCR_SERVICE_URL, pid_matches(), port_is_listening(), process_is_running(), launch-stack.sh script, start_streamlit(), stop_managed(), streamlit_environment_matches() (+2 more)

### Community 44 - "Manage Ocr Stack"
Cohesion: 0.46
Nodes (11): ensure_glm(), ensure_paddle(), glm_environment_current(), pid_matches(), port_is_listening(), process_is_running(), manage-ocr-stack.sh script, stop_glm() (+3 more)

### Community 45 - "Native Extraction"
Cohesion: 0.37
Nodes (11): LangExtractNativeExtractor, render_native_combined_result(), _extraction(), parametrize, _result(), _schema(), test_combined_native_export_contains_grounded_extraction(), test_native_extraction_rejects_partially_unanchored_interval() (+3 more)

### Community 46 - "Manifest V1 1 Schema"
Cohesion: 0.20
Nodes (12): type, type, minLength, type, properties, null, string, annotation_path (+4 more)

### Community 47 - "Batch"
Cohesion: 0.27
Nodes (10): BatchArchiveEntry, build_output_archive(), build_split_archive(), _pdf_range(), _safe_name(), output_archive(), split_output_archive(), test_batch_documents_are_stable_and_preserve_duplicate_uploads() (+2 more)

### Community 48 - "Schema Store"
Cohesion: 0.29
Nodes (4): ClassifierProfileStore, Connection, SchemaStore, _stored_schema()

### Community 49 - "Native Pdf Parser"
Cohesion: 0.35
Nodes (6): FakeLegacyParser, FakePdfInspector, _pdf(), test_mixed_ocr_to_native_override_fails_without_ocr_fallback(), test_mixed_pdf_merges_native_and_ocr_pages_in_source_order(), test_native_pdf_extracts_markdown_positions_and_table_metadata()

### Community 50 - "Manifest V1 1 Schema"
Cohesion: 0.18
Nodes (10): additionalProperties, $id, annotation_schema_version, corpus_id, documents, schema_version, required, $schema (+2 more)

### Community 51 - "Runtime Control"
Cohesion: 0.22
Nodes (6): ModuleType, RuntimeError, _pdf_inspector(), managed_shutdown_available(), schedule_managed_shutdown(), test_runtime_releases_permit_after_base_exception_and_callback_failure()

### Community 52 - "Checkboxes"
Cohesion: 0.20
Nodes (10): Checkboxes Document, Alpha Option (Selected), Beta Option (Not Selected), Gamma Option (Selected), Synthetic Options, Lists Document, Open the Public Fixture, Record the Result (+2 more)

### Community 53 - "Manifest V1 1 Schema"
Cohesion: 0.20
Nodes (10): kind, path, kind, path, sha256, source, additionalProperties, properties (+2 more)

### Community 54 - "Manifest V1 Schema"
Cohesion: 0.20
Nodes (10): kind, path, kind, path, sha256, source, additionalProperties, properties (+2 more)

### Community 55 - "Document Parse Studio Full"
Cohesion: 0.29
Nodes (10): Annotated PDF, Document Parse Studio, Document Parsing Pipeline, Document Upload, GLM-OCR, gpt-5.6-luna, Layout Tree, Markdown Output (+2 more)

### Community 57 - "Manifest V1 1 Schema"
Cohesion: 0.22
Nodes (9): items, type, additionalProperties, required, features, id, source, synthetic (+1 more)

### Community 58 - "Manifest V1 1 Schema"
Cohesion: 0.22
Nodes (9): enum, Bank Statement, Certificate, Contract, Form, Invoice, Letter, Other (+1 more)

### Community 59 - "Spec"
Cohesion: 0.25
Nodes (9): Grounded Native Document Ingestion, Parse-Then-Reason Split, OCR-Disabled Docling Conversion, Immutable Base Text, LangExtract Grounding, Manual Processing Type, Mixed PDF Page Routing, Native PDF Pipeline (+1 more)

### Community 60 - "Generate Evaluation Corpus"
Cohesion: 0.47
Nodes (8): _annotation(), generate_corpus(), main(), Any, Path, _save_degraded_scan(), _save_pdf(), _write_schemas()

### Community 61 - "Prepare Glmocr Runtime"
Cohesion: 0.42
Nodes (8): _atomic_write(), main(), _positive_int(), prepare(), Any, Path, _resolve_snapshot(), _runtime_config()

### Community 62 - "Run App"
Cohesion: 0.22
Nodes (8): DOCPARSE_GLMOCR_CONFIG_PATH, DOCPARSE_LOCAL_OCR_ENABLED, DOCPARSE_OCR_ENGINE, DOCPARSE_PADDLEOCR_SERVICE_URL, DOCPARSE_PRELOAD_LOCAL_OCR, HF_HOME, PYTHONPATH, run-app.sh script

### Community 63 - "Manifest V1 1 Schema"
Cohesion: 0.25
Nodes (8): const, minLength, type, properties, annotation_schema_version, corpus_id, schema_version, const

### Community 64 - "Manifest V1 Schema"
Cohesion: 0.25
Nodes (8): const, minLength, type, properties, annotation_schema_version, corpus_id, schema_version, const

### Community 65 - "Manifest V1 Schema"
Cohesion: 0.25
Nodes (8): type, minLength, type, properties, features, id, synthetic, type

### Community 66 - "Complete User Guide"
Cohesion: 0.39
Nodes (8): Complete User Workflow, Document Processing Flow, Product Overview, Layout-Aware Large Field Extraction, Local GLM-OCR Runtime, Local PaddleOCR-VL Runtime, Local Runtime Operations, Setup Guide

### Community 67 - "Prepare Paddleocr Runtime"
Cohesion: 0.61
Nodes (7): configure_pipeline(), ensure_cached_assets(), find_submodule(), main(), paddle_cache_root(), Path, validate_cached_assets()

### Community 68 - "Regression Policy"
Cohesion: 0.57
Nodes (7): evaluate_regression_policy(), _report(), test_regression_policy_fails_closed_for_missing_metric(), test_regression_policy_passes_absolute_and_baseline_limits(), test_regression_policy_rejects_incompatible_baseline(), test_regression_policy_reports_each_failed_constraint(), test_regression_policy_requires_matching_baseline_review_threshold()

### Community 69 - "Paddle Runtime Config"
Cohesion: 0.43
Nodes (7): _config(), MonkeyPatch, Path, test_configure_pipeline_preserves_full_v1_6_layout_and_uses_vllm(), test_configure_pipeline_rejects_non_v1_6_layout(), test_main_defaults_an_empty_forwarded_port(), test_validate_cached_assets_requires_all_runtime_downloads()

### Community 70 - "Cli And Python Api"
Cohesion: 0.29
Nodes (8): CLI and Python API, Streamlit Workflow, Mixed PDF Pipeline, Native PDF Pipeline, OCR Quality and Recovery, Scanned PDF and Image Pipeline, Processing Types and Manual Routing, System Overview

### Community 71 - "Knowledge"
Cohesion: 0.57
Nodes (6): init_repository(), load_refresh_module(), Path, test_repository_wiki_contract(), test_snapshot_is_deterministic_and_excludes_generated_or_secret_files(), test_validation_reports_stale_snapshot_and_unresolved_wikilink()

### Community 72 - "Manifest V1 Schema"
Cohesion: 0.33
Nodes (5): additionalProperties, $id, $schema, title, type

### Community 73 - "Manifest V1 Schema"
Cohesion: 0.33
Nodes (6): items, type, items, additionalProperties, type, documents

### Community 74 - "Integrations"
Cohesion: 0.33
Nodes (6): Docling Integration, External Integrations, LangExtract Integration, pdf-inspector Integration, Exact Interval Acceptance, LangExtract Grounded Extraction

### Community 75 - "Benchmark Glmocr"
Cohesion: 0.53
Nodes (5): _content(), main(), _page_image(), Any, Path

### Community 76 - "Setup Ollama"
Cohesion: 0.40
Nodes (5): download_and_extract(), OLLAMA_CONTEXT_LENGTH, OLLAMA_HOST, OLLAMA_MODELS, setup-ollama.sh script

### Community 77 - "Unicode Identifiers"
Cohesion: 0.40
Nodes (5): Unicode Identifiers Document, Cafe-Å42, Naive-Ü18, Unicode Identifier Register, Resume-É74

### Community 78 - "Manifest"
Cohesion: 0.40
Nodes (4): annotation_schema_version, corpus_id, documents, schema_version

### Community 79 - "Manifest V1 Schema"
Cohesion: 0.40
Nodes (5): required, features, id, source, synthetic

### Community 80 - "Manifest V1 Schema"
Cohesion: 0.40
Nodes (5): annotation_schema_version, corpus_id, documents, schema_version, required

### Community 81 - "Architecture"
Cohesion: 0.40
Nodes (5): Codebase Architecture, Explicit Routing Architecture, Immutable Evidence Spine, Immutable Base Text, Source Span Coordinate System

### Community 82 - "Serve Ollama"
Cohesion: 0.40
Nodes (4): OLLAMA_CONTEXT_LENGTH, OLLAMA_HOST, OLLAMA_MODELS, serve-ollama.sh script

### Community 83 - "Setup Paddleocr"
Cohesion: 0.40
Nodes (4): PADDLE_PDX_CACHE_HOME, PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK, setup-paddleocr.sh script, UV_PROJECT_ENVIRONMENT

### Community 84 - "Stop Stack"
Cohesion: 0.80
Nodes (4): process_is_running(), stop-stack.sh script, stop_streamlit(), streamlit_pid_matches()

### Community 86 - "Manifest V1 1 Schema"
Cohesion: 0.50
Nodes (4): items, type, type, features

### Community 87 - "Manifest V1 Schema"
Cohesion: 0.50
Nodes (4): type, null, string, annotation_path

### Community 88 - "Architecture"
Cohesion: 0.50
Nodes (4): Docling Adapter, Explicit Document Routing, Native Extraction Adapter, pdf-inspector Adapter

### Community 89 - "Testing"
Cohesion: 0.50
Nodes (4): Native Contract Tests, Testing Patterns, Routing Contract Tests, Testing Strategy

### Community 90 - "Codebase Structure"
Cohesion: 0.50
Nodes (4): Codebase Structure, Testing Strategy, Contribution Guidelines, Project Onboarding Guide

### Community 91 - "Extraction Quality Research"
Cohesion: 0.50
Nodes (4): Extraction Quality Research, Agentic Processing Boundaries, Private Calibration and Regression Evaluation, Parse-Then-Reason Design Basis

### Community 92 - "Grounding Immutable Base Text"
Cohesion: 0.50
Nodes (4): Base Text Coordinate System, Immutable Base Text, Source Anchors and Character Spans, Source Provenance Mapping

### Community 93 - "Grounding Langextract Extraction"
Cohesion: 0.50
Nodes (4): Interval-Validated Extraction, LangExtract Grounded Extraction, Grounded Schema Translation, Schema Translation and Value Validation

### Community 94 - "Grounding Native Document Model"
Cohesion: 0.50
Nodes (4): Grounded Native Document Model, Native Document Model, Deterministic Docling Grounding, Docling Native Conversion

### Community 95 - "Pipelines Mixed Pdf Pipeline"
Cohesion: 0.50
Nodes (4): Mixed PDF Pipeline, Mixed PDF Page Routing, Processing Types and Manual Routing, Manual Processing-Type Selection

### Community 96 - "Pipelines Native Pdf Pipeline"
Cohesion: 0.50
Nodes (4): Native PDF Pipeline, Native Text Extraction, Docling Native Conversion, Office and Native Formats

### Community 97 - "Product Grounding And Evidence"
Cohesion: 0.50
Nodes (4): Grounding and Evidence Contract, Source Anchors, System Overview, Document Ingestion System

### Community 98 - "Zero To Hero Tutorial"
Cohesion: 0.50
Nodes (4): Zero-to-Hero Tutorial HTML, Grounded Parsing Tutorial, Zero-to-Hero Tutorial, Grounded Parsing Tutorial

### Community 99 - "Generate Examples"
Cohesion: 0.83
Nodes (3): digital_report(), fax_document(), main()

### Community 100 - "Serve Glmocr"
Cohesion: 0.50
Nodes (3): HF_HUB_OFFLINE, serve-glmocr.sh script, TRANSFORMERS_OFFLINE

### Community 101 - "Setup Glmocr"
Cohesion: 0.50
Nodes (3): HF_HOME, setup-glmocr.sh script, UV_PROJECT_ENVIRONMENT

### Community 102 - "Render"
Cohesion: 0.50
Nodes (4): Allow safe table and figure HTML without changing surrounding Markdown., sanitize_markdown_preview(), render_grounded_html_preview(), test_markdown_preview_preserves_markdown_and_sanitizes_supported_html()

### Community 103 - "Schema Translation And Value"
Cohesion: 0.50
Nodes (4): Schema Translation and Value Validation, Source Anchors and Character Spans, Workspace Persistence and Exports, Grounding and Evidence Contract

### Community 104 - "Agentic Document Extraction Comparison"
Cohesion: 1.00
Nodes (3): Controlled Document Workflow, Deterministic Validation, Agentic Document Extraction Comparison

### Community 105 - "Api"
Cohesion: 0.67
Nodes (3): NativeParseResult, ProcessingType API, SourceAnchor API

### Community 106 - "Concerns"
Cohesion: 0.67
Nodes (3): Codebase Concerns, Canonical Contract Drift, Workspace Retention Risk

### Community 110 - "Docling Native Conversion"
Cohesion: 0.67
Nodes (3): Docling Native Conversion, Office and Native Formats, Product Capabilities and Boundaries

## Knowledge Gaps
- **338 isolated node(s):** `schema_version`, `annotation_schema_version`, `corpus_id`, `documents`, `$schema` (+333 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **60 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ParserConfig` connect `Simple Pipeline` to `Pipeline`, `Openai Vision Gateway`, `Agentic Contract`, `Agentic`, `Page Analysis`, `Cli`, `Page Analysis`, `Provider Runtime`, `Agentic Extraction`, `Universal`, `Native Extraction`, `Docling Native Parser`, `Native Pdf Parser`, `Paddle Ocr`, `Runtime Control`, `Native Extraction`, `Extraction`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Why does `Block` connect `Simple Pipeline` to `Pipeline`, `Openai Vision Gateway`, `Agentic Contract`, `Agentic`, `Benchmark`, `Render`, `Benchmark`, `Quality`, `Simple Pipeline`, `Workspace Store`, `Agentic Extraction`, `Native Pdf Parser`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Why does `DocumentParser` connect `Simple Pipeline` to `Pipeline`, `Openai Vision Gateway`, `Agentic Contract`, `Simple Pipeline`, `Render`, `Cli`, `Page Analysis`, `Evaluate Corpus`, `Workspace Store`, `Agentic Extraction`, `Universal`, `Runtime Control`, `Native Extraction`, `Simple Pipeline`, `Simple Pipeline`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 77 inferred relationships involving `ParserConfig` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`ParserConfig` has 77 INFERRED edges - model-reasoned connections that need verification._
- **Are the 44 inferred relationships involving `Block` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`Block` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 92 inferred relationships involving `DocumentParser` (e.g. with `DoclingNativeParser` and `PdfInspectorParser`) actually correct?**
  _`DocumentParser` has 92 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `Document` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`Document` has 48 INFERRED edges - model-reasoned connections that need verification._