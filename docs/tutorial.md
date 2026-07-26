# Grounded Document Parser: Zero to Mastery

This tutorial teaches the codebase from first principles. You need basic
computer skills, but you do not need prior experience with OCR systems,
document trees, Docker, or LLM orchestration.

By the end, you will be able to run the app, explain each pipeline stage,
inspect its evidence, evaluate it against corrected documents, and identify the
right place to extend it safely.

## 1. The problem this project solves

A document is more than its words. Consider a scanned invoice:

- a large bold line may be a title;
- two text blocks beside one another may be columns, not consecutive paragraphs;
- a number belongs to a field because it is beside `Invoice number`;
- a table cell belongs to a row and column;
- a caption belongs to a figure;
- a footer should not interrupt the main reading order.

Plain OCR often returns a flat string and loses those relationships. A language
model can try to reconstruct them, but unconstrained reconstruction can invent
text or silently attach a value to the wrong label.

Grounded Document Parser keeps both content and evidence. A text block is useful
because it says what was recognized, where it appeared, which systems agreed,
and how confident the parser is.

### Vocabulary

| Term | Meaning in this project |
|---|---|
| OCR | Converting visible text in an image into characters |
| Layout | Regions and roles such as heading, paragraph, table, or footer |
| Reading order | The intended sequence of regions on a page |
| Candidate | One provider's proposed text for one region |
| Grounding | A link from output back to page coordinates and source evidence |
| Provenance | Which provider, model, prompt, or derivation produced evidence |
| Semantic tree | Content organized by meaning rather than only page position |
| Agentic | Choosing bounded actions from evidence, then checking their results |
| Schema extraction | Mapping grounded content into a caller-defined JSON shape |

## 2. The mental model

Think of the parser as a small review team:

1. **The intake clerk** validates and renders the file.
2. **The page analyst, PaddleOCR-VL,** identifies regions and reading order.
3. **The local reader, GLM-OCR,** independently reads relevant regions.
4. **The reconciler** compares candidates and detects disagreements.
5. **The bounded planner** retries only failed pages or weak regions.
6. **The optional verifier, Luna,** checks uncertain or all pages.
7. **The optional document editor, Terra,** relates grounded nodes across pages
   without rewriting their text.
8. **The archivist** builds a validated tree, citations, audit records, and
   exports.

This separation matters. If the same model detected, read, corrected, and
approved everything, its confidence would not be independent evidence.

## 3. Prepare your machine

The project has three runtime layers:

- Python runs orchestration, validation, rendering, and Streamlit.
- Docker runs PaddleOCR-VL with NVIDIA GPU access.
- Ollama runs GLM-OCR locally.

Use Python 3.12 through `uv`. `uv` creates the environment and installs the
exact locked dependency graph; do not install packages globally with `pip`.

From the repository root, run the commands in [Run commands](run.md). The first
setup performs four important actions:

1. `uv sync` creates the Python environment.
2. `ollama pull glm-ocr` downloads the local recognition model.
3. `docker pull ...@sha256:...` downloads the exact Paddle image.
4. `grounded-docparse-paddle-setup` warms Paddle model weights into a Docker
   volume.

The warm-up command may take time and requires storage for model weights. After
the Docker image has already been pulled, it is the only Paddle cache/runtime
step that needs network access. Docker image and Ollama model pulls also require
network access. A normal parse uses the Paddle cache offline.

