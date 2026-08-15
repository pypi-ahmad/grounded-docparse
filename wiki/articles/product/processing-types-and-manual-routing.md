---
tags: routing, ui, cli, processing-types
sources: src/grounded_docparse/native.py, streamlit_app.py, src/grounded_docparse/cli.py
snapshot: content-988eedb6f7e0
status: released
---

# Processing types and manual routing

`ProcessingType` defines nine user-selectable modes: native PDF, scanned PDF, mixed PDF, Word, PowerPoint, Excel, CSV, image, and other native. The file extension narrows which choices are legal, while signature and container checks verify that the selected mode matches the uploaded content.

The selection is authoritative. Batch uploads carry one independent selection per file, the CLI receives a matching `--processing-type`, and dispatch reaches exactly one top-level pipeline. There is no automatic reinterpretation after validation fails.

Mixed PDF is the one reviewed routing mode: PDF Inspector suggests native or OCR per page, and the user may override those page routes before processing. See [[mixed-pdf-pipeline]], [[streamlit-workflow]], and [[cli-and-python-api]].

## Evidence

The enum and validation models are defined in `src/grounded_docparse/native.py`; UI and CLI propagation are implemented in `streamlit_app.py` and `src/grounded_docparse/cli.py`.
