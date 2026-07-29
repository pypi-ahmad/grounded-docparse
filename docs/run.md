# Run locally

On a fresh Windows 11 machine with no WSL yet, double-click `Setup-GLM-OCR.cmd`
once. It installs WSL2 + Ubuntu-24.04, verifies GPU passthrough, installs `uv`
and the Python/vLLM/glmocr environment inside WSL, downloads the GLM-OCR and
PP-DocLayout weights, and launches the app. It is safe to re-run any time,
including after WSL/GPU prerequisites are already in place.

For the local GLM-OCR stack once set up, double-click `Launch-GLM-OCR.cmd`. It installs the
locked WSL environment on first use, starts vLLM, waits for `glm-ocr`, starts
Streamlit with GPU layout preloaded, and opens <http://localhost:8501>. Runtime
logs and PID files are stored under the ignored `.runtime/` directory.
The large CUDA virtual environment is stored in WSL's native Linux filesystem at
`~/.local/share/grounded-docparse/.venv` for faster installation and startup.

Launching it again reuses healthy processes instead of reinstalling or restarting
them. After a Windows reboot, run the launcher once to load the models again.

From PowerShell in the repository root:

```powershell
# Optional: enables Luna visual recovery and Markdown refinement.
# $env:OPENAI_API_KEY = "..."
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

The app reads `OPENAI_API_KEY` from the process environment when available. Without it, parsing continues with GLM-OCR and marks unrecovered risks for review. Visual recovery is enabled by default, can be disabled in the sidebar, and is capped by `DOCPARSE_MAX_VISUAL_RECOVERY_CROPS` (default 8). Optional settings also cover render/crop DPI, upload/page limits, output-token limits, concurrency, and `DOCPARSE_FULL_PAGE_FALLBACK_FRACTION`; the Luna model is fixed to `gpt-5.6-luna`. PDFs are always rendered visually; selectable text is ignored.

The app reports run-level input and output token totals and stores no jobs or results. Use the Markdown, JSON, and annotated PDF download buttons before closing the session.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Browser is blank | Open the exact Local URL and keep Streamlit running |
| Extract button is disabled | Set both OpenAI environment variables and restart Streamlit |
| Provider error | Use its request ID, stage, page, and model when retrying or contacting the provider |
| Block marked `needs_review` in JSON | Compare its readable Markdown text with the source and inspect `verification_reason` |
