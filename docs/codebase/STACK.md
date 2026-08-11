# Stack

## Core Sections (Required)

### 1) Languages and runtimes

- Language: Python 3.12–3.14 (`requires-python = ">=3.12,<3.15"`)
- Package version: `0.5.0` (`pyproject.toml`)
- UI runtime: Streamlit process (`streamlit_app.py`)
- Local OCR runtime: WSL2/Ubuntu services (vLLM and/or Ollama, PaddleX) via launcher scripts

### 2) Frameworks and libraries

| Area | Package | Role |
|------|---------|------|
| UI | `streamlit[pdf]` | Document studio UI |
| Models | `pydantic` | Domain contracts |
| PDF/raster | `pymupdf`, `pillow` | Ingest, render, annotate |
| Cloud LLM | `openai` | Luna recovery + agentic Structured Outputs |
| Sanitization | `nh3` | HTML/sanitization helpers |
| Local OCR (optional, Linux) | `glmocr`, `torch`, `vllm`, `transformers` | Self-hosted GLM-OCR stack |

### 3) Tooling

- Package manager: `uv` (`uv.lock` present)
- Build backend: `hatchling`
- Tests: `pytest` (dev dependency group)
- Installers: `Setup-GLM-OCR.cmd`, `Launch-*.cmd`, Inno installer scripts under `installer/`

### 4) Persistence and services

- SQLite for reusable extraction schemas and routing profiles (`schema_store.py`, default `data/document_studio.sqlite3`)
- No application HTTP API, job queue, or multi-user auth layer (`docs/architecture.md`)

### 5) Evidence

- `pyproject.toml`
- `README.md`
- `docs/architecture.md`
- `src/grounded_docparse/`

## Notes / TODOs

- [TODO] Exact pinned OpenAI model string is configured in `config.py` / env; confirm current default name from source when documenting ops runbooks.
- [ASK USER] Whether docs-site HTML is considered product documentation vs internal review only.
