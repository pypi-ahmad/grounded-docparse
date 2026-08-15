---
tags: pdf, native, pdf-inspector
sources: src/grounded_docparse/native_parsers.py, src/grounded_docparse/native.py, docs/spec.md
snapshot: content-ee679d72076c
status: released
---

# Native PDF pipeline

Native PDF processing uses `PdfInspectorParser` to extract selectable text, layout items, tables, page positions, and bounding boxes without OCR. The parser constructs a `NativeDocument` whose evidence remains tied to PDF page anchors.

All selected pages must be usable as native evidence. If inspection identifies unusable pages, processing stops and recommends Mixed PDF rather than silently rasterizing or calling an OCR engine. This makes the manual processing choice observable and preserves a single-pipeline contract.

See [[mixed-pdf-pipeline]], [[native-document-model]], and [[source-anchors-and-character-spans]].

## Evidence

`PdfInspectorParser.parse` and its PDF subsetting adapter are implemented in `src/grounded_docparse/native_parsers.py`; the evidence contracts are in `src/grounded_docparse/native.py`.
