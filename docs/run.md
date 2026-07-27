# Run locally

From PowerShell in the repository root:

```powershell
if (-not $env:OPENAI_API_KEY) { throw "OPENAI_API_KEY is not set" }
if (-not $env:OPENAI_BASE_URL) { throw "OPENAI_BASE_URL is not set" }
uv sync --locked
uv run streamlit run streamlit_app.py
```

Open the printed local URL, normally <http://localhost:8501>. Keep the terminal running while using the app.

To stop, press `Ctrl+C`. To restart a detached instance:

```powershell
Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess }
uv run streamlit run streamlit_app.py
```

The app reads credentials from the process environment. If user-level variables were just created, open a new PowerShell window. Optional settings are `DOCPARSE_LUNA_MODEL`, `DOCPARSE_TERRA_MODEL`, render/crop DPI, upload/page limits, model output-token limits, `DOCPARSE_PAGE_BATCH_SIZE`, and `DOCPARSE_MAX_PAGE_CONCURRENCY`; see `.env.example` for defaults. Concurrency cannot exceed the batch size. Reduce it if the OpenAI project reaches request, token, or image rate limits.

The app reports run-level input and output token totals and stores no jobs or results. Use the Markdown, JSON, and annotated PDF download buttons before closing the session. Legacy `.docparse/` files are not read or changed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Browser is blank | Open the exact Local URL and keep Streamlit running |
| Extract button is disabled | Set both OpenAI environment variables and restart Streamlit |
| Provider error | Use its request ID, stage, page, and model when retrying or contacting the provider |
| Block marked `needs_review` in JSON | Compare its readable Markdown text with the source and inspect `verification_reason` |
