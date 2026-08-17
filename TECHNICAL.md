# Grounded DocParse technical overview

This explanation is the engineering entry point for new contributors. It describes the system boundaries and contracts needed to change the code safely. Use the [architecture guide](docs/architecture.md) for the full repository blueprint, [product specification](docs/spec.md) for required behavior, and [Python API reference](docs/api.md) for exact interfaces.

## Runtime boundary

Grounded DocParse is a modular Python application centered on one synchronous Streamlit process.

| Component | Runtime |
| --- | --- |
| Streamlit UI, CLI, persistence, native parsing | Windows |
| PP-DocLayoutV3 layout detection | Windows CPU |
| Ollama GLM-OCR, PaddleOCR-VL, DeepSeek-OCR | Windows Ollama |
| Docling and RapidOCR | Windows CPU |
| PDF Inspector | Windows |
| GLM-OCR vLLM | Optional WSL2 service on port `8080` |
| PaddleOCR-VL vLLM and PaddleX | Optional WSL2 services on ports `8118` and `8119` |

The application and model services bind to loopback. The product has no HTTP application API, durable worker queue, multi-user authentication, or tenant boundary.

## Entry points

- `streamlit_app.py` owns the interactive workflow.
- `grounded-docparse ingest` provides explicit native and OCR batch routing.
- `grounded-docparse parse` provides the legacy PDF and image OCR command.
- `DocumentParser` exposes grounded OCR parsing.
- `UniversalDocumentParser` exposes manually selected native, scanned, mixed, and image routes.
- `DocumentAgent` and `DocumentExtractor` expose optional analysis and extraction features.

## Routing contract

Each file has one required `ProcessingType`: `native-pdf`, `scanned-pdf`, `mixed-pdf`, `word`, `powerpoint`, `excel`, `csv`, `image`, or `other-native`.

The selected type is authoritative. Extension, signature, and container checks validate it. Invalid combinations fail before parsing. Native PDF does not fall back to OCR, and Mixed PDF requires a confirmed route for every selected page.

`UniversalDocumentParser` dispatches to one route:

```text
Native PDF      -> PDF Inspector
Scanned/Image   -> DocumentParser and selected extraction engine
Mixed PDF       -> confirmed native/OCR page routes, then ordered merge
Office/Open     -> OCR-disabled Docling or deterministic native parser
```

## Extraction engines

`ExtractionEngine` separates product choices from lower-level `OcrEngine` values. Only one extraction engine is active at a time.

- AI ADE uses the selected cloud model directly.
- GLM-OCR combines Windows CPU layout with the WSL vLLM recognizer.
- PaddleOCR-VL uses the WSL PaddleX and vLLM services.
- Docling + RapidOCR runs locally on Windows CPU.
- PDF Inspector reads selectable PDF structure without OCR.
- Local Ollama combines Windows CPU layout with one of three Ollama recognizers.

Local Ollama submits detected region crops sequentially through `/api/chat`. It uses a 4,096-token context, a 120-second request timeout, and a 300-second page deadline. Output is capped at 128, 256, or 512 tokens according to region size. DeepSeek-OCR retries a failed region once and stops the page after repeated consecutive failures.

## Parse lifecycle and progress

`DocumentParser.parse` ingests and rasterizes the selected pages, analyzes ordered page windows, constructs deterministic page elements, applies bounded recovery, renders outputs, and runs enabled optional features.

Local grounded OCR reports layout completion and every region request. The pipeline maps those events into the first 30 percent of document progress. Later recognition, assembly, enhancement, and rendering stages occupy the remaining progress bands. Streamlit receives progress on its caller thread.

Recognition has bounded failure behavior. A page-level runtime error becomes a visible page failure. AI ADE raises an error when a nonblank page contains no returned regions. An empty nonblank document is never reported as a successful parse.

## Evidence ownership

### OCR evidence

The grounded engine owns element identity, normalized geometry, type, confidence, and reading order. Optional AI enhancement may replace text on an existing failed or sub-75-percent-confidence element after validation. It cannot add a region or change geometry, structure, or order.

### Native evidence

`NativeDocument` stores immutable `base_text`, source units, elements, spans, anchors, tables, assets, and warnings. Each half-open character span maps back to one or more `SourceAnchor` records.

Native extraction sends only `base_text` to LangExtract. A result is accepted only when its exact `char_interval` matches the source and resolves through spans to anchors. Refined Markdown is presentation, not evidence.

## Optional AI stages

The selected cloud model can power direct AI ADE, failed-region enhancement, Markdown presentation refinement, classification, table of contents, extraction, routing, and chat. Each feature has its own structured contract and failure status.

Provider failures do not invalidate an already completed local parse. Requests use bounded concurrency and retry logic. Accepted citations must resolve to known elements or anchors.

## Persistence and session lifecycle

SQLite stores workspace metadata, settings, reusable schemas, routing profiles, failures, usage, and completed results. Sibling workspace directories store source bytes and completed artifacts.

Completed results can be restored after restart. A stored `processing` or legacy `interrupted` record is normalized to `pending`; partial progress, checkpoints, analysis, extraction state, and incomplete results are not restored. Extraction review, routing review, and chat remain session-only.

## Configuration and logging

`ParserConfig.from_env()` reads engine, model, rendering, threshold, concurrency, retry, endpoint, timeout, and analysis settings. Loopback validation protects local GLM, Paddle, and Ollama origins.

The Streamlit entry point configures INFO logging for the `grounded_docparse` package. OCR logs record page, region, model, timing, token counts, done reason, and output length without logging OCR text or image payloads. The Windows launcher follows Streamlit, WSL OCR, managed Ollama, and Ollama server logs in one terminal.

There is no external metrics, tracing, alerting, or centralized log service.

## Output contracts

| Output | Version |
| --- | --- |
| OCR parse JSON | `4.5.0` |
| OCR Full JSON | `4.6.0` |
| Legacy extraction JSON | `1.1.0` |
| Routed extraction JSON | `2.0.0` |
| Native document JSON | `5.0.0` |
| Native document plus extraction | `5.1.0` |

The Streamlit workspace compatibility version is separate from public output schema versions.

## Change the system safely

Before adding a format or engine:

1. Define its explicit route and compatibility checks.
2. Preserve deterministic identity and source evidence.
3. Keep optional AI work behind validated contracts.
4. Add focused unit and integration tests.
5. Update public exports, persistence compatibility, docs, and evaluation fixtures where applicable.
6. Run the repository verification commands.

```powershell
uv sync --locked
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
uv run python -m pytest -q
uv run grounded-docparse ingest --help
```

Follow [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the [codebase conventions](docs/codebase/CONVENTIONS.md).
