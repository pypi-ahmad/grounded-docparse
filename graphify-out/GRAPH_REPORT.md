# Graph Report - .  (2026-08-10)

## Corpus Check
- 152 files · ~257,144 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1614 nodes · 5905 edges · 92 communities (68 shown, 24 thin omitted)
- Extraction: 71% EXTRACTED · 29% INFERRED · 0% AMBIGUOUS · INFERRED: 1738 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Parser Configuration
- Document Models and Rendering
- Parsing Pipeline
- OpenAI Gateway
- Evaluation and Benchmarking
- Local OCR Runtime
- Page Analysis
- Quality Repair
- Schema Storage
- Markdown Rendering
- Annotation Schema
- Provider Runtime
- Core Models
- Extraction Validation
- Streamlit Classifier UI
- Agentic Runtime Usage
- Architecture and Security
- Agentic Context Models
- Grounding Quality
- Document Studio UI
- Documentation Site Builder
- Windows WSL Installer
- Parallel Page Processing
- Stack and Changelog
- Batch Processing
- Agentic Workflow
- OCR Stack Manager
- Corpus Source Schema
- Parsing UI Pages
- Line Item Fields
- Line Item Schema
- Stack Launcher
- Form Routing Tests
- Evaluation Corpus Generator
- GLM OCR Runtime Preparation
- Corpus Annotation Schema
- Corpus Feature Schema
- Application Runtime Script
- Paddle Runtime Tests
- GLM OCR Documentation
- User Guide Documentation
- Extraction Quality Research
- Invoice Core Schema
- Invoice Schema
- Invoice Number Fields
- Invoice Total Fields
- Manifest Schema
- Manifest Entries
- Evidence Governance
- Item Alias Schema
- GLM OCR Benchmark
- Ollama Setup
- Corpus Manifest
- Corpus Document Requirements
- Manifest Requirements
- Ollama Service
- PaddleOCR Setup
- Annotation Path Schema
- Example Document Generator
- GLM OCR Service
- GLM OCR Setup
- Product Classification
- Documentation Assets
- PDF Test Fixtures
- PaddleOCR Health Check
- Agentic Module
- Extraction Module
- Pipeline Module
- Codebase Structure
- Specification Alignment
- Corpus Manifest Rationale
- PaddleOCR WSL Setup
- Feature Request Template
- Paddle vLLM Profile
- Agentic Documentation
- IDP ADE Classification
- Layout Extraction Guide
- PaddleOCR Runtime Guide
- Research Design
- Local Run Guide
- Agentic Extraction Comparison
- Changelog Page
- Bug Report Template
- Feature Request Page
- Tutorial
- Python Package Metadata
- Paddle Runtime Package

## God Nodes (most connected - your core abstractions)
1. `ParserConfig` - 164 edges
2. `Block` - 143 edges
3. `DocumentParser` - 132 edges
4. `RegionDraft` - 115 edges
5. `Document` - 102 edges
6. `PageEvidence` - 99 edges
7. `PageDraft` - 96 edges
8. `BoundingBox` - 95 edges
9. `PageInspection` - 94 edges
10. `InspectionDecision` - 90 edges

## Surprising Connections (you probably didn't know these)
- `Trusted Local Workstation Boundary` --semantically_similar_to--> `System Boundary`  [INFERRED] [semantically similar]
  SECURITY.md → docs/architecture.md
- `Local OCR Evidence Ownership` --semantically_similar_to--> `Recovery Ownership Contract`  [INFERRED] [semantically similar]
  README.md → docs/architecture.md
- `Custom Form Routing` --semantically_similar_to--> `Logical Form Segmentation`  [INFERRED] [semantically similar]
  README.md → docs/agentic-document-extraction-comparison.md
- `Evidence Ownership` --semantically_similar_to--> `Evidence Grounding`  [INFERRED] [semantically similar]
  CHANGELOG.md → docs/codebase/CONVENTIONS.md
