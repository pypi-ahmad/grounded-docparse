---
type: navigation-guide
title: OpenWiki Quickstart
description: A task map for choosing the right Grounded DocParse workflow, implementation guide, and contract reference.
tags: [quickstart, navigation, routing]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-64f036a0fdbfaf2d9c3edc38
    resource: repo://src/grounded_docparse/universal.py
  - id: openwiki-source-6d98d900dbe919c220210d2e
    resource: repo://tests/test_universal_parser.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Start with your task

- **Parse one or more files in the studio:** start the Windows app using `Launch-Grounded-DocParse.cmd`, then follow [the studio workflow](interfaces/studio-and-workspace.md).
- **Run a batch from PowerShell:** use `grounded-docparse ingest` and supply a processing type for each input. For a mixed PDF, include a route for each selected page. See [explicit ingestion and routing](workflows/explicit-ingestion-and-routing.md).
- **Choose a parser or understand the package boundary:** start at [system overview](architecture/system-overview.md).
- **Trace scanned PDFs or images:** read [grounded OCR](pipelines/grounded-ocr.md).
- **Trace selectable PDFs, Office files, spreadsheets, CSV, or text:** read [native ingestion](pipelines/native-ingestion.md).
- **Understand evidence, anchors, extraction values, or citations:** read [source grounding](evidence/source-grounding.md).
- **Understand classification, form routing, extraction, or chat:** read [agentic document features](features/agentic-document-tools.md).
- **Check local runtimes and setup:** read [runtime operations](operations/runtimes-and-configuration.md).
- **Find the behavior tests and documented verification commands:** read [testing contracts](testing/contracts-and-verification.md).

## Small CLI example

This example declares the route for a selectable PDF:

```powershell
uv run grounded-docparse ingest invoice.pdf `
  --processing-type invoice.pdf=native-pdf `
  --output results
```

The selected `ProcessingType` controls parser dispatch after format and compatibility validation. For mixed PDFs, every selected page also needs an explicit reviewed route; the router fails when the route is missing or incompatible ([routing implementation](../src/grounded_docparse/universal.py), [route tests](../tests/test_universal_parser.py)).

For a broader map of entrypoints and evidence families, see [system overview](architecture/system-overview.md).
