---
tags: extension, formats, parser-development
sources: src/grounded_docparse/native.py, src/grounded_docparse/native_parsers.py, src/grounded_docparse/docling_native.py
snapshot: content-0efef1084957
status: feature-branch
---

# Adding a native format

A new native format requires an explicit source-format and processing-type mapping, signature or container validation, deterministic source-unit extraction, anchor creation, base-text assembly, and character-span coverage. It must then enter exactly one native parser path.

If Docling supports conversion, the adapter must still claim every converted block against the format's original structure. Embedded images remain assets unless a future product decision introduces a separately authorized OCR route.

See [[office-and-native-formats]], [[docling-native-conversion]], and [[source-anchors-and-character-spans]].

## Evidence

Enums and evidence contracts are in `src/grounded_docparse/native.py`; dispatch is in `src/grounded_docparse/native_parsers.py`; deterministic format readers are in `src/grounded_docparse/docling_native.py`.
