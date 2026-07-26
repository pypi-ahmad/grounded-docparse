# Run Commands

Commands are shown for PowerShell first. Run them from the repository root.

## Reference Compose deployment

### Configure

```powershell
Copy-Item .env.example .env
uv run python -m grounded_docparse.compose_env rotate .env
```

The rotation command generates URL-safe local values for:

- `DOCPARSE_API_TOKEN`
- `POSTGRES_PASSWORD`
- `MINIO_ROOT_PASSWORD`

Set `OPENAI_API_KEY` and `OPENAI_BASE_URL` as Windows user environment variables, then open a new PowerShell session. Compose maps those shell values into every application container. Keep `.env` out of Git.

Validate the resolved Compose file without printing secrets into an issue or log:

```powershell
docker compose config --quiet
docker compose run --rm --no-deps config-check
```

If port `8000` is already owned by another Windows service, persist a different host port without changing the container network:

```powershell
uv run python -m grounded_docparse.compose_env port .env 8001
```

### Start and inspect

```powershell
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 api worker batch-worker ui
```

Endpoints:

- UI: <http://localhost:8501>
- API documentation: <http://localhost:8000/docs>
- Health: <http://localhost:8000/healthz>

Stop services without deleting volumes:

```powershell
docker compose down
```

Removing Compose volumes deletes PostgreSQL, Redis, and MinIO data. Do not use `docker compose down --volumes` unless permanent deletion is intended and backups are complete.

## Streamlit workflow

1. Open <http://localhost:8501>.
2. Select `Local` for in-process testing or `API` for durable queued jobs.
3. For `Local`, launch Streamlit from a shell containing `OPENAI_BASE_URL` and `OPENAI_API_KEY`. For `API`, enter the parser API URL and token if they were not supplied through environment variables.
4. Select `fast`, `balanced`, or `maximum`. API mode also offers `realtime` or `batch` execution.
5. Optionally provide a JSON taxonomy or Draft 2020-12 extraction schema.
6. Upload supported PDFs or images and submit.
7. Monitor durable job status and download the ZIP result when the job is `completed` or `needs_review`.

API mode polls every two seconds, and closing the browser does not stop its worker. Local mode runs synchronously inside Streamlit and keeps completed bundles only in that Streamlit session. The Evaluate tab is informational; submit corrected trees through the evaluation API.

Run Streamlit locally without Docker:

```powershell
uv sync --python 3.13 --locked
uv run streamlit run streamlit_app.py
```

The OpenAI variables are read from the process environment; the UI does not display or persist their values.

## API workflow

### Set local client variables

```powershell
$env:DOCPARSE_API_URL = "http://localhost:8000"
# Set this to the same value configured in .env.
$env:DOCPARSE_API_TOKEN = "replace-locally"
```

### Submit

```powershell
$job = curl.exe -sS -X POST "$env:DOCPARSE_API_URL/api/v1/jobs" `
  -H "Authorization: Bearer $env:DOCPARSE_API_TOKEN" `
  -F "file=@examples/synthetic-report.pdf" `
  -F "profile=balanced" `
  -F "execution=realtime" `
  -F "segmentation=auto" | ConvertFrom-Json

$job.id
```

Optional multipart fields:

| Field | Values |
| --- | --- |
| `profile` | `fast`, `balanced`, or `maximum` for the production path |
| `execution` | `realtime` or `batch` |
| `segmentation` | `auto` or `off` |
| `taxonomy` | JSON value, normally an array of declared document types |
| `extraction_schema` | Draft 2020-12 JSON Schema as JSON text |

The API enum also accepts compatibility profiles, but the default Compose containers do not include their Paddle and Ollama services. Omit `Idempotency-Key` to derive it from the request. If you provide one, use a new stable key whenever content or options change.

### Poll status

```powershell
do {
  Start-Sleep -Seconds 2
  $job = Invoke-RestMethod `
    -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)" `
    -Headers @{ Authorization = "Bearer $env:DOCPARSE_API_TOKEN" }
  $job.status
} until ($job.status -in @("completed", "needs_review", "failed", "cancelled"))

if ($job.status -notin @("completed", "needs_review")) {
  throw "Job ended as $($job.status): $($job.error)"
}
```

Possible states are `queued`, `running`, `waiting_provider`, `needs_review`, `completed`, `failed`, and `cancelled`. There is no list-all-jobs endpoint in the current API.

### List and download artifacts

```powershell
$headers = @{ Authorization = "Bearer $env:DOCPARSE_API_TOKEN" }
$result = Invoke-RestMethod `
  -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)/artifacts" `
  -Headers $headers
$result.artifacts
```

Artifact names returned by this endpoint include their storage prefix. The download route expects the path relative to `jobs/{job_id}/result`. For a top-level ZIP:

```powershell
$zipName = [IO.Path]::GetFileName(($result.artifacts | Where-Object { $_ -like "*.zip" } | Select-Object -First 1))
Invoke-WebRequest `
  -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)/artifacts/$zipName" `
  -Headers $headers `
  -OutFile $zipName
```

### Record a review

```powershell
$body = @{
  node_id = "node-id-from-result-json"
  corrected_text = "Corrected literal text"
  corrected_bbox = @(0.10, 0.20, 0.60, 0.28)
  reason = "Confirmed against the source image"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)/reviews" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

This records a review artifact only. It does not modify the original tree, regenerate exports, or complete the job.
The response returns the review ID and storage key. The current result-artifact download route is restricted to the `result` prefix, so review retrieval requires direct authorized artifact-store access.

### Evaluate against corrected truth

The gold file must be a corrected `DocumentTree` JSON for the same source hash.

```powershell
curl.exe -sS -X POST "$env:DOCPARSE_API_URL/api/v1/evaluations" `
  -H "Authorization: Bearer $env:DOCPARSE_API_TOKEN" `
  -F "job_id=$($job.id)" `
  -F "gold=@labels/corrected-tree.json"
```

