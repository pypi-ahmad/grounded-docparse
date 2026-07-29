# Product specification

## Goal

Parse one PDF or image into grounded document outputs through a GLM-OCR-first pipeline and a unified engine-neutral result contract.

## Required behavior

- One document uploader with optional contiguous page-range parsing
- Evidence-triggered Luna visual recovery, schema proposal, and extraction
- Optional text-only Luna Markdown refinement using presentation directives
- Optional structured classification and hierarchical TOC generation
- On-demand schema extraction and optional cited document chat
- Luna-high for image recovery; Luna-medium for text-only refinement, classification, TOC, extraction, and chat
- One direct evidence-critic inspection pass for risky regions
- Strict Structured Outputs, no explicit prompt-cache controls, and `store=False`
- Overview, Markdown, annotated PDF, post-parse on-demand Extract, optional Chat, and hierarchical Layout Tree views
- Fast (default), Full, and automatically detected Custom ADE modes; visual recovery is enabled by default and can be turned off
- Unified JSON v4.4 with refined Markdown, grounded base Markdown, normalized elements and provenance, split recovery/agentic timing, top-level classification/sections/extraction, recovered-only recovery log, and correction history; annotated PDF bytes are separate
- Semantic PDF boxes, optional reading-order labels, and selected-element highlighting
- Actual input and output token totals from provider usage
- Deterministic source-coverage, duplicate, and critical-literal quality gates
- At most eight prioritized visual-recovery requests per document and three region crops per page by default
- Luna recovery applies only text-only corrections with confidence at or above 0.85; GLM IDs, boxes, types, confidence, reading order, and structure remain unchanged
- Luna cannot add or reject GLM elements; all-nonblank-page GLM failure stops before recovery, while isolated failed pages remain partial with warnings
- Unresolved content remains visible and is marked `needs_review` with a warning
- Verified block semantics have full Markdown coverage and exact emission spans; rejected text is JSON-auditable but never rendered or accepted as extraction evidence
- Page status includes rejected, skipped, conflicting, incomplete, unresolved-recovery, coverage, and geometry history
- SQLite-backed scalar schema builder with JSON import/export
- Extraction JSON v1.1 uses `element_id`; extracted fields are labeled `high`, `medium`, `inferred`, or `not_found`, and normalized boxes always come from GLM elements
- `OPENAI_API_KEY` optional; missing credentials disable Luna but never block GLM-OCR

## Non-goals

Document/chat persistence, queues, multi-user serving, open-ended agent loops, human-review storage, cost estimation, application caching, CLI operation, and batch orchestration.

## Done when

Contract, routing, evidence, gateway, ingest, and Streamlit tests pass; lint and compilation pass; no live paid request is required for automated verification.
