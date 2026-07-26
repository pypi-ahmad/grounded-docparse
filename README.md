# Grounded Document Parser

Grounded Document Parser converts PDFs and images into layout-aware Markdown,
LLM-ready Markdown, hierarchical JSON, annotated PDFs, and auditable evidence.
It is designed for scanned and digital documents whose reading order, tables,
figures, forms, and page coordinates matter downstream.

The pipeline combines three bounded roles:

- **PaddleOCR-VL 1.6** detects page layout, reading order, tables, formulas,
  charts, figures, headers, and footers in an isolated GPU container.
- **GLM-OCR** independently recognizes page regions locally through Ollama.
- **OpenAI Luna and Terra** optionally verify uncertain evidence and resolve
  cross-page structure. They may select or relate grounded evidence, but cannot
  silently replace source text.

The project does not claim a fixed accuracy percentage or proven superiority
over commercial parsers. Use its deterministic evaluation mode on documents
representative of your workload before production adoption.

## Start here

- [Run commands](docs/run.md): copy-paste PowerShell and Bash commands.
- [Zero-to-mastery tutorial](docs/tutorial.md): beginner-friendly, hands-on tour.
- [Architecture and design](docs/architecture.md): components, contracts, and
  design decisions.
- [How it works](docs/how-it-works.md): runtime behavior and agentic flow.
- [Research basis](docs/research.md): documented LlamaParse and LandingAI ADE
  ideas that influenced the design.
- [System specification](docs/spec.md): requirements and security boundaries.

## What it produces

For `document.pdf`, the CLI writes:

| Artifact | Purpose |
|---|---|
| `document.md` | Layout-aware structured Markdown |
| `document.llm.md` | Markdown with a grounding comment before every block |
| `document.json` | Hierarchical document tree, schema version 1.9.0 |
| `document.audit.json` | Provider runs, coverage, warnings, and retry summary |
| `document.failures.jsonl` | Safe, structured failure cases for review |
| `document.quality.json` | Page-level OCR and grounding quality indicators |
| `document.annotated.pdf` | Region boxes, order, confidence, and source overlay |
| `document.batch.manifest.json` | Page classifications and sub-document boundaries |
| `document.extraction.json` | Optional schema-first extraction |
| `document.zip` | Complete result bundle, assets, and sub-documents |

Table cells carry exact cell coordinates when Paddle supplies them. When cell
coordinates are unavailable, the output explicitly marks table-level grounding
instead of fabricating a box. LLM-ready Markdown includes stable citation IDs,
page numbers, normalized and source coordinates, confidence, and semantic
ancestor paths.

## Supported inputs and workloads

- PDF, PNG, JPEG, and multi-frame TIFF
- Scanned and digital documents
- Technical documentation and scientific papers
- Invoices, receipts, purchase orders, and contracts
- Insurance claims, healthcare forms, and generic forms
- Mixed multi-document PDFs with repeated identifiers
- Tables continued across pages and schema-defined table arrays

Default safety limits are 250 MB and 500 pages per document. The Streamlit UI
accepts up to 10 files or 1 GB per batch and processes them sequentially to
avoid GPU contention.

## Quick start

Requirements:

- Windows 11 with Docker Desktop, WSL2, and NVIDIA container support, or an
  equivalent Linux NVIDIA Docker environment
- Ollama with the `glm-ocr` model
- Python 3.12 managed by `uv`
- Optional `OPENAI_API_KEY` for cloud profiles

```powershell
uv sync --python 3.12 --locked
ollama pull glm-ocr
docker pull ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
uv run grounded-docparse-paddle-setup
uv run streamlit run streamlit_app.py
```

The Paddle setup command warms model weights into the dedicated
`grounded-docparse-paddle-cache` Docker volume. Normal parsing then mounts that
cache read-only and runs the pinned container without network access.

## Processing profiles

| Profile | Local processing | Cloud processing | Recommended use |
|---|---|---|---|
| `local-only` | Paddle + GLM, including bounded GLM retries | None | Private documents and first runs |
| `hybrid` | Paddle + GLM | For pages containing uncertain regions, Luna receives the full page image and only those regions; it may also adjudicate ambiguous boundaries | Cost-aware accuracy improvement |
| `maximum-accuracy` | Paddle + GLM | Luna verifies all pages; Terra resolves cross-page structure and difficult boundaries | Highest available quality |

