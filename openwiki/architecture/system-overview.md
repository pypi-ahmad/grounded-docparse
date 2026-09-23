---
type: architecture
title: System Overview and Boundaries
description: Shows how the public package, Streamlit studio, and CLI reach the processing router and its distinct OCR and native document paths.
tags: [architecture, entrypoints, routing, evidence]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-cac088b775d0e954b8cff6ec
    resource: repo://src/grounded_docparse/models.py
  - id: openwiki-source-e3904a2dee24b80010a9f39c
    resource: repo://src/grounded_docparse/native.py
  - id: openwiki-source-64f036a0fdbfaf2d9c3edc38
    resource: repo://src/grounded_docparse/universal.py
  - id: openwiki-source-328a73bba24dd28bfd898f4c
    resource: repo://tests/test_native_models.py
  - id: openwiki-source-6d98d900dbe919c220210d2e
    resource: repo://tests/test_universal_parser.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# System overview

Grounded DocParse is a Python package used through three entrypoints: the Streamlit studio, the `grounded-docparse` command, and the curated library API. The package exports the public parsers, document agents, models, and result types; internal helpers remain private ([public surface](../../src/grounded_docparse/__init__.py), [CLI registration](../../pyproject.toml)).

The central router is `UniversalDocumentParser`. Callers provide a `ProcessingType`; the router checks the upload size, detects its source format, validates that the selected type is compatible, and dispatches to the OCR parser, PDF Inspector, or native Docling parser. PDF routes are inspected before parsing, and the native parsers are imported lazily so users of other formats do not need those optional dependencies ([router](../../src/grounded_docparse/universal.py)). The route behavior is covered by tests for scanned delegation, native PDF dispatch, mismatch rejection, and mixed-PDF requirements ([routing tests](../../tests/test_universal_parser.py)).

The two result families preserve different evidence. Grounded OCR represents page content as ordered elements with layout and recognition metadata ([OCR models](../../src/grounded_docparse/models.py)). Native parsing keeps immutable `base_text` and source spans that resolve to format-specific anchors ([native models](../../src/grounded_docparse/native.py)). These paths share presentation and optional document features, but their evidence contracts remain separate.

## Follow a task

- Choose a format and processing type: [explicit ingestion and routing](../workflows/explicit-ingestion-and-routing.md).
- Trace scanned pages through layout and recognition: [grounded OCR](../pipelines/grounded-ocr.md).
- Trace selectable PDFs or Office files: [native ingestion](../pipelines/native-ingestion.md).
- Understand accepted values and citations: [source grounding](../evidence/source-grounding.md).
- Work through the UI or restore a session: [studio and workspace](../interfaces/studio-and-workspace.md).
- Find runtime and verification boundaries: [operations](../operations/runtimes-and-configuration.md) and [tests](../testing/contracts-and-verification.md).

## Core boundary

The router validates the caller's route; it does not choose a route from file contents or substitute another processing type. The universal-parser tests exercise these boundaries with injected parser doubles, keeping route selection checks independent from model or OCR services.
