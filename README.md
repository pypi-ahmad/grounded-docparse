# Grounded Document Parser

A single-page local Streamlit studio that uses GLM-OCR plus bounded `gpt-5.6-luna` visual recovery, refinement, classification, TOC generation, grounded extraction, and document chat.

The workflow mirrors ADE's parse-then-reason split without calling ADE. GLM-OCR performs layout analysis and parallel region OCR. Up to eight prioritized Luna recovery requests per document, capped at three region crops per page, repair hard existing regions. Luna may replace only high-confidence text; GLM-owned IDs, boxes, types, reading order, confidence, and structure never change. Image recovery uses high reasoning effort; text-only Luna work uses medium effort. A separate text-only Luna pass can refine Markdown presentation without changing grounded text or geometry.

Documents are processed in ordered windows of 16 pages with up to 8 isolated page workers by default. Every PDF page is rendered and processed as pixels; embedded or selectable PDF text is never extraction evidence, ground truth, or validation input. Drafting starts from deterministic raster regions. Luna never synthesizes missing regions or replaces a full page; if every nonblank page lacks usable GLM elements, parsing stops before agentic stages.

## Run

Requirements: Python 3.12–3.14 through `uv`. `OPENAI_API_KEY` enables Luna recovery and refinement; without it, GLM-OCR still returns grounded output. `OPENAI_BASE_URL` is optional.

```powershell
uv sync --locked
uv run streamlit run streamlit_app.py
```

On a fresh Windows 11 + NVIDIA GPU machine, double-click `Setup-GLM-OCR.cmd` once
for a full offline GLM-OCR setup (WSL2, GPU check, `uv`, weights); use
`Launch-GLM-OCR.cmd` afterward. See [run commands](docs/run.md).

Open <http://localhost:8501>, upload one document, choose an ADE mode, and select **Parse document**. **Fast** is the default and runs classification without Markdown refinement or TOC generation; **Full** enables all three. Extraction remains on demand: define or load field keys inside the post-parse Extract tab, then run it. Chat is off by default and makes no request until enabled and a question is submitted. Source actions open the cited annotated page and highlight its GLM box.

## Output

- Ordered headings, paragraphs, lists, tables, figures, charts, forms, and checkboxes, including distinct form values and printed hints
- Nested sections and page structure
- Truthful `not_checked`, `verified`, `needs_review`, or `rejected` state plus block confidence and optional exact low-confidence spans for atoms and table cells
- Lossless document-first Markdown with per-block semantic coverage and exact spans
- Unified JSON v4.4 with top-level `document_type`, `sections`, `extracted_fields`, and recovered-only `recovery_log`, plus element provenance, split Luna timing, refined `markdown`, grounded `base_markdown`, normalized elements, engine/model metadata, correction history, usage, and agent trace; annotated PDF bytes remain a separate download
- Schema-driven extraction with exact, near-exact, inferred, or not-found grounding
- Optional document classification, hierarchical TOC, and cited document chat
- Versioned, compact Luna prompts with one schema-repair retry and reusable prepared context
- SQLite-backed reusable schema library under the gitignored `data/` directory
- Actual run-level input and output token totals
- Viewable and downloadable annotated PDF with semantic type colors, reading-order labels, and Layout Tree selection highlighting

## Development

```powershell
uv run pytest -q
uvx ruff check .
uv run python -m compileall -q src streamlit_app.py tests
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
latency, calls, tokens, recovery deferrals, retries, throttles, and estimated
cost. Missing annotations are reported as unavailable rather than scored as zero. The
dated rate card is a reproducibility input, not a billing source. This small public and
synthetic corpus does not establish broad production accuracy or equivalence with ADE,
LandingAI, or any external benchmark. DocVQA answer rate is a question-answering metric;
it is not character, field, table-cell, or grounding accuracy.

See [extraction quality research](docs/extraction-quality-research.md) for the
reference-provenance policy, observed failure modes, and targeted crop experiment.

See [run commands](docs/run.md), [architecture](docs/architecture.md), and [the specification](docs/spec.md). Licensed under the [MIT License](LICENSE).
