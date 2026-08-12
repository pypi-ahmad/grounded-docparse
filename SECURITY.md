# Security policy

Report vulnerabilities privately through the repository's [GitHub Security Advisory form](https://github.com/pypi-ahmad/grounded-docparse/security/advisories/new). Do not include real documents, credentials, or personal data in a public issue.

For harassment or other community-conduct concerns, use the same private form,
prefix the title with `Conduct report`, and follow
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security reports are handled under
this policy; conduct reports are handled under the code of conduct.

The application is intended for a trusted local workstation and has no multi-user authentication or tenant isolation. The launch scripts bind Streamlit and OCR services to `127.0.0.1`; do not override that boundary or expose ports `8501`, `8080`, `8118`, or `8119` to an untrusted network.

Keep `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` in environment variables. A custom base URL receives the same crop images and document context that would otherwise go to OpenAI; trust the destination host shown in the UI before use. Never commit `.env`, `.docparse/`, source documents, or result bundles. Uploaded documents, model output, filenames, schemas, and PDFs are untrusted inputs.

With a key present, Fast mode performs classification and visual recovery defaults on. Selecting **Parse document** may therefore send selected crops and recognized context remotely. Disable all Luna toggles for GLM-only processing.

Feature egress is bounded as follows:

- visual recovery: selected region crops and existing region context;
- Markdown refinement: anchored Markdown and compact layout records;
- classification: recognized content/layout from the first two pages;
- TOC and scalar extraction: all recognized document content/layout may be sent across multiple bounded requests, plus the extraction schema;
- chat: the question, recent history, and either the bounded document context or retrieved relevant elements.

Uploaded bytes and generated results, including batch workspaces and archives, remain in temporary parser storage, the active Streamlit process, and the browser session; normal parse completion removes the temporary directory, but abnormal process termination and storage recovery are outside the application's cleanup guarantee. Reusable extraction schemas are intentionally persisted in `data/document_studio.sqlite3`, or the path selected by `DOCPARSE_STUDIO_DB_PATH`. Delete that database and its SQLite sidecars to remove saved schemas. Downloads, browser state, backups, model caches, runtime logs, and legacy `.docparse/` data are operator-managed residuals. The setup-created WSL environment defaults to `~/.local/share/grounded-docparse/.venv`; upstream model-cache locations are not controlled by this repository.

Operational instructions are in [USAGE.md](USAGE.md); implementation trust
boundaries are summarized in [TECHNICAL.md](TECHNICAL.md).
