# Design basis

The current design follows a parse-then-reason split: a local visual parser establishes the evidence geometry, then optional model calls operate on selected crops or compact structured context. The repository does not call or reproduce ADE, LandingAI, or LlamaParse.

The accuracy strategy is intentionally bounded:

- rasterize every page and ignore selectable PDF text;
- use GLM-OCR/PP-DocLayout for every element, box, and reading-order decision;
- rank weak existing regions with deterministic quality signals;
- send only selected crops to Luna for medium-effort visual recovery;
- accept only high-confidence text corrections while preserving GLM structure;
- constrain document features with typed Structured Outputs and deterministic citation checks; and
- retain unresolved evidence as `needs_review` or `not_found` instead of inventing content.

Markdown refinement is presentation-only. Luna returns directives keyed by existing elements, and deterministic code renders them. Extraction and chat operate on Markdown plus a compact layout tree; returned element IDs are validated before the UI can highlight them.

OpenAI requests set `store=False` and omit application-supplied prompt-cache controls. The UI may reuse a successful parse within the current Streamlit session, but there is no durable or cross-session result cache. Reusable scalar schemas are the only intentional application-managed persistence.

Automated tests use synthetic documents and fake gateways. Live evaluation is opt-in. The bundled corpus and the targeted crop experiment in [extraction quality research](extraction-quality-research.md) are regression evidence, not broad accuracy, throughput, cost, or external-product-equivalence claims.
