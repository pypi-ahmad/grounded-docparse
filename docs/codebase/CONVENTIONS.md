# Coding Conventions

## Core Sections (Required)

### 1) Naming Rules

- Modules, functions, arguments, fixtures, and variables use `snake_case`.
- Classes, enums, dataclasses, and Pydantic contracts use `PascalCase`.
- Constants and environment-variable names use `UPPER_SNAKE_CASE`.
- Tests use `test_<observable_behavior>` rather than implementation-step names.
- Native identifiers expose source scope (`page-1`, `p1-e1`, `element-1`) and are validated for uniqueness.
- JSON Pointer paths identify extracted leaves; schema/output payloads carry explicit version fields.

### 2) Formatting and Linting

- Python uses four-space indentation, type annotations, and modern union/generic syntax supported by Python 3.12.
- Ruff is the repository lint gate: `uvx ruff check src streamlit_app.py tests scripts`.
- There is no `[tool.ruff]` configuration, formatter command, or enforced line-length override in the repository.
- `compileall`, pytest, and `git diff --check` are required alongside Ruff.
- Generated artifacts, unrelated reformatting, and live-provider fixtures are excluded from normal contributions.

### 3) Import and Module Conventions

- Package modules use relative imports (`from .native import ...`); entry points/tests import `grounded_docparse` publicly.
- `src/grounded_docparse/__init__.py` explicitly curates the supported package surface through imports and `__all__`.
- Optional integrations are imported lazily inside the functions/classes that require them, then raise an actionable `RuntimeError` naming the `native` extra.
- Runtime-only circular dependencies are avoided with local imports at adapter boundaries.
- Standard-library imports precede third-party and package imports in Ruff-compatible groups.

### 4) Error and Logging Conventions

- Contract and user-input failures normally raise `ValueError` or a narrow subclass such as `ProcessingTypeMismatch`.
- Missing optional runtimes raise `RuntimeError` with installation context.
- CLI command boundaries convert expected `OSError`/`ValueError` failures to `error: ...` on stderr and exit code `2`; per-document execution records other exceptions as failed manifest entries.
- Streamlit presents recoverable failures in UI state while persisting per-document status/error details.
- Provider calls use `ProviderRuntime` for bounded retries, cooldown, concurrency, and diagnostics; SDK retries are disabled to keep one policy owner.
- The Streamlit entry point configures INFO logging for the `grounded_docparse` package. Structured `AgentTraceEvent`, `RunUsage`, and runtime diagnostics remain the durable observability records; scripts and CLI commands may use `print`.

### 5) Testing Conventions

- Add a failing public-contract test before behavior changes.
- Use synthetic bytes/documents and fakes; never require live OpenAI or real user documents in the default suite.
- Use `monkeypatch` for environment/provider boundaries and `tmp_path` for persistence/output isolation.
- Parameterize validation cases; use `pytest.importorskip` only for optional native dependency coverage.
- Assert observable routes, exact evidence spans, serialized contracts, and failure behavior—not private call ordering unless routing itself is the contract.
- Public schema changes require versioning plus renderer, persistence, and compatibility tests.

### 6) Evidence

- `CONTRIBUTING.md`
- `pyproject.toml`
- `src/grounded_docparse/__init__.py`
- `src/grounded_docparse/universal.py`
- `src/grounded_docparse/runtime.py`
- `src/grounded_docparse/cli.py`
- `src/grounded_docparse/native.py`
- `tests/conftest.py`
- `tests/test_cli.py`
- `tests/test_provider_runtime.py`
- `tests/test_native_extraction.py`
