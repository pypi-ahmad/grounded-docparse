# Grounded DocParse technical overview

This page is the engineering entry point for Grounded DocParse. The canonical
deep references are the [architecture guide](docs/architecture.md),
[product specification](docs/spec.md), and [Python API](docs/api.md).

## System boundary

The application is a synchronous Streamlit process backed by local OCR
services in Ubuntu 24.04 under WSL2. Local services bind to loopback. Optional
AI-provider calls are outbound model requests for bounded recovery and document-level
features; they do not own source geometry or evidence identity.

## Explicit routing

Every file has one required `ProcessingType`:

```text
NATIVE_PDF, SCANNED_PDF, MIXED_PDF, WORD, POWERPOINT,
EXCEL, CSV, IMAGE, OTHER_NATIVE
```

The UI or CLI selection controls dispatch. Extension checks narrow legal
choices; signature and container validation confirm the selection. Invalid
combinations stop before parsing, and no pipeline silently falls back to
another route.

## Processing pipelines

### Scanned PDFs and images

Pages are rasterized and sent to the selected extraction engine. Native Windows
PP-DocLayoutV3 grounds GLM-OCR vLLM and Ollama crops; PaddleOCR-VL retains its
full WSL Paddle pipeline. The grounded engine owns layout, element identity, type, confidence, bounding
boxes, and reading order. Deterministic quality analysis may request bounded
text recovery, but recovery cannot add regions or alter geometry.

### Native PDFs

`pdf-inspector` extracts selectable text, layout, tables, page positions, and
bounding boxes without OCR. A page that cannot provide usable native evidence
causes Native PDF processing to stop and recommend Mixed PDF.

### Mixed PDFs

`pdf-inspector` proposes a Native or OCR route per page. The user confirms or
overrides every route before execution. Native and OCR page results are merged
in original page order with no silent fallback.

### Office and other native formats

OCR-disabled Docling conversion supports DOCX, PPTX, XLSX, CSV, HTML, EPUB,
Markdown, selected OpenDocument formats, and other explicitly supported native
inputs. Deterministic manifests claim converted blocks against original
paragraphs, shapes, sheets, cells, tables, rows, or columns. Embedded images
are recorded as assets and are not OCRed.

## Evidence model

`NativeDocument` stores immutable `base_text`, source spans, source anchors,
blocks, tables, assets, warnings, and rendered views. Each source span maps a
half-open character interval in `base_text` to one or more `SourceAnchor`
records.

LangExtract receives only `base_text`. A candidate is accepted only when it has
an exact `char_interval`, its value matches the referenced source text, and the
interval resolves through source spans to anchors. Refined Markdown cannot
become evidence, and ungrounded values are rejected.

## Interfaces and persistence

- `streamlit_app.py` is the interactive application entry point.
- `grounded-docparse ingest` is the batch CLI entry point.
- `src/grounded_docparse/` contains public parsing models and orchestration.
- Workspace persistence retains processing types, page routes, `base_text`,
  spans, anchors, assets, warnings, and grounded extraction evidence.
- Visual formats can export annotated PDFs; nonvisual native formats expose
  Markdown, JSON, and source-structure views instead.

## Security properties

Uploaded files and model outputs are untrusted. Container parsing, XML
handling, filenames, Markdown rendering, and persisted state must remain
validated and bounded. OCR, Docling, PDF Inspector, and LangExtract must not
gain network or OCR behavior beyond their documented route. Review
[SECURITY.md](SECURITY.md) before changing egress, storage, or trust boundaries.

## Development and extension

Install the locked development environment:

```powershell
uv sync --python 3.12.10 --locked --extra native
```

Before adding a native format, define its compatible processing type, validate
its signature/container, preserve exact source anchors, add public-contract and
fixture tests, update exports and persistence, and extend the evaluation
corpus. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and the
[code of conduct](CODE_OF_CONDUCT.md).
