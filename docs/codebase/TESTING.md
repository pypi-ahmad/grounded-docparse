# Testing

## Core Sections (Required)

### 1) Framework and layout

- Framework: `pytest` (`pyproject.toml` `[tool.pytest.ini_options]`, `testpaths = ["tests"]`)
- ~26 modules under `tests/` covering pipeline, agentic, extraction, engines, UI contracts, installer

### 2) Strategy (from docs + suite names)

- Prefer unit/contract tests with fake gateways over live model calls
- Live evaluation is opt-in via `scripts/evaluate_corpus.py`
- `--glm-only` mode verifies zero Luna activity for local-only provenance runs
- Bundled corpus is a regression suite, not external product equivalence claims

### 3) Notable test themes

| Theme | Example modules |
|-------|-----------------|
| Agentic contracts | `test_agentic_contract.py`, `test_agentic_extraction.py`, `test_agentic_features.py` |
| Extraction/evidence | `test_simple_pipeline.py`, extraction-related tests |
| OCR engines | `test_paddle_ocr.py`, `test_glmocr_runtime_config.py`, `test_paddle_runtime_config.py` |
| UI/simple contracts | `test_simple_streamlit.py`, `test_simple_contract.py` |
| Evaluation | `test_evaluation_metrics.py`, `test_evaluation_report.py`, `test_corpus_manifest.py` |
| Recovery ownership | `test_strict_recovery_contract.py` |

### 4) Evidence

- `pyproject.toml`
- `tests/` directory listing
- `docs/architecture.md` evaluation boundary
- `docs/research.md`
- `scripts/evaluate_corpus.py`

## Notes

- [TODO] Document exact default pytest markers/fixtures from `tests/conftest.py` in a later pass if needed for contributor onboarding.
