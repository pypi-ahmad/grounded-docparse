# Run locally

## Recommended Windows launcher

Run `Setup-GLM-OCR.cmd` once on a new Windows 11 machine. It validates WSL2 and GPU passthrough, creates the locked WSL environment, starts vLLM and Streamlit, waits for health checks, and opens <http://localhost:8501>.

Use `Launch-GLM-OCR.cmd` afterward, including after a reboot. It reuses healthy managed processes and starts only missing services. A managed vLLM process is healthy only after model discovery and a real image-recognition probe both pass. Normal launches resolve the setup-pinned GLM-OCR and PP-DocLayoutV3 commits from the WSL cache with network fallback disabled. Logs, resolved model metadata, generated SDK configuration, and PID files are under `.runtime/`; the WSL environment defaults to `~/.local/share/grounded-docparse/.venv`.

## Manual commands

Inside WSL:

```bash
bash scripts/wsl/setup-glmocr.sh
bash scripts/wsl/launch-stack.sh
```

For foreground development, keep vLLM in one WSL terminal and Streamlit in another:

```bash
bash scripts/wsl/serve-glmocr.sh
```

```bash
bash scripts/wsl/run-app.sh
```

The normal URLs are:

- GLM-OCR-compatible vLLM endpoint: <http://127.0.0.1:8080>
- Streamlit: <http://localhost:8501>

`OPENAI_API_KEY` is optional. `Launch-GLM-OCR.cmd` reads it and optional `OPENAI_BASE_URL` from the Windows user environment on every launch and restarts managed Streamlit when those values change. Without a key, GLM-OCR parsing still runs and all Luna controls are disabled or reported unavailable. Use a custom endpoint only when it is trusted and compatible.

With a key present, the default Fast preset performs remote classification and visual recovery is enabled. Selecting **Parse document** can therefore send selected recovery crops and recognized document context to the configured endpoint. Disable the corresponding toggles for GLM-only operation.

The launch scripts do not set Streamlit's `server.address`, and the vLLM script does not pass an explicit host flag. Localhost URLs are displayed, but loopback-only binding is not enforced by this repository. Keep ports `8501` and `8080` blocked from untrusted networks. For an explicit loopback Streamlit process, run `scripts/wsl/run-app.sh --server.address=127.0.0.1` manually.

## Use the studio

1. Upload one PDF, PNG, JPEG, or TIFF.
2. Optionally select an inclusive contiguous PDF page range.
3. Choose Fast, Full, or Custom mode and the visual-recovery/chat toggles.
4. Select **Parse document**.
5. Review the tabs and download results before ending the session.

Fast runs classification without Markdown refinement or TOC generation. Full enables refinement, classification, and TOC. Visual recovery is a separate toggle and defaults on when Luna is available. Extraction is configured and run inside the post-parse Extract tab. Chat appears only when enabled.

“ADE mode” is the UI label for these Luna-feature presets; it does not connect to an external ADE service.

## Stop and restart

The launch scripts start detached WSL processes. To stop them, open WSL in the repository root and run:

```bash
for file in .runtime/vllm.pid .runtime/streamlit.pid; do
  if [[ -f "$file" ]]; then
    kill "$(cat "$file")" 2>/dev/null || true
  fi
done
```

The next launcher run recreates missing processes.

For an OpenAI-variable change, only Streamlit needs to stop:

```bash
if [[ -f .runtime/streamlit.pid ]]; then
  kill "$(cat .runtime/streamlit.pid)" 2>/dev/null || true
fi
```

Then relaunch. A healthy reused process keeps its existing environment.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Browser is blank | Open the exact local URL and confirm `/_stcore/health` responds |
| Parse fails before layout | Confirm GLM-OCR is installed in WSL and vLLM exposes `glm-ocr` on port `8080` |
| Luna controls are disabled | Set `OPENAI_API_KEY` in the Windows user environment, then run `Launch-GLM-OCR.cmd` |
| Provider call fails | Use the displayed request ID, stage, page, and model; optional features fail independently |
| Block is `needs_review` | Compare its text with the highlighted source box and inspect `verification_reason` |
| Startup fails | Read `.runtime/vllm.log` and `.runtime/streamlit.log` |

See [setup](../SETUP.md) for every supported environment variable.
