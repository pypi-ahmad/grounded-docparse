---
tags: product, scope, formats
sources: docs/spec.md, README.md
snapshot: content-0efef1084957
status: feature-branch
---

# Product capabilities and boundaries

The feature accepts manually classified native PDFs, scanned PDFs, mixed PDFs, Office documents, spreadsheets, CSV, images, and other selected native formats. It preserves the existing OCR behavior while adding source-traceable native extraction and grounded schema extraction.

The first native release deliberately excludes OCR inside PDF Inspector, Docling, and LangExtract. Embedded images in native documents are recorded as assets but are not recognized. Invalid file-signature or selected-mode combinations stop with an error instead of silently switching pipelines.

These boundaries prevent convenience features from weakening traceability. See [[office-and-native-formats]], [[ocr-quality-and-recovery]], and [[security-privacy-and-trust-boundaries]].

## Evidence

Supported inputs, non-goals, and completion criteria are specified in `docs/spec.md`; the user-facing behavior is summarized in `README.md`.
