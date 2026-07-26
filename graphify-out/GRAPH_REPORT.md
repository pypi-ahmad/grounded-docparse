# Graph Report - D:\AI\Project  (2026-07-25)

## Corpus Check
- Corpus is ~11,894 words - fits in a single context window. You may not need a graph.

## Summary
- 206 nodes · 557 edges · 17 communities (15 shown, 2 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 82 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- AI Model Gateways
- Document Ingestion
- CLI and Configuration
- Paddle Runtime
- Parsing and Rendering
- Document Data Model
- Schema Validation Tests
- Specifications and Samples
- Grounding and Verification
- Parser Architecture
- Example Generation
- Cross-Page Semantics
- Remediation Tracking
- Accuracy Evidence
- Package Entry Point

## God Nodes (most connected - your core abstractions)
1. `DocumentParser` - 53 edges
2. `ParserConfig` - 28 edges
3. `BoundingBox` - 24 edges
4. `OpenAIDocumentGateway` - 21 edges
5. `GlmOcrGateway` - 18 edges
6. `PageEvidence` - 18 edges
7. `DocumentTree` - 17 edges
8. `DocumentNode` - 16 edges
9. `NodeType` - 15 edges
10. `RegionEvidence` - 15 edges

## Surprising Connections (you probably didn't know these)
- `test_mutable_paddle_image_is_rejected()` --calls--> `ParserConfig`  [INFERRED]
  tests/test_models.py → src/grounded_docparse/config.py
- `test_normalized_bbox_rejects_coordinates_above_one()` --calls--> `BoundingBox`  [INFERRED]
  tests/test_models.py → src/grounded_docparse/models.py
- `test_source_bbox_allows_absolute_coordinates()` --calls--> `BoundingBox`  [INFERRED]
  tests/test_models.py → src/grounded_docparse/models.py
- `test_runtime_command_is_offline_and_least_privilege()` --calls--> `ParserConfig`  [INFERRED]
  tests/test_paddle.py → src/grounded_docparse/config.py
- `test_timeout_forcibly_removes_container()` --calls--> `ParserConfig`  [INFERRED]
  tests/test_paddle.py → src/grounded_docparse/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Bounded Multi-Model Grounding Flow** — readme_paddleocr_vl_pipeline, readme_glm_ocr_region_recognition, readme_luna_candidate_verification, readme_deterministic_grounding_gate [EXTRACTED 1.00]
- **Secure Hierarchical Parser Contract** — docs_spec_explicit_per_run_cloud_consent, docs_spec_untrusted_boundary_validation, docs_spec_json_schema_1_1_0 [EXTRACTED 1.00]

## Communities (17 total, 2 thin omitted)

### Community 0 - "AI Model Gateways"
Cohesion: 0.15
Nodes (22): BaseModel, GlmOcrGateway, OpenAIDocumentGateway, Any, Path, DocumentLink, DocumentResolution, NodeType (+14 more)

### Community 1 - "Document Ingestion"
Cohesion: 0.16
Nodes (24): _deskew_and_enhance(), ingest_document(), _ingest_image(), _ingest_pdf(), IngestedDocument, _normalized_bbox(), PageEvidence, Path (+16 more)

### Community 2 - "CLI and Configuration"
Cohesion: 0.15
Nodes (19): main(), _bool_env(), ParserConfig, Grounded document parsing pipeline., ParseResult, main(), DocumentParser, offline_config() (+11 more)

### Community 3 - "Paddle Runtime"
Cohesion: 0.12
Nodes (16): RuntimeError, ProgressEvent, find_paddle_regions(), PaddleDockerRunner, PaddleUnavailable, Any, Path, ProgressCallback (+8 more)

### Community 4 - "Parsing and Rendering"
Cohesion: 0.22
Nodes (15): DocumentNode, _emit(), Path, ProgressCallback, _bounded_int(), build_bundle(), _meta(), Any (+7 more)

### Community 5 - "Document Data Model"
Cohesion: 0.23
Nodes (7): Confidence, DocumentTree, PageRecord, Provenance, Relationship, _confidence(), _derived_id()

### Community 6 - "Schema Validation Tests"
Cohesion: 0.18
Nodes (6): Any, RegionDraft, test_mutable_paddle_image_is_rejected(), test_normalized_bbox_rejects_coordinates_above_one(), test_region_bbox_cannot_bypass_normalized_limit(), test_source_bbox_allows_absolute_coordinates()

### Community 7 - "Specifications and Samples"
Cohesion: 0.20
Nodes (10): Explicit Per-Run Cloud Consent, Grounded JSON Schema 1.1.0, Secure Hierarchical Document Parser Specification, Untrusted Boundary Validation, Layout-Aware Markdown with Grounding Metadata, Synthetic Clinical Operations Report Output, Routine Imaging Review Request, Synthetic Medical Fax (+2 more)

### Community 8 - "Grounding and Verification"
Cohesion: 0.33
Nodes (6): Bounded Agentic Pipeline, Unreadable Region Marker, OpenAI Structured Outputs, Two Independent Local OCR Paths, Deterministic Grounding Gate, Luna Candidate Verification

### Community 9 - "Parser Architecture"
Cohesion: 0.40
Nodes (5): LlamaParse Architectural Inspiration, GLM-OCR Region Recognition, Grounded Document Parser, PaddleOCR-VL 1.6 Pipeline, Secure Offline Container Runtime

### Community 10 - "Example Generation"
Cohesion: 0.83
Nodes (3): digital_report(), fax_document(), main()

### Community 11 - "Cross-Page Semantics"
Cohesion: 0.67
Nodes (3): Physical and Semantic Dual-Index Hierarchy, LandingAI ADE Architectural Inspiration, Terra Cross-Page Reasoning

### Community 12 - "Remediation Tracking"
Cohesion: 0.67
Nodes (3): Security and Hierarchy Remediation Plan, Implementation Checklist, Pending Live Model Smoke Tests

## Knowledge Gaps
- **13 isolated node(s):** `grounded-docparse`, `GLM-OCR Region Recognition`, `Terra Cross-Page Reasoning`, `Unreadable Region Marker`, `LlamaParse Architectural Inspiration` (+8 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DocumentParser` connect `CLI and Configuration` to `AI Model Gateways`, `Document Ingestion`, `Paddle Runtime`, `Parsing and Rendering`, `Document Data Model`?**
  _High betweenness centrality (0.151) - this node is a cross-community bridge._
- **Why does `ParserConfig` connect `CLI and Configuration` to `AI Model Gateways`, `Document Ingestion`, `Paddle Runtime`, `Schema Validation Tests`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `BoundingBox` connect `Document Ingestion` to `AI Model Gateways`, `CLI and Configuration`, `Parsing and Rendering`, `Schema Validation Tests`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Are the 33 inferred relationships involving `DocumentParser` (e.g. with `ParserConfig` and `GlmOcrGateway`) actually correct?**
  _`DocumentParser` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `ParserConfig` (e.g. with `GlmOcrGateway` and `OpenAIDocumentGateway`) actually correct?**
  _`ParserConfig` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `BoundingBox` (e.g. with `IngestedDocument` and `PageEvidence`) actually correct?**
  _`BoundingBox` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `OpenAIDocumentGateway` (e.g. with `ParserConfig` and `PageEvidence`) actually correct?**
  _`OpenAIDocumentGateway` has 9 INFERRED edges - model-reasoned connections that need verification._