# Testing Patterns

## Core Sections (Required)

### 1) Test Stack and Commands

The default suite uses pytest 8+ with `testpaths = ["tests"]` and quiet output. The checked-in suite has 39 `test_*.py` modules.

```powershell
uv run python -m pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
git diff --check
```

Live provider, accuracy, and load evaluation are opt-in. Corpus evaluation is run separately through `scripts/evaluate_corpus.py` and policy fixtures under `benchmarks/`.

### 2) Test Layout

- `tests/conftest.py` supplies small synthetic PDF bytes.
- `tests/test_simple_pipeline.py`, `test_strict_recovery_contract.py`, and related modules cover the OCR/evidence pipeline.
- `tests/test_universal_parser.py`, `test_native_pdf_parser.py`, `test_docling_native_parser.py`, and `test_native_extraction.py` cover manual routing and native grounding.
- `tests/test_simple_streamlit.py` uses `streamlit.testing.v1.AppTest` for UI/session/restart contracts.
- `tests/test_cli.py`, launcher, runtime, and installer tests cover operational entry points.
- `tests/test_workspace_store.py` and `test_schema_store.py` cover SQLite/artifact round trips and compatibility behavior.
- Evaluation modules validate corpus schemas, metrics, calibration, reports, and regression policy.

### 3) Test Scope Matrix

| Scope | Evidence in suite | Default external dependency |
|---|---|---|
| Pydantic/data contracts | Model validation, IDs, ranges, schema versions | None |
| OCR parsing/quality | Synthetic pages, fake OCR/gateway results, crop/recovery rules | None |
| Native routing | Extension/signature/container mismatch and exact route assertions | None |
| Native PDF | Fake pdf-inspector and fake legacy parser; mixed order/no fallback | None |
| Docling formats | Generated DOCX/PPTX/XLSX/CSV/HTML/EPUB/ODF fixtures and exact anchors | Optional Docling import |
| LangExtract | Fake extraction function, exact intervals, rejection cases | None; fake key only |
| UI | Streamlit AppTest uploads, selectors, batch isolation, restart persistence | None |
| CLI/install/runtime | Temporary paths, fakes, script/config contract checks | None |
| Evaluation | Synthetic corpus and deterministic policy/metric checks | None by default |

### 4) Mocking and Isolation Strategy

- `monkeypatch` replaces gateways, parser classes, `urlopen`, environment values, and expensive rendering/OCR boundaries.
- Small `Fake*` classes encode only the protocol required by the behavior under test.
- `tmp_path` isolates output directories and each test database; the Streamlit suite has an autouse database fixture.
- Native tests inject `pdf_module`, converter, inspector, or LangExtract callables instead of patching library internals.
- Provider-runtime tests use fake time/sleep/random behavior so retry and cooldown assertions remain deterministic.
- Optional Docling coverage calls `pytest.importorskip("docling")`; the rest of the default suite remains independent of native dependencies.

### 5) Coverage and Quality Signals

- The suite emphasizes public contracts: exact selected route, no silent fallback, source spans, original mixed-page order, serialized output, persistence, and rejected ungrounded values.
- Evaluation schemas and regression policies supplement unit tests with measurable corpus checks.
- Ruff, compileall, and diff checks catch issues outside pytest.
- No coverage plugin/configuration, minimum percentage, browser E2E suite, or CI workflow is checked in.
- `[TODO]` Establish a reproducible coverage baseline before setting any threshold; no measured coverage percentage exists in the repository.

### 6) Evidence

- `pyproject.toml`
- `CONTRIBUTING.md`
- `tests/conftest.py`
- `tests/test_simple_pipeline.py`
- `tests/test_simple_streamlit.py`
- `tests/test_cli.py`
- `tests/test_universal_parser.py`
- `tests/test_native_pdf_parser.py`
- `tests/test_docling_native_parser.py`
- `tests/test_native_extraction.py`
- `tests/test_workspace_store.py`
- `tests/test_provider_runtime.py`
- `scripts/evaluate_corpus.py`
- `benchmarks/`
