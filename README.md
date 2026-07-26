# Grounded Document Parser

Production document extraction for PDFs and images. The pipeline emits layout-aware Markdown, hierarchical JSON, schema-defined fields, annotated PDFs, and crop-backed citations.

Its architecture is inspired by LlamaParse and LandingAI ADE: layout-first parsing, visual grounding, bounding-coordinate auditability, and bounded inspection loops. It does not call either service.

## Pipeline

1. **Luna draft** segments pages, detects reading order and bounding boxes, and produces typed text/table/figure/form blocks.
2. **Terra inspection** checks each draft against the page image, requests 450-DPI crops for ambiguous regions, and accepts, corrects, rejects, or routes evidence to review.
3. **Fail-closed export** includes only verified values in strict LLM Markdown and schema extraction. Unsupported content remains explicitly unresolved.

All model calls use strict Structured Outputs, low reasoning effort, temperature 0, `store=false`, original-detail images, stable cache prefixes, and 24-hour explicit prompt-cache retention.

## Outputs

- Layout-aware Markdown and strict LLM-ready Markdown
- Hierarchical JSON blocks for text, tables, cells, figures, charts, forms, and checkboxes
- Page, normalized, pixel, and PDF coordinates with crop hashes
- Per-value schema extraction citations
- Annotated PDF with region order, confidence, source, and verification state
- Mixed-document classification, repeated-identifier instance detection, and split manifest
- Evaluation report against labeled document trees
- Complete ZIP audit bundle

## Profiles

| Profile | Behavior | Use |
|---|---|---|
| `fast` | Luna page draft; grounded but not independently verified | Lowest latency/cost |
| `balanced` | Luna draft + one Terra inspection/crop pass | Production default |
| `maximum` | Luna draft + Terra inspection with up to two crop passes | Dense tables and fine print |

Full pages render at 200 DPI. Requested evidence crops render directly from the source at 450 DPI with 5% padding.

## Production quick start

Requirements: Docker Compose and an OpenAI API key.

```powershell
Copy-Item .env.example .env
# Fill OPENAI_API_KEY and replace every placeholder secret in .env
docker compose up --build -d
```

Open the UI at `http://localhost:8501`. The API is at `http://localhost:8000`; use `Authorization: Bearer <DOCPARSE_API_TOKEN>`.

The Compose stack runs FastAPI, Celery workers, Redis, PostgreSQL, MinIO, and Streamlit. Source and result artifacts remain until the authenticated purge endpoint is called. Scale workers independently:

```powershell
docker compose up --scale worker=8 -d
```

## API example

```powershell
curl.exe -X POST http://localhost:8000/api/v1/jobs `
  -H "Authorization: Bearer $env:DOCPARSE_API_TOKEN" `
  -H "Idempotency-Key: invoice-2026-0001" `
  -F "file=@invoice.pdf" `
  -F "profile=balanced" `
  -F "execution=realtime" `
  -F "segmentation=auto"
```

Job submissions return immediately. Poll `GET /api/v1/jobs/{id}`, list result artifacts at `/artifacts`, and download the ZIP bundle. Repeated submissions are idempotent; identical source/configuration results use the content-addressed processing cache.

## Configuration

| Variable | Default |
|---|---|
| `DOCPARSE_LUNA_MODEL` | `gpt-5.6-luna` |
| `DOCPARSE_TERRA_MODEL` | `gpt-5.6-terra` |
| `DOCPARSE_RENDER_DPI` | `200` |
| `DOCPARSE_CROP_DPI` | `450` |
| `DOCPARSE_CROP_PADDING` | `0.05` |
| `DOCPARSE_DATABASE_URL` | local SQLite outside Compose |
| `DOCPARSE_REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `DOCPARSE_S3_BUCKET` | unset; local artifact directory |

Never commit `.env`. The API requires one bearer token and is therefore single-tenant; put TLS, rate limits, and identity-aware access at the ingress for internet exposure.

## Development

```powershell
uv sync --python 3.13 --locked
uv run python -m pytest -q
uv run python -m compileall -q src streamlit_app.py tests
docker compose --env-file .env.example config --quiet
```

Tests use synthetic documents and fake providers. Live model evaluation is intentionally opt-in because it incurs cost.

See [architecture](docs/architecture.md), [specification](docs/spec.md), [contributing](CONTRIBUTING.md), [security](SECURITY.md), and [license](LICENSE).
