# Product specification

## Goal

Parse one PDF or image into grounded document outputs, then optionally extract user-defined structured fields with source evidence.

## Required behavior

- One document uploader with separate **Parse document** and **Extract** stages
- Luna-medium draft, manager, specialists, schema proposal, and initial extraction
- Terra-medium only for explicit risky parse escalation or one failed-extraction repair
- At most two specialist delegations per parse round and two repair rounds
- Strict Structured Outputs, no explicit prompt-cache controls, and `store=False`
- Markdown, agentic JSON v2, legacy JSON, agent trace, and annotated PDF previews/downloads
- Actual input and output token totals from provider usage
- Deterministic source-coverage, duplicate, and critical-literal quality gates
- All high-resolution quality candidates processed in batches of eight across up to two targeted Terra rounds
- Unresolved content remains visible and is marked `needs_review` with a warning
- Verified block semantics have full Markdown coverage and exact emission spans; rejected text is JSON-auditable but never rendered or accepted as extraction evidence
- Page status includes rejected, skipped, conflicting, incomplete, unresolved-recovery, coverage, and geometry history
- Editable strict JSON Schema and evidence for every non-null extracted scalar
- `OPENAI_API_KEY` required; `OPENAI_BASE_URL` optional

## Non-goals

Persistence, queues, multi-user serving, open-ended agent loops, human-review storage, cost estimation, application caching, CLI operation, and batch orchestration.

## Done when

Contract, routing, evidence, gateway, ingest, and Streamlit tests pass; lint and compilation pass; no live paid request is required for automated verification.
