# How the Grounded Document Parser Works

This document follows one file from upload to export. For component boundaries
and design tradeoffs, see [Architecture and design](architecture.md). For a
guided first run, see the [zero-to-mastery tutorial](tutorial.md).

## The short version

```text
Upload
  ↓
Validate, render, and classify pages as scanned or digital
  ↓
PaddleOCR-VL: layout, order, regions, tables, formulas, visuals
  ↓
Automatic high-resolution Paddle retry for failed page layouts
  ↓
GLM-OCR: independent, type-specific recognition of required regions
  ↓
Reconcile candidates; automatically retry weak local regions
  ↓
Optional Luna verification and Terra cross-page reasoning
  ↓
Build and validate physical pages plus semantic hierarchy
  ↓
Classify, segment, extract, cite, audit, and render
  ↓
Markdown + JSON + quality + annotated PDF + assets + ZIP
```

No provider owns the final output. Providers produce evidence or bounded typed
decisions; deterministic code decides whether that evidence is supported.

## Before a parse starts

The public entrypoint is `DocumentParser.parse`. It receives bytes, a filename,
an optional progress callback, processing and document profiles, segmentation
mode, and an optional extraction schema.

If a schema is supplied, it is validated before OCR begins. A cloud profile is
also rejected before ingestion when OpenAI is disabled or `OPENAI_API_KEY` is
missing. This avoids expensive work for a request that cannot complete as
configured.

The Paddle model cache must be warmed once:

```powershell
uv run grounded-docparse-paddle-setup
```

Warm-up permits the pinned image to download model files into a named Docker
volume. Normal parsing mounts that volume read-only and disables container
networking.

## Stage 1: ingestion

`ingest.py` treats the upload as untrusted. It validates:

- non-empty content and the configured byte limit;
- a supported PDF, PNG, JPEG, or TIFF extension;
- the PDF signature or image decodability;
- password state, page count, and rendered-pixel limits.

For each PDF page, PyMuPDF extracts native text spans, fonts, PDF-point boxes,
links, and a rendered image. A page with fewer than 20 native characters is
routed as scanned. Scans and uploaded images receive deskewing, denoising, and
contrast enhancement for OCR. The source remains unchanged.

This scanned/digital flag controls recognition routing; it does not bypass
layout analysis. Paddle analyzes every page.

## Stage 2: PaddleOCR-VL layout and reading order

`paddle.py` starts `paddle_worker.py` in the digest-pinned official
PaddleOCR-VL 1.6 GPU image. Paddle provides the primary page structure:

- semantic region type;
- reading order;
- normalized coordinates;
- text candidates;
- table HTML and available cell boxes;
- formulas, charts, figures, captions, headers, and footers.

Large PDFs are temporarily split into 25-page source chunks so the provider is
not asked to hold a multi-hundred-page document at once. Downstream recognition
uses 10-page windows. Original page numbering never changes.

Each Paddle source chunk gets one initial execution plus two retries by default.
This is process recovery: any exception reruns the whole chunk, and the first
successful attempt is accepted. If every attempt fails, each page in that chunk
receives a typed provider-error payload. The pipeline records warnings and
creates fallback regions; it does not silently omit the pages. This chunk retry
is separate from the page-layout quality retry in the next stage.

## Stage 3: automatic layout retry

The bounded planner checks each page after initial layout. It retries Paddle
once when:

- Paddle returned a provider error for that page; or
- the only usable structure is a full-page fallback.

The rendered page is enlarged toward 450 DPI without crossing the configured
pixel limit. A deterministic score measures how many proposed regions have
boxes and non-empty text. The new layout is applied only when its score is
higher. Applied, rejected, and failed attempts appear in `adaptive_retries`,
the audit manifest, failure records, and the Streamlit inspector.

## Stage 4: GLM-OCR region recognition

Paddle and GLM have different jobs. Paddle determines where and what a region
is; GLM independently reads a crop of that region.

The region type selects the prompt:

| Region | GLM task |
|---|---|
| Paragraph, heading, list, header, footer | Text recognition |
| Table | Table recognition |
| Formula | Formula recognition |
| Figure, image, chart | Figure recognition |

Every region on a scanned page is sent to GLM. On a digital page, native PDF
text remains useful and GLM is reserved for complex or conflicting regions.
Calls are sequential, and Paddle has already released its container, so the two
local vision workloads do not compete for GPU memory.

Ten-page windows can retry twice after their first attempt by default. A window
that still fails becomes `degraded`; available regions continue through the
pipeline.

## Stage 5: reconciliation and local adaptive retry

Native PDF text, Paddle text, and GLM text are retained as separate
`RecognitionCandidate` values. The reconciler normalizes whitespace and case,
compares similarity, and treats differing numeric tokens as a conflict even
when the surrounding sentence is similar.

Each region retains:

- every candidate and its source;
- the selected candidate ID;
- agreement and confidence scores;
- verification status;
- candidate-level provenance and alternatives.

