# Grounded Document Parser

A single-page local Streamlit app that uses a bounded manager-and-specialist workflow to turn a PDF or image into layout-aware Markdown, agentic JSON, and an annotated PDF. A second stage generates an editable JSON Schema and extracts values with atomic page, span, and bounding-box evidence.

The workflow is inspired by LlamaParse and LandingAI ADE, but calls neither service. A Luna manager chooses only the specialists needed for each page. Luna performs the first pass; Terra is reserved for explicit repair or extraction-critic escalation. Delegation is bounded to two specialists per round and two repair rounds. Deterministic validation builds the hierarchy, verifies extraction evidence, and produces the exports.

Documents are processed in ordered windows of 100 pages with up to 50 isolated page workers by default. Page-local agent calls run concurrently, while cross-page hierarchy, output order, usage, and traces are finalized deterministically. Provider capacity is account- and model-specific; lower `DOCPARSE_MAX_PAGE_CONCURRENCY` if the project reaches request, token, or image rate limits.

## Run

Requirements: Python 3.12–3.14 through `uv` and `OPENAI_API_KEY` in the launching environment. `OPENAI_BASE_URL` is optional.

```powershell
uv sync --locked
uv run streamlit run streamlit_app.py
```

Open <http://localhost:8501>, upload one document, and select **Parse document**. Inspect actual input/output token usage, the agent trace, Markdown, agentic or legacy JSON, and the annotated PDF. In **Extract**, describe the fields, review the generated schema, then run the grounded extraction. No cost estimator, cache window, Docker, database, background worker, local model download, or application cache is used.

## Output

- Ordered headings, paragraphs, lists, tables, figures, charts, forms, and checkboxes, including distinct form values and printed hints
- Nested sections and page structure
- Truthful `not_checked`, `verified`, `needs_review`, or `rejected` state plus confidence, page, and normalized coordinates per block
- Lossless document-first Markdown with per-block semantic coverage and exact spans
- Agentic JSON v2 with page quality, rejected/correction audit history, atomic evidence, usage, and agent trace; legacy JSON remains downloadable
- Schema-driven extraction where every non-null scalar must resolve to source evidence
- Actual run-level input and output token totals
- Viewable and downloadable annotated PDF with audit boxes and labels

## Development

```powershell
uv run pytest -q
uvx ruff check .
uv run python -m compileall -q src streamlit_app.py tests
```

Run the opt-in source-grounded regression with configured provider credentials:

```powershell
uv run python scripts/evaluate_public_water.py --pdf D:\path\to\PublicWaterMassMailing.pdf
```

See [run commands](docs/run.md), [architecture](docs/architecture.md), and [the specification](docs/spec.md). Licensed under the [MIT License](LICENSE).
