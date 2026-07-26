# Grounded Document Parser: Zero to First Audit

This tutorial takes a synthetic document through the asynchronous production path, explains the result bundle, and shows how to evaluate or review uncertain evidence. It ends with the separate compatibility CLI setup.

## 1. Mental model

The parser does not treat OCR text as truth. It creates a chain of evidence:

```text
source page
  -> typed region draft
  -> visual inspection decision
  -> source coordinates and crop hash
  -> document node and citation
  -> strict Markdown or extracted value
```

The production roles are:

- Luna: draft page layout, reading order, and literal region content.
- Terra: inspect the draft against the page and request closer crops when needed.
- Deterministic Python: validate contracts, create IDs and coordinates, assemble hierarchy, and decide what can enter strict output.

LlamaParse and LandingAI ADE are architectural inspiration only. No account or API key for either product is used.

## 2. Start the stack

Requirements are Docker Compose and an OpenAI API key with access to the configured models.

```powershell
Copy-Item .env.example .env
uv run python -m grounded_docparse.compose_env rotate .env
```

Set `OPENAI_API_KEY` and `OPENAI_BASE_URL` in the Windows user environment and open a new PowerShell session. Then:

```powershell
docker compose config --quiet
docker compose run --rm --no-deps config-check
docker compose up --build -d
docker compose ps
```

Open <http://localhost:8501>. The API documentation is available at <http://localhost:8000/docs>.

The stack contains the API, realtime worker, batch worker, Redis, PostgreSQL, MinIO, and Streamlit. In API mode the UI is a client, so processing survives browser refreshes and closures. Its separate Local mode runs in-process for Docker-free testing and is not durable.

## 3. Choose a profile

| Profile | Independent verification | Crop attempts | Typical use |
| --- | --- | --- | --- |
| Fast | No | 0 | Exploration and routing |
| Balanced | Terra | 1 | Default production extraction |
| Maximum | Terra | 2 | Fine print and dense tables |

Fast still provides coordinates and crop hashes, but its model text remains only grounded. Strict LLM Markdown replaces it with unresolved markers.

Balanced and Maximum release literal content only when Terra accepts or corrects it. Maximum spends more time and tokens; it is not a guarantee of perfect accuracy.

## 4. Submit the synthetic report

In Streamlit:

1. Choose `API` and confirm the parser API URL and token. For Docker-free testing, choose `Local` after launching Streamlit with `OPENAI_BASE_URL` and `OPENAI_API_KEY` in the environment.
2. Choose `Balanced`, `realtime`, and automatic segmentation.
3. Upload `examples/synthetic-report.pdf`.
4. Select the file in Source preview and confirm it contains only synthetic data.
5. Submit the job.

The Jobs table shows durable status. Terminal outcomes are:

- `completed`: no node ended rejected or unresolved;
- `needs_review`: at least one node needs human attention;
- `failed`: the worker could not produce a result; or
- `cancelled`: reserved by the state model, although the current API has no cancellation endpoint.

`waiting_provider` is temporary while Celery retries OpenAI connection, timeout, or rate-limit failures.

## 5. Submit through the API

Set local client variables without committing them:

```powershell
$env:DOCPARSE_API_URL = "http://localhost:8000"
$env:DOCPARSE_API_TOKEN = "the-value-from-your-env-file"
```

Submit:

```powershell
$job = curl.exe -sS -X POST "$env:DOCPARSE_API_URL/api/v1/jobs" `
  -H "Authorization: Bearer $env:DOCPARSE_API_TOKEN" `
  -F "file=@examples/synthetic-report.pdf" `
  -F "profile=balanced" `
  -F "execution=realtime" `
  -F "segmentation=auto" | ConvertFrom-Json

$job | Format-List
```

When `Idempotency-Key` is omitted, the API derives one from the source and request. If you supply your own key, never reuse it for different content or options: the existing job is returned without comparing a second payload.

Poll:

```powershell
$headers = @{ Authorization = "Bearer $env:DOCPARSE_API_TOKEN" }
do {
  Start-Sleep 2
  $job = Invoke-RestMethod `
    -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)" `
    -Headers $headers
  $job.status
} until ($job.status -in @("completed", "needs_review", "failed", "cancelled"))

