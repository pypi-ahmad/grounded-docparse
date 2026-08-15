# Security policy

Report vulnerabilities privately through the repository's [GitHub Security Advisory form](https://github.com/pypi-ahmad/grounded-docparse/security/advisories/new). Do not include real documents, credentials, or personal data in a public issue.

For harassment or other community-conduct concerns, use the same private form,
prefix the title with `Conduct report`, and follow
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security reports are handled under
this policy; conduct reports are handled under the code of conduct.

The application is intended for a trusted local workstation and has no multi-user authentication or tenant isolation. The launch scripts bind Streamlit and OCR services to `127.0.0.1`; do not override that boundary or expose ports `8600`, `8080`, `8118`, or `8119` to an untrusted network.

Keep `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `AGNES_API_KEY`, and optional provider base URLs in environment variables. A custom base URL receives the same crop images and document context as its default provider; trust the destination before use. Never commit `.env`, `.docparse/`, source documents, or result bundles. Uploaded documents, model output, filenames, schemas, and PDFs are untrusted inputs.

With a provider key present, enabled AI features may send selected crops and recognized context remotely. AI enhancement defaults off and targets only failed or sub-75%-confidence regions. Disable all AI features for fully local processing.

Feature egress is bounded as follows:

- visual recovery: selected region crops and existing region context;
- Markdown refinement: anchored Markdown and compact layout records;
- classification: recognized content/layout from the first two pages;
- TOC and scalar extraction: all recognized document content/layout may be sent across multiple bounded requests, plus the extraction schema;
- chat: the question, recent history, and either the bounded document context or retrieved relevant elements.

The studio intentionally persists more than schemas. `data/document_studio.sqlite3`, or the path selected by `DOCPARSE_STUDIO_DB_PATH`, stores reusable extraction schemas, routing profiles, and the active batch workspace: settings, progress, parse results, analyses, native extraction checkpoints, failures, and usage. The sibling `workspaces/` directory stores uploaded source bytes, selected-page sources, parse checkpoints, and annotated PDFs. That durable batch is restored after an app restart. **Clear saved workspace** deletes the active batch rows and the `workspaces/` artifacts after confirmation. Delete the database and its SQLite sidecars (`-wal`, `-shm`) to remove saved schemas, profiles, and workspace metadata.

Extraction, routing review, and chat remain session-only. Uploaded bytes and generated results also remain in temporary parser storage, the active Streamlit process, and the browser session while a workflow is open. Normal parse completion removes the parser temporary directory, but abnormal process termination and storage recovery are outside the application's cleanup guarantee. Closing a browser tab or restarting the app is not deletion of the durable workspace. Downloads, browser state, backups, Windows/WSL model caches, runtime logs, Streamlit caches, and legacy `.docparse/` data are operator-managed residuals. Native app state defaults to `%LOCALAPPDATA%\GroundedDocParse`; WSL GPU environments remain separately operator-managed.

Operational instructions are in [USAGE.md](USAGE.md); implementation trust
boundaries are summarized in [TECHNICAL.md](TECHNICAL.md).
