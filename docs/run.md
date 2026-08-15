# Run locally

## Recommended Windows launcher

Run `Launch-Grounded-DocParse.cmd` on Windows 11 22H2 or newer. It installs or reuses `uv`, Python 3.12, the locked native environment, CPU PP-DocLayoutV3 assets, and Windows Ollama, then starts Streamlit natively on <http://localhost:7137>.

Keep its terminal open. It follows new Streamlit, GLM-OCR, PaddleOCR, and Ollama entries with source labels. When the app exits, the terminal preserves the final output until a key is pressed.

Use `Setup-GLM-OCR.cmd` or `Setup-PaddleOCR-VL-1.6.cmd` only to install and warm an explicit WSL GPU backend. GLM lives in `.venv`; Paddle and its compatible vLLM stack live in `.paddle-venv`. `Launch-Grounded-DocParse-WSL-Legacy.cmd` temporarily preserves the old WSL-hosted app.

## Manual commands

Inside WSL:

```bash
bash scripts/wsl/setup-glmocr.sh
bash scripts/wsl/launch-stack.sh
```

For foreground GPU-service development, keep vLLM in WSL and Streamlit on Windows:

```bash
bash scripts/wsl/serve-glmocr.sh
```

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\GroundedDocParse\venv"
$env:DOCPARSE_MANAGE_OCR_SERVICES = "true"
$env:DOCPARSE_STUDIO_DB_PATH = "$env:LOCALAPPDATA\GroundedDocParse\studio.sqlite3"
uv run --extra native --extra windows-layout streamlit run streamlit_app.py --server.port 7137
```

These two `DOCPARSE_*` values reproduce the managed launcher's WSL engine switching and durable workspace location. Without `DOCPARSE_MANAGE_OCR_SERVICES=true`, selecting a vLLM engine does not start or stop WSL services automatically.

The normal URLs are:

- GLM-OCR-compatible vLLM endpoint: <http://127.0.0.1:8080>
- PaddleOCR-VL vLLM endpoint: <http://127.0.0.1:8118>
- PaddleX full document parser: <http://127.0.0.1:8119>
- Streamlit: <http://localhost:7137>

Set Windows user variables `DOCPARSE_PADDLE_VLLM_PORT` and
`DOCPARSE_PADDLE_API_PORT` before launching to override the two Paddle defaults.
The ports must be distinct integers from 1 through 65535.

Cloud keys are optional. `Launch-Grounded-DocParse.cmd` reads OpenAI, Google, Agnes, and Ollama settings from the Windows User environment on every launch. Use custom endpoints only when trusted and compatible.

With a selected provider key present, enabled AI features may send crops or recognized context to that provider. AI enhancement defaults off and considers only failed or sub-75%-confidence regions. Disable all AI features for fully local operation.

The managed scripts bind Streamlit and OCR services to loopback. Do not expose ports `7137`, `8080`, `8118`, or `8119` to an untrusted network.

## Use the studio

1. Upload up to 20 supported PDFs, Office/open formats, CSV, HTML, EPUB, Markdown, or images (250 MB each and 1 GB combined).
2. Choose a compatible **Processing type** for every file. Files are validated by signature and container structure; the app never silently changes a selection.
3. For Mixed PDF, review the Native/OCR suggestion for each page, choose every page route, and confirm the table. For one scanned PDF, an inclusive contiguous page range remains available.
4. Select exactly one extraction engine. For Local Ollama, choose GLM-OCR, PaddleOCR-VL, or DeepSeek-OCR. Then configure Fast, Full, or Custom mode and optional AI enhancement/chat.
5. Select **Parse document** or **Process documents**. Batch files run sequentially and failures can be retried without rerunning completed files.
6. Review Markdown, JSON, Extract, and source structure. An annotated PDF appears only when the selected route produces a visual artifact; the ZIP includes only available artifacts.

Fast runs classification without Markdown refinement or TOC generation. Full enables refinement, classification, and TOC. AI enhancement is a separate toggle and defaults off. Extraction is configured and run inside the post-parse Extract tab. Chat appears only when enabled.

“ADE mode” is the UI label for optional AI-feature presets; it does not connect to an external ADE service.

Native PDFs use `pdf-inspector`; Word, PowerPoint, Excel, CSV, ODF, HTML, Markdown, and EPUB use Docling without OCR. Native extraction is optional and sends immutable `base_text`, never refined Markdown, to LangExtract. An accepted field must have an exact character interval that resolves to source anchors.

## Stop and restart

The native launcher records the verified Streamlit listener PID under `%LOCALAPPDATA%\GroundedDocParse\runtime`. Every launch discards stale PID entries, stops verified Grounded DocParse listeners on port `7137` and former ports `8600`/`9356`, clears Streamlit cache state, and starts a fresh session without deleting the durable workspace or stopping GPU OCR services. Unrelated listeners are left untouched; an unrelated listener on `7137` blocks startup.

The sidebar **Session cost** view reports launch-scoped token usage and estimated cost by cloud model plus a total. Restored workspace usage is intentionally not added to the new launch's ledger.

To stop only the verified WSL Streamlit app while keeping GLM/Paddle OCR warm, run:

```bash
bash scripts/wsl/stop-stack.sh 0 --app-only
```

To stop the verified WSL app and all managed WSL OCR services, omit the app-only option:

```bash
bash scripts/wsl/stop-stack.sh 0
```

The next launcher run recreates missing processes. The stop helper refuses a live PID whose command or working directory does not match this repository.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Browser is blank | Open the exact local URL and confirm `/_stcore/health` responds |
| Parse fails before layout | Confirm GLM-OCR is installed in WSL and vLLM exposes `glm-ocr` on port `8080` |
| Paddle parse fails before layout | Confirm ports `8118` and `8119` are healthy and inspect both Paddle logs under `.runtime/` |
| AI controls are disabled | Set the key required by the selected AI model in the Windows User environment, then relaunch |
| Provider call fails | Use the displayed request ID, stage, page, and model; optional features fail independently |
| Block is `needs_review` | Compare its text with the highlighted source box and inspect `verification_reason` |
| Startup fails | Read `%LOCALAPPDATA%\GroundedDocParse\logs\native-launch.log` and the relevant `.runtime` GPU-service log |

See [setup](../SETUP.md) for every supported environment variable.
