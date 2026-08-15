---
tags: docx, pptx, xlsx, csv, native
sources: src/grounded_docparse/docling_native.py, src/grounded_docparse/native_parsers.py, docs/spec.md
snapshot: content-a3c6bf27aca5
status: released
---

# Office and native formats

The native-document path supports DOCX, PPTX, XLSX, CSV, HTML, EPUB, Markdown, and selected OpenDocument formats. PDFs and standalone images are excluded from Docling dispatch because they have dedicated processing modes.

Container signatures and internal structure are validated before conversion. Paragraphs, slides, shapes, sheets, cells, tables, rows, and columns become source units and anchors. Embedded media is recorded as assets but is not OCRed.

See [[docling-native-conversion]], [[source-anchors-and-character-spans]], and [[product-capabilities-and-boundaries]].

## Evidence

Format-specific source manifests are built in `src/grounded_docparse/docling_native.py`; top-level dispatch and mode enforcement are implemented in `src/grounded_docparse/native_parsers.py`.
