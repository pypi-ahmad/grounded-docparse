# How it works

1. The app validates the extension, bytes, upload size, page count, and per-page pixel count.
2. Every PDF page or image frame is rasterized locally. Selectable PDF text is ignored.
3. GLM-OCR runs layout and recognition in ordered windows of 16 pages. The process-wide SDK runtime serializes model access while the parser prepares and finalizes up to eight pages concurrently.
4. Deterministic quality analysis scores GLM regions using OCR confidence, text density, garbage ratio, empty-region area, and table structure.
5. When enabled and credentialed, the parser selects at most eight recovery crops per document and three per page. Luna inspects only those crops at high effort.
6. Deterministic code accepts only crop-backed text corrections with confidence at least `0.85`. It ignores Luna additions, rejections, geometry, types, confidence, order, and structure.
7. Completed pages return to source order. The pipeline builds hierarchy, quality state, normalized elements, grounded `base_markdown`, JSON v4.4.0, and an annotated PDF.
8. When enabled, text-only Luna returns presentation directives keyed by existing IDs. Deterministic rendering creates refined Markdown; grounding still targets `base_markdown`.
9. Classification and hierarchical TOC generation run concurrently. Classification uses recognized Markdown/layout from the first two pages; TOC generation traverses every compact document context. A failed TOC call falls back to grounded headings; either feature can fail without losing parse output.
10. Extraction runs on demand from a saved or imported scalar schema. Exact and normalized matches are grounded directly, cited approximations are marked `inferred`, and absent values remain `null`/`not_found`.
11. Optional chat reuses prepared context. Long-document questions use deterministic element retrieval, and returned citations are filtered to known IDs before source highlighting is exposed.
12. Structured Luna calls retry one schema-invalid response. Extraction additionally performs one evidence-repair call before deterministic fallback.
13. The app downloads Markdown, full JSON, extraction JSON when present, and the annotated PDF. Usage, latency, recovery provenance, and feature statuses are included in result metadata.

There is no open-ended autonomous loop. GLM parsing remains usable without Luna, and every optional Luna failure is isolated from the core parse.
