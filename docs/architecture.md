# Architecture

## System boundary

The application is one synchronous Streamlit process plus a local GLM-OCR/vLLM service. There is no HTTP application API, queue, worker service, job store, artifact store, durable/cross-session result cache, or multi-user authentication layer. Streamlit session state reuses a successful GLM parse when only agentic toggles change. SQLite persists reusable extraction schemas and routing profiles only.

```text
Browser
  -> Streamlit (`streamlit_app.py`)
     -> ingest and rasterization
     -> GLM-OCR SDK -> local vLLM (`glm-ocr`, port 8080)
     -> deterministic quality/recovery planning
     -> optional Luna crop recovery
     -> deterministic hierarchy, Markdown, JSON, and PDF annotations
     -> optional Luna document features
  -> downloads and source highlighting
```

## Repository map

| Path | Responsibility |
| --- | --- |
| `Setup-GLM-OCR.cmd` / `Launch-GLM-OCR.cmd` | Windows bootstrap/launch entry points and user-scope OpenAI environment forwarding |
| `streamlit_app.py` | Upload, modes, progress, tabs, schema UI, chat, downloads |
| `src/grounded_docparse/__init__.py` | Package-root public exports |
| `src/grounded_docparse/config.py` | `ParserConfig`, analysis thresholds, environment parsing, fixed Luna model |
| `src/grounded_docparse/ingest.py` | Input validation, PDF/image rasterization, region rerendering |
| `src/grounded_docparse/local_ocr.py` | Process-wide GLM-OCR runtime and SDK-result normalization |
| `src/grounded_docparse/page_analysis.py` | Page quality signals and GLM region conversion |
| `src/grounded_docparse/quality.py` | Deterministic block quality, verification, and document quality aggregation |
| `src/grounded_docparse/pipeline.py` | Parse orchestration, recovery selection, deterministic validation, hierarchy |
| `src/grounded_docparse/gateways.py` | OpenAI Responses API calls, Structured Outputs, usage and trace collection |
| `src/grounded_docparse/prompts.py` | Versioned prompt templates for Luna document features |
| `src/grounded_docparse/enhancement.py` | Bounded Markdown-refinement chunks and presentation-plan application |
| `src/grounded_docparse/agentic.py` | Prepared contexts, classification, TOC, extraction orchestration, chat |
| `src/grounded_docparse/extraction.py` | JSON Schema subset validation and evidence resolution |
| `src/grounded_docparse/models.py` | Pydantic domain contracts, API result records, progress events, diagnostics |
| `src/grounded_docparse/schema_store.py` | SQLite schema/profile CRUD, Markdown import, and UI-schema compilation |
| `src/grounded_docparse/render.py` | Markdown, JSON v4.4 parse/v4.5 full results, elements, quality, and annotations |
| `src/grounded_docparse/runtime.py` | Provider concurrency, retries, cooldown, usage, diagnostics |
| `src/grounded_docparse/benchmark.py` | Corpus contracts and evaluation metrics |
| `config/glmocr.yaml` | Source GLM-OCR SDK, layout, recognition, and formatter configuration |
| `scripts/wsl/prepare_glmocr_runtime.py` | Pinned model resolution and generated offline SDK configuration |
| `scripts/wsl/*.sh` | Locked WSL environment setup, vLLM serving, Streamlit launch, health checks |
| `scripts/evaluate_corpus.py` | Opt-in live/offline corpus evaluation and artifact export |

## Parse pipeline

```text
1. Validate bytes, extension, page count, and pixel limits.
2. Render every page to PNG; never read selectable PDF text.
3. Analyze GLM-OCR in ordered windows of 16 pages.
4. Rank recovery candidates from GLM confidence and deterministic quality signals.
5. Process up to eight pages concurrently within each ordered window.
6. Send at most eight selected Luna crops per document and three per page.
7. Apply only high-confidence textual corrections to existing elements.
8. Restore source page order and build the cross-page hierarchy.
9. Materialize quality, elements, base Markdown, and annotations.
10. Optionally refine Markdown with presentation directives.
11. Render canonical JSON with grounded and refined Markdown.
12. Optionally classify and generate the TOC concurrently.
13. Run extraction and chat only when requested in the UI.
```