- `RoutingGateway` --uses--> `DocumentAgent`  [INFERRED]
  tests/test_form_routing.py → src/grounded_docparse/agentic.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Grounded Document Control Flow** — docs_site_how_grounded_docparse_is_agentic_local_ocr_evidence_layer, docs_site_how_grounded_docparse_is_agentic_human_review_gates, docs_site_how_grounded_docparse_is_agentic_finite_repair, docs_site_how_it_works_grounded_extraction [EXTRACTED 1.00]
- **Local Runtime Documentation** — docs_site_setup_supported_runtime, docs_site_run_local_operation, docs_site_local_glmocr_glmocr_runtime, docs_site_local_paddleocr_vl_paddleocr_vl_runtime [INFERRED 0.85]
- **Grounded Parse-Then-Reason Flow** — readme_local_ocr_evidence_ownership, docs_architecture_parse_pipeline, docs_architecture_recovery_contract, docs_api_grounded_extraction [EXTRACTED 1.00]
- **Workstation to Azure Production Transition** — docs_architecture_system_boundary, docs_azure_bulk_fax_deployment_production_baseline, docs_azure_bulk_fax_deployment_durable_queue_processing [INFERRED 0.85]
- **Reviewed Mixed-Packet Extraction Workflow** — docs_complete_user_guide_custom_form_routing, docs_complete_user_guide_schema_constrained_extraction, docs_how_grounded_docparse_is_agentic_deterministic_evidence_layer [EXTRACTED 1.00]
- **Grounded Agentic Document Processing** — docs_how_it_works_local_ocr_parse, docs_how_it_works_luna_reasoning, docs_how_grounded_docparse_is_agentic_finite_repair, docs_how_grounded_docparse_is_agentic_deterministic_evidence_layer [EXTRACTED 1.00]
- **Document Parse Studio Workflow** — docs_site_assets_content_docs_images_document_parse_studio_full_document_upload, docs_site_assets_content_docs_images_document_parse_studio_full_parse_configuration, docs_site_assets_content_docs_images_document_parse_studio_full_document_parsing_pipeline, docs_site_assets_content_docs_images_document_parse_studio_full_parse_results [INFERRED 0.85]
- **Document Parse Studio Processing Stages** — docs_images_document_parse_studio_full_layout_detection, docs_images_document_parse_studio_full_region_recognition, docs_images_document_parse_studio_full_luna_visual_recovery, docs_images_document_parse_studio_full_base_markdown, docs_images_document_parse_studio_full_annotated_pdf, docs_images_document_parse_studio_full_luna_markdown_refinement, docs_images_document_parse_studio_full_document_classification, docs_images_document_parse_studio_full_table_of_contents [EXTRACTED 1.00]
- **Document Parse Studio Configurable Capabilities** — docs_images_document_parse_studio_full_reading_order, docs_images_document_parse_studio_full_ade_fast_mode, docs_images_document_parse_studio_full_hard_region_visual_recovery, docs_images_document_parse_studio_full_document_classification, docs_images_document_parse_studio_full_table_of_contents, docs_images_document_parse_studio_full_document_chat [EXTRACTED 1.00]
- **Document Parse Studio Result Views** — docs_images_document_parse_studio_full_markdown_output, docs_images_document_parse_studio_full_annotated_pdf, docs_images_document_parse_studio_full_layout_tree_output [EXTRACTED 1.00]
- **Local OCR Engine Implementation** — docs_codebase_stack_wsl_local_ocr, docs_codebase_structure_local_ocr, docs_codebase_structure_paddle_ocr, changelog_paddleocr_vl_local_parsing [INFERRED 0.85]
- **Grounded Recovery Governance** — changelog_evidence_ownership, changelog_luna_recovery_restrictions, docs_codebase_conventions_evidence_grounding, docs_codebase_conventions_geometry_ownership [INFERRED 0.85]

## Communities (92 total, 24 thin omitted)

### Community 0 - "Parser Configuration"
Cohesion: 0.06
Nodes (134): OcrEngine, ParserConfig, StrEnum, IngestedDocument, PageEvidence, OcrPageResult, OcrRegion, AgentRole (+126 more)

