---
type: processing-pipeline
title: Grounded OCR Pipeline
description: Traces scanned PDFs and images from bounded page rendering through layout detection, region recognition, document assembly, and optional review.
tags: [ocr, pipeline, layout, recovery]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-54411f24a6eecf31adece354
    resource: repo://src/grounded_docparse/grounded_ocr.py
  - id: openwiki-source-83737120952115ec6f38de20
    resource: repo://src/grounded_docparse/pipeline.py
  - id: openwiki-source-5f5abbeb9cde3900e1c9ba9f
    resource: repo://tests/test_grounded_ocr.py
  - id: openwiki-source-56d8c52e6f51d992b503004a
    resource: repo://tests/test_strict_recovery_contract.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Processing path

Scanned PDFs and images enter `DocumentParser`. `ingest_document` validates the upload's bytes, extension, size, page count, and rendered-pixel limits, then writes the selected PDF pages or image frames into a temporary work directory ([ingestion](../../src/grounded_docparse/ingest.py)). Selectable PDFs and other native formats use different paths; see [explicit routing](../workflows/explicit-ingestion-and-routing.md).

For local OCR, `DocumentParser.parse` processes pages in configured batches and asks `PageAnalyzer` to analyze each batch. The analyzer chooses a runtime for the configured OCR engine, while `GroundedOcrRuntime` uses the layout detector to establish regions and then gives the recognizer crops from those detector-owned boxes ([page analysis](../../src/grounded_docparse/page_analysis.py), [grounded OCR runtime](../../src/grounded_docparse/grounded_ocr.py)). The recognized region content is assembled into typed blocks with page number, reading order, bounding box, confidence, and citation metadata ([block assembly](../../src/grounded_docparse/pipeline.py)).

## Failure and recovery behavior

A recognizer exception marks that region as failed and leaves the other regions eligible for processing, unless the recognizer explicitly sets `fail_fast`. A detector or page-level exception becomes an `OcrPageResult` with an error for that page ([runtime failure handling](../../src/grounded_docparse/grounded_ocr.py)). If every nonblank page has no usable local OCR regions, `DocumentParser` raises instead of returning an empty successful parse ([document check](../../src/grounded_docparse/pipeline.py)). Tests verify preserved detector boxes and confidence, region-level failure state, and rejection of an all-empty nonblank OCR result ([runtime tests](../../tests/test_grounded_ocr.py), [pipeline tests](../../tests/test_strict_recovery_contract.py)).

Optional visual recovery is limited to existing regions. A correction can replace text after evidence and confidence checks; it cannot add a missing region, move its box, or reorder the page. Rejected or insufficiently confident corrections preserve the primary text and mark it for review ([recovery tests](../../tests/test_strict_recovery_contract.py)).

Progress reports layout and recognition stages as well as document stages. For local OCR requests, see [runtime configuration](../operations/runtimes-and-configuration.md). For the distinct native span model and accepted extraction rules, see [source grounding](../evidence/source-grounding.md).
