# Spec: Secure Hierarchical Document Parser

## Objective

Convert local PDF/image uploads into grounded structured Markdown, LLM-ready Markdown, hierarchical JSON, and a ZIP bundle. Preserve physical pages and semantic structure while treating uploads, labels, model output, provider errors, and container images as untrusted. OpenAI use requires per-run consent.

## Tech Stack

Python 3.12, uv, Streamlit, PyMuPDF, Pillow/OpenCV, Pydantic, Ollama, OpenAI Responses API, and pinned PaddleOCR-VL 1.6 Docker image.

## Commands

- Sync: `uv sync --python 3.12 --locked`
- Test: `uv run pytest -q`
- Compile: `uv run python -m compileall -q src streamlit_app.py scripts tests`
- Dev: `uv run streamlit run streamlit_app.py`
- CLI: `uv run grounded-docparse DOCUMENT --output output [--profile local-only|hybrid|maximum-accuracy] [--document-profile auto|generic|technical-documentation|scientific-paper|invoice|insurance-claim|healthcare-form] [--gold-json labels.json]`
- Paddle cache: `uv run grounded-docparse-paddle-setup`

## Project Structure

- `src/grounded_docparse/`: ingestion, gateways, hierarchy, rendering, CLI
- `tests/`: public-contract and abuse-case tests
- `docs/`: architecture, security, research
- `tasks/`: implementation plan and checklist
- `examples/`: synthetic, non-sensitive fixtures and outputs

## Code Style

```python
def parse(data: bytes, filename: str, *, profile: ProcessingProfile | None = None, document_profile: DocumentProfile = DocumentProfile.AUTO) -> ParseResult:
    document = ingest_document(data, filename)
    return build_grounded_result(document, profile=profile or ProcessingProfile.LOCAL_ONLY, document_profile=document_profile)
```

Use typed, direct functions; validate at boundaries; deterministic IDs; no speculative abstraction or new dependency.

## Testing Strategy

Pytest exercises public parser, renderer, CLI/runtime command construction, and Streamlit seams. Abuse tests cover resource limits, model-output validation, Markdown injection, consent, and container cleanup. Live model checks use only synthetic documents.

## Boundaries

- Always: validate uploads/model output, escape exports, bound resource use, run locked tests/audit.
- Ask first: new dependencies, cloud providers, authentication, persistence, and schema-breaking changes beyond 1.9.0.
- Never: log document contents/secrets, enable cloud without consent, run mutable/networked parsing containers, expose stack traces.

## Success Criteria

- JSON 1.9.0 contains processing/document profiles, physical Page indexes, semantic hierarchy, typed visual analysis, grounded fields/forms, logical tables, schema extractions, block citations, batch segmentation, validation findings, window execution metadata, structured failure cases, and adaptive retry records.
- Each parse exports a quality report and annotated PDF. Parse-mode table metrics are explicitly structural/grounding proxies; measured accuracy requires a matching gold tree.
- Streamlit review is read-only, supports sequential batches of at most 10 files/1 GB, and synchronizes tree selection with Markdown, candidates, and page overlays.
- Custom Draft 2020-12 schemas are bounded and validated before OCR. Every emitted leaf value has source-node citations and no unsupported required value is fabricated.
- Continued page tables preserve physical nodes while exposing a logical table and full JSONL/CSV exports without silent 1,000-row truncation.
- LLM-ready Markdown grounds every block with stable citations, pages, bounding boxes, confidence, and semantic ancestry.
- Table cells preserve Paddle HTML spans and exact cell boxes when present; unavailable cell boxes are explicitly marked as table-level grounding rather than fabricated.
- A separate audit manifest reports citation coverage, unresolved nodes, model/window runs, warnings, validation findings, and failure summaries without duplicating raw document text.
- Failure JSONL records stable safe diagnostics for provider, OCR, grounding, extraction, validation, and segmentation failures; it does not include raw exception messages, document text, images, or crops.
- PDFs up to 500 pages/250 MB are sent to Paddle as sequential 25-page chunks, while source page numbering remains stable.
- Segmentation uses grounded document types and identifiers; uncertain local boundaries stay joined, while consented cloud profiles may adjudicate only the adjacent evidence window.
- Evaluation compares a parse with a corrected same-source tree using deterministic text, type, layout, order, and hierarchy metrics.
- Documents are processed in temporary 10-page windows with two in-run retries; no restart-persistent cache is created.
- Chart/image summaries are derived only in maximum-accuracy mode and are explicitly marked non-literal.
- OpenAI is never called without explicit per-run consent.
- Paddle runtime is digest-pinned, offline, least-privilege, bounded, and forcibly cleaned up on timeout.
- Uploads, model outputs, links, Markdown, and provider errors cannot bypass documented limits or output encoding.
- Existing offline behavior remains deterministic; all automated and synthetic live checks pass.
- Scanned pages use Paddle layout followed by type-routed GLM recognition for every region.
- Cloud-consented Luna selects local candidates; novel corrections require unbiased GLM retry evidence.
- Nodes preserve all recognition candidates, agreement, verification status, and selected candidate.

## Open Questions

None. Approved defaults: dual-index hierarchy, per-run cloud consent, explicit Paddle cache warm-up.
