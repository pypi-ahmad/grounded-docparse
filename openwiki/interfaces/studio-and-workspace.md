---
type: interface-workflow
title: Studio Workflow and Workspace Persistence
description: Follows the Streamlit batch workflow and explains what workspace state survives a restart and how stored results are invalidated.
tags: [streamlit, workspace, persistence, batch]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-89140fb14e5438f3c5cbed4a
    resource: repo://src/grounded_docparse/workspace_store.py
  - id: openwiki-source-964922c41d4be25ac5f159ec
    resource: repo://streamlit_app.py
  - id: openwiki-source-395c4ce873ad3fa6789f3e8d
    resource: repo://tests/test_simple_streamlit.py
  - id: openwiki-source-e848318f79b62a5e7e4c0f73
    resource: repo://tests/test_workspace_store.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Studio workflow

The Streamlit studio collects uploaded documents, processing types, page routes where needed, engine and feature settings, then starts parsing from the **Parse document** or **Process documents** action. The selected settings are folded into a per-document selection key. If a parse-affecting choice changes, the old result is reset to pending so it will not be reused for the new choice ([selection and invalidation](../../streamlit_app.py)). Batch processing retains per-document progress and failure state, so a failed document can be handled without discarding completed neighbors ([batch tests](../../tests/test_simple_streamlit.py)). For CLI batch behavior, see [explicit ingestion and routing](../workflows/explicit-ingestion-and-routing.md).

The UI keeps active review state in Streamlit session state. The durable store is narrower: `WorkspaceStore` keeps workspace and document metadata in SQLite, while source bytes and result artifacts live in per-document directories beneath the database directory ([store layout and writes](../../src/grounded_docparse/workspace_store.py)). Completed parse results, extraction state, settings, and usage can be restored when compatible. See [agentic features](../features/agentic-document-tools.md) for which document operations populate those results.

## Restart and compatibility behavior

On load, the store compares the saved result version with the current version. A mismatch clears saved parse, analysis, extraction, and progress data and returns documents to pending. A row saved as `processing` or legacy `interrupted` is also reset to pending; partial work is not resumed. The loader verifies the saved source hash and isolates corrupt artifacts as a failed document ([load behavior](../../src/grounded_docparse/workspace_store.py)). Tests cover completed round trips, interrupted work, version changes, and corrupt results ([workspace tests](../../tests/test_workspace_store.py)).

The studio's **Clear saved workspace** action clears the workspace store, including its local artifact directory. Workspace persistence is for one local application workspace; the project does not define multi-user authentication or tenant isolation.

## Related paths

- [System boundaries](../architecture/system-overview.md) explain how the UI reaches the parser.
- [Runtime operations](../operations/runtimes-and-configuration.md) cover the Windows launcher and optional OCR services.
- [Testing contracts](../testing/contracts-and-verification.md) maps UI and persistence tests to these behaviors.
