# Product specification

## Goal

Parse one PDF or image into grounded document outputs through a GLM-OCR-first pipeline and a unified engine-neutral result contract.

## Required behavior

- One document uploader with optional contiguous page-range parsing
- Luna-medium draft, manager, specialists, schema proposal, and initial extraction
- Luna-medium only for targeted risky-region or failed-extraction repair
- At most two specialist delegations per parse round and two repair rounds
- Strict Structured Outputs, no explicit prompt-cache controls, and `store=False`
- Overview, Markdown, annotated PDF, and hierarchical Layout Tree views
- Unified JSON v4 with normalized flat elements plus the compatible nested audit document
- Semantic PDF boxes, optional reading-order labels, and selected-element highlighting
- Actual input and output token totals from provider usage
- Deterministic source-coverage, duplicate, and critical-literal quality gates
- All high-resolution quality candidates processed in batches of eight across bounded targeted Luna rounds
- Unresolved content remains visible and is marked `needs_review` with a warning
- Verified block semantics have full Markdown coverage and exact emission spans; rejected text is JSON-auditable but never rendered or accepted as extraction evidence
- Page status includes rejected, skipped, conflicting, incomplete, unresolved-recovery, coverage, and geometry history
- Editable strict JSON Schema and evidence for every non-null extracted scalar
- `OPENAI_API_KEY` required; `OPENAI_BASE_URL` optional

## Non-goals

Persistence, queues, multi-user serving, open-ended agent loops, human-review storage, cost estimation, application caching, CLI operation, and batch orchestration.

## Done when

Contract, routing, evidence, gateway, ingest, and Streamlit tests pass; lint and compilation pass; no live paid request is required for automated verification.
