# Technology Stack

## Core Sections (Required)

### 1) Runtime Summary

- Python package and local Streamlit application targeting Python `>=3.12,<3.15`.
- `uv` owns dependency resolution, locked environments, and command execution; Hatchling builds the wheel.
- The primary host is Windows 11. GPU OCR runtimes execute in WSL/Linux, while the Streamlit app, CLI, installer, and SQLite state can run on Windows.
- The project version is `0.6.1`; the installed console command is `grounded-docparse`.

### 2) Production Frameworks and Dependencies

| Area | Package | Role |
|---|---|---|
| UI | `streamlit[pdf]` | Upload, manual route selection, review, extraction, and exports |
| Contracts | `pydantic` | Strict result, evidence, routing, and persistence models |
| PDF | `pymupdf`, `pdf-inspector` | Rendering/annotation and optional native PDF inspection/extraction |
| Native documents | `docling`, `beautifulsoup4`, `odfdo`, `openpyxl` | Non-OCR conversion plus source-structure manifests |
| Grounded extraction | `langextract[openai]` | Optional schema extraction over immutable `base_text` |
| Provider | `openai` | Luna classification, recovery, refinement, chat, and extraction calls |
| Safety/rendering | `defusedxml`, `nh3`, `pillow` | Safer XML parsing, HTML sanitization, and image operations |
| Local OCR extras | `glmocr`, `torch`, `torchvision`, `transformers`, `vllm` | WSL-hosted GLM-OCR GPU or CPU runtime |

The `native` extra enables native PDF/Office/text formats. `local-ocr` and `local-ocr-cpu` are mutually exclusive Linux extras with separate PyTorch indexes. `pywin32` is declared in the native extra on Windows, but no current source module imports it.

### 3) Development Toolchain

- `pytest` is the test runner; configuration lives in `pyproject.toml`.
- Ruff is invoked through `uvx`; the repository has no custom Ruff section, so command-line/default rules apply.
- `compileall` provides a syntax/import compilation check.
- PowerShell, CMD, Bash, and Python scripts provision local runtimes, build the installer/docs site, and run evaluation.
- There is no checked-in CI workflow, coverage tool, or coverage threshold.

### 4) Key Commands

```powershell
uv sync --python 3.12.10 --locked
uv sync --extra native --locked
uv run streamlit run streamlit_app.py
uv run grounded-docparse ingest <inputs> --processing-type <path>=<type> --output <dir>
uv run python -m pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
git diff --check
```

The legacy OCR CLI remains available as `grounded-docparse parse`. Evaluation runs through `uv run python scripts/evaluate_corpus.py` with explicit arguments.

### 5) Environment and Config

- `OPENAI_API_KEY` enables Luna-backed operations; `OPENAI_BASE_URL` optionally redirects the same provider payloads.
- `DOCPARSE_STUDIO_DB_PATH` defaults to `data/document_studio.sqlite3` and controls schemas, profiles, and durable workspace state.
- `DOCPARSE_*` variables control upload/page limits, rendering, OCR engine, concurrency, retries, crop recovery, and service endpoints.
- `config/glmocr.yaml` and `config/paddle-vllm.yaml` configure local OCR runtimes.
- `.streamlit/config.toml` configures the local web application.
- `.env` is local-only; `.env.example` contains names and non-secret defaults.

### 6) Evidence

- `pyproject.toml`
- `uv.lock`
- `.env.example`
- `.streamlit/config.toml`
- `config/glmocr.yaml`
- `config/paddle-vllm.yaml`
- `CONTRIBUTING.md`
- `src/grounded_docparse/config.py`
- `src/grounded_docparse/cli.py`
