# Architecture

## Core Sections (Required)

### 1) Architectural Style

Grounded DocParse is a local-first modular monolith: an installable Python package supplies parsing and evidence contracts, while one Streamlit process orchestrates the product workflow. It has two explicit ingestion families:

1. the established OCR pipeline for scanned PDFs and images; and
2. a native pipeline for selectable-text PDFs and structured document formats.

The user-supplied `ProcessingType` is authoritative. Detection validates that choice; it does not silently reroute work. Both families converge on grounded Markdown/JSON and optional schema extraction, but native parsing uses immutable character spans while OCR parsing uses page elements/citations.

### 2) System Flow

```text
Upload / CLI inputs
  -> required per-file ProcessingType
  -> extension + signature/container validation
  -> UniversalDocumentParser
       -> Scanned PDF / Image: existing DocumentParser OCR pipeline
       -> Native PDF: pdf-inspector extraction; reject unusable pages
       -> Mixed PDF: pdf-inspector suggestions + explicit page routes
            -> native pages + OCR page subset -> merge in original page order
       -> Office/text/native: Docling SimplePipeline without OCR/VLM/enrichment
  -> grounded parse result
       -> OCR: page elements and citations
       -> Native: frozen base_text + SourceSpan -> SourceAnchor mappings
  -> optional schema extraction
       -> OCR DocumentAgent or native LangExtract adapter
       -> deterministic evidence validation
  -> Markdown / JSON / annotated PDF when visual / workspace persistence
```

For native extraction, LangExtract receives only `NativeDocument.base_text`. A value is accepted only when its returned interval is valid, the exact substring matches, and every non-whitespace character resolves through source spans to source anchors.

### 3) Layer/Module Responsibilities

| Layer | Responsibility | Principal modules |
|---|---|---|
| Interface | Per-file selection, mixed-page review, batch status, CLI binding, exports | `streamlit_app.py`, `cli.py` |
| Dispatch/validation | Size, extension, signature, ZIP structure, processing compatibility, one route | `universal.py` |
| OCR parsing | Render, selected engine, deterministic assembly, optional AI enhancement | `pipeline.py`, `ingest.py`, `grounded_ocr.py`, `ollama_runtime.py`, `paddle_ocr.py` |
| Native parsing | Native PDF positions/tables; Docling conversion; exact structure claims | `native_parsers.py`, `docling_native.py` |
| Contracts/grounding | Pydantic output models, frozen base text, source units/elements/spans/anchors | `models.py`, `native.py` |
| Provider operations | OpenAI requests plus document-scoped retry/concurrency diagnostics | `gateways.py`, `runtime.py`, `agentic.py` |
| Extraction/export | Schema translation, grounded acceptance, rendering | `extraction.py`, `native_extraction.py`, `render.py` |
| State/evaluation | SQLite/artifact workspace, saved schemas/profiles, corpus metrics | `workspace_store.py`, `schema_store.py`, `benchmark.py` |

### 4) Reused Patterns

- **Fail-closed routing:** invalid file/selection pairs, incomplete mixed routes, unusable native pages, and unclaimed Docling blocks raise errors instead of falling back.
- **Adapter boundary:** OCR engines, pdf-inspector, Docling, LangExtract, and OpenAI are wrapped behind project-owned classes/functions.
- **Immutable evidence spine:** native `base_text` is frozen; each element owns a character interval and source anchor.
- **Typed external output:** Pydantic validates provider and persistence payloads before they enter public results.
- **Deterministic final authority:** model proposals can add/refine text only within contract; code owns IDs, source mappings, ordering, and export shape.
- **Per-document isolation:** batch/CLI failures are recorded per file so one failure does not silently alter or erase another route.

### 5) Known Architectural Risks

- `streamlit_app.py` and `pipeline.py` each exceed 3,000 lines and combine orchestration with many behavior branches.
- Product docs on `main` now describe native ingestion as the canonical contract; keep them synchronized when routing, JSON versions, or persistence change.
- Optional native libraries have independent conversion models; `docling_native.py` maintains a second source manifest specifically to prove exact structural provenance.
- Workspace invalidation uses app `RESULT_VERSION = "4.6.1"`, while OCR Full JSON remains `4.6.0` and native JSON is versioned `5.0.0`/`5.1.0`; maintainers must update the workspace version whenever compatibility changes.
- The local Streamlit deployment is trusted-workstation software, not a multi-user service boundary.

### 6) Evidence

- `README.md`
- `docs/spec.md`
- `streamlit_app.py`
- `src/grounded_docparse/universal.py`
- `src/grounded_docparse/native.py`
- `src/grounded_docparse/native_parsers.py`
- `src/grounded_docparse/docling_native.py`
- `src/grounded_docparse/native_extraction.py`
- `src/grounded_docparse/pipeline.py`
- `src/grounded_docparse/workspace_store.py`
- `tests/test_universal_parser.py`
- `tests/test_native_pdf_parser.py`
- `tests/test_docling_native_parser.py`
- `tests/test_native_extraction.py`
