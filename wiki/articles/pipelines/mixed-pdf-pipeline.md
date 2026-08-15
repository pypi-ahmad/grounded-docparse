---
tags: pdf, mixed, page-routing
sources: src/grounded_docparse/native_parsers.py, src/grounded_docparse/native.py, streamlit_app.py
snapshot: content-ee679d72076c
status: released
---

# Mixed PDF pipeline

Mixed PDF mode handles documents containing both usable native pages and pages that require OCR. PDF Inspector proposes a route for each page, the UI displays those suggestions, and the user confirms or overrides every route before execution.

Native pages are parsed through PDF Inspector; OCR pages are sent through the unchanged visual pipeline. Page results are merged by original one-based page number so output ordering cannot depend on completion order or routing group.

There is no silent fallback between page routes. A failure remains attached to its selected route and page. See [[native-pdf-pipeline]], [[scanned-pdf-and-image-pipeline]], and [[streamlit-workflow]].

## Evidence

Page route values and mixed-result contracts are defined in `src/grounded_docparse/native.py`; inspection and parsing live in `src/grounded_docparse/native_parsers.py`; review controls live in `streamlit_app.py`.
