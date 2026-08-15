# Testing Grounded DocParse

Grounded DocParse welcomes testing with synthetic, public, or explicitly
authorized documents. Do not use confidential, regulated, personal, or
third-party material unless you are authorized to process it and have reviewed
[data responsibility](DATA_RESPONSIBILITY.md) and [security](SECURITY.md).

## Manual application testing

Use the latest release or a named commit and record it with every report. A
useful smoke test covers this path:

1. Start the native Windows application and confirm the page loads on its
   displayed loopback URL.
2. Upload a small synthetic document and choose its correct processing type.
3. Select one extraction engine and, when applicable, one AI model.
4. Process a short page range or document and confirm that progress reaches a
   terminal state.
5. Inspect Markdown, JSON, layout evidence, and the annotated PDF when that
   output is supported.
6. Download any result needed for the test, then use **Clear saved workspace**
   and confirm the batch is no longer restored.

Test one variable at a time. When comparing engines or models, keep the source,
processing type, page range, and feature settings unchanged. A successful run
does not establish production accuracy; review grounding, reading order,
tables, omissions, and uncertain regions against the source.

## Safe test data

Prefer repository fixtures or documents created specifically for testing.
Synthetic samples should exercise the relevant layout without copying real
names, account numbers, health information, credentials, or document images.
Never attach real documents, crops, result bundles, raw provider responses,
tokens, or local data paths to a public report.

## Reporting a bug

Search [existing issues](https://github.com/pypi-ahmad/grounded-docparse/issues)
before opening a [bug report](https://github.com/pypi-ahmad/grounded-docparse/issues/new?template=bug_report.md).
Include:

- release or commit;
- interface, processing type, extraction engine, and AI model;
- enabled AI features and page range;
- operating system, relevant runtime versions, and hardware;
- minimal reproduction steps using synthetic input;
- expected and actual behavior; and
- bounded, sanitized error text, stage, page number, and request ID when
  available.

Use a private [GitHub Security Advisory](https://github.com/pypi-ahmad/grounded-docparse/security/advisories/new)
for vulnerabilities. General setup and usage questions belong in
[GitHub Discussions](https://github.com/pypi-ahmad/grounded-docparse/discussions).

## Contributor verification

From the repository root, use the locked `uv` environment:

```powershell
uv run python -m pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
uv run grounded-docparse ingest --help
python scripts/refresh_knowledge_wiki.py --check
git diff --check
```

Tests must use synthetic fixtures and fake provider gateways. Live-provider,
load, hardware, and private accuracy evaluations are opt-in and must document
their environment, cost, dataset authority, and reference basis. See
[contributing](CONTRIBUTING.md) and the
[private evaluation workflow](docs/private-evaluation.md) for deeper guidance.
