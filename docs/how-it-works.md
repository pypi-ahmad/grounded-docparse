# How the Grounded Document Parser Works

## The short version

The production parser treats each model result as a proposal that must remain tied to visible source evidence.

```text
PDF or image
  -> validated page images
  -> Luna typed layout draft
  -> Fast: grounded document tree
  -> Balanced/Maximum: Terra visual inspection
       -> optional 450-DPI source crops
       -> verified or needs-review document tree
  -> Markdown, JSON, citations, evaluation, and audit artifacts
```

LlamaParse and LandingAI ADE influenced the layout-first and visually grounded design. They are not runtime dependencies or called services.

## Before processing starts

The API validates the filename extension and stores the upload under a job-specific source prefix. It derives a default idempotency key from the source hash, processing profile, execution queue, segmentation mode, taxonomy, and extraction schema. Supplying the same effective request returns the existing job.

The API then queues a short task reference. Source bytes remain in the artifact store; they are not placed in Redis messages or database rows.

## Stage 1: ingestion

`ingest_document` validates file type, size, page count, and page dimensions. PDFs retain native text blocks where available. Scanned pages and images are normalized into a common page representation.

Full-page model images default to 200 DPI. This keeps the common path bounded while preserving enough layout detail for region detection.

## Stage 2: Luna draft

Luna receives one page image and returns a strict `PageDraft`. The contract supports:

- headings, paragraphs, lists, headers, footers, sidebars, and footnotes;
- tables with row, column, span, header, text, and cell boxes;
- figures, charts, captions, formulas, signatures, and seals;
- form-field labels and values; and
- checked, unchecked, indeterminate, or unknown checkboxes.

The parser rejects extra schema fields and invalid coordinate ranges. It generates stable node IDs, converts normalized boxes into pixel and PDF boxes, renders evidence crops, and hashes those crops.

Draft confidence is evidence for triage, not proof of correctness.

## Stage 3: profile-specific inspection

### Fast

Fast stops after Luna. Nodes are spatially grounded but not independently verified. Ordinary Markdown includes the draft for human inspection. Strict LLM Markdown replaces it with an `[UNRESOLVED ...]` marker.

Use Fast for exploration, routing, or workloads where a later human or application-specific verifier supplies the quality gate.

### Balanced

Balanced sends the complete page draft and page image to Terra. Terra can accept, correct, reject, or request one high-resolution crop for each region.

Use Balanced as the default production profile. A value enters strict output only after Terra accepts or corrects it.

### Maximum

Maximum uses the same contracts but permits up to two crop inspections per region. Use it for small fonts, dense financial tables, forms, and other pages where the extra latency and token cost are justified.

Maximum does not mean perfect accuracy. It means the deepest bounded inspection loop implemented by this repository.

## Stage 4: visual crop inspection

When Terra requests `inspect_crop`, the parser rerenders the requested region from the original source at 450 DPI rather than enlarging the lower-resolution page image. Five-percent padding is the default; any model-requested padding remains bounded.

Terra receives the crop, region ID, current candidate text, evidence reference, and attempt number. It must return another typed inspection decision. An unresolved final attempt becomes `needs_review`.

Every crop has a content hash. This makes the exact visual evidence used for a decision auditable even when two crops have similar coordinates.

## Stage 5: document tree construction

The parser builds one validated `DocumentTree` with:

- a physical page index;
- semantic parents and children;
- ordered content nodes;
- provenance and model-run records;
- citations and source coordinates;
- verification states;
- classification, grounded fields, and validation findings;
- logical tables, schema extractions, and batch segmentation; and
- failure and retry records.

The hierarchy never replaces source coordinates. A heading may organize paragraphs semantically while every paragraph still points to its original page box and crop.

## Stage 6: classification and segmentation

With `segmentation=auto`, deterministic classification examines grounded page content and identifiers. An optional taxonomy restricts page types to caller-declared values.

Boundary decisions consider document-type changes and repeated or changed identifiers such as invoice numbers, dates, and order IDs. The result is a batch manifest and, when boundaries are found, a source PDF and artifact set for each subdocument inside the batch ZIP. The compatibility CLI additionally writes separate subdocument ZIPs.

Uncertain evidence remains recorded in boundary reasons. Classification is not a substitute for downstream business validation.

## Stage 7: schema extraction