### Community 1 - "Document Models and Rendering"
Cohesion: 0.07
Nodes (93): CorpusSource, DocumentExtractor, AgentUsage, AtomicEvidence, Block, CheckboxState, Document, Page (+85 more)

### Community 2 - "Parsing Pipeline"
Cohesion: 0.06
Nodes (89): GlmPageResult, ProgressCallback, RecoveryBoxKey, ingest_document(), _ingest_image(), _ingest_pdf(), Path, render_region_crop() (+81 more)

### Community 3 - "OpenAI Gateway"
Cohesion: 0.07
Nodes (60): computed_field, build_enhancement_chunks(), combine_page_markdown(), _compatible(), EnhancementChunk, _page_input(), Document, render_chunk_plan() (+52 more)

### Community 4 - "Evaluation and Benchmarking"
Cohesion: 0.05
Nodes (84): Namespace, _glm_only_proof(), _live_report(), main(), _page_subset_mappings(), _path_mappings(), Any, Path (+76 more)

### Community 5 - "Local OCR Runtime"
Cohesion: 0.05
Nodes (50): cache_resource, RuntimeError, configure_pipeline(), ensure_cached_assets(), find_submodule(), main(), paddle_cache_root(), Path (+42 more)

### Community 6 - "Page Analysis"
Cohesion: 0.09
Nodes (44): HTMLParser, AnalysisThresholds, Deterministic image-analysis thresholds; ratios use rendered page pixels., glmocr_version(), AnalysisEngineEvidence, BoundingBoxProvenance, CoordinateBox, DetectedPageFeatures (+36 more)

### Community 7 - "Quality Repair"
Cohesion: 0.11
Nodes (55): _area(), _box_overlap(), _clipped(), _covered_fraction(), _critical_values(), _duplicate(), find_missing_source_regions(), _fingerprint() (+47 more)

### Community 8 - "Schema Storage"
Cohesion: 0.08
Nodes (31): Connection, model_validator, SchemaField, StoredSchema, ClassifierProfileStore, compile_json_schema(), _field(), _markdown_text() (+23 more)

### Community 9 - "Markdown Rendering"
Cohesion: 0.11
Nodes (40): Counter, Element, Engine-neutral, layout-aware document element., _agentic_atoms(), _annotation_group(), _annotation_label(), _as_pdf(), _atom_values() (+32 more)

### Community 10 - "Annotation Schema"
Cohesion: 0.05
Nodes (42): additionalProperties, type, type, type, minLength, type, type, type (+34 more)

### Community 11 - "Provider Runtime"
Cohesion: 0.10
Nodes (21): APIStatusError, BudgetExceeded, Exception, T, FakeTime, parametrize, Path, _runtime() (+13 more)

### Community 12 - "Core Models"
Cohesion: 0.14
Nodes (24): Grounded document parsing pipeline., AgenticAnalysis, AgentTraceEvent, ChartPoint, ChatAnswer, ChatSource, FormClassificationResult, FormSegment (+16 more)

### Community 13 - "Extraction Validation"
Cohesion: 0.15
Nodes (30): _active_blocks(), _bbox_tuple(), _boolean_token(), _canonical_evidence_pointer(), _citations_contain_value(), _evidence_contains_boolean(), _extracted_fields(), _extraction_payload() (+22 more)

### Community 14 - "Streamlit Classifier UI"
Cohesion: 0.10
Nodes (20): cache_data, ClassifierCategory, append_session_usage(), capture_document_state(), _classification_rows(), default_document_state(), load_workspace(), _missing_profile_schemas() (+12 more)

### Community 15 - "Agentic Runtime Usage"
Cohesion: 0.17
Nodes (19): DocumentAgent, _feature_error(), PreparedDocumentContext, Exception, AgenticFeatureMetadata, ChatCitationWire, ExtractedField, ExtractionResult (+11 more)

### Community 16 - "Architecture and Security"
Cohesion: 0.08
Nodes (26): Bug Report Template, Contribution Contract, Evidence-First Architecture Constraint, Logical Form Segmentation, DocumentParser API, Grounded Schema Extraction, ParseResult, DocumentAgent (+18 more)

