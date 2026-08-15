---
tags: model, evidence, native
sources: src/grounded_docparse/native.py
snapshot: content-7de86a1331e2
status: released
---

# Native document model

`NativeDocument` is the shared evidence model for native PDFs and non-PDF native formats. It contains immutable base text, source units, character-to-source spans, normalized elements, tables, assets, rendered views, and warnings.

The model validates its own grounding. Character ranges must be ordered and bounded, spans must point into base text, and every referenced anchor must resolve to declared source structure. Supporting result models carry previews and extraction evidence without weakening those invariants.

See [[source-anchors-and-character-spans]], [[immutable-base-text]], and [[workspace-persistence-and-exports]].

## Evidence

Pydantic models including `NativeDocument`, `NativeElement`, `SourceUnit`, `SourceSpan`, and extraction result types are defined in `src/grounded_docparse/native.py`.