Install missing prerequisites from their official projects before continuing:
[uv](https://docs.astral.sh/uv/getting-started/installation/),
[Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/),
[NVIDIA container support](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
and [Ollama](https://ollama.com/download). On Windows, the Ollama application
normally starts its local service; on Linux, start `ollama serve` in a separate
terminal when no service manager is running it.

### Lab 1: verify the interfaces

Run:

```powershell
uv run grounded-docparse --help
uv run python -c "import grounded_docparse; print('Python package ready')"
docker image inspect ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
ollama list
```

You should see the parser's CLI options, the package message, image metadata,
and `glm-ocr` in the Ollama model list. None of these commands prints an API
key.

## 4. Make your first local parse

Start with `local-only`. It keeps document content on the workstation while
still using both local perception paths.

```powershell
uv run grounded-docparse examples/synthetic-report.pdf --output output
```

The command may take several minutes on its first real run. When it finishes,
open `output`. Start with these files:

- `synthetic-report.annotated.pdf` shows what the parser saw.
- `synthetic-report.llm.md` shows what a downstream text model receives.
- `synthetic-report.json` shows the full machine-readable tree.
- `synthetic-report.quality.json` shows operational quality signals.
- `synthetic-report.audit.json` shows provider and retry activity.

### Lab 2: trace one block to its source

1. Open the annotated PDF and choose a visible paragraph.
2. Find its text in `synthetic-report.llm.md`.
3. Read the grounding comment immediately above the block.
4. Copy its citation or node ID into a search in `synthetic-report.json`.
5. Compare the page number and bounding box with the annotation.

You have now followed a downstream LLM block back to physical evidence.

## 5. Use the Streamlit application

Run:

```powershell
uv run streamlit run streamlit_app.py
```

Open the local URL printed by Streamlit. The app presents two modes.

### Parse mode

Parse mode accepts one or more documents. Select:

- a processing profile;
- a document type or auto-detection;
- automatic segmentation or off;
- no schema, pasted JSON Schema, or an uploaded schema.

You can preview an upload before processing. Cloud profiles expose a consent
checkbox and remain disabled until consent and `OPENAI_API_KEY` are both
present.

After processing, use the Review tab to search by text, type, role, or candidate
source. Selecting a node synchronizes four views:

- the selected region is blue on the page image;
- its Markdown or unreadable marker appears beside the image;
- every recognition candidate is listed;
- citations and provenance are available in an expander.

The other tabs show the source, annotated PDF, quality report, LLM Markdown,
structured artifacts, sub-documents, and optional evaluation.

### Evaluate mode

Evaluate mode accepts exactly one source document plus a corrected hierarchical
JSON tree created from that same source. It parses the source again and reports
deterministic differences.

### Lab 3: inspect disagreement

1. Upload a scanned PDF or `examples/synthetic-medical-fax.pdf`.
2. Choose `Local only` and process it.
3. In Review, filter Status to `disputed`, `unreadable`, or `unresolved`.
4. Select a region and compare its Paddle, GLM, and any digital candidates.
5. Inspect Automatic retry decisions.
6. Check whether the retry was applied, rejected, or failed and compare its
   before/after score.

The workbench is intentionally read-only. It explains the parse; it does not
change evidence after the fact.

## 6. Understand the repository

The code is organized by responsibility rather than provider alone:

```text
streamlit_app.py                 user interface
src/grounded_docparse/
├── cli.py                       command-line adapter
├── config.py                    environment-backed runtime settings
├── models.py                    typed contracts
├── ingest.py                    validation and page preparation
├── paddle.py                    secure Docker runner and normalization
├── paddle_worker.py             code executed inside the container
├── gateways.py                  GLM and OpenAI calls
├── pipeline.py                  orchestration and tree construction
├── domain.py                    document profiles and grounded fields
├── segmentation.py              mixed-document splitting
├── extraction.py                schema extraction and logical tables
├── evaluation.py                gold-tree metrics
├── render.py                    Markdown, JSON, and ZIP
├── review.py                    quality reports and annotations
├── audit.py                     audit manifest
└── failures.py                  safe failure cases
tests/                           public contracts and abuse cases
examples/                        synthetic documents, schemas, and outputs
```

When learning a codebase, begin at its public boundary, not its largest file.
Trace this path:

```text
CLI main or Streamlit Process button
  → DocumentParser.parse / parse_path
  → ParseResult
  → renderer or download
```

### Lab 4: follow the call path

Open these symbols in order:

1. `cli.main`
2. `DocumentParser.parse_path`
3. `DocumentParser.parse`
4. `ingest_document`
5. `PaddleDockerRunner.run`
6. `GlmOcrGateway.recognize_region`
7. `DocumentParser._build_tree`
8. `render_llm_markdown`
9. `build_bundle`

For each symbol, answer two questions:

- What type enters this function?
- What validated type or artifact leaves it?

That exercise reveals the architecture without requiring you to understand the
entire 2,000-line pipeline at once.

## 7. Learn the data model

`models.py` uses Pydantic. Pydantic validates Python data against declared
types, ranges, sizes, and relationships before it becomes trusted application
state.

The important layers are:

### RecognitionCandidate

One possible literal reading of one region. It records source, task, prompt
version, pass number, text, optional box, and validation signals.

### RegionEvidence

The working state before the final tree. It combines region type, page, box,
order, candidates, agreement, verification status, confidence, and selection.

### DocumentNode

The stable exported content unit. It can represent a heading, paragraph, table,
cell, figure, formula, form field, footer, and other semantic types.

### DocumentTree

The complete versioned representation. It contains pages, nodes, hierarchy,
links, assets, classifications, grounded fields, tables, extractions, model and
window runs, warnings, failures, segmentation, and adaptive retries.

### ParseResult

The in-memory return value for callers. It contains the tree plus already
rendered artifacts and sub-document results.

### Lab 5: query the tree with Python

After completing Lab 2, run:

```powershell
uv run python -c "import json, pathlib; d=json.loads(pathlib.Path('output/synthetic-report.json').read_text(encoding='utf-8')); print(d['schema_version']); print(len(d['pages']), len(d['nodes'])); print(sorted({n['type'] for n in d['nodes'].values()}))"
```

Then print low-confidence nodes without revealing more text than necessary:

```powershell
uv run python -c "import json, pathlib; d=json.loads(pathlib.Path('output/synthetic-report.json').read_text(encoding='utf-8')); print([(n['id'], n.get('page_number'), (n.get('confidence') or {}).get('score')) for n in d['nodes'].values() if (n.get('confidence') or {}).get('score', 1) < 0.65])"
```

## 8. Follow one page through the pipeline

### Ingestion

The page becomes a `PageEvidence` with dimensions, DPI, render path, OCR path,
native blocks, links, and a scanned flag.

### Layout

Paddle output is normalized into `RegionEvidence`. Provider coordinates become
normalized boxes in the interval 0 to 1. Table HTML is parsed into rows and
cells; provider cell boxes are attached when present.

### Recognition

GLM receives a crop. The crop is derived from the region box, so its result can
be attached back to that exact region.

### Reconciliation

Candidates are compared. Number changes force a conflict because `12.50` and
`1250` may look textually similar while having completely different meaning.

### Retry

The planner observes layout failure or region uncertainty, chooses one fixed
retry, and measures whether it improved evidence. It cannot loop indefinitely.

### Cloud verification

When enabled, Luna receives bounded candidate data and the page image. Terra
receives summaries, not authority to rewrite the tree.

### Materialization

The final node receives a stable ID, citations, provenance, confidence,
relationships, and rendered Markdown. Validators ensure references point to
known nodes and pages.

## 9. Choose a processing profile

Use one recommended rule:

- Start with `local-only`.
- Use `hybrid` when review shows unresolved or disputed regions that matter.
- Use `maximum-accuracy` when cross-page structure and exhaustive verification
  justify higher latency, cost, and cloud exposure.

| Question | Local only | Hybrid | Maximum accuracy |
|---|---|---|---|
| Sends content to OpenAI? | No | Yes: full page image for pages with uncertainty, plus only uncertain regions | Yes: every page image and all regions |
| Automatic local retries? | Page + region | Page; Luna can request confirmation | Page; Luna can request confirmation |
| Terra document reasoning? | No | No | Yes |
| Relative cost and latency | Lowest | Medium | Highest |

OpenAI is optional. The code constructs the standard SDK client, which reads
`OPENAI_API_KEY` and `OPENAI_BASE_URL`. The runbook checks that a key exists but
never prints it.

## 10. Extract data with a schema

Schema-first extraction asks a different question from parsing:

- Parsing asks, "What is present in this document?"
- Extraction asks, "Which grounded values fill this requested JSON shape?"

The example invoice schema is in `examples/schemas/invoice.schema.json`.

A minimal schema asks for one nested value:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Invoice extraction",
  "type": "object",
  "properties": {
    "invoice": {
      "type": "object",
      "properties": {
        "number": {
          "type": "string",
          "title": "Invoice number",
          "x-docparse-aliases": ["invoice no", "invoice #"]
        }
      },
      "required": ["number"],
      "additionalProperties": false
    }
  },
  "required": ["invoice"],
  "additionalProperties": false
}
```

If the extracted data is `{"invoice": {"number": "INV-42"}}`, its provenance
map uses the RFC 6901 path `/invoice/number`. That entry identifies the source
node, page, bounding box, confidence, and selected literal value. RFC 6901 is
simply a standard way to address a value inside JSON; `/invoice/number` means
the `number` property inside `invoice`.

### Lab 6: inspect and use a schema

```powershell
Get-Content examples/schemas/invoice.schema.json
uv run grounded-docparse invoice.pdf --output output --document-profile invoice --schema examples/schemas/invoice.schema.json
```

Inspect `output/invoice.extraction.json`. For every leaf, find its corresponding
entry in `provenance`. Confirm that required but unsupported values are reported
as unresolved rather than guessed.

For a table marked with `x-docparse-kind: table`, inspect the `tables` directory.
JSONL is the canonical large-table export because each line is one complete row
and does not require loading the entire table. CSV is provided for spreadsheet
interoperability and escapes values that could be interpreted as formulas.

## 11. Segment a mixed PDF

A multi-document PDF may contain several invoices, an attachment, and
correspondence. Page count alone cannot identify boundaries. The parser combines
page type with repeated identifiers and continuation evidence.

### Lab 7: compare segmentation modes

```powershell
uv run grounded-docparse batch.pdf --output output-auto --segmentation auto
uv run grounded-docparse batch.pdf --output output-off --segmentation off
```

Compare the two batch manifests. With automatic segmentation, inspect each
descriptor's start/end page, profile, confidence, identifier evidence, and
boundary decisions. Verify that source page numbers remain stable inside the
segment tree and that segment page numbers begin at one.

## 12. Evaluate against corrected truth

Quality indicators such as OCR coverage and mean confidence can tell you where
to inspect. They cannot tell you the true error rate without labels.

A gold tree is a corrected `DocumentTree` for the exact same source document.
The source hash prevents accidentally comparing unrelated files. This project
does not yet include a labeling editor, so gold creation is a manual workflow:

1. Parse the source and copy its exported JSON to a label directory.
2. Correct node text, type, bounding boxes, reading order, hierarchy, grounded
   fields, and optional segmentation/extraction labels in that copy.
3. Preserve `source_sha256`, page numbers, and reciprocal parent/child links.
4. Ensure `root_id`, every page ID, every `content_node_id`, and all referenced
   node IDs exist in `nodes`.
5. Validate the result with `load_gold_tree` before running evaluation.

The minimum top-level tree contract is `document_id`, `source_name`,
`source_sha256`, `root_id`, `nodes`, and `pages`; the exported parse is the safest
starting template because it already contains valid page and hierarchy records.

```powershell
uv run python -c "from pathlib import Path; from grounded_docparse import load_gold_tree; load_gold_tree(Path('labels/document.gold.json').read_bytes()); print('Gold tree valid')"
```

### Lab 8: run evaluation

```powershell
uv run grounded-docparse document.pdf --output evaluated --gold-json labels/document.gold.json
```

Open `evaluated/document.evaluation.json`. Read individual dimensions rather
than searching for one score:

- CER and WER measure literal text differences.
- Type precision/recall/F1 measure semantic classification.
- IoU measures box overlap.
- Reading-order accuracy measures sequence.
- Hierarchy accuracy measures parent-child structure.
- Citation and form metrics measure grounding completeness.

For production readiness, build a labeled set that represents actual scanner
quality, languages, forms, tables, handwriting, and domain variation.

## 13. Understand failures and quality

The pipeline distinguishes three ideas:

- **Warning:** something degraded, but parsing continued.
- **Failure case:** a structured record of a known problem or fallback.
- **Exception:** the request could not continue at a boundary.

`failures.jsonl` is safe for aggregation because it excludes document text,
images, crops, and raw provider exception messages. `audit.json` summarizes
coverage and runs. `quality.json` presents page-level review signals.

### Common problems

#### Docker CLI or Linux engine unavailable

Start Docker Desktop and confirm it is using Linux containers. Run
`docker info` before retrying.

#### Paddle image missing

Pull the exact digest-pinned image. A tag without the digest is rejected by
configuration validation.

#### Paddle cache missing

Run `uv run grounded-docparse-paddle-setup` once. Do not run it before every
parse.

#### GLM unavailable

Confirm Ollama is running and `ollama list` contains `glm-ocr`. The parser can
degrade to other evidence, but scanned-region accuracy will suffer.

#### Cloud profile disabled

Confirm the key is present without printing it and set the requested base URL.
In Streamlit, also select the consent checkbox for that batch.

#### Page exceeds the pixel limit

Do not simply remove the guard. Lower `DOCPARSE_RENDER_DPI` or preprocess an
unusually large source after assessing the impact on small text.

#### Low table grounding quality

Inspect whether Paddle supplied cell boxes. A table can have correct text while
some cells inherit table-level grounding; that is a grounding limitation, not
necessarily a text error.

## 14. Read and run the tests

Tests are executable documentation. They use synthetic documents and fake
providers so the main suite is deterministic and does not require GPU or paid
calls.

```powershell
uv run pytest -q
uv run pytest -q tests/test_pipeline.py
uv run pytest -q tests/test_segmentation.py tests/test_extraction.py
uv run pytest -q tests/test_review.py tests/test_evaluation.py
```

Useful test groups:

- `test_ingest.py`: signatures, pages, scans, and limits.
- `test_paddle.py`: secure command construction and Paddle normalization.
- `test_pipeline.py`: provider routing, profiles, retries, and exports.
- `test_citations_forms.py`: citations, forms, audit, and schema versions.
- `test_segmentation.py`: page classification and boundaries.
- `test_extraction.py`: schemas, provenance, and table sidecars.
- `test_evaluation.py`: deterministic gold comparisons.
- `test_review.py`: quality, annotated PDFs, and batch ZIPs.
- `test_streamlit.py`: UI consent and widget seams.

## 15. Extend the system safely

Before editing, identify which contract changes.

### Add a document profile

Work in `domain.py`. Derive fields only from existing nodes, attach source IDs,
and add public-contract tests for classification, grounding, and validation.

### Add a provider

Work behind a gateway. Convert provider output into a
`RecognitionCandidate` or an existing typed decision. Do not let a provider
write directly to exports or bypass tree validation.

### Add a retry rule

Define all four parts before coding:

1. deterministic trigger;
2. maximum attempt count;
3. measurable acceptance rule;
4. complete adaptive-retry record.

### Add an export

Consume the validated `DocumentTree` in a renderer. Preserve citations and
escape untrusted content. Do not re-run OCR during rendering.

### Change the tree schema

Treat this as a public API change. Update the schema version, models, renderers,
audit output, sub-document slicing, examples, tests, and migration notes.

### Lab 9: design an extension before coding

Choose one missing capability, such as handwriting routing. Write down:

- the evidence that triggers it;
- the provider input and typed output;
- its resource and privacy boundary;
- how a result is accepted or rejected;
- how it appears in provenance and audit;
- the public tests that prove the contract.

If any answer is "the model decides," the design is not bounded enough yet.

## 16. Mastery checklist

You are ready to work independently when you can:

- explain why layout and OCR are separate stages;
- trace an LLM Markdown block to a page box and recognition candidate;
- describe when Paddle, GLM, Luna, and Terra run;
- distinguish quality proxies from gold-label accuracy;
- explain why a rejected retry candidate is still retained;
- navigate from UI or CLI to `DocumentParser.parse` and `ParseResult`;
- describe the physical and semantic indexes in `DocumentTree`;
- run schema extraction and verify leaf provenance;
- explain conservative segmentation and cloud boundary adjudication;
- diagnose a provider fallback from audit and failure artifacts;
- choose the smallest safe extension point and its required tests.

Keep [Architecture and design](architecture.md) open while modifying the
pipeline, and use [Run commands](run.md) as the operational command reference.
