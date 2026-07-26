# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| `main` and `feat/grounded-vision-pipeline` | Security fixes under active development |
| `0.1.x` | Best-effort fixes until a newer release is published |

## Reporting a vulnerability

Do not open a public issue for an undisclosed vulnerability. Use the repository's GitHub **Report a vulnerability** flow to submit a private report.

Include the affected version or commit, impact, minimum reproduction, and any suggested mitigation. Do not attach real customer documents, API keys, bearer tokens, database dumps, or object-store exports. The maintainer will assess the report and coordinate remediation privately.

## Deployment security model

The included Compose stack is a reference deployment for a trusted network:

- one shared bearer token protects all `/api/v1` routes;
- there are no users, tenants, per-job ACLs, or role-based permissions;
- HTTP is exposed without TLS termination;
- rate limiting and web application filtering are not included; and
- PostgreSQL, Redis, and MinIO use deployment-supplied credentials.

Before internet exposure, place the services behind TLS, identity-aware authorization, rate limits, request-size enforcement, network policy, and monitored secret management. Do not rely on the Streamlit password field as an identity system.

## Document and artifact handling

Uploads and derived artifacts can contain sensitive or regulated information. Operators are responsible for encryption, access control, backups, regional requirements, retention, and deletion.

`DELETE /api/v1/jobs/{job_id}` removes the job row and job-scoped artifact prefix. It does not delete the shared content-addressed processing-cache copy, which currently has no TTL or authenticated purge endpoint. Until that is fixed, configure an external object-lifecycle policy, disable cache reuse in a deployment-specific fork, or avoid data that requires guaranteed erasure.

Review and evaluation artifacts may repeat corrected document text. Apply the same controls as source and result artifacts.

## Provider data handling

Production vision calls use `store=false`, but provider-side abuse monitoring, cache handling, and organization data controls remain governed by the configured OpenAI account and current provider policy.

The gateway uses stable prompt-cache keys. Do not place customer identifiers or document text in those keys. Prompt-cache retention is controlled by the provider and must not be treated as application artifact deletion.

## Untrusted-input boundaries

Treat uploads, filenames, PDF structures, images, extraction schemas, taxonomies, model responses, Markdown, links, reviewer corrections, and provider errors as untrusted.

Security-sensitive changes must preserve:

- bounded upload, page, pixel, table, and schema limits;
- path normalization for artifact keys;
- strict model-output validation;
- output escaping;
- bounded error reporting without raw provider payloads;
- digest-pinned compatibility containers; and
- logs that exclude raw documents, crops, credentials, and full PII.

## Secrets

Keep `.env` local. Generate URL-safe local Compose secrets with `uv run python -m grounded_docparse.compose_env rotate .env`; this command does not print their values. Rotate any credential that appears in a commit, issue, log, screenshot, artifact bundle, or chat transcript. Use separate credentials and storage for development, evaluation, and production.
