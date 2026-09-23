---
type: testing-guide
title: Testing and Verification Contracts
description: Maps the offline test suite to routing, evidence, OCR, persistence, and UI contracts and lists the verification commands documented by the repository.
tags: [testing, contracts, verification, ci]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-164e2da859b5277df81c7d94
    resource: repo://.github/workflows/ci.yml
  - id: openwiki-source-cbd647eee54921144f512eef
    resource: repo://TESTING.md
  - id: openwiki-source-f0a6e7dc03522b2682f88655
    resource: repo://tests/conftest.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Test boundaries

The test suite uses synthetic documents and injected parser or provider doubles to verify behavior without relying on live model output. The shared `simple_pdf` fixture creates its PDF in memory ([fixture](../../tests/conftest.py)); the testing guide requires synthetic fixtures and fake provider gateways for tests ([policy](../../TESTING.md)).

Representative contracts include:

- **Route selection:** `tests/test_universal_parser.py` checks detected-format mismatches, caller-selected routes, and complete mixed-PDF page routes. See [explicit ingestion and routing](../workflows/explicit-ingestion-and-routing.md).
- **OCR evidence:** `tests/test_grounded_ocr.py` checks detector boxes, confidence, region failure state, crop bounds, and progress. See [grounded OCR](../pipelines/grounded-ocr.md).
- **Native evidence:** `tests/test_native_models.py` and `tests/test_native_extraction.py` reject out-of-bounds or unanchored source intervals. See [source grounding](../evidence/source-grounding.md).
- **Persistence:** `tests/test_workspace_store.py` covers result round trips, version invalidation, interruption reset, and corrupt artifacts. See [studio and workspace](../interfaces/studio-and-workspace.md).
- **Product workflow:** `tests/test_simple_streamlit.py` exercises routing review, batch isolation, stale-result handling, and restart restoration.
- **Operational boundary:** `tests/test_launcher_contract.py` checks loopback service addresses and launcher assumptions. See [runtime operations](../operations/runtimes-and-configuration.md).

These tests establish the checked behaviors under their fixtures; they do not establish live provider availability, hardware readiness, production accuracy, or external branch-protection settings. `TESTING.md` treats live-provider, load, hardware, and private accuracy evaluations as opt-in and asks that their environment and reference basis be recorded.

## Repository-documented commands

From the repository root, `TESTING.md` documents these commands with the locked `uv` environment:

```powershell
uv run python -m pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
uv run grounded-docparse ingest --help
python scripts/refresh_knowledge_wiki.py --check
git diff --check
```

The GitHub Actions workflow is configured for `windows-latest` with Python `3.12.10`; it installs the locked native extra, then runs Ruff, compileall, and the full Pytest suite ([CI workflow](../../.github/workflows/ci.yml)). These are repository-configured checks, not a record of checks run while generating this wiki.