### Community 17 - "Agentic Context Models"
Cohesion: 0.21
Nodes (20): _active_elements(), AgenticContext, _category_map(), _fallback_toc(), _flatten_sections(), _nest_sections(), _page_markdown(), _prepare_agentic_context() (+12 more)

### Community 18 - "Grounding Quality"
Cohesion: 0.08
Nodes (24): Contribution Guidelines, Deterministic Export Behavior, Source Grounding, Context Crop Experiment, Extraction Quality Evaluation Policy, Source-Verified Metrics, Bounded Evidence-Grounded Agentic Workflow, Finite Repair (+16 more)

### Community 19 - "Document Studio UI"
Cohesion: 0.12
Nodes (22): ADE Fast Mode, Annotated PDF, Base Markdown, Document Chat, Document Classification, Document Parse Studio, Document Parse Studio Interface, Document Processing Pipeline (+14 more)

### Community 20 - "Documentation Site Builder"
Cohesion: 0.25
Nodes (19): copy_local_images(), discover_markdown(), Document, document_cards(), excluded_page(), extract_document(), grouped_documents(), is_security_document() (+11 more)

### Community 21 - "Windows WSL Installer"
Cohesion: 0.32
Nodes (18): Ensure-LinuxUser(), Ensure-Wsl(), Get-HardwareMode(), Get-WslProjectRoot(), Install-LinuxPrerequisites(), Install-PaddleRuntime(), Install-Runtime(), Invoke-External() (+10 more)

### Community 22 - "Parallel Page Processing"
Cohesion: 0.23
Nodes (9): ConcurrencyTracker, ParallelGateway, Path, _stub_document(), test_parallel_page_config_rejects_concurrency_above_batch_size(), test_parser_does_not_start_later_batches_after_a_fatal_page_error(), test_parser_finalizes_cross_page_hierarchy_and_progress_on_caller_thread(), test_parser_processes_pages_concurrently_and_aggregates_in_page_order() (+1 more)

### Community 23 - "Stack and Changelog"
Cohesion: 0.15
Nodes (13): Changelog, Luna Recovery Scaling, PaddleOCR-VL-1.6 Local Parsing, Session-Scoped Batch Processing, Codebase Stack, OpenAI Luna Integration, SQLite Schema Store, Streamlit (+5 more)

### Community 24 - "Batch Processing"
Cohesion: 0.26
Nodes (10): BatchArchiveEntry, BatchDocument, build_batch_documents(), build_output_archive(), _safe_name(), document_selection_key(), output_archive(), test_batch_documents_are_stable_and_preserve_duplicate_uploads() (+2 more)

### Community 25 - "Agentic Workflow"
Cohesion: 0.18
Nodes (12): Custom Form Routing, Schema-Constrained Field Extraction, Bounded Evidence-Grounded Agentic Workflow, Deterministic OCR Evidence Layer, Finite Validation and Repair, Local OCR Parse, Optional Luna Reasoning, Agentic Document Extraction (+4 more)

### Community 26 - "OCR Stack Manager"
Cohesion: 0.53
Nodes (9): ensure_glm(), ensure_paddle(), pid_matches(), port_is_listening(), manage-ocr-stack.sh script, stop_glm(), stop_managed(), stop_paddle() (+1 more)

### Community 28 - "Corpus Source Schema"
Cohesion: 0.20
Nodes (10): kind, path, sha256, source, additionalProperties, properties, required, type (+2 more)

### Community 29 - "Parsing UI Pages"
Cohesion: 0.29
Nodes (10): Annotated PDF, Document Parse Studio, Document Parsing Pipeline, Document Upload, GLM-OCR, gpt-5.6-luna, Layout Tree, Markdown Output (+2 more)

### Community 30 - "Line Item Fields"
Cohesion: 0.20
Nodes (10): type, x-docparse-aliases, properties, amount, quantity, type, x-docparse-aliases, line total (+2 more)

### Community 31 - "Line Item Schema"
Cohesion: 0.20
Nodes (10): additionalProperties, required, type, items, title, type, x-docparse-kind, line_items (+2 more)

