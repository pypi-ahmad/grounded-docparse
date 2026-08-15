---
tags: architecture, repository, development
sources: docs/architecture.md, docs/codebase/ARCHITECTURE.md, pyproject.toml
snapshot: content-338dd11260b6
status: released
---

# Repository architecture

The repository separates core parsing under `src/grounded_docparse`, the Streamlit entry point, evaluation assets, operational scripts, installers, documentation, and tests. Public dependencies and optional native integrations are declared in `pyproject.toml`.

Native ingestion is additive: shared models and dispatch sit beside the established OCR pipeline, while format adapters and grounded extraction remain isolated modules. Interfaces converge at result rendering, persistence, and exports rather than by sharing unverified evidence.

See [[system-overview]], [[adding-a-native-format]], and [[testing-strategy]].

## Evidence

The supported component map is in `docs/architecture.md`; the broader repository layout is in `docs/codebase/ARCHITECTURE.md`; dependency groups and package metadata are in `pyproject.toml`.