if ($job.status -notin @("completed", "needs_review")) {
  throw "Job ended as $($job.status): $($job.error)"
}
```

## 6. Inspect the result bundle

List artifacts:

```powershell
$artifacts = Invoke-RestMethod `
  -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)/artifacts" `
  -Headers $headers
$artifacts.artifacts
```

Download the top-level ZIP through Streamlit or the artifact route:

```powershell
$zipName = [IO.Path]::GetFileName(($artifacts.artifacts | Where-Object { $_ -like "*.zip" } | Select-Object -First 1))
Invoke-WebRequest `
  -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)/artifacts/$zipName" `
  -Headers $headers `
  -OutFile $zipName
```

Extract it into a directory outside the repository if it contains real documents. Listed artifact keys include the storage prefix, while the download route expects the portion relative to `jobs/{job_id}/result/`.

### Review Markdown

`*.md` is optimized for human review. It can contain grounded draft text that strict consumers should not trust yet. HTML metadata retains node IDs, confidence, and coordinates.

### Strict LLM Markdown

`*.llm.md` is the downstream-safe representation:

- verified values retain source comments;
- unresolved Fast content becomes an explicit marker;
- rejected or needs-review values do not masquerade as facts; and
- semantic ancestry preserves section context.

### Document tree

`*.json` is a `DocumentTree` with schema version `1.9.0`. Start by examining:

```powershell
$treePath = Get-ChildItem -Recurse -Filter '*.json' extracted-result |
  Where-Object { $_.Name -notmatch '(audit|quality|manifest|extraction)' } |
  Select-Object -First 1
$tree = Get-Content -Raw $treePath | ConvertFrom-Json

$tree.schema_version
$tree.processing_profile
$tree.pages.Count
$tree.nodes.PSObject.Properties.Count
```

Select content nodes and inspect evidence:

```powershell
$tree.nodes.PSObject.Properties.Value |
  Where-Object page_number |
  Select-Object id, type, page_number, reading_order, verification_state, text
```

For production nodes, `grounding` contains the normalized box, optional pixel/PDF boxes, page dimensions, crop reference, and crop SHA-256.

### Annotated PDF

Open `*.annotated.pdf` to compare regions with the source. Overlays show reading order, confidence, evidence source, and verification state. Use this before accepting a low-confidence correction or marking a review.

### Failures and quality

`*.failures.jsonl` is the machine-readable queue for unresolved, degraded, or recovered cases. `*.quality.json` summarizes structural and verification coverage. Neither is an accuracy benchmark.

## 7. Understand verification states

| State | Meaning | Allowed in strict output |
| --- | --- | --- |
| `draft` | Not grounded yet | No |
| `grounded` | Bound to visible source evidence, usually Luna-only | No |
| `verified` | Terra accepted or corrected the literal evidence | Yes |
| `rejected` | Inspection found it unsupported | No |
| `needs_review` | Automated attempts ended without a safe decision | No |
| `human_verified` | A human-confirmed state supplied by an external curation workflow | Yes, when already present in the tree |

The current review endpoint creates a separate artifact carrying `human_verified` metadata. It does not apply the correction back into the tree, so the original export remains unchanged and does not gain that state.

## 8. Extract fields with a schema

The repository includes `examples/schemas/invoice.schema.json`. In Streamlit, paste its JSON into Extraction JSON Schema before submitting an invoice-like document. Through the API, send it as JSON text in the `extraction_schema` multipart field.

An extraction result contains:

- validated data;
- schema name and hash;
- status and validation errors; and
- per-path provenance with one or more source citations.

Every leaf must be supported by existing nodes. Balanced and Maximum filter out unverified evidence before extraction. If a required value cannot be grounded, the result remains incomplete or invalid.

## 9. Classify and split mixed files

Automatic segmentation classifies pages and looks for changes in document type or repeated primary identifiers.

You can restrict classification with a declared taxonomy:

```json
["invoice", "purchase_order", "contract"]
```

