# How it works

1. The upload is size/page limited and rendered locally.
2. Pages are scheduled in ordered windows of 16, with up to 8 isolated page workers by default.
3. GLM-OCR drafts ordered typed regions and atomic evidence.
4. One Luna evidence-critic pass inspects risky targets directly. Deterministic code validates corrections, additions, coordinates, ordering, and evidence.
6. Completed pages are restored to source order before cross-page hierarchy, usage, traces, and exports are finalized.
7. When enabled, a text-only Luna pass returns presentation directives keyed by accepted element IDs. Deterministic rendering produces refined Markdown while grounding continues to target `base_markdown`.
8. Classification and hierarchical TOC generation run concurrently over compact text/layout context and use strict structured outputs.
9. Extraction runs on demand from a SQLite-backed schema. Exact and normalized matches are grounded directly; unmatched but cited values are visibly marked `inferred`; absent values remain `null`.
10. The prepared Markdown/layout context is reused by document-level features. Optional Chat sends full context for small documents or deterministically retrieved grounded blocks for long documents. Returned source IDs are validated before the UI exposes highlighting.
11. Structured Luna calls retry one schema-invalid response. Extraction separately gets one semantic grounding repair, then deterministic inferred grounding or `not_found`.
12. The app emits Markdown, full JSON, extraction JSON when available, actual token totals, and an annotated PDF labeled with stable block IDs.

The document-level features use bounded structured model calls; parsing itself has no open-ended autonomous loop.
