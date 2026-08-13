# Codebase Structure

## Core Sections (Required)

### 1) Top-Level Map

| Path | Responsibility |
|---|---|
| `src/grounded_docparse/` | Installable parsing, OCR, native ingestion, evidence, extraction, and persistence package |
| `streamlit_app.py` | Single-file Streamlit application and workflow orchestration |
| `tests/` | 39 pytest modules covering contracts, pipelines, UI, CLI, persistence, and evaluation |
| `benchmarks/` | Corpus manifests, annotations, schemas, and regression policies |
| `scripts/` | Evaluation, corpus/example generation, docs/wiki refresh, installer build, and WSL runtime operations |
| `installer/` | Windows PowerShell installer and Inno Setup definition |
| `config/` | GLM-OCR and PaddleOCR runtime configuration |
| `docs/`, `docs-site/` | Maintained Markdown documentation and generated static site |
| `wiki/` | Repository knowledge wiki and its generated graph metadata |
| `.ua/`, `.codegraph/`, `.code-review-graph/`, `graphify-out/` | Generated code/knowledge graph artifacts; do not treat these as application modules |

### 2) Entry Points

- `streamlit_app.py`: interactive upload, manual processing-type selection, mixed-PDF page review, parsing, extraction, and downloads.
- `src/grounded_docparse/cli.py`: installed `grounded-docparse parse` and `grounded-docparse ingest` commands.
- `Launch-GLM-OCR.cmd`, `Launch-PaddleOCR-VL-1.6.cmd`: Windows launchers for the app plus local OCR stack.
- `scripts/wsl/launch-stack.sh`, `scripts/wsl/manage-ocr-stack.sh`: WSL service lifecycle.
- `installer/Install-GroundedDocParse.ps1`: workstation installation entry point.
- `scripts/evaluate_corpus.py`: offline/live evaluation and regression reporting.

### 3) Module Boundaries

| Module group | Files | Boundary |
|---|---|---|
| Public API/config | `__init__.py`, `config.py`, `models.py`, `native.py` | Exported contracts, immutable evidence models, configuration, and versions |
| Manual routing/native ingestion | `universal.py`, `native_parsers.py`, `docling_native.py` | File/container validation and exactly one explicitly selected parsing route |
| OCR ingestion | `pipeline.py`, `ingest.py`, `page_analysis.py`, `local_ocr.py`, `paddle_ocr.py`, `ocr_services.py` | PDF/image rendering, local OCR, page analysis, and recovery |
| Agent/provider layer | `gateways.py`, `runtime.py`, `agentic.py`, `enhancement.py` | OpenAI calls, bounded retries/concurrency, analysis, refinement, and chat |
| Extraction/grounding | `extraction.py`, `native_extraction.py`, `quality.py`, `ocr_disagreement.py` | Schema extraction, source validation, quality checks, and OCR comparison |
| Rendering/export | `render.py` | Markdown, JSON, annotated PDF, and combined output contracts |
| Persistence/batch | `batch.py`, `schema_store.py`, `workspace_store.py` | Batch identity, SQLite schemas/profiles, durable results and artifacts |
| Evaluation | `benchmark.py` | Corpus validation, metrics, calibration, and policy evaluation |

The package currently contains 29 Python modules. Public imports are curated in `src/grounded_docparse/__init__.py`; UI-only state and presentation remain in `streamlit_app.py`.

### 4) Naming and Organization Rules

- Python modules, functions, parameters, and local variables use `snake_case`; classes and Pydantic models use `PascalCase`; constants use `UPPER_SNAKE_CASE`.
- Tests mirror behavior areas as `tests/test_<area>.py` and use descriptive `test_<observable_behavior>` names.
- Source-format adapters stay behind `UniversalDocumentParser`; provider behavior stays behind gateway/runtime classes.
- Durable formats and public JSON include explicit version fields. New source nodes must retain stable IDs and source anchors.
- Generated site/graph files live outside `src/`; application imports must not depend on them.

### 5) Evidence

- `pyproject.toml`
- `streamlit_app.py`
- `src/grounded_docparse/__init__.py`
- `src/grounded_docparse/universal.py`
- `src/grounded_docparse/native_parsers.py`
- `src/grounded_docparse/workspace_store.py`
- `tests/`
- `scripts/`
- `installer/`
- `CONTRIBUTING.md`
