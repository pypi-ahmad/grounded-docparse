# Graph Report - .  (2026-07-27)

## Corpus Check
- Corpus is ~22,831 words - fits in a single context window. You may not need a graph.

## Summary
- 482 nodes · 1748 edges · 33 communities (21 shown, 12 thin omitted)
- Extraction: 55% EXTRACTED · 45% INFERRED · 0% AMBIGUOUS · INFERRED: 779 edges (avg confidence: 0.64)
- Token cost: 100,000 input · 18,512 output

## Community Hubs (Navigation)
- Pipeline Contract Tests & Core Models
- Rendering & Benchmark Evaluation
- Ingestion & Quality Gate
- OpenAI Vision Gateway
- Draft Models & Page Processing
- Architecture & Usage Docs
- Schema Extraction & Validation
- Parallel Page Config Tests
- Invoice Total Fields
- Invoice Schema Root
- Invoice Line Item Amounts
- Invoice Line Items Array
- Invoice Object Definition
- Invoice Description Aliases
- Fail-Closed Grounding Policy
- Synthetic Example Documents
- Example Generation Script
- Security Trust Boundaries
- Project Task Tracking
- Deterministic Export Policy
- Public Contract Testing Policy
- Coordinate-Backed Auditability
- Layout-First Extraction Research
- No Local Result Cache
- Agent Trace Spec
- Agentic JSON v2 Spec
- Annotated PDF Spec
- Legacy JSON Spec
- Markdown Output Spec
- Two-Stage Tutorial Workflow
- Package Root

## God Nodes (most connected - your core abstractions)
1. `DocumentParser` - 85 edges
2. `ParserConfig` - 82 edges
3. `RegionDraft` - 67 edges
4. `PageInspection` - 57 edges
5. `PageDraft` - 53 edges
6. `Block` - 49 edges
7. `InspectionDecision` - 48 edges
8. `OpenAIDocumentGateway` - 46 edges
9. `Document` - 40 edges
10. `NodeType` - 33 edges

## Surprising Connections (you probably didn't know these)
- `DOCPARSE_LUNA_MODEL setting` --references--> `ParserConfig`  [INFERRED]
  docs/run.md → src/grounded_docparse/config.py
- `DOCPARSE_PAGE_BATCH_SIZE setting` --references--> `ParserConfig`  [INFERRED]
  docs/run.md → src/grounded_docparse/config.py
- `DOCPARSE_TERRA_MODEL setting` --references--> `ParserConfig`  [INFERRED]
  docs/run.md → src/grounded_docparse/config.py
- `DOCPARSE_MAX_PAGE_CONCURRENCY setting` --references--> `ParserConfig`  [INFERRED]
  docs/run.md → src/grounded_docparse/config.py
- `Bounded Manager-and-Specialist Workflow` --references--> `DocumentExtractor`  [INFERRED]
  docs/architecture.md → src/grounded_docparse/extraction.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Evidence Enforcement System** — docs_spec_strict_structured_outputs, docs_research_fail_closed_grounding, contributing_source_grounding [INFERRED 0.95]
- **Bounded Agentic Role Set** — docs_spec_luna, docs_spec_terra, graphify_out_memory_query_20260727_081710_how_many_agents_are_there_now__and_will_increasing_nine_agent_roles, docs_architecture_bounded_manager_specialist_workflow [INFERRED 0.85]
- **Parse Output Artifact Bundle** — docs_spec_markdown_output, docs_spec_agentic_json_v2, docs_spec_legacy_json, docs_spec_annotated_pdf, docs_spec_agent_trace [INFERRED 0.85]
- **Page Concurrency Tuning Guidance** — graphify_out_memory_query_20260727_081710_how_many_agents_are_there_now__and_will_increasing_agent_scaling_rationale, graphify_out_memory_query_20260727_081850_can_every_page_be_processed_in_parallel_in_batches_batch_concurrency_separation, graphify_out_memory_query_20260727_081947_is_5__10__or_20_pages_in_parallel_more_feasible_five_concurrent_pages_default, docs_run_docparse_max_page_concurrency [INFERRED 0.85]

## Communities (33 total, 12 thin omitted)

### Community 0 - "Pipeline Contract Tests & Core Models"
Cohesion: 0.10
Nodes (58): ParserConfig, AgentDelegation, AgentRole, InspectionAction, InspectionDecision, InspectionRegionAddition, NodeType, PageDraft (+50 more)

### Community 1 - "Rendering & Benchmark Evaluation"
Cohesion: 0.08
Nodes (65): DocumentParser as Cross-Community Orchestration Bridge, main(), accuracy_threshold_failures(), compare_markdown(), _edit_distance(), evaluate_result(), _flatten(), _normalize_whitespace() (+57 more)

### Community 2 - "Ingestion & Quality Gate"
Cohesion: 0.12
Nodes (44): ingest_document(), _ingest_image(), _ingest_pdf(), IngestedDocument, _normalized_bbox(), PageEvidence, Path, render_region_crop() (+36 more)

### Community 3 - "OpenAI Vision Gateway"
Cohesion: 0.13
Nodes (25): Strict Structured Outputs, store=False, No Prompt-Cache Controls, OpenAIDocumentGateway, Any, Path, AgentTraceEvent, CropInspectionRequest, SchemaProposalWire, T (+17 more)

### Community 4 - "Draft Models & Page Processing"
Cohesion: 0.17
Nodes (33): BaseModel, ProgressCallback, AtomicDraft, AtomicEvidence, ChartPoint, CheckboxState, Citation, DraftBoundingBox (+25 more)

