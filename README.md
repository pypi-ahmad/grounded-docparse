# Grounded Document Parser

A single-page local Streamlit studio that uses GLM-OCR plus a bounded Luna manager-and-specialist workflow to turn a PDF or image into layout-aware Markdown, unified JSON, and an annotated PDF.

The workflow is inspired by LlamaParse and LandingAI ADE, but calls neither service. GLM-OCR performs layout analysis and parallel region OCR; Luna handles only targeted repair, extraction, and bounded full-page fallback. Deterministic validation builds the hierarchy, verifies extraction evidence, and produces the exports.

Documents are processed in ordered windows of 16 pages with up to 8 isolated page workers by default. Every PDF page is rendered and processed as pixels; embedded or selectable PDF text is never extraction evidence, ground truth, or validation input. Drafting starts from deterministic raster regions. Full-page VLM fallback is reserved for region-discovery failures and capped at 10% of pages by default.

## Run

Requirements: Python 3.12–3.14 through `uv` and `OPENAI_API_KEY` in the launching environment. `OPENAI_BASE_URL` is optional.

```powershell
uv sync --locked
uv run streamlit run streamlit_app.py
```

Open <http://localhost:8501>, upload one document, optionally select a page range, and select **Parse document**. Inspect the Overview, Markdown, Annotated PDF, and Layout Tree tabs, then download Markdown, unified JSON, or the annotated PDF. Luna token usage and GLM-OCR runtime metadata appear in the result bar.

## Output

- Ordered headings, paragraphs, lists, tables, figures, charts, forms, and checkboxes, including distinct form values and printed hints
- Nested sections and page structure
- Truthful `not_checked`, `verified`, `needs_review`, or `rejected` state plus block confidence and optional exact low-confidence spans for atoms and table cells
- Lossless document-first Markdown with per-block semantic coverage and exact spans
- Unified JSON v4 with flat normalized elements, engine/model metadata, page quality, audit history, atomic evidence, usage, and agent trace; legacy JSON remains available through the Python API
- Schema-driven extraction where every non-null scalar must resolve to source evidence
- Actual run-level input and output token totals
- Viewable and downloadable annotated PDF with semantic type colors, reading-order labels, and Layout Tree selection highlighting

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

Run the representative visual live corpus with an
explicit public-water source and reference:

```powershell
uv run python scripts/evaluate_corpus.py --live --output benchmarks/baselines/live-visual-v1.json
uv run python scripts/evaluate_corpus.py --live `
  --external-source public-water-mass-mailing=data/pdf/PublicWaterMassMailing.pdf `
  --reference public-water-mass-mailing=data/groundtruth/PublicWaterMassMailing.md `
  --rate-card benchmarks/rate-cards/openai-standard-2026-07-28.json `
  --output output/evaluation-corpus-live.json
```

External references default to generated-reference diagnostics. Mark a reference
as primary only when it has been checked against the source:

```powershell
uv run python scripts/evaluate_corpus.py --live `
  --document public-water-mass-mailing `
  --page-subset public-water-mass-mailing=4,5,6 `
  --external-source public-water-mass-mailing=data/pdf/PublicWaterMassMailing.pdf `
  --reference public-water-mass-mailing=data/groundtruth/PublicWaterMassMailing.md `
  --reference-basis public-water-mass-mailing=generated
```

The live report groups results by manifest feature and records character/word accuracy,
reading order, table cells, schema fields, continuity, hallucination/review outcomes,
latency, calls, tokens, full-page fallbacks, retries, throttles, budget denials, and estimated
cost. Missing annotations are reported as unavailable rather than scored as zero. The
dated rate card is a reproducibility input, not a billing source. This small public and
synthetic corpus does not establish broad production accuracy or equivalence with ADE,
LandingAI, or any external benchmark. DocVQA answer rate is a question-answering metric;
it is not character, field, table-cell, or grounding accuracy.

See [extraction quality research](docs/extraction-quality-research.md) for the
reference-provenance policy, observed failure modes, and targeted crop experiment.

See [run commands](docs/run.md), [architecture](docs/architecture.md), and [the specification](docs/spec.md). Licensed under the [MIT License](LICENSE).