Clients may submit a bounded Draft 2020-12 JSON Schema. Deterministic extraction maps grounded labels, fields, and tables to schema paths. Model-assisted selection is constrained to known source-node IDs and literal values.

Every emitted leaf includes citations with node ID, page, box, confidence, and table-cell grounding where available. Balanced and Maximum ignore nodes that did not reach a verified state. Unsupported required values produce validation errors instead of fabricated defaults.

## Stage 8: exports

The worker persists:

| Artifact | Purpose |
| --- | --- |
| `*.md` | Review-oriented layout-aware Markdown |
| `*.llm.md` | Fail-closed Markdown for downstream LLMs |
| `*.json` | Complete document tree |
| `*.audit.json` | Coverage and provenance summary |
| `*.failures.jsonl` | Safe structured failures |
| `*.quality.json` | Structural and verification quality report |
| `*.annotated.pdf` | Region overlays, order, confidence, source, and state |
| `*.batch.manifest.json` | Page classification and subdocument boundaries |
| `*.extraction.json` | Schema-defined values and citations, when requested |
| `*.zip` | Consolidated audit bundle |

Additional table and crop assets are stored under their relative asset paths.

## Stage 9: job completion and review

If any node is rejected or needs review, the worker finishes the job as `needs_review`; otherwise it uses `completed`.

`POST /api/v1/jobs/{job_id}/reviews` stores a reviewer correction with `human_verified` metadata. It does not mutate the original tree, regenerate exports, or transition the job. Consumers must treat review artifacts as a separate curation stream until an apply-review workflow is implemented.

## Evaluation mode

`POST /api/v1/evaluations` compares any available candidate tree—including a `needs_review` result—with a corrected tree whose `source_sha256` identifies the same source. Metrics include text error, node types, layout overlap, reading order, hierarchy, segmentation, fields, tables, forms, citations, and relationships.

The endpoint returns the report and stores an evaluation copy without modifying the job, candidate tree, or exports. The current public artifact listing covers only result artifacts, so clients should retain the response.

The Streamlit Evaluate tab currently points users to this API. It does not upload gold data itself.

Evaluation answers “how did this parser perform on labeled documents?” Confidence and quality reports answer different questions and must not be presented as measured accuracy.

## Idempotency and caching

Submission idempotency prevents duplicate jobs for the same request key. The worker also computes a processing-cache key and copies an existing completed result when it matches.

These mechanisms are separate:

- An idempotency hit returns the same job.
- A processing-cache hit creates or completes another job by copying cached artifacts.
- OpenAI prompt caching can reduce repeated-prefix cost and latency inside provider requests.

The processing cache has no TTL and is not removed by the job purge endpoint. Its key also does not include every rendering environment variable. Operators must account for this when changing render settings or handling data with erasure requirements.

## Transient failures

OpenAI connection errors, timeouts, and rate limits move a running job to `waiting_provider` before Celery retries it. Backoff is exponential with jitter, capped at five minutes, with three retries.

Validation errors, unsupported inputs, and unexpected processing exceptions fail the job. The error field is bounded, but deployments should still avoid returning or logging raw provider payloads.

## Compatibility CLI pipeline

The older profile family remains callable from `grounded-docparse`:

- `local-only`: native text, PaddleOCR-VL layout, and GLM-OCR recognition;
- `hybrid`: local evidence plus bounded Luna adjudication; and
- `maximum-accuracy`: broader Luna verification and Terra document reasoning.

Paddle runs in a digest-pinned Docker image and stores downloaded weights in a named volume. `grounded-docparse-paddle-setup` warms that volume once; normal parses reuse it offline. GLM-OCR is downloaded once into Ollama and reused from Ollama's model store.

This path is not available merely by starting the default reference Compose deployment. See [Run Commands](run.md#compatibility-cli-pipeline).

## Why the pipeline is agentic

The loop is bounded and evidence-driven:

1. draft a typed page;
2. inspect each proposed region;
3. decide whether existing evidence is sufficient;
4. acquire a higher-resolution crop when necessary;
5. accept, correct, reject, or route to review; and
6. stop at the profile's fixed attempt limit.

The model does not receive permission to loop indefinitely, invent evidence IDs, or bypass deterministic export policy.

## Accuracy and scale claims

The repository's automated suite tests contracts with synthetic documents and fake providers. It does not establish real-world OCR accuracy, model availability, production latency, or million-page throughput. Publish such claims only after running representative labeled evaluations and load tests in the target deployment.
