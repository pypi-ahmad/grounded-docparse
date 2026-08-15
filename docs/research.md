# Design basis

The current design follows a parse-then-reason split: a local visual parser establishes the evidence geometry, then optional model calls operate on selected crops or compact structured context. The repository does not call or reproduce ADE, LandingAI, or LlamaParse.

The accuracy strategy is intentionally bounded.

For scanned PDFs, images, and Mixed PDF OCR pages:

- rasterize those pages and ignore selectable PDF text on the OCR route;
- use the selected grounded local engine for every element, box, and reading-order decision;
- rank weak existing regions with deterministic quality signals;
- send only selected crops to the selected AI provider for bounded visual recovery; and
- accept only high-confidence text corrections while preserving local OCR structure.

For Native PDF, Mixed PDF native pages, and Docling formats:

- keep original structure as the evidence owner;
- freeze immutable `base_text` plus character spans and `SourceAnchor` records;
- disable Docling OCR, VLM/model enrichments, remote services, and plugins; and
- accept native extraction only through exact `char_interval` values that resolve to source anchors.

Across both families:

- constrain document features with typed Structured Outputs and deterministic citation checks; and
- retain unresolved evidence as `needs_review` or `not_found` instead of inventing content.

Markdown refinement is presentation-only. The selected AI provider returns directives keyed by existing elements, and deterministic code renders them. Extraction and chat operate on Markdown plus a compact layout tree; returned element IDs are validated before the UI can highlight them.

OpenAI requests set `store=False` and omit application-supplied prompt-cache controls. The UI restores the active batch workspace after restart: sources, parse checkpoints, analyses, settings, and usage persist in SQLite plus sibling `workspaces/` artifacts. Reusable schemas and routing profiles persist in the same database. Extraction, routing review, and chat remain session-only.

Automated tests use synthetic documents and fake gateways. Live evaluation is opt-in. The bundled corpus and the targeted crop experiment in [extraction quality research](extraction-quality-research.md) are regression evidence, not broad accuracy, throughput, cost, or external-product-equivalence claims.
