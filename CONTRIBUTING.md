# Contributing

## Setup

```powershell
uv sync --python 3.12 --locked
```

## Verify changes

```powershell
uv run pytest -q
uv run python -m compileall -q src streamlit_app.py scripts tests
```

Tests use synthetic inputs and fake providers. Keep live Docker, GPU, Ollama,
and paid cloud checks separate from automated tests.

## Contribution guidelines

- Open an issue before substantial changes.
- Keep changes focused and include tests for changed behavior.
- Do not commit secrets, model caches, build artifacts, or local document data.
- Describe user impact and verification in pull requests.
