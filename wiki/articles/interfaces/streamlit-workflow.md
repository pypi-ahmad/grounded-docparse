---
tags: streamlit, ui, workflow
sources: streamlit_app.py, src/grounded_docparse/native.py, src/grounded_docparse/config.py, src/grounded_docparse/usage_costs.py
snapshot: content-0117589c51ef
status: working-tree
---

# Streamlit workflow

The Streamlit application requires a processing-type selection for each uploaded file. Legal choices depend on the extension, and file validation decides whether the chosen mode is accepted.

For Mixed PDF, the application presents a page review table containing the suggested route and the user's selected route. Processing begins only after review, then native and OCR page results are merged in source order. Native results expose Markdown, JSON, and source-structure views; annotated PDF is optional when the source is not visual.

See [[processing-types-and-manual-routing]], [[mixed-pdf-pipeline]], and [[workspace-persistence-and-exports]].

## Current working-tree model and cost changes

The default GPT choice is **GPT 6 Sol** (`gpt-6-sol`) with medium reasoning. Obsolete session model selections reset to Sol. Other supported cloud-provider choices remain available.

The **Session cost** view shows input, cache-read, cache-write, and output tokens, plus estimated Standard cost per model and in total. Sol's rates are $2.00, $0.20, $2.50, and $10.00 per million tokens respectively. An individual request above 272,000 input tokens doubles input/cache rates and increases output rates by 50%. Calls marked as having unavailable telemetry are excluded with a warning. The ledger resets on app restart and does not constitute an invoice.

## Evidence

Upload state, per-file selectors, page-route review, and result presentation are implemented in `streamlit_app.py`; UI values use contracts from `src/grounded_docparse/native.py`.
