# Security policy

Report vulnerabilities privately through GitHub Security Advisories. Do not include real documents, credentials, or personal data in a public issue.

The application is intended for a trusted local workstation. It binds Streamlit locally by default and has no multi-user authentication or tenant isolation. Do not expose it directly to an untrusted network.

Keep `OPENAI_API_KEY` and `OPENAI_BASE_URL` in environment variables. Never commit `.env`, `.docparse/`, source documents, or result bundles. Uploaded documents, model output, filenames, schemas, and PDFs are untrusted inputs.

Uploaded bytes and generated results remain in the active Streamlit process and browser session; the application does not intentionally persist them. Use OS protections and download sensitive outputs only to approved locations. Legacy `.docparse/` data from earlier releases is outside the current app and is not deleted automatically.
