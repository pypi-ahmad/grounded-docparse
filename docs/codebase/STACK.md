# Technology Stack

## Core Sections (Required)

### 1) Runtime Summary

- Python package and local Streamlit application targeting Python `>=3.12,<3.15`.
- `uv` owns dependency resolution, locked environments, and command execution; Hatchling builds the wheel.
- The primary host is Windows 11. Streamlit, CLI, SQLite, CPU PP-DocLayoutV3, native parsers, and Ollama run on Windows; the two GPU vLLM runtimes execute in WSL/Linux.
- The project version is `0.6.1`; the installed console command is `grounded-docparse`.

### 2) Production Frameworks and Dependencies

| Area | Package | Role |
|---|---|---|
| UI | `streamlit[pdf]` | Upload, manual route selection, review, extraction, and exports |
| Contracts | `pydantic` | Strict result, evidence, routing, and persistence models |
| PDF | `pymupdf`, `pdf-inspector` | Rendering/annotation and optional native PDF inspection/extraction |
| Native documents | `docling`, `beautifulsoup4`, `odfdo`, `openpyxl` | Non-OCR conversion plus source-structure manifests |
| Grounded extraction | `langextract[openai]` | Optional schema extraction over immutable `base_text` |
| Providers | `openai`, `google-genai` | OpenAI, Gemini, and Agnes-compatible classification, enhancement, refinement, chat, and extraction |
| Safety/rendering | `defusedxml`, `nh3`, `pillow` | Safer XML parsing, HTML sanitization, and image operations |
| Windows layout extra | `torch`, `torchvision`, `transformers` | CPU PP-DocLayoutV3 grounding for GLM vLLM and Ollama |
| WSL OCR extras | `glmocr`, `vllm`, PaddleOCR/PaddleX | Isolated GLM-OCR and PaddleOCR-VL GPU services |

The `native` extra enables native PDF/Office/text formats. `windows-layout` installs CPU detector dependencies. `local-ocr` and `local-ocr-cpu` remain mutually exclusive Linux extras for WSL service provisioning.

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

- `OPENAI_API_KEY`, `GOOGLE_API_KEY`, and `AGNES_API_KEY` enable their selectable AI models; OpenAI and Agnes support optional base-URL overrides.
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
