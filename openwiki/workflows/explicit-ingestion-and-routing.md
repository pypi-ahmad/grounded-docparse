---
type: user-workflow
title: Explicit Ingestion and Routing
description: Shows how the UI and CLI validate input formats, require a processing type, apply ranges and mixed-PDF routes, and write results.
tags: [ingestion, routing, cli, content-ranges]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-f88169d5eb439e5b0cae3d3b
    resource: repo://src/grounded_docparse/cli.py
  - id: openwiki-source-64f036a0fdbfaf2d9c3edc38
    resource: repo://src/grounded_docparse/universal.py
  - id: openwiki-source-9ec6473d05fcc2cd40915af2
    resource: repo://tests/test_cli.py
  - id: openwiki-source-af2de2797baedce528291e1d
    resource: repo://tests/test_content_range.py
  - id: openwiki-source-6d98d900dbe919c220210d2e
    resource: repo://tests/test_universal_parser.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Choose the route

The caller selects a `ProcessingType` for each document. The router checks the file signature or container against its extension, then verifies that the selected type is compatible with the detected format ([format detection and compatibility](../../src/grounded_docparse/universal.py)). Supported routes include native, scanned, and mixed PDFs; images; and native Word, PowerPoint, Excel, CSV, and other formats ([processing types](../../src/grounded_docparse/native.py)).

For scanned PDFs and images, the router delegates to the OCR pipeline. Native PDFs go through PDF inspection and native extraction. A native PDF selection fails if any selected page needs OCR; it does not silently fall back. Mixed PDFs require one explicit native or OCR choice for every selected page. The PDF parser uses those choices to assemble a page-ordered result ([PDF route validation](../../src/grounded_docparse/universal.py), [PDF parser](../../src/grounded_docparse/native_parsers.py)). See [grounded OCR](../pipelines/grounded-ocr.md) and [native ingestion](../pipelines/native-ingestion.md) for those routes.

## CLI batch flow

Use `grounded-docparse ingest` for manually classified native and OCR inputs. Supply one `--processing-type PATH=TYPE` entry for each input; for mixed PDFs, add `--page-route PATH#PAGE=ROUTE` values. The CLI rejects missing, duplicate, or unused type assignments, discovers supported files in supplied directories, and writes each successful document's Markdown and full JSON under a hash-named folder plus a batch manifest. A failed document is recorded in the manifest and does not stop later files in the batch ([CLI](../../src/grounded_docparse/cli.py)). Tests cover required assignments, output behavior, and continuing after a document failure ([CLI tests](../../tests/test_cli.py)).

The legacy `grounded-docparse parse` command remains the simpler PDF/image OCR path. The Python API exposes `UniversalDocumentParser` for callers that need the explicit native and OCR routes.

## Ranges and batch limits

`ContentRange` is resolved against the input's natural unit: PDF page, image page or TIFF frame, CSV row, slide, sheet, EPUB section, or generic native block ([range inspection](../../src/grounded_docparse/universal.py)). The parser carries original source indices through a selected range; tests check page-range validation and original page numbering ([range tests](../../tests/test_content_range.py)).

Streamlit upload batches have file-count and combined-size limits and preserve duplicate uploads as distinct documents ([batch builder](../../src/grounded_docparse/batch.py)). See [studio persistence](../interfaces/studio-and-workspace.md) for progress, review, and restart behavior.
