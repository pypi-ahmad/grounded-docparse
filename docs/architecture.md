# Architecture

## System boundary

The application is one synchronous native-Windows Streamlit process with explicit per-file routing and six mutually exclusive extraction engines. GLM-OCR and PaddleOCR-VL keep their existing WSL vLLM services; Ollama, CPU PP-DocLayoutV3, Docling/RapidOCR, and PDF Inspector run on Windows. There is no HTTP application API, queue, worker service, production job service, remote artifact store, or multi-user authentication layer.

```text
Browser
  -> Streamlit (`streamlit_app.py`)
     -> required processing-type selection and signature/container validation
     -> scanned PDF/image: rasterization -> selected extraction engine
        -> Windows CPU PP-DocLayoutV3 -> GLM vLLM (port 8080) or Windows Ollama
        -> PaddleX API (port 8119) -> PaddleOCR-VL vLLM (port 8118)
        -> Docling + RapidOCR, or direct AI ADE extraction
     -> native PDF: `pdf-inspector` text/layout/table positions
     -> mixed PDF: confirmed per-page native/OCR merge
     -> Office/open formats: Docling SimplePipeline without OCR or enrichments
     -> immutable native source spans or OCR elements
     -> optional selected-provider enhancement and LangExtract features
  -> downloads and source highlighting
```

## Repository map

| Path | Responsibility |
| --- | --- |
| `Launch-Grounded-DocParse.cmd` / `scripts/windows/` | Native Windows setup, launch, and process lifecycle |
| `Setup-GLM-OCR.cmd` / `Setup-PaddleOCR-VL-1.6.cmd` | WSL GPU-service provisioning and warmup |
| `streamlit_app.py` | Batch upload, engine selection, modes, progress, tabs, schema UI, chat, downloads |
| `src/grounded_docparse/batch.py` | Upload limits, stable document identity, and batch archive records |
| `src/grounded_docparse/cli.py` | Installed synchronous batch parsing, schema loading, manifests, and filesystem outputs |
| `src/grounded_docparse/universal.py` | Signature/container validation and manual route selection |
| `src/grounded_docparse/native.py` | Native processing types, source anchors/spans, and JSON v5 contracts |
| `src/grounded_docparse/native_parsers.py` / `docling_native.py` | `pdf-inspector` and OCR-disabled Docling adapters |
| `src/grounded_docparse/workspace_store.py` | Durable active-batch metadata, parse checkpoints, progress, and local artifacts |
| `src/grounded_docparse/__init__.py` | Package-root public exports |
| `src/grounded_docparse/config.py` | Engine/model enums, parser thresholds, endpoints, and environment parsing |
| `src/grounded_docparse/ingest.py` | Input validation, PDF/image rasterization, region rerendering |
| `src/grounded_docparse/grounded_ocr.py` | CPU PP-DocLayoutV3 detection and crop-grounded GLM/Ollama recognition |
| `src/grounded_docparse/ollama_runtime.py` | Ollama model lifecycle and region recognition |
| `src/grounded_docparse/paddle_ocr.py` | PaddleX document-parser client and result normalization |
| `src/grounded_docparse/page_analysis.py` | Page quality signals and selected-engine region conversion |
| `src/grounded_docparse/quality.py` | Deterministic block quality, verification, and document quality aggregation |
| `src/grounded_docparse/pipeline.py` | Parse orchestration, recovery selection, deterministic validation, hierarchy |
| `src/grounded_docparse/gateways.py` | OpenAI, Gemini, and Agnes gateway selection, usage, and trace collection |
| `src/grounded_docparse/prompts.py` | Versioned prompt templates for provider-neutral AI document features |
| `src/grounded_docparse/enhancement.py` | Bounded Markdown-refinement chunks and presentation-plan application |
| `src/grounded_docparse/agentic.py` | Prepared contexts, classification, TOC, extraction orchestration, chat |
| `src/grounded_docparse/extraction.py` | JSON Schema subset validation and evidence resolution |
| `src/grounded_docparse/native_extraction.py` | LangExtract over immutable `base_text` with fail-closed source-span grounding |
| `src/grounded_docparse/models.py` | Pydantic domain contracts, API result records, progress events, diagnostics |
| `src/grounded_docparse/schema_store.py` | SQLite schema/profile CRUD, Markdown import, and UI-schema compilation |
| `src/grounded_docparse/render.py` | OCR Markdown, JSON v4.5 parse/v4.6 full results, elements, quality, and annotations |
| `src/grounded_docparse/runtime.py` | Provider concurrency, retries, cooldown, usage, diagnostics |
| `src/grounded_docparse/benchmark.py` | Corpus contracts and evaluation metrics |
| `config/glmocr.yaml` | Source GLM-OCR SDK, layout, recognition, and formatter configuration |
| `config/paddle-vllm.yaml` | PaddleOCR-VL vLLM serving configuration |
| `scripts/wsl/prepare_glmocr_runtime.py` | Pinned model resolution and generated offline SDK configuration |
| `scripts/wsl/*.sh` | Locked WSL environment setup, vLLM serving, Streamlit launch, health checks |
| `scripts/evaluate_corpus.py` | Opt-in live/offline corpus evaluation and artifact export |

## Parse pipeline

```text
1. Require a compatible `ProcessingType` for each file and validate its extension, bytes, signature, and container structure.
2. Route exactly once: scanned PDF/image to OCR; Native PDF to `pdf-inspector`; Mixed PDF to confirmed Native/OCR page routes; Office/open formats to Docling.
3. For OCR routes, render pages, parse with the selected local engine, rank recovery candidates, and apply only high-confidence crop-backed text corrections to existing elements.
4. For Native PDF, stop if an unusable page requires Mixed PDF. For Mixed PDF, merge native and OCR pages in original order.
5. For Docling formats, build source manifests, convert with remote services/plugins/OCR/VLM enrichments disabled, and fail if the converter cannot claim every source block.
6. Materialize OCR elements or native immutable `base_text`, source units, character spans, and anchors; render Markdown, JSON, and an annotated PDF only when visual output exists.
7. Optionally run refinement, classification, TOC, extraction, and chat. Native LangExtract receives `base_text` only and returns accepted values only through exact anchored intervals.
```

