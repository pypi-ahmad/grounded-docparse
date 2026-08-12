---
tags: workspace, persistence, exports
sources: src/grounded_docparse/workspace_store.py, src/grounded_docparse/native.py
snapshot: content-dde17504a128
status: feature-branch
---

# Workspace persistence and exports

Workspace persistence stores native processing type, immutable base text, source spans, anchors, page routes, rendered views, assets, warnings, and grounded extraction evidence. Reloading must preserve character offsets and evidence identity rather than rebuilding them from Markdown.

Exports include Markdown, JSON, and source-structure data. Visual formats may also provide an annotated PDF; nonvisual native formats can omit it without making the result incomplete.

See [[native-document-model]], [[source-anchors-and-character-spans]], and [[streamlit-workflow]].

## Evidence

Serialization and restoration are implemented in `src/grounded_docparse/workspace_store.py`; persisted native result types are defined in `src/grounded_docparse/native.py`.
