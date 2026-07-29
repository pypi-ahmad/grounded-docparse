# Security best-practices report: grounded-docparse

> Repository state reviewed: 2026-07-29. See [the threat model](grounded-docparse-threat-model.md) for trust boundaries and abuse paths.

## Summary

No critical or high code-level finding was identified in this repository/code/documentation audit. The threat model tracks four medium-priority areas: native parsing, indirect prompt injection, endpoint confidentiality, and unauthenticated network exposure. The first two are code/data-path risks; the latter two are deployment risks. The trusted-workstation assumption bounds them but does not eliminate them.

## Medium

### SBP-001: untrusted native parsing runs in the Streamlit process

- **Where:** `src/grounded_docparse/ingest.py` and crop rendering in the same module.
- **Current controls:** extension/magic checks, byte/page/pixel limits, password-protected PDF rejection, temporary storage.
- **Gap:** MuPDF and Pillow decode attacker-controlled bytes in the process that also holds provider credentials.
- **Recommendation:** keep dependencies current and isolate decode/render work before accepting sensitive or externally supplied documents.

### SBP-002: grounding does not eliminate indirect prompt injection

- **Where:** crop prompts in `src/grounded_docparse/gateways.py`; compact Markdown/layout prompts used by classification, TOC, extraction, and chat.
- **Current controls:** Structured Outputs, known-element validation, extraction evidence resolution, strict GLM ownership, `store=False`.
- **Gap:** a schema-valid response can cite real evidence while interpreting malicious visible instructions as task instructions.
- **Recommendation:** preserve human review for consequential outputs and surface the destination endpoint and confidence/provenance clearly.

## Low / informational

### SBP-003: no structured application logging

- **Where:** `src/grounded_docparse/` and `streamlit_app.py` do not use Python's logging module.
- **Impact:** failures are visible in the Streamlit session and result trace, but there is no durable application audit log after the session closes. Launcher stdout/stderr logs cover service startup, not structured parse events.
- **Recommendation:** if operational auditability becomes a requirement, add redacted structured logs at parse/provider boundaries. Do not log document text, crops, schemas, keys, or full model responses.

### SBP-004: custom endpoint destination is not shown before egress

- **Where:** `OpenAI()` consumes `OPENAI_BASE_URL` from the environment; the UI shows only whether a key exists.
- **Impact:** an operator may forget that a custom proxy receives document content.
- **Recommendation:** display the destination host without credentials before enabling Luna calls.

### SBP-005: reusable schemas persist unencrypted

- **Where:** `data/document_studio.sqlite3` or `DOCPARSE_STUDIO_DB_PATH`.
- **Impact:** schema names/descriptions may reveal business context on a shared workstation.
- **Current controls:** local path, gitignored `data/`, parameterized SQL.
- **Recommendation:** avoid sensitive values in schema descriptions and rely on OS disk/user protections; delete the database when schemas should be removed.

## Checked and current

- No hardcoded API key or bearer token is present in tracked source or documentation.
- Provider requests set `store=False`.
- No TLS-verification bypass is present in the application source.
- SQL statements use parameters for user-controlled values.
- Uploaded filenames are not used to construct temporary source paths.
- Canonical annotation labels do not embed arbitrary model text.
- Unknown model-returned source IDs are filtered before UI highlighting.
- Saved results are not persisted by the application; schemas are the documented exception.

## Deployment boundary

This report does not approve public or multi-user deployment. The app has no authentication, authorization, tenant isolation, or per-user quota, and the launcher does not set an explicit Streamlit loopback address. Any network exposure requires a new threat model and deployment controls.
