# External Integrations

## Core Sections (Required)

### 1) Integration Inventory

| Integration | Direction | Data/role | Boundary and constraints |
|---|---|---|---|
| OpenAI API / compatible base URL | Outbound HTTPS | Luna classification, recovery, refinement, chat, schema work, native LangExtract | `OPENAI_API_KEY`; optional `OPENAI_BASE_URL`; fixed project model settings; provider output is validated |
| GLM-OCR | Local in-process/WSL | Default scanned PDF/image recognition and layout | Linux extras; process-wide serialized runtime because model loading is expensive |
| PaddleOCR-VL | Local HTTP | Alternate OCR and disagreement checks | Default endpoint `http://127.0.0.1:8119`; URL is validated; bounded timeout |
| pdf-inspector | In-process optional library | PDF type/page suggestions, native Markdown, text positions, structure roles | PDFs only; never performs OCR in this project; unusable pages fail or require explicit mixed routing |
| Docling | In-process optional library | DOCX/PPTX/XLSX/CSV/HTML/EPUB/ODF/Markdown conversion | `SimplePipeline`; remote services, external plugins, picture classification/description, and chart extraction disabled |
| LangExtract | Outbound through OpenAI provider | Optional schema extraction over native `base_text` | No URL fetching or fuzzy alignment; values without exact character/source grounding are rejected |
| Streamlit | Local HTTP/browser | UI and PDF preview/download transport | Intended for a trusted workstation; launchers bind locally |

The `native` extra declares `pywin32` on Windows, but no source path currently imports or invokes it. Treat it as an unresolved dependency decision, not an active integration.

### 2) Data Stores

- SQLite at `DOCPARSE_STUDIO_DB_PATH` (default `data/document_studio.sqlite3`) stores reusable schemas, classifier profiles, workspace metadata, results, analyses, and native extraction payloads.
- Parsed source bytes and larger workspace artifacts are stored under a sibling `workspaces/<sha256(document_id)>/` directory.
- `WorkspaceStore.clear()` verifies the artifact root remains below the database directory before recursive deletion.
- Output directories and downloads contain Markdown, full JSON, optional extraction JSON, optional annotated PDFs, and a batch manifest.
- Model caches, browser downloads/state, WSL environments, and runtime logs are operator-managed rather than application-owned stores.

### 3) Secrets and Credentials Handling

- Secrets come from environment variables; `.env` is ignored and `.env.example` contains empty placeholders only.
- Code checks whether `OPENAI_API_KEY` exists but does not persist it in SQLite or output contracts.
- A custom `OPENAI_BASE_URL` receives the same document context/crops as OpenAI; the UI surfaces that trust boundary.
- Fixtures use synthetic keys and fake clients; credentials and raw provider responses must not be committed.

### 4) Reliability and Failure Behavior

- `ProviderRuntime` owns retryable HTTP status handling, exponential backoff, `Retry-After`, concurrency, cooldown, and usage diagnostics. The OpenAI SDK is created with `max_retries=0`.
- CLI batch loops isolate failures per document and produce a manifest; native routing never falls back to another parser.
- File signatures and ZIP container parts/mimetypes are validated before parsing. Archive entry count and expanded-size limits reduce archive abuse.
- Docling runs with `raises_on_error=True`; source records left unclaimed cause the parse to fail.
- pdf-inspector/Docling/LangExtract are optional imports with explicit install errors. Scanned/image paths do not import these integrations.
- Workspace loading isolates corrupt artifacts, marks affected documents failed, and invalidates incompatible stored results by `RESULT_VERSION`.

### 5) Observability for Integrations

- `AgentTraceEvent` records agent/model/action/status, targets, duration, reasoning effort, and prompt version.
- `RunUsage` and `RuntimeDiagnostics` record tokens, attempts, retries, throttling, cooldown, and sleep time.
- Native source units record the effective parser and page route; extraction JSON records accepted evidence and rejection warnings.
- CLI stderr reports progress and per-document failures; the batch manifest records stage, status, and truncated error text.
- There is no external metrics, tracing, alerting, or centralized logging backend.

### 6) Evidence

- `.env.example`
- `SECURITY.md`
- `pyproject.toml`
- `src/grounded_docparse/gateways.py`
- `src/grounded_docparse/runtime.py`
- `src/grounded_docparse/local_ocr.py`
- `src/grounded_docparse/paddle_ocr.py`
- `src/grounded_docparse/universal.py`
- `src/grounded_docparse/native_parsers.py`
- `src/grounded_docparse/docling_native.py`
- `src/grounded_docparse/native_extraction.py`
- `src/grounded_docparse/workspace_store.py`
