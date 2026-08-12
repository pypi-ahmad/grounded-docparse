# Run locally

## Recommended Windows launcher

Run `Setup-GLM-OCR.cmd` once on a supported Windows 10 22H2 or Windows 11 machine. It validates WSL2 and available OCR capability, creates the locked WSL environment with the native-document extra, starts the selected local OCR stack and Streamlit, waits for health checks, and opens <http://localhost:8501>.

Use `Launch-GLM-OCR.cmd` afterward, or `Launch-PaddleOCR-VL-1.6.cmd` to start with Paddle selected. Both open the same app and the in-app dropdown can switch the exclusive managed GPU backend. GLM lives in `.venv`; Paddle and its compatible vLLM stack live in `.paddle-venv`.

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
- PaddleOCR-VL vLLM endpoint: <http://127.0.0.1:8118>
- PaddleX full document parser: <http://127.0.0.1:8119>
- Streamlit: <http://localhost:8501>

Set Windows user variables `DOCPARSE_PADDLE_VLLM_PORT` and
`DOCPARSE_PADDLE_API_PORT` before launching to override the two Paddle defaults.
The ports must be distinct integers from 1 through 65535.

`OPENAI_API_KEY` is optional. `Launch-GLM-OCR.cmd` reads it and optional `OPENAI_BASE_URL` from the Windows user environment on every launch and restarts managed Streamlit when those values change. Without a key, GLM-OCR parsing still runs and all Luna controls are disabled or reported unavailable. Use a custom endpoint only when it is trusted and compatible.

With a key present, the default Fast preset performs remote classification and visual recovery is enabled. Selecting **Parse document** can therefore send selected recovery crops and recognized document context to the configured endpoint. Disable the corresponding toggles for GLM-only operation.

The managed scripts bind Streamlit and OCR services to loopback. Do not expose ports `8501`, `8080`, `8118`, or `8119` to an untrusted network.

## Use the studio

1. Upload up to 20 supported PDFs, Office/open formats, CSV, HTML, EPUB, Markdown, or images (250 MB each and 1 GB combined).
2. Choose a compatible **Processing type** for every file. Files are validated by signature and container structure; the app never silently changes a selection.
3. For Mixed PDF, review the Native/OCR suggestion for each page, choose every page route, and confirm the table. For one scanned PDF, an inclusive contiguous page range remains available.
4. For scanned PDFs and images, choose the OCR engine, then Fast, Full, or Custom mode and the visual-recovery/chat toggles.
5. Select **Parse document** or **Process documents**. Batch files run sequentially and failures can be retried without rerunning completed files.
6. Review Markdown, JSON, Extract, and source structure. An annotated PDF appears only when the selected route produces a visual artifact; the ZIP includes only available artifacts.

Fast runs classification without Markdown refinement or TOC generation. Full enables refinement, classification, and TOC. Visual recovery is a separate toggle and defaults on when Luna is available. Extraction is configured and run inside the post-parse Extract tab. Chat appears only when enabled.

“ADE mode” is the UI label for these Luna-feature presets; it does not connect to an external ADE service.

Native PDFs use `pdf-inspector`; Word, PowerPoint, Excel, CSV, ODF, HTML, Markdown, and EPUB use Docling without OCR. Native extraction is optional and sends immutable `base_text`, never refined Markdown, to LangExtract. An accepted field must have an exact character interval that resolves to source anchors.

## Stop and restart

The launch scripts start detached WSL processes. To stop them, open WSL in the repository root and run:

```bash
for file in .runtime/vllm.pid .runtime/ollama.pid .runtime/paddle-vllm.pid .runtime/paddle-api.pid .runtime/streamlit.pid; do
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
| Paddle parse fails before layout | Confirm ports `8118` and `8119` are healthy and inspect both Paddle logs under `.runtime/` |
| Luna controls are disabled | Set `OPENAI_API_KEY` in the Windows user environment, then run `Launch-GLM-OCR.cmd` |
| Provider call fails | Use the displayed request ID, stage, page, and model; optional features fail independently |
| Block is `needs_review` | Compare its text with the highlighted source box and inspect `verification_reason` |
| Startup fails | Read `.runtime/vllm.log` and `.runtime/streamlit.log` |

See [setup](../SETUP.md) for every supported environment variable.