Worker progress is queued and replayed on the Streamlit caller thread. Pages are sorted before hierarchy construction and export. Provider calls share a document-scoped runtime limiter. Retryable failures use bounded jittered exponential backoff; HTTP 429 responses reduce effective concurrency and apply `Retry-After` or the configured cooldown.

## Ownership and recovery contract

| Data | Owner | AI enhancement may change it? |
| --- | --- | --- |
| Element ID | Local OCR/deterministic pipeline | No |
| Normalized bounding box | Local OCR | No |
| Type and structure | Local OCR/deterministic pipeline | No |
| Reading order | Local OCR/deterministic pipeline | No |
| OCR confidence | Local OCR | No |
| Existing element text | Grounded engine initially | Yes, only for failed or sub-75%-confidence candidates passing response validation |
| Refined Markdown presentation | Deterministic renderer from selected-provider directives | Yes, without changing grounded text |
| Classification, TOC, extraction, chat | Selected AI model plus deterministic validation; classification/TOC retain an OpenAI-key compatibility preflight | Feature-specific output only |

AI additions, geometry changes, structural changes, and order changes are ignored. Enhancement never synthesizes a missing detector region or replaces a full page. If at least one page is nonblank and none of the nonblank pages contains a layout region, grounded parsing fails before enhancement.

The UI's AI-enhancement phase considers recognition failures and confidence below `0.75`. It is optional and unavailable without the key required by the selected cloud model.

## Agentic layer

`DocumentAgent.prepare` builds compact Markdown/layout contexts from non-rejected elements. Each context is limited to 48,000 characters and eight pages; additional contexts cover the rest of a long document. Classification uses the first two pages. TOC and scalar extraction iterate all contexts. Classification and TOC run concurrently and fail independently; TOC failure falls back to grounded local OCR headings.

Markdown presentation directives may select source, heading, paragraph, list-item, or caption rendering and may set heading level, list depth, or grouping. They contain no replacement document text and cannot modify canonical element order or geometry.

Scalar extraction can run per context and merge the highest-confidence results; equal-rank conflicts are arbitrated over the implicated pages. Nested object/array schemas supported by the direct Python API use one direct extraction path and do not receive this per-context scalar merge. Every accepted field resolves to an existing block/atom. Invalid or missing evidence triggers one semantic repair; unresolved leaves become `null`/`not_found`, while on-demand agent extraction may expose a nearest cited region as `inferred`.

Optional custom routing classifies grounded text/layout into contiguous form page ranges using a reusable profile. Long inputs use bounded windows with a boundary-page overlap. Invalid coverage, categories, or element citations receive one repair attempt; unresolved failures block extraction. Low-confidence or boundary-merged segments require review. After all ranges are approved, every segment can be downloaded in a dedicated ZIP as a source-page PDF, Markdown, and canonical document JSON with a routing manifest. Approved eligible ranges are also converted to in-memory parse subsets that retain original page numbers, element IDs, and bounding boxes before their assigned schemas run sequentially.

Chat sends the full prepared context when it fits. For long documents it deterministically retrieves up to 40 relevant elements plus neighbors. Only citations to known element IDs are exposed; an uncited answer receives low confidence.

All text-only structured features use medium reasoning effort and retry one schema-invalid response. Visual recovery uses original-detail crops and high reasoning effort. Requests set `store=False`.

## Result contracts

`DocumentParser.parse` returns the legacy OCR `ParseResult` with `document`, refined `markdown`, grounded `base_markdown`, parse JSON, elements, annotated PDF bytes, usage, trace, metadata, and recovery log. `UniversalDocumentParser.parse` accepts an explicit `ProcessingType` and returns either that OCR result or a `NativeParseResult`.

Parse JSON schema version is `4.5.0`. Full JSON is `4.6.0`, preserving the existing envelope and adding `custom_classification` and `form_extractions`. Legacy extraction JSON remains `1.1.0`; routed multi-form extraction JSON uses `2.0.0`.

Markdown source spans target `base_markdown`, not presentation-refined Markdown. Normalized boxes remain owned by the selected grounded engine.

Native JSON is schema version `5.0.0`; combined native/extraction JSON is `5.1.0`. Its canonical evidence is frozen `base_text`, with Unicode-codepoint source spans resolving to `SourceAnchor` values. Native nonvisual results do not contain annotated-PDF bytes.

## Evaluation boundary

`scripts/evaluate_corpus.py` performs opt-in live evaluation. `--glm-only` disables AI recovery, refinement, and extraction, verifies zero AI-provider activity, and can write Markdown, parse JSON, and run-provenance artifacts with `--artifacts-dir`. Annotation schema v1.1 distinguishes `source_verified`, `synthetic_exact`, and `generated` references. Markdown references are scored as content after presentation syntax is removed. Generated references are diagnostics rather than primary accuracy evidence. The bundled corpus is a regression suite and does not establish equivalence with ADE, LandingAI, or another external benchmark.

Labeled private manifests may add `expected_document_type`. Full live evaluation
runs classification only for labeled documents, reports type accuracy,
calibration, confidence-based review rates, and OCR block review rates, and can
apply JSON regression policies with absolute and baseline-relative limits. The
private calibration and locked holdout sets remain outside the repository.