The Streamlit UI requires explicit consent before either cloud profile runs.
The CLI profile itself is the explicit operator choice. Cloud profiles require
`OPENAI_API_KEY`; the SDK also honors `OPENAI_BASE_URL`, including
`https://us.api.openai.com/v1`.

```powershell
uv run grounded-docparse examples/synthetic-report.pdf --output output
uv run grounded-docparse document.pdf --output output --profile hybrid
uv run grounded-docparse document.pdf --output output --profile maximum-accuracy
```

## Major capabilities

- Layout-first processing and multi-column reading order
- Independent local OCR evidence and numeric-disagreement detection
- Automatic high-resolution page and region retries when evidence is weak
- Physical page indexes plus a semantic section hierarchy
- Typed tables, rows, cells, figures, captions, formulas, forms, and visuals
- Grounded document-type profiles and non-decisional validation findings
- Automatic classification and splitting of mixed-document PDFs
- Bounded Draft 2020-12 JSON Schema extraction with per-value citations
- Logical continued-table exports as JSONL and spreadsheet-safe CSV
- Deterministic evaluation against a corrected same-source document tree
- Searchable read-only review UI synchronized with Markdown and page overlays
- Fail-soft provider boundaries with warnings and structured failure records

## CLI examples

```powershell
uv run grounded-docparse document.pdf --output output --segmentation off
uv run grounded-docparse invoice.pdf --output output --document-profile invoice
uv run grounded-docparse invoice.pdf --output output --schema examples/schemas/invoice.schema.json
uv run grounded-docparse document.pdf --output output --gold-json labels/document.gold.json
```

The accepted schema subset includes objects, properties, required fields,
arrays, scalar types, enums, formats, numeric bounds, titles, descriptions,
`x-docparse-aliases`, and table arrays marked with
`x-docparse-kind: table`. Remote references, `$ref`, composition keywords, and
unknown keywords are rejected.

## Configuration

| Variable | Default |
|---|---|
| `DOCPARSE_TERRA_MODEL` | `gpt-5.6-terra` |
| `DOCPARSE_LUNA_MODEL` | `gpt-5.6-luna` |
| `DOCPARSE_GLM_MODEL` | `glm-ocr` |
| `DOCPARSE_OLLAMA_HOST` | `http://127.0.0.1:11434` |
| `DOCPARSE_PADDLE_IMAGE` | Digest-pinned NVIDIA PaddleOCR-VL image |
| `DOCPARSE_PADDLE_CACHE_VOLUME` | `grounded-docparse-paddle-cache` |
| `DOCPARSE_RENDER_DPI` | `300` |
| `DOCPARSE_MAX_UPLOAD_BYTES` | `262144000` |
| `DOCPARSE_MAX_PAGES` | `500` |
| `DOCPARSE_MAX_PAGE_PIXELS` | `20000000` |
| `DOCPARSE_MAX_TABLE_ROWS` | `100000` |
| `DOCPARSE_MAX_TABLE_COLUMNS` | `200` |
| `DOCPARSE_MAX_TABLE_CELLS` | `2000000` |
| `DOCPARSE_PADDLE_TIMEOUT_SECONDS` | `3600` |
| `DOCPARSE_PAGE_WINDOW_SIZE` | `10` |
| `DOCPARSE_SOURCE_CHUNK_PAGES` | `25` |
| `DOCPARSE_CHUNK_RETRY_COUNT` | `2` |
| `DOCPARSE_WINDOW_RETRY_COUNT` | `2` |
| `DOCPARSE_ENABLE_CHART_RECOGNITION` | `true` |
| `DOCPARSE_ENABLE_IMAGE_OCR` | `true` |
| `DOCPARSE_PADDLE_MAX_NEW_TOKENS` | `16384` |
| `DOCPARSE_GLM_MAX_OUTPUT_TOKENS` | `16384` |
| `DOCPARSE_LUNA_MAX_OUTPUT_TOKENS` | `16384` |
| `DOCPARSE_TERRA_MAX_OUTPUT_TOKENS` | `16384` |
| `DOCPARSE_ENABLE_PADDLE` | `true` |
| `DOCPARSE_ENABLE_GLM` | `true` |
| `DOCPARSE_ENABLE_OPENAI` | `true` |

## Development verification

```powershell
uv run pytest -q
uv run python -m compileall -q src streamlit_app.py scripts tests
uv run python scripts/generate_examples.py
```

Automated tests use synthetic documents and fake providers. Live model testing
is intentionally separate because it requires Docker, GPU resources, Ollama,
and potentially paid cloud calls.
