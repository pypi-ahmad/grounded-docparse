# Structure

## Core Sections (Required)

### 1) Top-level layout

| Path | Role |
|------|------|
| `streamlit_app.py` | Main UI entry |
| `src/grounded_docparse/` | Core library (19 Python modules) |
| `app_pages/` | Streamlit page modules |
| `config/` | GLM/Paddle runtime YAML |
| `scripts/wsl/` | WSL setup, serve, health checks |
| `tests/` | Pytest suite (~26 test modules) |
| `docs/` | Design and user docs |
| `docs-site/` | Built HTML docs site |
| `benchmarks/` | Corpus, schemas, baselines |
| `data/` | Local DB path, sample PDFs/outputs (gitignored DB) |
| `components/` | Streamlit grounding review component |

### 2) Package modules (`src/grounded_docparse/`)

| File | Responsibility |
|------|----------------|
| `pipeline.py` | `DocumentParser` orchestration |
| `agentic.py` | `DocumentAgent` prepare/analyze/route/chat |
| `extraction.py` | `DocumentExtractor` schema extract + evidence resolve |
| `local_ocr.py` / `paddle_ocr.py` | Engine clients |
| `ingest.py` | Validation + rasterization |
| `page_analysis.py` / `quality.py` | Quality signals |
| `gateways.py` / `prompts.py` | OpenAI gateway + prompts |
| `enhancement.py` | Markdown presentation plan |
| `models.py` | Pydantic contracts |
| `render.py` | Export rendering |
| `schema_store.py` | SQLite schemas/profiles |
| `config.py` | `ParserConfig`, engines |
| `runtime.py` | Provider concurrency/retries |
| `batch.py` | Batch limits/identity |
| `benchmark.py` | Evaluation contracts |

### 3) Entry points

- Windows: `Setup-GLM-OCR.cmd`, `Launch-GLM-OCR.cmd`, `Launch-PaddleOCR-VL-1.6.cmd`
- App: `streamlit_app.py`
- Public API: package exports in `__init__.py`
- Eval: `scripts/evaluate_corpus.py`

### 4) Evidence

- Directory listing of repo root
- `docs/architecture.md` repository map
- `src/grounded_docparse/__init__.py`