Worker progress is queued and replayed on the Streamlit caller thread. Pages are sorted before hierarchy construction and export. Provider calls share a document-scoped runtime limiter. Retryable failures use bounded jittered exponential backoff; HTTP 429 responses reduce effective concurrency and apply `Retry-After` or the configured cooldown.

## Ownership and recovery contract

| Data | Owner | Luna recovery may change it? |
| --- | --- | --- |
| Element ID | GLM/deterministic pipeline | No |
| Normalized bounding box | GLM | No |
| Type and structure | GLM/deterministic pipeline | No |
| Reading order | GLM/deterministic pipeline | No |
| OCR confidence | GLM | No |
| Existing element text | GLM initially | Yes, with a crop-backed confidence of at least `0.85` |
| Refined Markdown presentation | Deterministic renderer from Luna directives | Yes, without changing grounded text |
| Classification, TOC, extraction, chat | Luna plus deterministic validation | Feature-specific output only |

Luna additions, rejections, geometry changes, structural changes, and order changes are ignored. The default application never asks Luna to synthesize a missing GLM region or replace a full page. If at least one page is nonblank and none of the nonblank pages contains a GLM layout region, parsing fails before recovery. An isolated failed page remains in partial output with warnings.

Recovery candidates include OCR confidence below `0.55`, empty large regions, low character density, high garbage ratio, and weak table structure. Selection is document-wide and severity-ranked. Recovery is optional and unavailable without `OPENAI_API_KEY`.

## Agentic layer

`DocumentAgent.prepare` builds compact Markdown/layout contexts from non-rejected elements. Each context is limited to 48,000 characters and eight pages; additional contexts cover the rest of a long document. Classification uses the first two pages. TOC and scalar extraction iterate all contexts. Classification and TOC run concurrently and fail independently; TOC failure falls back to grounded GLM headings.

Markdown presentation directives may select source, heading, paragraph, list-item, or caption rendering and may set heading level, list depth, or grouping. They contain no replacement document text and cannot modify canonical element order or geometry.

Scalar extraction can run per context and merge the highest-confidence results; equal-rank conflicts are arbitrated over the implicated pages. Nested object/array schemas supported by the direct Python API use one direct extraction path and do not receive this per-context scalar merge. Every accepted field resolves to an existing block/atom. Invalid or missing evidence triggers one semantic repair; unresolved leaves become `null`/`not_found`, while on-demand agent extraction may expose a nearest cited region as `inferred`.

Optional custom routing classifies grounded text/layout into contiguous form page ranges using a reusable profile. Long inputs use bounded windows with a boundary-page overlap. Invalid coverage, categories, or element citations receive one repair attempt; unresolved failures block extraction. Low-confidence or boundary-merged segments require review. Approved eligible ranges are converted to in-memory parse subsets that retain original page numbers, element IDs, and bounding boxes before their assigned schemas run sequentially.

Chat sends the full prepared context when it fits. For long documents it deterministically retrieves up to 40 relevant elements plus neighbors. Only citations to known element IDs are exposed; an uncited answer receives low confidence.

All text-only structured features use medium reasoning effort and retry one schema-invalid response. Visual recovery uses original-detail crops and high reasoning effort. Requests set `store=False`.

## Result contracts

`DocumentParser.parse` returns `ParseResult` with `document`, refined `markdown`, grounded `base_markdown`, parse JSON, elements, annotated PDF bytes, usage, trace, metadata, and recovery log.

Parse JSON remains schema version `4.4.0`. Full JSON is `4.5.0`, preserving the existing envelope and adding `custom_classification` and `form_extractions`. Legacy extraction JSON remains `1.1.0`; routed multi-form extraction JSON uses `2.0.0`.

Markdown source spans target `base_markdown`, not presentation-refined Markdown. Normalized boxes always remain GLM-owned.

## Evaluation boundary

`scripts/evaluate_corpus.py` performs opt-in live evaluation. `--glm-only` disables Luna recovery, refinement, and extraction, verifies zero Luna activity, and can write Markdown, parse JSON, and run-provenance artifacts with `--artifacts-dir`. Annotation schema v1.1 distinguishes `source_verified`, `synthetic_exact`, and `generated` references. Markdown references are scored as content after presentation syntax is removed. Generated references are diagnostics rather than primary accuracy evidence. The bundled corpus is a regression suite and does not establish equivalence with ADE, LandingAI, or another external benchmark.
