# Integrations

## Core Sections (Required)

### 1) Local OCR services

| Integration | Interface | Notes |
|-------------|-----------|-------|
| GLM-OCR | SDK + vLLM/Ollama serving | Primary local recognition path; Windows launchers bootstrap WSL |
| PaddleOCR-VL-1.6 | PaddleX API + local vLLM | Alternate engine; exclusive GPU selection with GLM |

Evidence: `local_ocr.py`, `paddle_ocr.py`, `config/glmocr.yaml`, `config/paddle-vllm.yaml`, `scripts/wsl/*`, `Launch-*.cmd`.

### 2) OpenAI / Luna

| Integration | Interface | Notes |
|-------------|-----------|-------|
| OpenAI-compatible API | Responses API via `gateways.py` | Visual recovery crops + structured agentic features |
| Auth | `OPENAI_API_KEY` env (optional `OPENAI_BASE_URL`) | Loaded from Windows user env by launchers |

Requests set `store=False`. Optional; local parse works without key.

### 3) Persistence

| Store | Purpose |
|-------|---------|
| SQLite (`schema_store.py`) | Reusable extraction schemas and routing profiles only |
| Streamlit session state | Per-document workspaces; reuse successful local parses when only agentic toggles change |

No durable cross-session parse result cache, job store, or artifact service.

### 4) Explicit non-integrations

- Not LandingAI ADE (UI “ADE mode” is a preset name only)
- No ERP/CRM/RPA connectors
- No multi-tenant auth provider
- No HTTP application API for remote clients

### 5) Evidence

- `docs/architecture.md`
- `docs/agentic-document-extraction-comparison.md`
- `src/grounded_docparse/gateways.py`
- `src/grounded_docparse/schema_store.py`
- `README.md` env setup
- `.env.example` (if present)