### Community 32 - "Stack Launcher"
Cohesion: 0.36
Nodes (8): DOCPARSE_PADDLEOCR_SERVICE_URL, pid_matches(), port_is_listening(), launch-stack.sh script, start_streamlit(), stop_managed(), streamlit_environment_matches(), wait_for_url()

### Community 33 - "Form Routing Tests"
Cohesion: 0.47
Nodes (7): _profile(), _result(), RoutingGateway, test_adjacent_same_category_forms_remain_separate_within_a_window(), test_custom_classification_gates_low_confidence_and_assigns_schema(), test_custom_classification_repairs_invalid_grounding_once(), test_routed_extraction_processes_only_approved_eligible_segments()

### Community 34 - "Evaluation Corpus Generator"
Cohesion: 0.47
Nodes (8): _annotation(), generate_corpus(), main(), Any, Path, _save_degraded_scan(), _save_pdf(), _write_schemas()

### Community 35 - "GLM OCR Runtime Preparation"
Cohesion: 0.42
Nodes (8): _atomic_write(), main(), _positive_int(), prepare(), Any, Path, _resolve_snapshot(), _runtime_config()

### Community 36 - "Corpus Annotation Schema"
Cohesion: 0.25
Nodes (8): const, minLength, type, properties, annotation_schema_version, corpus_id, schema_version, const

### Community 37 - "Corpus Feature Schema"
Cohesion: 0.25
Nodes (8): type, minLength, type, properties, features, id, synthetic, type

### Community 38 - "Application Runtime Script"
Cohesion: 0.25
Nodes (7): DOCPARSE_GLMOCR_CONFIG_PATH, DOCPARSE_LOCAL_OCR_ENABLED, DOCPARSE_OCR_ENGINE, DOCPARSE_PADDLEOCR_SERVICE_URL, DOCPARSE_PRELOAD_LOCAL_OCR, HF_HOME, run-app.sh script

### Community 39 - "Paddle Runtime Tests"
Cohesion: 0.43
Nodes (7): _config(), MonkeyPatch, Path, test_configure_pipeline_preserves_full_v1_6_layout_and_uses_vllm(), test_configure_pipeline_rejects_non_v1_6_layout(), test_main_defaults_an_empty_forwarded_port(), test_validate_cached_assets_requires_all_runtime_downloads()

### Community 40 - "GLM OCR Documentation"
Cohesion: 0.33
Nodes (7): GLM-OCR Configuration, Layout-to-Recognition Task Mapping, OpenAI-Compatible Local OCR Service, PP-DocLayoutV3 Layout Stage, Local GLM-OCR Runtime, Pinned Offline GLM-OCR Runtime, Serialized Process-Wide GLM Runtime

### Community 41 - "User Guide Documentation"
Cohesion: 0.48
Nodes (7): Grounded DocParse Complete User Guide, Python API, Architecture, Azure Bulk Medical Fax Deployment, Business User Extraction Workflow, Complete User Guide Site Page, Zero-to-Hero Tutorial

### Community 42 - "Extraction Quality Research"
Cohesion: 0.43
Nodes (7): Coarse-to-Fine Document Parsing, Extraction Quality Research, Generated References as Diagnostics, OmniDocBench, Separated Text, Layout, and Table Metrics, Targeted Context Crop Experiment, TEDS Table Structure Metric

### Community 43 - "Invoice Core Schema"
Cohesion: 0.29
Nodes (6): additionalProperties, required, $schema, title, type, invoice #

### Community 44 - "Invoice Schema"
Cohesion: 0.29
Nodes (7): additionalProperties, required, type, properties, invoice, number, total

### Community 45 - "Invoice Number Fields"
Cohesion: 0.29
Nodes (7): properties, title, type, x-docparse-aliases, number, invoice no, invoice.number

### Community 46 - "Invoice Total Fields"
Cohesion: 0.29
Nodes (7): total, title, type, x-docparse-aliases, amount due, grand total, invoice.total

### Community 47 - "Manifest Schema"
Cohesion: 0.33
Nodes (5): additionalProperties, $id, $schema, title, type

