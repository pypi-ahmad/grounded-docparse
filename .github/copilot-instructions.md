# Copilot instructions — Grounded DocParse

This file is auto-loaded by GitHub Copilot. It summarizes the canonical
commands and gating rules from [MODERNIZATION_PLAN.md](../MODERNIZATION_PLAN.md),
[CONTRIBUTING.md](../CONTRIBUTING.md), and [TECHNICAL.md](../TECHNICAL.md).
Edit freely to match your own gates as they evolve.

## Canonical commands

```powershell
uv sync --python 3.12.10 --locked --extra native
uv run python -m pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
uv run grounded-docparse ingest --help
git diff --check
```

The 528-item `pytest` suite runs entirely offline in under 90 seconds — no
WSL2, GPU, or live network call is required. All OCR gateways and providers
are exercised through synthetic documents and fake gateways in tests.

## Known, tracked pre-existing gaps (as of MODERNIZATION_PLAN.md Phase 1)

- **9 tests are marked `xfail`, not deleted**: 1 documentation
  self-consistency check (`tests/test_knowledge_wiki.py`) and 8
  `AppTest`-based UI tests (`tests/test_simple_streamlit.py`). See
  MODERNIZATION_PLAN.md § 2 and § 9 for what's known about each. Do not
  remove an `xfail` marker without confirming the underlying test actually
  passes now.
- **2 `ruff` violations** (unsorted `__all__` export list) are known and
  auto-fixable (`uvx ruff check --fix`) but were left as a fast-follow
  rather than bundled into the CI-authoring PR.

## Phase gating

- **Lit-regime phases** (this project has none in a "dark" state — the test
  suite already runs offline): exit criteria are runnable commands / green
  CI. Green CI on a PR is the authoritative signal.
- **CI Milestone:** Phase 1 of MODERNIZATION_PLAN.md, `.github/workflows/ci.yml`,
  targeting `windows-latest` (this project's primary supported OS) with
  Python 3.12.10.
- **CI enforcement is a manual step this repo's CI cannot self-configure:**
  making the workflow a required status check is done in GitHub → Settings
  → Branches by a human, not by any commit.

## Branch and PR rules

- Branch per phase, cut from `main`. One PR back to `main`. Never stack a
  phase branch on a sibling phase branch.
- A PR must explain what changed, which public contracts/artifacts are
  affected, how it was verified (paste real command output), and residual
  risks — see CONTRIBUTING.md's "Pull requests" section and
  `.github/PULL_REQUEST_TEMPLATE.md`.
- Never commit API keys, bearer tokens, source documents, crops, local data,
  or raw provider responses — see DATA_RESPONSIBILITY.md and SECURITY.md.
