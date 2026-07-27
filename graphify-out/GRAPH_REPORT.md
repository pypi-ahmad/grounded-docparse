# Graph Report - .  (2026-07-27)

## Corpus Check
- Corpus is ~18,892 words - fits in a single context window. You may not need a graph.

## Summary
- 392 nodes · 1389 edges · 15 communities (14 shown, 1 thin omitted)
- Extraction: 56% EXTRACTED · 44% INFERRED · 0% AMBIGUOUS · INFERRED: 618 edges (avg confidence: 0.64)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Core Data Models
- Benchmark Evaluation
- OpenAI Gateway
- Evidence Model Types
- Schema Extraction
- Agentic Architecture
- Invoice Schema
- Extraction Schema Fields
- Document Ingestion
- Document Fixtures
- Fixture Generation
- Implementation Planning
- Package Metadata

## God Nodes (most connected - your core abstractions)
1. `DocumentParser` - 69 edges
2. `ParserConfig` - 63 edges
3. `RegionDraft` - 55 edges
4. `PageInspection` - 48 edges
5. `PageDraft` - 46 edges
6. `InspectionDecision` - 43 edges
7. `OpenAIDocumentGateway` - 37 edges
8. `Document` - 37 edges
9. `Block` - 36 edges
10. `AcceptingGateway` - 32 edges

## Surprising Connections (you probably didn't know these)
- `test_provider_draft_accepts_unordered_coordinates_for_local_validation()` --indirect_call--> `RegionDraft`  [INFERRED]
  tests/test_simple_contract.py → src/grounded_docparse/models.py
- `main()` --calls--> `DocumentParser`  [INFERRED]
  scripts/evaluate_public_water.py → src/grounded_docparse/pipeline.py
- `test_reference_comparison_reports_order_sensitive_and_token_metrics()` --calls--> `compare_markdown()`  [INFERRED]
  tests/test_public_water_benchmark.py → src/grounded_docparse/benchmark.py
- `test_reference_normalization_removes_html_tags_and_splits_punctuation()` --calls--> `compare_markdown()`  [INFERRED]
  tests/test_public_water_benchmark.py → src/grounded_docparse/benchmark.py
- `RecordingCreateResponses` --uses--> `ParserConfig`  [INFERRED]
  tests/test_openai_vision_gateway.py → src/grounded_docparse/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Bounded Agentic Parse Pipeline** — docs_architecture_luna_manager, docs_how_it_works_adaptive_delegation, docs_architecture_terra_repair, docs_architecture_deterministic_validation [EXTRACTED 1.00]
- **Grounded Output Bundle** — readme_agentic_json_v2, readme_annotated_pdf, readme_atomic_evidence, docs_how_it_works_actual_token_usage [EXTRACTED 1.00]
- **Evidence Enforcement System** — docs_spec_strict_structured_outputs, docs_research_fail_closed_grounding, docs_architecture_deterministic_validation, contributing_source_grounding [INFERRED 0.95]

## Communities (15 total, 1 thin omitted)

### Community 0 - "Core Data Models"
Cohesion: 0.11
Nodes (53): ParserConfig, AgentDelegation, AgentRole, InspectionAction, InspectionDecision, InspectionRegionAddition, NodeType, PageDraft (+45 more)

### Community 1 - "Benchmark Evaluation"
Cohesion: 0.09
Nodes (56): main(), accuracy_threshold_failures(), compare_markdown(), _edit_distance(), evaluate_result(), _flatten(), _normalize_whitespace(), _searchable_text() (+48 more)

### Community 2 - "OpenAI Gateway"
Cohesion: 0.13
Nodes (22): OpenAIDocumentGateway, Any, Path, CropInspectionRequest, SchemaProposalWire, T, _additional_properties_values(), _assert_no_prompt_cache() (+14 more)

### Community 3 - "Evidence Model Types"
Cohesion: 0.17
Nodes (33): BaseModel, ProgressCallback, AtomicDraft, AtomicEvidence, ChartPoint, CheckboxState, Citation, DraftBoundingBox (+25 more)

### Community 4 - "Schema Extraction"
Cohesion: 0.14
Nodes (26): DocumentExtractor, _issue_pointer(), _non_null_leaves(), _pointer_exists(), _pointer_parts(), Any, Validate the strict, fail-closed JSON Schema subset used by Extract., _set_pointer() (+18 more)

### Community 5 - "Agentic Architecture"
Cohesion: 0.08
Nodes (29): Unreleased Agentic Rewrite, Deterministic Export Policy, Public-Contract Testing, Source Grounding, Deterministic Validation, Luna Manager, Schema-Driven Extraction, Synchronous Streamlit Architecture (+21 more)

### Community 6 - "Invoice Schema"
Cohesion: 0.07
Nodes (27): additionalProperties, additionalProperties, properties, required, type, title, type, x-docparse-aliases (+19 more)

### Community 7 - "Extraction Schema Fields"
Cohesion: 0.08
Nodes (26): type, x-docparse-aliases, type, x-docparse-aliases, additionalProperties, properties, required, type (+18 more)

### Community 8 - "Document Ingestion"
Cohesion: 0.25
Nodes (16): ingest_document(), _ingest_image(), _ingest_pdf(), IngestedDocument, _normalized_bbox(), PageEvidence, Path, render_region_crop() (+8 more)

### Community 9 - "Document Fixtures"
Cohesion: 0.50
Nodes (4): Routine Imaging Review Request, Synthetic Medical Fax, Monthly Operations Metrics, Synthetic Clinical Operations Report PDF

### Community 10 - "Fixture Generation"
Cohesion: 0.83
Nodes (3): digital_report(), fax_document(), main()

### Community 12 - "Implementation Planning"
Cohesion: 0.67
Nodes (3): Security and Hierarchy Remediation Plan, Implementation Checklist, Pending Live Model Smoke Tests

## Knowledge Gaps
- **44 isolated node(s):** `$schema`, `title`, `type`, `type`, `type` (+39 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DocumentParser` connect `Core Data Models` to `Benchmark Evaluation`, `OpenAI Gateway`, `Evidence Model Types`, `Schema Extraction`, `Document Ingestion`?**
  _High betweenness centrality (0.080) - this node is a cross-community bridge._
- **Why does `ParserConfig` connect `Core Data Models` to `OpenAI Gateway`, `Evidence Model Types`, `Schema Extraction`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `RegionDraft` connect `Core Data Models` to `Benchmark Evaluation`, `OpenAI Gateway`, `Evidence Model Types`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 65 inferred relationships involving `DocumentParser` (e.g. with `main()` and `ParserConfig`) actually correct?**
  _`DocumentParser` has 65 INFERRED edges - model-reasoned connections that need verification._
- **Are the 53 inferred relationships involving `ParserConfig` (e.g. with `DocumentExtractor` and `OpenAIDocumentGateway`) actually correct?**
  _`ParserConfig` has 53 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `RegionDraft` (e.g. with `DocumentParser` and `RecordingCreateResponses`) actually correct?**
  _`RegionDraft` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `PageInspection` (e.g. with `OpenAIDocumentGateway` and `DocumentParser`) actually correct?**
  _`PageInspection` has 41 INFERRED edges - model-reasoned connections that need verification._