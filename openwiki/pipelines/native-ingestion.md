---
type: processing-pipeline
title: Native Document Ingestion
description: Explains how selectable PDFs and supported native formats become structured documents with source-linked spans and format-specific anchors.
tags: [native-ingestion, pdf, docling, source-anchors]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-e6c817cecab4cc45de19dd1a
    resource: repo://src/grounded_docparse/docling_native.py
  - id: openwiki-source-670784db7e4d0c72383edee4
    resource: repo://src/grounded_docparse/native_parsers.py
  - id: openwiki-source-af2de2797baedce528291e1d
    resource: repo://tests/test_content_range.py
  - id: openwiki-source-759f704579fd95847f95eb24
    resource: repo://tests/test_docling_native_parser.py
  - id: openwiki-source-43231eac8734bf67e74c990e
    resource: repo://tests/test_native_pdf_parser.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Native routes

Native ingestion uses `PdfInspectorParser` for PDFs and `DoclingNativeParser` for supported non-PDF formats. `UniversalDocumentParser` validates the caller's processing type before constructing either parser ([routing](../workflows/explicit-ingestion-and-routing.md)). The native result models, including their source units, spans, anchors, and JSON version, are defined separately from the OCR result model ([native contracts](../../src/grounded_docparse/native.py)).

## PDF Inspector and mixed PDFs

For a native PDF route, PDF Inspector extracts selectable text, positions, and structure. The parser fails if inspection or actual extraction marks a selected native page as requiring OCR; it does not silently switch that page to OCR. A mixed PDF instead uses the caller's reviewed page routes, sends only the OCR-selected pages through `DocumentParser`, then combines native and OCR page content in original page order into one native document ([PDF parser](../../src/grounded_docparse/native_parsers.py)). Tests cover the ordered merge, page-range indices, and rejection of an OCR-to-native override ([PDF parser tests](../../tests/test_native_pdf_parser.py)).

## Office and other native formats

For Word, PowerPoint, Excel, OpenDocument, HTML, EPUB, and other supported native formats, `DoclingNativeParser` builds a source manifest and converts with the project's configured native converter. The converter disables OCR and remote model features ([converter setup](../../src/grounded_docparse/docling_native.py)). The parser matches converted items to manifest records and raises on unclaimed content instead of silently dropping it ([parser](../../src/grounded_docparse/native_parsers.py)). CSV input has a deterministic manifest path, with row and column anchors; XLSX cells use sheet and cell-range anchors, while text formats use line and column locations ([manifest builders](../../src/grounded_docparse/docling_native.py), [anchor models](../../src/grounded_docparse/native.py)).

Content ranges use natural units where available: PDF pages, image frames, CSV rows, slides, sheets, EPUB sections, or generic blocks. CSV ranges are applied before conversion and their anchors are mapped back to original row numbers ([range handling](../../src/grounded_docparse/universal.py), [Docling range handling](../../src/grounded_docparse/native_parsers.py)). Focused tests exercise DOCX structure, PPTX shapes, XLSX formulas and cells, CSV rows, HTML assets, EPUB sections, and Markdown line anchors ([native parser tests](../../tests/test_docling_native_parser.py), [range tests](../../tests/test_content_range.py)).

Native source spans and extraction acceptance rules are described in [source grounding](../evidence/source-grounding.md). Native and OCR output versions remain separate contracts.
