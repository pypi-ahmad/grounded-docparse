---
tags: cli, api, integration
sources: src/grounded_docparse/cli.py, src/grounded_docparse/__init__.py, docs/api.md
snapshot: content-f03a0de2c1a2
status: released
---

# CLI and Python API

The command-line interface exposes the same manual routing contract through `--processing-type`. The selected value is validated against file content and dispatched once; invalid combinations fail before parsing rather than being reclassified.

The Python package exports native models, parsers, extraction results, and existing OCR interfaces through a single public surface. Callers can persist or render native evidence without depending on internal parser-specific objects.

See [[processing-types-and-manual-routing]], [[native-document-model]], and [[schema-translation-and-value-validation]].

## Evidence

Argument handling and dispatch live in `src/grounded_docparse/cli.py`; public exports are in `src/grounded_docparse/__init__.py`; usage contracts are documented in `docs/api.md`.
