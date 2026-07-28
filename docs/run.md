# Run locally

For the local GLM-OCR stack, double-click `Launch-GLM-OCR.cmd`. It installs the
locked WSL environment on first use, starts vLLM, waits for `glm-ocr`, starts
Streamlit with GPU layout preloaded, and opens <http://localhost:8501>. Runtime
logs and PID files are stored under the ignored `.runtime/` directory.
The large CUDA virtual environment is stored in WSL's native Linux filesystem at
`~/.local/share/grounded-docparse/.venv` for faster installation and startup.

Launching it again reuses healthy processes instead of reinstalling or restarting
them. After a Windows reboot, run the launcher once to load the models again.

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

The app requires `OPENAI_API_KEY` and reads credentials from the process environment. Optional settings are `DOCPARSE_LUNA_MODEL`, render/crop DPI, upload/page limits, model output-token limits, concurrency, and `DOCPARSE_FULL_PAGE_FALLBACK_FRACTION`; see `.env.example` for defaults. PDFs are always rendered and evaluated visually; selectable text is ignored.

`DOCPARSE_TARGETED_REPAIR_CONTEXT_PADDING` is an opt-in evaluation setting. When
set above `DOCPARSE_CROP_PADDING`, Luna receives a second surrounding crop for an
already-eligible uncertain span in the same request. Leave it unset in production;
the current three-run Public Water experiment did not pass the accuracy and call-count
promotion gates.

The app reports run-level input and output token totals and stores no jobs or results. Use the Markdown, JSON, and annotated PDF download buttons before closing the session. Legacy `.docparse/` files are not read or changed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Browser is blank | Open the exact Local URL and keep Streamlit running |
| Extract button is disabled | Set both OpenAI environment variables and restart Streamlit |
| Provider error | Use its request ID, stage, page, and model when retrying or contacting the provider |
| Block marked `needs_review` in JSON | Compare its readable Markdown text with the source and inspect `verification_reason` |
