# Product specification

## Goal

Parse PDFs and images into grounded Markdown, structured JSON, and annotated PDFs through a selectable local OCR workflow, with optional bounded Luna recovery and document reasoning.

## Inputs

- Up to 20 PDFs, PNGs, JPEGs, or TIFFs; 250 MB per file and 1 GB combined
- Optional inclusive contiguous PDF page range when exactly one PDF is uploaded
- Optional Luna feature toggles
- Optional reusable scalar extraction schemas and custom form-routing profiles
- Optional document-chat questions after parsing

## Required behavior

- Render PDFs visually and never treat selectable PDF text as evidence.
- Use the selected GLM-OCR or PaddleOCR-VL-1.6 engine as the source of layout, identity, geometry, type, confidence, and reading order.
- Process ordered 16-page windows with up to eight page workers by default.
- When GLM-OCR is selected, reprocess every eligible form region with local GLM first, capped at three crops per page.
- Detect weak existing local OCR regions deterministically and assign Luna an independent budget that scales from eight crops to the configured ceiling of 64 based on document length, capped at three per page.
- Use medium Luna effort for every request and apply only image-recovery text corrections with confidence at least `0.85`.
- Ignore Luna additions, rejections, geometry changes, order changes, type changes, confidence changes, and structural changes.
- Stop before Luna when at least one page is nonblank and none of the nonblank pages contains a local OCR layout region; preserve isolated page failures as partial output with warnings.
- Optionally refine Markdown through presentation directives keyed by existing elements.
- Optionally classify the document and generate a hierarchical, source-linked TOC.
- Run extraction on demand with a strict nullable JSON Schema subset and existing-element evidence.
- Native v5 extraction uses immutable `base_text`, never refined Markdown, and accepts only exact `char_interval` values resolving to source anchors.
- Run chat on demand and expose only citations to known elements.
- Use strict Structured Outputs, one schema-format retry, `store=False`, and no application-supplied cache controls.
- Keep Fast as classification-only, Full as refinement/classification/TOC, and Custom as any other toggle combination.
- Keep visual recovery independently configurable and chat disabled by default.
- Provide Overview, Markdown, Annotated PDF, Extract, optional Chat, and Layout Tree tabs.
- Provide source highlighting from TOC, extraction, chat, page elements, and layout-tree selections.
- Emit parse JSON v4.5.0 with refined Markdown, grounded base Markdown, elements/provenance, page/block evidence, correction history, recovery and OCR-comparison logs, parse timing/usage/trace, and empty agentic placeholders.
- Emit Full JSON v4.6.0 with the same envelope plus optional custom classification and per-form extraction, combined usage/trace/timing, and feature statuses.
- Emit extraction JSON v1.1.0 with values, evidence, fields, `element_id`, source text, confidence, and local-OCR-owned normalized boxes.
- Keep annotated PDF bytes outside JSON and offer them as a separate download.
- Use SQLite only for intentional application-managed schema and routing-profile persistence; keep parse and routing results in temporary/process/session state.
- Process batch files sequentially, isolate per-file failures, skip unchanged completed files on rerun, and export a ZIP archive.
- Allow local-only parsing without `OPENAI_API_KEY`.

## Public interfaces

- Streamlit entry point: `streamlit_app.py`
- Parse API: `DocumentParser.parse(data, filename, progress_callback=None, *, refine_markdown=True, visual_recovery=True)`
- Prepared context: `DocumentAgent.prepare(parse_result)`
- Document analysis: `DocumentAgent.analyze(parse_result, *, classify=True, generate_toc=True, prepared_context=None)`
- Extraction: `DocumentAgent.extract(parse_result, schema, *, prepared_context=None)`
- Custom routing: `DocumentAgent.classify_forms(...)` and `DocumentAgent.extract_forms(...)`
- Chat: `DocumentAgent.chat(parse_result, question, history, *, prepared_context=None)`
- Direct schema proposal/extraction: `DocumentExtractor.propose_schema` and `DocumentExtractor.extract`
- Combined JSON: `render_combined_result(parse_result, analysis=None, extraction=None)`
- Evaluation entry point: `scripts/evaluate_corpus.py`

The project installs `grounded-docparse parse` for synchronous local batch parsing. It accepts explicit files or non-recursive directories, writes per-document artifacts plus a manifest, and optionally applies one JSON or Markdown extraction schema to every input. It is not a durable job service or worker queue.
Signatures, return-model summaries, schema rules, and envelope examples are in [the Python API reference](api.md). The repository does not publish a standalone JSON Schema for every nested v4.6.0 domain object.

## Non-goals

Document/chat persistence, durable jobs, queues, multi-user serving, an HTTP application API, open-ended agent loops, human-review storage, cost estimation, durable or cross-session result caching, full-page Luna fallback, missing-region synthesis, and production batch orchestration. Session-scoped sequential batch processing is in scope.

## Done when

- Public contract, routing, evidence, gateway, ingest, agentic, schema-store, and Streamlit tests pass.
- Ruff, compilation, Markdown link/fence checks, and `git diff --check` pass.
- No live paid request is required for automated verification.
- Documentation matches code paths, defaults, UI labels, and output versions.
