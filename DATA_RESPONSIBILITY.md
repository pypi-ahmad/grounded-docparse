# Data responsibility

Grounded DocParse is software that you run and configure. You are responsible
for deciding whether a document may be processed, where processing may occur,
which providers may receive data, how outputs are reviewed, and when all copies
must be deleted. This document is operational guidance, not legal advice.

## Authority and compliance

Before processing a document, confirm that you have the necessary ownership,
permission, consent, and lawful basis. Identify any contractual, employment,
privacy, confidentiality, records-management, export, sector-specific, or
regional requirements that apply to the source and generated outputs.

Do not assume that running the application locally makes every workflow local.
When an AI feature is enabled with a provider key or custom endpoint, selected
crops, recognized content, layout records, schemas, questions, or conversation
context may be sent to that provider. Review the provider's terms, retention,
training, residency, and security controls before enabling it.

## Local protection and deletion

You are responsible for protecting the workstation, Windows and WSL accounts,
API keys, databases, workspaces, downloads, backups, browser state, caches,
logs, exports, and model-provider accounts. Use least-privilege access and do
not expose the loopback services to an untrusted network.

**Clear saved workspace** removes the active durable batch from the application
database and workspace directory after confirmation. It does not erase
downloads, backups, browser data, logs, provider-held copies, model caches,
legacy data, or copies made by other software. Follow the complete retention
and deletion inventory in [SECURITY.md](SECURITY.md).

## Output responsibility

OCR, extraction, classification, refinement, tables, and generated answers may
be incomplete or incorrect. Confidence values and successful execution are not
proof of accuracy. Review outputs against source evidence before using them,
especially for legal, medical, financial, safety, eligibility, compliance, or
other consequential decisions.

You are responsible for downstream access, correction, disclosure, retention,
and deletion of exports and derived data. Do not publish sensitive examples in
issues or discussions; reproduce problems with synthetic data and sanitized
diagnostics as described in [TESTING.md](TESTING.md).

## Project boundary

The open-source project does not operate a hosted document-processing service
and does not receive your documents merely because you install the software.
Data may nevertheless reach third parties that you select or configure,
including AI providers, custom compatible endpoints, storage, backup, logging,
or monitoring systems. The software is provided under the
[MIT License](LICENSE), including its warranty and liability disclaimer.
