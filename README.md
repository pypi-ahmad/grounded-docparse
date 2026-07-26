# Grounded Document Parser

Grounded Document Parser converts PDFs and images into auditable Markdown, hierarchical JSON, schema-defined fields, annotated PDFs, and crop-backed citations.

The production path uses GPT-5.6 Luna for fast page drafting and GPT-5.6 Terra for visual inspection. Its design is inspired by LlamaParse and LandingAI ADE—layout-first parsing, typed regions, visual grounding, and bounded verification loops—but it does not call either service.

> [!IMPORTANT]
> This repository is an early production reference, not a benchmark result. Accuracy, throughput, and operating cost depend on document mix, model availability, worker sizing, and evaluation data.

## What it produces

- Layout-aware Markdown and strict LLM-ready Markdown
- A hierarchical document tree for text, tables, cells, figures, charts, forms, and checkboxes
- Normalized, pixel, and PDF coordinates with crop hashes
- Per-value citations for schema extraction
- Annotated PDFs showing reading order, confidence, source, and verification state
- Mixed-document classification, repeated-identifier splitting, and subdocument manifests
- Evaluation reports against corrected document trees
- ZIP audit bundles containing the parse and supporting artifacts

Strict exports fail closed: Balanced and Maximum include only verified evidence. Rejected or unresolved regions remain visible in audit outputs but are not silently promoted to extracted facts.

## Production pipeline

1. Luna drafts ordered, typed regions from a 200-DPI page image.
2. Terra compares the draft with the page and accepts, corrects, rejects, or requests a closer inspection.
3. Requested regions are rendered directly from the source at 450 DPI with bounded padding.
4. Deterministic code builds the hierarchy, citations, Markdown, JSON, segmentation, schema extraction, quality report, and review artifacts.