### Community 48 - "Manifest Entries"
Cohesion: 0.33
Nodes (6): items, type, items, additionalProperties, type, documents

### Community 49 - "Evidence Governance"
Cohesion: 0.33
Nodes (6): Evidence Ownership, Luna Recovery Restrictions, Agentic Failure Isolation, Codebase Conventions, Evidence Grounding, Local OCR Geometry Ownership

### Community 50 - "Item Alias Schema"
Cohesion: 0.33
Nodes (6): type, x-docparse-aliases, description, item, product, service

### Community 51 - "GLM OCR Benchmark"
Cohesion: 0.53
Nodes (5): _content(), main(), _page_image(), Any, Path

### Community 52 - "Ollama Setup"
Cohesion: 0.40
Nodes (5): download_and_extract(), OLLAMA_CONTEXT_LENGTH, OLLAMA_HOST, OLLAMA_MODELS, setup-ollama.sh script

### Community 53 - "Corpus Manifest"
Cohesion: 0.40
Nodes (4): annotation_schema_version, corpus_id, documents, schema_version

### Community 54 - "Corpus Document Requirements"
Cohesion: 0.40
Nodes (5): required, features, id, source, synthetic

### Community 55 - "Manifest Requirements"
Cohesion: 0.40
Nodes (5): schema_version, required, annotation_schema_version, corpus_id, documents

### Community 56 - "Ollama Service"
Cohesion: 0.40
Nodes (4): OLLAMA_CONTEXT_LENGTH, OLLAMA_HOST, OLLAMA_MODELS, serve-ollama.sh script

### Community 57 - "PaddleOCR Setup"
Cohesion: 0.40
Nodes (4): PADDLE_PDX_CACHE_HOME, PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK, setup-paddleocr.sh script, UV_PROJECT_ENVIRONMENT

### Community 59 - "Annotation Path Schema"
Cohesion: 0.50
Nodes (4): type, null, string, annotation_path

### Community 60 - "Example Document Generator"
Cohesion: 0.83
Nodes (3): digital_report(), fax_document(), main()

### Community 61 - "GLM OCR Service"
Cohesion: 0.50
Nodes (3): HF_HUB_OFFLINE, serve-glmocr.sh script, TRANSFORMERS_OFFLINE

### Community 62 - "GLM OCR Setup"
Cohesion: 0.50
Nodes (3): HF_HOME, setup-glmocr.sh script, UV_PROJECT_ENVIRONMENT

### Community 63 - "Product Classification"
Cohesion: 0.67
Nodes (3): Agentic Document Extraction Pattern, ADE Workstation Classification, Product Taxonomy Risk

### Community 64 - "Documentation Assets"
Cohesion: 1.00
Nodes (3): Content Lines, Documentation Favicon, Focus Frame

## Knowledge Gaps
- **184 isolated node(s):** `schema_version`, `annotation_schema_version`, `corpus_id`, `documents`, `$schema` (+179 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load_corpus_manifest()` connect `Evaluation and Benchmarking` to `Corpus Source Schema`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `path` connect `Corpus Source Schema` to `Evaluation and Benchmarking`, `Local OCR Runtime`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Are the 63 inferred relationships involving `ParserConfig` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`ParserConfig` has 63 INFERRED edges - model-reasoned connections that need verification._
- **Are the 39 inferred relationships involving `Block` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`Block` has 39 INFERRED edges - model-reasoned connections that need verification._
- **Are the 84 inferred relationships involving `DocumentParser` (e.g. with `OcrEngine` and `ParserConfig`) actually correct?**
  _`DocumentParser` has 84 INFERRED edges - model-reasoned connections that need verification._
- **Are the 56 inferred relationships involving `RegionDraft` (e.g. with `PageAnalyzer` and `_TableHTMLParser`) actually correct?**
  _`RegionDraft` has 56 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `Document` (e.g. with `AgenticContext` and `DocumentAgent`) actually correct?**
  _`Document` has 38 INFERRED edges - model-reasoned connections that need verification._