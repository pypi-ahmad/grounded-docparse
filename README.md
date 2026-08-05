# Grounded Document Parser

A workstation-oriented Streamlit studio that parses PDFs and images with selectable local GLM-OCR or PaddleOCR-VL-1.6, then optionally sends selected crops or recognized document context to `gpt-5.6-luna` for bounded visual recovery and document-level reasoning.

Repository: [github.com/pypi-ahmad/grounded-docparse](https://github.com/pypi-ahmad/grounded-docparse)

The selected local OCR engine owns layout, element IDs, normalized bounding boxes, types, confidence, and reading order. PaddleOCR-VL-1.6 uses the full PP-DocLayoutV3 plus PaddleOCR-VL-1.6-0.9B pipeline with a local vLLM recognition backend. Luna visual recovery can replace only text on an existing element when the returned confidence is at least `0.85`; additions, deletions, geometry changes, type changes, and reading-order changes are ignored. Every Luna request uses medium reasoning effort.

```text
upload
  -> raster ingest
  -> selected GLM-OCR or PaddleOCR-VL-1.6 layout and recognition
  -> deterministic quality analysis
  -> optional bounded Luna crop recovery
  -> grounded Markdown, elements, JSON v4.4.0, annotated PDF
  -> optional Luna refinement, classification, TOC, extraction, and chat
```

## Application preview

![Document Parse Studio ready for a document upload](docs/images/document-parse-studio-full.png)

Every PDF page is rendered to pixels. Selectable or embedded PDF text is not extraction evidence. GLM-OCR processes ordered windows of 16 pages with up to eight page workers by default; PaddleOCR-VL submits the full document to its local API. If at least one page is nonblank and none of the nonblank pages contains a local OCR layout region, parsing stops before Luna features run; isolated page failures remain visible as warnings.

When GLM-OCR is selected, form-heavy scans receive a GLM-only recovery pass for every eligible risky region, capped at three per page. For PDFs parsed with PaddleOCR-VL, incomplete checkbox tables may receive a conservative local recovery pass; a state is accepted only when independent 190 and 200 DPI parses agree. Both engines then enter the same deterministic quality and optional Luna-recovery stages.

## Install and set up

The supported installer target is Windows 10 22H2 or Windows 11 x64 with AVX2, at least 16 GB RAM, 20 GB free disk, and network access during first setup. It installs or reuses WSL2, Ubuntu 24.04, Python, dependencies, and pinned models. NVIDIA CUDA uses vLLM; AMD uses Ollama acceleration when supported; every failed or unavailable GPU path falls back to Ollama CPU.

1. Clone the repository from PowerShell:

   ```powershell
   git clone https://github.com/pypi-ahmad/grounded-docparse.git
   Set-Location grounded-docparse
   ```

2. Run setup. It installs missing Windows/WSL dependencies and resumes after a required restart:

   ```powershell
   .\Setup-GLM-OCR.cmd
   ```

   On a release, run `GroundedDocParse-<version>-Setup.exe` instead; Git is not required. Setup reuses a healthy Ubuntu user or securely prompts once for Linux credentials.

3. Optional: enable Luna visual recovery and document reasoning by saving the OpenAI values in the Windows user environment. Skip this step for local-only parsing.

   ```powershell
   [Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-key", "User")
   # Optional OpenAI-compatible endpoint:
   # [Environment]::SetEnvironmentVariable("OPENAI_BASE_URL", "https://example.com/v1", "User")
   ```

4. For later sessions, start or reuse the managed services with:

   ```powershell
   .\Launch-GLM-OCR.cmd
   ```

   To start with PaddleOCR-VL-1.6 selected, use `Launch-PaddleOCR-VL-1.6.cmd`. Either launcher can switch the exclusive GPU backend later from the in-app model dropdown.

`Launch-GLM-OCR.cmd` refreshes `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` from Windows user scope each time. See [setup](SETUP.md) for manual WSL installation, configuration, security boundaries, and troubleshooting, or [run commands](docs/run.md) for service lifecycle commands.

## How to use the app

1. Upload up to 20 PDFs, PNGs, JPEGs, or TIFFs (250 MB per file and 1 GB combined). Files are processed sequentially. An optional inclusive page range is available only when one PDF is uploaded; batches process every page.
2. Choose **GLM-OCR** or **PaddleOCR-VL-1.6** from **Document extraction model**, then choose an **ADE mode** for optional Luna features:
   - **Fast**: classification is the only preset-controlled Luna feature; visual recovery is a separate toggle and defaults on when a key is available.
   - **Full**: Markdown refinement, classification, and TOC generation.
   - **Custom**: any other combination of those toggles.
3. Keep visual recovery enabled to inspect prioritized hard regions. The Luna budget scales from eight crops to the configured ceiling of 64 based on document length and remains capped at three crops per page.
4. Select **Parse document** or **Process documents**. A failed file does not stop the rest of the queue; running the batch again retries failures and skips unchanged completed files.
5. Choose a file from **Document results**, then review Overview, Markdown, Annotated PDF, Extract, optional Chat, and Layout Tree.
6. Download individual results or **Download all outputs**. The ZIP includes every original, a manifest, and the generated Markdown, annotated PDF, full JSON, and extraction JSON when available.

Extraction is always on demand after parsing. The field builder remains available for flat scalar fields. **Raw JSON Schema** mode stores and routes the supported strict nested schema subset, including objects, arrays, enums, and nullable booleans for checkbox/selectable fields. Imported raw JSON Schemas use the filename as their saved name; saved-schema envelope imports remain backward compatible. Markdown imports continue to populate the flat field builder.

Flat Markdown schemas support a table or bullet list (not both), with an optional H1 schema name and optional type (`string` by default):

```markdown
# Invoice
| Field name | Description | Type |
| --- | --- | --- |
| invoice_number | Official invoice ID | string |
| total_amount | Final payable amount | number |
```

```markdown
# Invoice
- invoice_number: Official invoice ID
- total_amount (number): Final payable amount
```

Supported types are `string`, `number`, `integer`, `boolean`, and `date`. Without an H1, the filename becomes the schema name.

For mixed-form PDFs, enable **Use custom form routing** in Extract. A reusable routing profile defines category keys and descriptions, which categories are extractable, and the saved extraction schema assigned to each eligible category. Luna classifies contiguous page ranges from grounded Markdown/layout; results below 85% confidence require review. Users may correct ranges and categories before selecting **Extract eligible forms**. Only approved, eligible segments are sent for extraction. Routing profiles support the same editable, JSON, and Markdown workflows as extraction schemas; `other` is always a non-extractable fallback.

Chat is off by default and sends no request until enabled and a question is submitted. **Show source** actions open the cited annotated page and highlight the local-OCR-owned box.

## Outputs

- Refined Markdown plus grounded `base_markdown`
- Parse JSON v4.4.0 with normalized elements, page/block evidence, provenance, correction history, parse usage/trace, empty agentic placeholders, and recovery log
- Full JSON v4.5.0 using the same envelope with current classification, sections, legacy extraction, custom form routing, per-form extraction, combined usage/trace, and feature statuses populated
- Extraction JSON v1.1.0 with values, evidence, `element_id`, source text, confidence, and local-OCR-owned normalized boxes
- Annotated PDF with semantic colors, reading-order labels, selected-element highlighting, and dashed Luna-recovery boxes
- Run metadata including GLM, Luna recovery, and Luna agentic timing

Annotated PDF bytes are downloaded separately and are not embedded in JSON. Reusable extraction schemas and routing profiles persist in the gitignored SQLite database at `data/document_studio.sqlite3` unless `DOCPARSE_STUDIO_DB_PATH` overrides it.

## Public Python API

The package exports `DocumentParser`, `DocumentAgent`, `DocumentExtractor`, `ParserConfig`, result models, and `render_combined_result`.

```python
from pathlib import Path

from grounded_docparse import DocumentAgent, DocumentParser, render_combined_result

source = Path("invoice.pdf")
result = DocumentParser().parse(
    source.read_bytes(),
    source.name,
    refine_markdown=False,
    visual_recovery=True,
)

agent = DocumentAgent()
analysis = agent.analyze(result, classify=True, generate_toc=False)
full_json = render_combined_result(result, analysis)
```

`DocumentParser.parse` is synchronous. Luna failures do not invalidate a successful local OCR parse; unavailable or failed optional features expose warnings or feature statuses. See the complete [Python API contract](docs/api.md).

## Repository layout

```text
.
├── Setup-GLM-OCR.cmd             # First-run Windows/WSL bootstrap and launch
├── Launch-GLM-OCR.cmd            # Subsequent Windows launcher
├── Launch-PaddleOCR-VL-1.6.cmd   # Start with PaddleOCR selected
├── paddle-runtime/               # Isolated locked Paddle/vLLM environment
├── streamlit_app.py              # Streamlit entry point
├── src/grounded_docparse/        # Parser, models, gateways, renderers, agentic layer
├── config/glmocr.yaml            # Source GLM-OCR SDK configuration
├── scripts/wsl/                  # Locked WSL setup and launch scripts
├── scripts/                      # Corpus generation and evaluation utilities
├── benchmarks/                   # Versioned corpus, schemas, rate cards, baselines
├── examples/                     # Synthetic documents and extraction schema
├── tests/                        # Offline contract and behavior tests
├── docs/                         # Architecture, operation, API, workflows, research
├── pyproject.toml                # Package metadata and dependency declarations
└── uv.lock                       # Cross-platform locked dependency graph
```

## Documentation

| Guide | Purpose |
| --- | --- |
| [Setup](SETUP.md) | Supported Windows/WSL installation, runtime configuration, and troubleshooting |
| [Run locally](docs/run.md) | Launcher behavior, manual service commands, and shutdown steps |
| [Tutorial](docs/tutorial.md) | End-user walkthrough of parsing, extraction, chat, and downloads |
| [Complete user guide](docs/complete-user-guide.md) | In-depth feature and workflow guide for business users, reviewers, and technical operators |
| [Zero-to-hero technical tutorial](docs/zero-to-hero-tutorial.md) | First-principles setup, usage, Python integration, internals, testing, and production boundaries |
| [Business extraction workflow](docs/business-user-extraction-workflow.md) | Non-technical workflow for large reusable field sets |
| [Architecture](docs/architecture.md) | Components, ownership rules, pipeline stages, and failure boundaries |
| [Python API](docs/api.md) | Exported names, signatures, schemas, and result contracts |
| [Product specification](docs/spec.md) | Required behavior, public interfaces, and non-goals |
| [Local GLM-OCR](docs/local-glmocr.md) | Locked GLM-OCR/vLLM runtime and evaluation path |
| [Local PaddleOCR-VL-1.6](docs/local-paddleocr-vl.md) | Isolated Paddle runtime installation, health checks, and troubleshooting |
| [Azure bulk medical fax deployment](docs/azure-bulk-fax-deployment.md) | Production design and operations runbook for secure bulk medical-fax processing on Azure |
| [Security policy](SECURITY.md) | Reporting process, deployment boundary, egress, and retention |

## Development

```powershell
uv sync --locked
uv run pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
git diff --check
```

Live evaluation is opt-in and must run inside WSL with the setup-created environment while the local GLM service is available. External references default to generated-reference diagnostics unless an explicit reference basis is supplied. Use `--glm-only` to disable and verify the absence of Luna recovery, refinement, and extraction:

```bash
source "${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}/bin/activate"
python scripts/evaluate_corpus.py --live --glm-only \
  --document synthetic-report \
  --artifacts-dir output/synthetic-report-glm-only \
  --output output/synthetic-report-glm-only.eval.json
```

The bundled public/synthetic corpus is a regression suite, not evidence of broad production accuracy or equivalence with an external product. See [extraction quality research](docs/extraction-quality-research.md), [architecture](docs/architecture.md), and [specification](docs/spec.md).

Licensed under the [MIT License](LICENSE).