Model responses use Pydantic-backed Structured Outputs, low reasoning effort, `temperature=0`, original-detail images, and `store=false`. Stable prompt-cache keys improve routing for repeated prefixes. OpenAI controls actual cache eligibility and retention; see [Architecture](docs/architecture.md#model-and-processing-caches).

## Profiles

| Profile | Behavior | Recommended use |
| --- | --- | --- |
| `fast` | Luna drafts and grounds regions; no independent Terra verification | Lowest latency and exploratory parsing |
| `balanced` | Luna draft plus Terra inspection and at most one crop pass | Default production profile |
| `maximum` | Luna draft plus Terra inspection and at most two crop passes | Dense tables, forms, and fine print |

The CLI also retains `local-only`, `hybrid`, and `maximum-accuracy` for compatibility with the earlier PaddleOCR-VL/GLM pipeline. Those modes require separate Docker, model-cache, and Ollama setup and are not part of the default Compose stack. See [Run Commands](docs/run.md#compatibility-cli-pipeline).

## Quick start

Requirements:

- Docker with Compose, configured for Linux containers, and enough local disk for images and service volumes
- An OpenAI API key with access to the configured Luna and Terra models
- Available ports `8000` and `8501`

```powershell
git clone https://github.com/pypi-ahmad/grounded-docparse.git
Set-Location grounded-docparse
Copy-Item .env.example .env
# OPENAI_API_KEY and OPENAI_BASE_URL are read from this PowerShell environment.
uv run python -m grounded_docparse.compose_env rotate .env
docker compose up --build -d
docker compose ps
```

Open:

- Streamlit UI: <http://localhost:8501>
- FastAPI OpenAPI UI: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/healthz>

The API requires `Authorization: Bearer <DOCPARSE_API_TOKEN>`. The default deployment uses one shared token and is therefore single-tenant. Put TLS, request-size controls, rate limits, and identity-aware authorization at the ingress before exposing it outside a trusted network.

## Submit a job

```powershell
$headers = @{ Authorization = "Bearer $env:DOCPARSE_API_TOKEN" }

curl.exe -X POST http://localhost:8000/api/v1/jobs `
  -H "Authorization: Bearer $env:DOCPARSE_API_TOKEN" `
  -H "Idempotency-Key: invoice-2026-0001" `
  -F "file=@invoice.pdf" `
  -F "profile=balanced" `
  -F "execution=realtime" `
  -F "segmentation=auto"
```

The endpoint returns `202 Accepted` with a durable job record. Poll `GET /api/v1/jobs/{job_id}`, list `GET /api/v1/jobs/{job_id}/artifacts`, and download an artifact from `GET /api/v1/jobs/{job_id}/artifacts/{artifact_path}`. Listed keys include the storage prefix; the download parameter is the portion relative to `jobs/{job_id}/result/`.

`execution=batch` selects a lower-concurrency Celery queue; it does not use the OpenAI Batch API. Repeated submissions without a custom idempotency key derive one from the source hash and request. A caller-supplied key must identify one immutable request.

See [Run Commands](docs/run.md) for review, evaluation, purge, scaling, and compatibility CLI examples.

## Services and persistence

The Compose stack runs:

- FastAPI for authenticated job and artifact endpoints
- Separate Celery workers for `realtime` and `batch` queues
- PostgreSQL for job state
- Redis for Celery delivery
- MinIO for source, result, review, evaluation, and cache artifacts
- Streamlit as an asynchronous submit/poll client

Streamlit also supports a Docker-free `Local` backend. When
`OPENAI_BASE_URL` and `OPENAI_API_KEY` are present in the launching process,
it runs the parser in-process and returns the ZIP bundle directly. Local work
does not survive a browser or process restart.

Scale realtime workers independently:

```powershell
docker compose up --scale worker=8 -d
```

The architecture can scale horizontally, but this repository does not include a million-page benchmark, autoscaling policy, queue backpressure controller, or tenant isolation.

## Configuration

| Variable | Default outside Compose | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | unset | OpenAI authentication |
| `OPENAI_BASE_URL` | unset | OpenAI-compatible API endpoint |
| `DOCPARSE_API_TOKEN` | required by the API | Shared bearer token |
| `DOCPARSE_API_PORT` | `8000` | Published host API port in Compose |
| `DOCPARSE_LUNA_MODEL` | `gpt-5.6-luna` | Draft model |
| `DOCPARSE_TERRA_MODEL` | `gpt-5.6-terra` | Inspection model |
| `DOCPARSE_RENDER_DPI` | `200` | Full-page render resolution |
| `DOCPARSE_CROP_DPI` | `450` | Source crop resolution |
| `DOCPARSE_CROP_PADDING` | `0.05` | Default crop padding ratio |
| `DOCPARSE_DATABASE_URL` | `sqlite:///.docparse/jobs.db` | Durable job database |
| `DOCPARSE_REDIS_URL` | `redis://127.0.0.1:6379/0` | Celery broker |
| `DOCPARSE_ARTIFACT_ROOT` | `.docparse/artifacts` | Local artifact root when S3 is unset |
| `DOCPARSE_S3_BUCKET` | unset | Enables S3-compatible artifact storage |
| `DOCPARSE_S3_ENDPOINT` | unset | S3-compatible endpoint, such as MinIO |

Never commit `.env`, source documents, model caches, or result artifacts.

## Data lifecycle limitations

`DELETE /api/v1/jobs/{job_id}` removes the job row and its `jobs/{job_id}` artifact prefix. The content-addressed `cache/{cache_key}` copy is currently separate and has no TTL or authenticated purge endpoint. Do not treat job deletion as complete erasure of cached outputs; disable or externally expire the artifact cache for regulated data until cache lifecycle management is implemented.

Review submissions create immutable review artifacts. They do not rewrite the parsed tree or move a `needs_review` job to `completed` automatically.

## Development

```powershell
uv sync --python 3.13 --locked
uv run python -m pytest -q
uv run python -m compileall -q src streamlit_app.py tests
docker compose --env-file .env.example config --quiet
```

Automated tests use synthetic documents and fake providers. Live model calls, Docker image builds, throughput tests, and accuracy evaluations are opt-in because they require external services or incur cost.

## Documentation

- [Architecture and design](docs/architecture.md)
- [How the pipeline works](docs/how-it-works.md)
- [Run commands and operations](docs/run.md)
- [Zero-to-first-audit tutorial](docs/tutorial.md)
- [Implemented specification](docs/spec.md)
- [Research basis](docs/research.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

Licensed under the [MIT License](LICENSE).
