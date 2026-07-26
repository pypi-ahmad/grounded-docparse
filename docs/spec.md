# Implemented Specification

## Objective

Convert PDF and image uploads into layout-aware Markdown, strict LLM-ready Markdown, a validated hierarchical document tree, schema-defined values, source-grounded citations, annotated review artifacts, and an audit bundle.

The system must preserve physical source evidence, expose uncertainty, and reject unsupported values rather than manufacture a complete-looking result.

## Supported execution paths

### Production path

- Profiles: `fast`, `balanced`, `maximum`
- Providers: GPT-5.6 Luna for page drafting and GPT-5.6 Terra for inspection
- Runtime: FastAPI, Celery, Redis, PostgreSQL, S3-compatible or local artifacts, and Streamlit
- Default deployment: `compose.yaml`

### Compatibility path

- Profiles: `local-only`, `hybrid`, `maximum-accuracy`
- Providers: native PDF text, PaddleOCR-VL, GLM-OCR, and optional OpenAI adjudication
- Runtime: direct `grounded-docparse` CLI with separately installed Docker and Ollama services

The production documentation leads with the first path. Compatibility profiles remain public until code removes them.

## Inputs

- Supported PDF and image types defined by `SUPPORTED_EXTENSIONS`
- Processing profile
- `realtime` or `batch` Celery queue for API jobs
- `auto` or `off` segmentation
- Optional declared document taxonomy
- Optional bounded Draft 2020-12 extraction schema
- Optional corrected `DocumentTree` for evaluation

Uploads, filenames, schemas, model responses, labels, and provider errors are untrusted inputs.

## Production processing contract

1. Validate and ingest the document.
2. Render full pages at the configured DPI, default 200.
3. Parse each Luna response into strict `PageDraft` models.
4. Create stable IDs, coordinate variants, source crops, and crop hashes.
5. For Balanced and Maximum, parse Terra decisions into strict `PageInspection` models.
6. Rerender requested regions from the source at 450 DPI with bounded padding.
7. Stop after one crop attempt in Balanced or two in Maximum.
8. Materialize hierarchy, citations, verification states, classification, extraction, segmentation, and artifacts deterministically.
9. Mark the job `needs_review` if any content node is rejected or unresolved; otherwise mark it `completed`.

Fast produces grounded draft content but must not represent it as independently verified in strict output.

## Public HTTP interface

All `/api/v1` routes require one configured bearer token.

| Method | Path | Contract |
| --- | --- | --- |
| `POST` | `/api/v1/jobs` | Accept multipart source and options; return `202` durable job record |
| `GET` | `/api/v1/jobs/{job_id}` | Return status and bounded error information |
| `GET` | `/api/v1/jobs/{job_id}/artifacts` | List result artifact keys |
| `GET` | `/api/v1/jobs/{job_id}/artifacts/{path}` | Download one result artifact |
| `POST` | `/api/v1/jobs/{job_id}/reviews` | Store a human correction artifact |
| `POST` | `/api/v1/evaluations` | Compare the candidate tree with corrected truth |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete the job and job-scoped artifact prefix |
| `GET` | `/healthz` | Return process health without authentication |

There is no list-jobs, cancel, apply-review, streaming-progress, or cache-purge endpoint.

## Job and cache semantics

- Job states: `queued`, `running`, `waiting_provider`, `needs_review`, `completed`, `failed`, `cancelled`.
- A default idempotency key is derived from the source and request. A caller-provided key maps to one immutable logical request.
- Re-delivery of an already-terminal job is a no-op.
- OpenAI connection, timeout, and rate-limit failures receive at most three Celery retries with jittered exponential backoff.
- The processing cache key contains source hash, profile, segmentation, taxonomy, extraction schema, model IDs, and prompt version.
- The processing cache has no TTL, does not cover every rendering setting, and is not removed by the job purge endpoint.

## Document model contract

`DocumentTree.schema_version` is `1.9.0`. It contains:

- physical pages and semantic nodes;
- ordered content and relationships;
- normalized, source, pixel, and PDF coordinates where available;
- provenance, model runs, candidates, and verification state;
- crop references and SHA-256 hashes for production grounded nodes;
- typed forms, checkboxes, tables, figures, charts, and formulas;
- classification, fields, logical tables, and schema extractions;
- validation findings, failures, retries, and quality summaries; and
- mixed-document classifications, boundaries, identifiers, and subdocuments.

Every schema-extracted leaf must cite existing source nodes. Table values use cell-level grounding when available and explicitly fall back to table-level grounding otherwise.

## Verification contract

Verification states are `draft`, `grounded`, `verified`, `rejected`, `needs_review`, and `human_verified`.

- Luna draft content begins as grounded evidence.
- Terra `accept` and `correct` produce verified evidence.
- Terra `reject` produces rejected evidence.
- An unresolved crop request produces needs-review evidence.
- Review API artifacts are marked human-verified but do not currently update the parsed tree.

Balanced and Maximum strict exports and schema extraction accept verified evidence. Renderers also recognize human-verified evidence when an externally curated tree already contains it, but the current review endpoint does not create such a tree. Fast strict output exposes unresolved markers.

## Output contract

Every completed or needs-review API job can produce:

- review Markdown;
- fail-closed LLM Markdown;
- complete JSON tree;
- audit JSON;
- failures JSONL;
- quality JSON;
- annotated PDF;
- batch manifest JSON;
- optional extraction JSON;
- optional table and crop assets; and
- a ZIP bundle.

Output renderers must escape untrusted content and preserve stable source references.

## Evaluation contract

Evaluation requires an available candidate artifact and a corrected tree with the same `source_sha256`. Both `completed` and `needs_review` jobs can be evaluated. Metrics are deterministic and cover text, types, layout, order, hierarchy, segmentation, document fields, extraction, citations, tables, forms, visuals, and relationships.

Evaluation returns and persists a report but does not change job state, the candidate tree, or exports. Review and evaluation prefixes are not exposed by the current result-artifact listing route.

Quality scores and model confidence are not substitutes for labeled accuracy metrics.

## Security boundaries

- The bearer-token API is single-tenant and must not be exposed directly to the public internet.
- TLS, user identity, per-tenant authorization, rate limiting, and web application filtering are ingress responsibilities.
- Source and derived artifacts may contain sensitive content and require encrypted storage, access controls, backups, and lifecycle policies.
- Logs must identify stage, model, prompt version, token usage, and latency without raw document text, crops, credentials, or full PII.
- Prompt and processing caches are separate data-retention surfaces.
- Compatibility Paddle containers remain digest-pinned, offline during normal execution, resource-bounded, and backed by an explicit persistent model volume.

## Verification commands

```powershell
uv sync --python 3.13 --locked
uv run python -m pytest -q
uv run python -m compileall -q src streamlit_app.py tests
docker compose --env-file .env.example config --quiet
uv run grounded-docparse --help
```

Automated tests use synthetic documents and fake providers. Docker builds, live OpenAI calls, real OCR accuracy, and production load tests remain separate opt-in checks.

## Known limitations

- No published real-document accuracy or million-page throughput benchmark
- No tenant model, per-job ACL, TLS termination, or rate limiting
- No Alembic migration history despite the dependency being present
- No cache TTL or complete cache purge
- No automated application of human reviews
- No job listing or cancellation API
- No OpenAI Batch API integration
- Default Compose does not run the compatibility Paddle/GLM services
- The GPT-5.6 gateway still sends a deprecated prompt-cache retention field

These are documentation-visible implementation limits, not implied future commitments.