In `local-only`, a region receives one automatic high-resolution GLM retry when
it is disputed, unreadable, unresolved, or below 0.65 confidence. The retry uses
an 8% wider crop and up to twice the page DPI. It is applied only when it turns
unusable evidence into a selected result or improves confidence. Otherwise the
prior selection is restored and the new candidate remains available for audit.

If evidence cannot support text, the exported node is explicitly unreadable
rather than filled with a plausible guess.

### Retry taxonomy

| Retry | Trigger | Attempts | Acceptance |
|---|---|---|---|
| Paddle source chunk | Container/worker exception for a 25-page chunk | Initial attempt plus two retries by default | First execution that returns page results |
| Paddle page layout | Provider-error page or full-page-only fallback | One higher-resolution attempt | Layout score must improve |
| GLM recognition window | Exception while processing a 10-page window | Initial attempt plus two retries by default | First execution that completes; otherwise window is degraded |
| Local adaptive GLM region | Disputed, unreadable, unresolved, or confidence below 0.65 in `local-only` | One wider, enlarged crop | Must produce usable evidence or improve confidence |
| Luna confirmation GLM region | Luna proposes novel visible text or requests confirmation | One wider, enlarged crop | Independent GLM result must support the proposal |

## Stage 6: optional cloud verification

The processing profile controls cloud scope:

### Local only

Paddle and GLM run locally. No document content is sent to OpenAI. The local
adaptive region retry is the final recognition escalation.

### Hybrid

For every page containing uncertainty, Luna receives the full page image plus
only the regions that remain uncertain. It can
select an existing candidate ID, refine a semantic role, or request another
local OCR pass. This minimizes cloud work while targeting disagreements.

### Maximum accuracy

Luna verifies every page. Terra also receives grounded node summaries in
overlapping windows to refine heading roles and add cross-page relationships.
Terra cannot rewrite node text, create new nodes, or cite unknown IDs.

Luna may propose literal text that all local candidates missed, but the proposal
is provisional. The application creates a wider, enlarged GLM crop without
showing GLM Luna's answer. The correction is selected only when the independent
recognition agrees. This confirmation gate reduces model-to-model anchoring.

## Stage 7: physical and semantic structure

`pipeline.py` builds `DocumentTree` schema 1.9.0. It has two indexes over the
same content nodes:

```text
Document
├── Pages
│   ├── Page 1 → content node IDs
│   └── Page 2 → content node IDs
└── Sections
    ├── Heading
    ├── Paragraph
    ├── List → ListItem
    ├── Table → TableRow → TableCell
    └── Figure → Caption
```

Pages retain physical order for overlays and citations. Sections expose logical
navigation for LLMs and applications. Stable IDs are derived from source and
layout evidence, not random generation.

Nodes may include page and segment-page numbers, bounding boxes, reading order,
semantic role, literal text, Markdown, confidence, provenance, citations,
relationships, recognition candidates, form data, and visual analysis.

Table rows and cells become first-class nodes. Merged spans are preserved.
Exact cell grounding is used only when a provider supplied a cell box; other
cells explicitly use table-level grounding. Figures and captions are associated
by page order and geometry. Repeated decorations and cross-page continuations
are linked without deleting their source evidence.

## Stage 8: document profiles and forms

The selected or auto-detected profile can be generic, technical documentation,
scientific paper, invoice, insurance claim, healthcare form, purchase order,
receipt, contract, correspondence, or generic form.

Profiles derive normalized fields and validation findings from existing nodes.
They do not invent operational decisions. Deterministic form pairing adds typed
form-field nodes while preserving original OCR blocks. Checkboxes, signatures,
and seals remain distinct node types.

Every grounded field identifies its source nodes, page, box, confidence, and
derivation method.

## Stage 9: mixed-file segmentation

With automatic segmentation enabled, the parser classifies each page and looks
for repeated identifiers such as invoice number, order ID, claim number, and
date. Boundaries use document-type changes, identifier changes, continuation
signals, and geometry.

The local rule is conservative: uncertain adjacent pages stay together. In a
cloud profile, Luna can adjudicate only the two pages surrounding an uncertain
boundary. Maximum-accuracy may ask Terra when Luna remains uncertain. An
override requires at least 0.65 confidence.

Each resulting sub-document gets its own PDF, tree, Markdown, audit, failure
records, quality report, annotated PDF, assets, optional extraction, and ZIP.

## Stage 10: schema-first extraction

An optional Draft 2020-12 JSON Schema defines the requested result shape.
Supported schemas can contain nested objects, scalar arrays, multiple table
arrays, required values, aliases, enums, formats, and numeric bounds.

The deterministic extractor first matches profile fields, form labels,
label-value regions, captions, and table headers. Cloud profiles can resolve
ambiguous mappings, but a model may select only existing node IDs and literal
values. The application supplies coordinates from those nodes.

