---
tags: streamlit, ui, workflow
sources: streamlit_app.py, src/grounded_docparse/native.py
snapshot: content-6684c0091b62
status: feature-branch
---

# Streamlit workflow

The Streamlit application requires a processing-type selection for each uploaded file. Legal choices depend on the extension, but file validation—not extension guessing—decides whether the chosen mode is accepted.

For Mixed PDF, the application presents a page review table containing the suggested route and the user's selected route. Processing begins only after review, then native and OCR page results are merged in source order. Native results expose Markdown, JSON, and source-structure views; annotated PDF is optional when the source is not visual.

See [[processing-types-and-manual-routing]], [[mixed-pdf-pipeline]], and [[workspace-persistence-and-exports]].

## Evidence

Upload state, per-file selectors, page-route review, and result presentation are implemented in `streamlit_app.py`; UI values use contracts from `src/grounded_docparse/native.py`.
