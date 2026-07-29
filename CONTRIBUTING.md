# Contributing

Contributions should preserve source grounding, explicit uncertainty, and deterministic export behavior.

## Setup

```powershell
git clone https://github.com/pypi-ahmad/grounded-docparse.git
Set-Location grounded-docparse
uv sync --python 3.12.10 --locked
```

Do not install project dependencies with system `pip`. Keep `pyproject.toml` and `uv.lock` synchronized when an approved dependency changes.

## Development workflow

1. Open an issue before substantial or schema-breaking work.
2. Create a focused branch from the current target branch.
3. Add a failing public-contract test before changing behavior.
4. Keep provider output behind validated models and preserve evidence references.
5. Update user-facing documentation and `CHANGELOG.md` with behavior changes.
6. Run the verification commands and documentation checks before opening a pull request.

Avoid unrelated refactors, generated artifacts, real documents, and live-provider fixtures.

## Verify changes

```powershell
uv run python -m pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
git diff --check
```

Automated tests use synthetic documents and fake OpenAI gateways. The project has no installed CLI entry point; use `streamlit_app.py` for the application and `scripts/evaluate_corpus.py` for evaluation. Keep live OpenAI, load, and accuracy checks opt-in and document their exact environment.

For documentation changes, also verify that every relative Markdown link resolves and every fenced block has a language identifier and closing fence. The repository does not install a dedicated Markdown-link checker.

## Documentation changes

- Treat code and tests as the source of truth for implemented behavior.
- Verify version-sensitive external claims against official documentation.
- Keep README quick-start material concise; place operational depth in `docs/run.md`.
- Distinguish measured results from confidence, quality proxies, or architectural goals.
- Never claim that a provider cache duration, model capability, accuracy, or throughput is guaranteed without current evidence.
- Validate internal links and remove stale command, profile, route, and environment-variable references.

## Pull requests

A pull request must explain:

- what changed and why;
- which public contracts or artifacts are affected;
- how the change was verified;
- provider cost, retention, security, or compatibility consequences; and
- residual risks or checks not run.

Do not include API keys, bearer tokens, source documents, crops, local data, or raw provider responses.

## Architecture constraints

- Models may propose typed evidence; deterministic code derives stable IDs from GLM regions and owns validation, hierarchy, and export policy.
- GLM-OCR originates element identity, geometry, type, confidence, and reading order; deterministic code may normalize IDs and correct dense-form ordering. Luna recovery may change only high-confidence text on existing elements.
- Unsupported text must remain unresolved or rejected in strict outputs.
- Every extracted leaf requires existing source-node citations.
- New output-affecting configuration must be covered by public-contract tests.
- New persistence requires an explicit retention and deletion design.
- Public schema changes require versioning, migrations where applicable, renderer updates, and compatibility tests.

## Reporting security issues

Do not open public issues for undisclosed vulnerabilities. Follow [SECURITY.md](SECURITY.md).
