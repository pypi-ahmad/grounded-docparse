---
tags: grounding, evidence, invariants
sources: docs/spec.md, docs/architecture.md, src/grounded_docparse/native.py
snapshot: content-063b756c4b68
status: released
---

# Grounding and evidence contract

Every accepted native value must match exact text in an immutable `base_text` string and resolve through character spans to at least one source anchor. Anchors identify the original PDF page and bounding box, document paragraph or shape, spreadsheet sheet and cell, CSV row and column, or another native structural location.

The contract separates presentation from evidence. Markdown may be rendered or refined for readability, but it never replaces `base_text` as extraction input. Values without a valid character interval, exact text match, complete span coverage, or resolvable anchor are rejected.

This is the native equivalent of the OCR pipeline's element ownership rules. See [[native-document-model]], [[source-anchors-and-character-spans]], and [[langextract-grounded-extraction]].

## Evidence

`NativeDocument.valid_grounding` and related Pydantic models live in `src/grounded_docparse/native.py`; the system-level invariants are recorded in `docs/spec.md` and `docs/architecture.md`.