The response is the evaluation report and should be saved by the caller. The API also stores a copy under the job's `evaluations` prefix without changing job state or parsed artifacts; that prefix is not exposed by the current result-artifact listing route.

### Purge a job

```powershell
Invoke-WebRequest `
  -Method Delete `
  -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)" `
  -Headers $headers
```

This removes the job row and `jobs/{job_id}` artifact prefix. It does not remove the shared `cache/{cache_key}` result copy. Configure MinIO lifecycle rules or avoid sensitive production data until complete cache-purge support exists.

## Worker scaling

Scale realtime workers:

```powershell
docker compose up --scale worker=8 -d
```

Scale batch-worker replicas independently while retaining one task per replica:

```powershell
docker compose up --scale batch-worker=4 -d
```

The `batch-worker` has concurrency one by default. `execution=batch` routes one parse job to that Celery queue; it does not use the OpenAI Batch API. This scheduling choice is separate from a mixed-document batch that segmentation may split into subdocuments.

Before increasing concurrency, measure provider limits, memory, image-rendering CPU, database connections, object-store throughput, and Redis backlog. This repository does not ship an autoscaler or backpressure policy.

## Local development

### Install and verify

```powershell
uv sync --python 3.13 --locked
uv run python -m pytest -q
uv run python -m compileall -q src streamlit_app.py tests
docker compose --env-file .env.example config --quiet
```

### Run services without Compose application containers

Point the application at reachable PostgreSQL/Redis/S3-compatible services, then run:

```powershell
uv run uvicorn grounded_docparse.server:app --host 127.0.0.1 --port 8000
uv run celery -A grounded_docparse.worker:celery_app worker --loglevel=INFO --queues=realtime
uv run celery -A grounded_docparse.worker:celery_app worker --loglevel=INFO --queues=batch --concurrency=1
uv run streamlit run streamlit_app.py
```

Each command runs in its own terminal. `DOCPARSE_API_TOKEN` is required before importing the default API application.

## Compatibility CLI pipeline

The compatibility path is separate from the default reference Compose deployment.

### One-time model setup

Requirements:

- Docker with a Linux engine and NVIDIA support for the pinned Paddle image
- Ollama running locally
- Enough disk space for the Paddle and GLM weights

```powershell
ollama pull glm-ocr
docker pull ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
uv run grounded-docparse-paddle-setup
```

The setup command warms the named `paddleocr-vl-cache` Docker volume. The image and model weights remain on this PC until their Docker image/volume or Ollama model is explicitly removed. Normal parses reuse them instead of downloading them again.

Verify setup:

```powershell
ollama list
docker volume inspect paddleocr-vl-cache
docker image inspect ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
```

### Parse locally

```powershell
uv run grounded-docparse examples/synthetic-report.pdf `
  --output output `
  --profile local-only `
  --segmentation auto
```

### Parse with compatibility cloud adjudication

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
  throw "OPENAI_API_KEY is not set"
}

uv run grounded-docparse document.pdf --output output --profile hybrid
uv run grounded-docparse document.pdf --output output --profile maximum-accuracy
```

The deprecated `--allow-cloud` flag is an alias for `--profile maximum-accuracy`.

### Schema extraction and evaluation

```powershell
uv run grounded-docparse invoice.pdf `
  --output output `
  --profile local-only `
  --document-profile invoice `
  --schema examples/schemas/invoice.schema.json

uv run grounded-docparse document.pdf `
  --output output `
  --profile local-only `
  --gold-json labels/corrected-tree.json
```

## Bash equivalents

The commands and API shapes are identical. Replace PowerShell continuations with `\`, set variables with `export`, and use `curl` directly:

```bash
cp .env.example .env
docker compose up --build -d

export DOCPARSE_API_URL=http://localhost:8000
export DOCPARSE_API_TOKEN=replace-locally

curl -X POST "$DOCPARSE_API_URL/api/v1/jobs" \
  -H "Authorization: Bearer $DOCPARSE_API_TOKEN" \
  -F file=@examples/synthetic-report.pdf \
  -F profile=balanced \
  -F execution=realtime \
  -F segmentation=auto
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| API container exits | `DOCPARSE_API_TOKEN`, database URL, and service health |
| `config-check` exits | required OpenAI variables, placeholder values, or local secrets shorter than 32 URL-safe characters |
| MinIO reports invalid credentials | rotate local secrets before first start; changing persisted service credentials later requires a migration |
| Job stays queued | matching Celery queue and Redis connectivity |
| Job enters `waiting_provider` | OpenAI key, model access, network, and rate limits |
| Job ends `needs_review` | annotated PDF, failures JSONL, and node verification states |
| UI cannot submit | API URL, bearer token, browser-to-API reachability, and upload type |
| Host port `8000` is unavailable | set `DOCPARSE_API_PORT` in `.env`; the Compose UI continues to use internal `api:8000` |
| Artifact is missing | job terminal state and path relative to the result prefix |
| Old result after config change | processing cache key coverage and cache lifecycle |
| Paddle downloads repeatedly | named cache volume exists, the Docker context is unchanged, and the configured image/model identifiers still match the warmed cache |
| GLM unavailable | Ollama is running and `ollama list` contains `glm-ocr` |
