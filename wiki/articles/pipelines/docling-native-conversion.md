---
tags: docling, conversion, no-ocr
sources: src/grounded_docparse/docling_native.py, src/grounded_docparse/native_parsers.py
snapshot: content-7e6cbb56ddf0
status: released
---

# Docling native conversion

Docling supplies normalized document conversion, but source grounding is built from deterministic format-specific manifests. The adapter claims converted records against original paragraphs, shapes, sheets, cells, tables, or rows before emitting the common native model.

OCR, VLM processing, and model enrichments are disabled. This prevents Docling from introducing text that cannot be traced to native document structure. The outputs include Markdown, JSON, and a source-structure representation derived from the same grounded document.

See [[office-and-native-formats]], [[native-document-model]], and [[immutable-base-text]].

## Evidence

`build_source_manifest`, asset extraction, record claiming, and the converter factory are implemented in `src/grounded_docparse/docling_native.py`; orchestration is in `DoclingNativeParser`.