Every leaf value has RFC 6901 provenance. Required values without evidence are
reported as unresolved rather than fabricated. Continued tables are stitched
into logical JSONL and spreadsheet-safe CSV exports while their page-level nodes
remain unchanged.

## Stage 11: validation, failure capture, and export

Before output, validators check references, page membership, hierarchy,
citations, table limits, links, extraction grounding, and model decisions.
Renderers escape untrusted Markdown, HTML, URLs, filenames, and model text.

The parser derives structured failure cases for provider fallbacks, degraded
windows, unreadable OCR, grounding gaps, extraction problems, uncertain
boundaries, and retry outcomes. These JSONL records use controlled codes and
safe exception classes; they exclude raw document text, images, crops, and
provider exception messages.

The final artifacts are:

- structured Markdown;
- LLM-ready Markdown with a grounding comment per block;
- hierarchical JSON 1.9.0;
- audit JSON and failure JSONL;
- quality JSON and annotated PDF;
- cropped visual assets;
- batch and sub-document manifests;
- optional extraction JSON, table JSONL, and CSV;
- a ZIP containing the complete result.

## How the Streamlit app works

The app has Parse and Evaluate modes. Parse mode accepts up to 10 files or 1 GB
and processes them sequentially with shared profile, document type,
segmentation, and schema settings. A failure is isolated to its file, and the
combined batch ZIP records both successes and safe failure classes.

After parsing, the read-only workbench lets an operator:

- search and filter document nodes;
- synchronize a selected node with its annotated page;
- inspect Markdown, confidence, candidates, citations, and provenance;
- inspect automatic retry decisions;
- view the original and fully annotated document;
- inspect page-level quality indicators and warnings;
- download individual or batch artifacts.

The UI does not edit recognized text or expose manual provider buttons. This
keeps the parse reproducible from its source and configuration.

## How deterministic evaluation works

Evaluate mode accepts one source document and a corrected `DocumentTree` JSON
for that exact source. The source hash must match. Metrics include:

- character and word error rate;
- node-type precision, recall, and F1;
- bounding-box overlap, including table cells;
- reading-order and hierarchy agreement;
- citation coverage and grounded-form recall;
- node-level discrepancies.

There is no LLM judge and no composite score that can hide a weak dimension.
The quality report shown after an ordinary parse is not a substitute for this
labeled evaluation.

## Why this is agentic

This is a bounded agentic workflow, not an unrestricted autonomous agent. It
observes evidence, detects failure conditions, chooses from fixed escalation
paths, performs targeted retries, compares the result with the previous state,
and accepts only an improvement. It also delegates specialized tasks to layout,
recognition, verification, and cross-page reasoning components.

Its authority is deliberately narrow:

- fixed retry scope and count;
- schema-valid model responses;
- candidate IDs instead of free-form replacement where possible;
- independent confirmation for novel cloud text;
- deterministic acceptance and final validation;
- complete retry, confidence, and provenance records.

The system does not learn from corrections, retrain models, maintain a training
corpus, or change thresholds automatically between runs.

## Ideas retained from LlamaParse

No proprietary implementation was copied. Documented ideas reflected here
include layout-first parsing, RAG-oriented Markdown, spatial grounding,
multi-column reading order, HTML tables, cross-page context, figure assets,
tiered processing, and document-level output.

The project does not currently match all LlamaParse capabilities. In particular,
word- and line-level grounding, specialized chart extraction breadth, and
provider-calibrated confidence require further work.

Reference: [Official LlamaParse documentation](https://developers.llamaindex.ai/llamaparse/parse/)

## Ideas retained from LandingAI ADE

Documented ADE ideas reflected here include vision-first typed elements, stable
IDs, visual grounding, hierarchical JSON, literal-versus-generated provenance,
semantic reading order, parse-once/query-many outputs, and separation of
physical evidence from logical views.

References: [ADE overview](https://docs.landing.ai/ade/ade-overview) and
[ADE Gen2 architecture](https://landing.ai/blog/introducing-agentic-document-extraction-gen2)

## Accuracy claims and limitations

LandingAI's published 99.16% result was not a universal Markdown accuracy
claim. Its reported DocVQA progression used Markdown plus spatial JSON and
guided prompting, answering 5,286 of 5,331 questions without original images at
the QA stage. The result belongs to that benchmark and proprietary parser.

Reference: [LandingAI DocVQA benchmark](https://landing.ai/blog/docvqa-benchmark)

This project has no comparable published result. Its current evidence for
quality is the deterministic evaluation machinery, synthetic tests, grounding
coverage, annotated review, and explicit uncertainty. Production confidence
requires a representative labeled corpus covering your scans, tables, forms,
handwriting, languages, and failure modes.

Known gaps include:

- no general word- or line-level grounding;
- no handwriting-specific router;
- no learned confidence calibration;
- no human correction or active-learning loop;
- chart extraction that depends on available Paddle output;
- no distributed queue or worker system for million-page workloads;
- live provider behavior that must be tested separately from offline tests.