The batch manifest records page classifications, boundary decisions, identifiers, and subdocument ranges. API results place each subdocument's source PDF and artifact set inside the top-level ZIP. The compatibility CLI also writes a separate ZIP per subdocument.

Segmentation is evidence-driven but still requires evaluation on the target document mix, especially when identifiers repeat across attachments.

## 10. Evaluate with corrected truth

Create a corrected copy of the candidate `DocumentTree`. Preserve the source identity and correct node text, types, coordinates, hierarchy, citations, fields, and boundaries as needed.

Submit it:

```powershell
curl.exe -sS -X POST "$env:DOCPARSE_API_URL/api/v1/evaluations" `
  -H "Authorization: Bearer $env:DOCPARSE_API_TOKEN" `
  -F "job_id=$($job.id)" `
  -F "gold=@labels/corrected-tree.json"
```

Use evaluation results to build a curated failure set by document type and failure mode. Confidence is useful for triage; only labeled comparison supports accuracy claims.

## 11. Record a review

Find the target node ID and normalized coordinates in the JSON tree, then:

```powershell
$review = @{
  node_id = "replace-with-node-id"
  corrected_text = "Literal text confirmed by a reviewer"
  corrected_bbox = @(0.10, 0.20, 0.70, 0.28)
  reason = "Confirmed against the source page"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)/reviews" `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body $review
```

Store the returned review artifact with curation data. Until apply-review support exists, downstream systems must merge reviews through their own approved workflow.

## 12. Purge and retention

Delete the job:

```powershell
Invoke-WebRequest `
  -Method Delete `
  -Uri "$env:DOCPARSE_API_URL/api/v1/jobs/$($job.id)" `
  -Headers $headers
```

This removes job-scoped data, not the content-addressed processing-cache copy. The default cache has no TTL. Do not process regulated documents without an external object-lifecycle policy or a deployment change that disables/removes cache reuse.

## 13. Compatibility CLI and persistent local weights

Use this path only when you intentionally need the earlier Paddle/GLM workflow. It is not started by the production Compose file.

One-time setup:

```powershell
ollama pull glm-ocr
docker pull ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
uv run grounded-docparse-paddle-setup
```

The Paddle image remains in Docker's image store, its model weights remain in the `paddleocr-vl-cache` named volume, and GLM remains in Ollama's model store. Normal parses reuse all three; downloads recur only if those assets are removed, a different Docker context is used, or the configured image digest or model ID changes.

Parse:

```powershell
uv run grounded-docparse examples/synthetic-report.pdf `
  --output output `
  --profile local-only
```

Hybrid and Maximum Accuracy add OpenAI adjudication and require `OPENAI_API_KEY`.

## 14. Repository map

```text
src/grounded_docparse/
  api.py           HTTP boundary
  jobs.py          job state and artifacts
  worker.py        Celery execution and result cache
  pipeline.py      production and compatibility orchestration
  gateways.py      provider contracts
  ingest.py        validation, page rendering, and crops
  models.py        document and provider schemas
  render.py        Markdown, JSON, and bundles
  review.py        annotated PDF and quality report
  evaluation.py    corrected-tree metrics
  segmentation.py  classification and splitting
streamlit_app.py   asynchronous UI client
tests/             contract tests with synthetic providers
```

## 15. Safe extension checklist

Before extending the parser:

1. identify the public contract that changes;
2. add a failing contract test first;
3. keep provider output behind strict models;
4. preserve source IDs, coordinates, and crop hashes;
5. make uncertainty explicit in strict exports;
6. update cache-key inputs when output-affecting configuration changes;
7. document retention and security consequences; and
8. evaluate representative labeled documents before making accuracy claims.

## 16. What this tutorial does not prove

Completing the tutorial proves that your configured stack can process one synthetic file. It does not prove:

- access to every model in every OpenAI project;
- correctness on handwritten, multilingual, financial, medical, or adversarial documents;
- a specific cost or latency target;
- safe multi-tenant internet exposure; or
- million-page throughput.

Use the evaluation API, load tests, and deployment-specific security review to establish those properties.