### Community 5 - "Architecture & Usage Docs"
Cohesion: 0.08
Nodes (33): Bounded Autonomy Cost/Latency Tradeoff (vs open-ended recovery), Two-Specialist / Two-Repair-Round Delegation Bound, Bounded Manager-and-Specialist Workflow, Deterministic Quality Gate (70% coverage recovery, dedupe, crop batch), 100-Page Window / 50-Thread Page Scheduling, Terra as Non-Mandatory Second Pass, 8-Step Parse-to-Export Workflow, Definition of 'Agentic' as Bounded, Not Open-Ended (+25 more)

### Community 6 - "Schema Extraction & Validation"
Cohesion: 0.18
Nodes (21): Sequential Roles Limit Speed Gains from More Agents, Nine Logical Agent Roles, DocumentExtractor, _issue_pointer(), _non_null_leaves(), _pointer_exists(), _pointer_parts(), Any (+13 more)

### Community 7 - "Parallel Page Config Tests"
Cohesion: 0.17
Nodes (10): ConcurrencyTracker, ParallelGateway, Path, _stub_document(), test_parallel_page_config_defaults_and_environment(), test_parallel_page_config_rejects_concurrency_above_batch_size(), test_parser_does_not_start_later_batches_after_a_fatal_page_error(), test_parser_finalizes_cross_page_hierarchy_and_progress_on_caller_thread() (+2 more)

### Community 8 - "Invoice Total Fields"
Cohesion: 0.18
Nodes (11): properties, title, type, number, total, title, type, x-docparse-aliases (+3 more)

### Community 9 - "Invoice Schema Root"
Cohesion: 0.20
Nodes (9): additionalProperties, x-docparse-aliases, required, $schema, title, type, invoice #, invoice no (+1 more)

### Community 10 - "Invoice Line Item Amounts"
Cohesion: 0.20
Nodes (10): type, x-docparse-aliases, properties, amount, quantity, type, x-docparse-aliases, line total (+2 more)

### Community 11 - "Invoice Line Items Array"
Cohesion: 0.20
Nodes (10): additionalProperties, required, type, items, title, type, x-docparse-kind, line_items (+2 more)

### Community 12 - "Invoice Object Definition"
Cohesion: 0.29
Nodes (7): additionalProperties, required, type, properties, invoice, number, total

### Community 13 - "Invoice Description Aliases"
Cohesion: 0.33
Nodes (6): type, x-docparse-aliases, description, item, product, service

### Community 14 - "Fail-Closed Grounding Policy"
Cohesion: 0.50
Nodes (4): Unreleased Agentic Rewrite, Source Grounding, Fail-Closed Visual Grounding, Feature Evidence and Audit Requirements

### Community 15 - "Synthetic Example Documents"
Cohesion: 0.50
Nodes (4): Routine Imaging Review Request, Synthetic Medical Fax, Monthly Operations Metrics, Synthetic Clinical Operations Report PDF

### Community 16 - "Example Generation Script"
Cohesion: 0.83
Nodes (3): digital_report(), fax_document(), main()

### Community 17 - "Security Trust Boundaries"
Cohesion: 0.67
Nodes (3): Sanitized Bug Diagnostics, Trusted Local Workstation Security Model, Untrusted Document Inputs

### Community 19 - "Project Task Tracking"
Cohesion: 0.67
Nodes (3): Security and Hierarchy Remediation Plan, Implementation Checklist, Pending Live Model Smoke Tests

## Knowledge Gaps
- **56 isolated node(s):** `$schema`, `title`, `type`, `type`, `type` (+51 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DocumentParser` connect `Pipeline Contract Tests & Core Models` to `Rendering & Benchmark Evaluation`, `Ingestion & Quality Gate`, `OpenAI Vision Gateway`, `Draft Models & Page Processing`, `Architecture & Usage Docs`, `Schema Extraction & Validation`, `Parallel Page Config Tests`?**
  _High betweenness centrality (0.139) - this node is a cross-community bridge._
- **Why does `ParserConfig` connect `Pipeline Contract Tests & Core Models` to `OpenAI Vision Gateway`, `Draft Models & Page Processing`, `Architecture & Usage Docs`, `Schema Extraction & Validation`, `Parallel Page Config Tests`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Why does `Block` connect `Rendering & Benchmark Evaluation` to `Pipeline Contract Tests & Core Models`, `Ingestion & Quality Gate`, `Draft Models & Page Processing`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 75 inferred relationships involving `DocumentParser` (e.g. with `Bounded Manager-and-Specialist Workflow` and `Deterministic Quality Gate (70% coverage recovery, dedupe, crop batch)`) actually correct?**
  _`DocumentParser` has 75 INFERRED edges - model-reasoned connections that need verification._
- **Are the 71 inferred relationships involving `ParserConfig` (e.g. with `DOCPARSE_LUNA_MODEL setting` and `DOCPARSE_MAX_PAGE_CONCURRENCY setting`) actually correct?**
  _`ParserConfig` has 71 INFERRED edges - model-reasoned connections that need verification._
- **Are the 52 inferred relationships involving `RegionDraft` (e.g. with `DocumentParser` and `_ProcessedPage`) actually correct?**
  _`RegionDraft` has 52 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `PageInspection` (e.g. with `OpenAIDocumentGateway` and `DocumentParser`) actually correct?**
  _`PageInspection` has 48 INFERRED edges - model-reasoned connections that need verification._