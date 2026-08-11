# How it works

1. The app validates the extension, bytes, upload size, page count, and per-page pixel count.
2. Every PDF page or image frame is rasterized locally. Selectable PDF text is ignored.
3. The selected local engine runs layout and recognition. GLM-OCR uses ordered 16-page windows with up to eight page workers; PaddleOCR-VL submits the full document to its local API.
4. Deterministic quality analysis scores local OCR regions using confidence, text density, garbage ratio, empty-region area, and table structure.
5. With GLM selected, local recovery first reprocesses every eligible form region, capped at three per page. With either engine, enabled and credentialed Luna recovery receives an independent medium-effort crop budget that scales from eight to 64 with document length and remains capped at three per page.
6. Deterministic code accepts only crop-backed text corrections with confidence at least `0.85`. It ignores Luna additions, rejections, geometry, types, confidence, order, and structure.
7. Completed pages return to source order. The pipeline builds hierarchy, quality state, normalized elements, grounded `base_markdown`, JSON v4.5.0, and an annotated PDF.
8. When enabled, text-only Luna returns presentation directives keyed by existing IDs. Deterministic rendering creates refined Markdown; grounding still targets `base_markdown`.
9. Classification and hierarchical TOC generation run concurrently. Classification uses recognized Markdown/layout from the first two pages; TOC generation traverses every compact document context. A failed TOC call falls back to grounded headings; either feature can fail without losing parse output.
10. Extraction runs on demand from a saved or imported scalar schema. Exact and normalized matches are grounded directly, cited approximations are marked `inferred`, and absent values remain `null`/`not_found`.
11. Optional chat reuses prepared context. Long-document questions use deterministic element retrieval, and returned citations are filtered to known IDs before source highlighting is exposed.
12. Structured Luna calls retry one schema-invalid response. Extraction additionally performs one evidence-repair call before deterministic fallback.
13. The app downloads Markdown, full JSON, extraction JSON when present, and the annotated PDF. Usage, latency, recovery provenance, and feature statuses are included in result metadata.

There is no open-ended autonomous loop. Local parsing remains usable without Luna, and every optional Luna failure is isolated from the core parse.
