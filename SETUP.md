# Setup

> Last verified against this repository: 2026-08-12.

The supported local runtime is Windows 10 22H2 or Windows 11 x64 with Ubuntu 24.04 under WSL2. GLM-OCR retains NVIDIA vLLM and Ollama fallback support. PaddleOCR-VL-1.6 requires NVIDIA compute capability 8.0 or newer and CUDA 12.6 or newer for its vLLM recognition service; it fails closed rather than silently using GLM. The two OCR dependency stacks use separate locked environments. Native document parsing is available with the `native` extra and does not require local OCR or a GPU.

## Prerequisites

- Windows 10 22H2 or Windows 11 x64 with AVX2
- At least 16 GB RAM and 20 GB free disk; 40 GB is recommended when both model caches are populated
- Network access during first setup for Python packages and model weights
- Administrator approval when Windows must enable WSL2

Obtain the repository from PowerShell:

```powershell
git clone https://github.com/pypi-ahmad/grounded-docparse.git
Set-Location grounded-docparse
```

The release installer bundles the application, so target computers do not need Git. Source checkouts still require Git.

## Automated Windows setup

From the repository root, run:

```powershell
.\Setup-GLM-OCR.cmd
```

The setup assistant:

1. validates Windows, AVX2, RAM, and disk;
2. installs or reuses WSL2 and Ubuntu 24.04, resuming after restart when required;
3. reuses the Ubuntu user or securely creates one without persisting its password;
4. installs only missing or stale locked local-OCR and native-document dependencies;
5. tries NVIDIA CUDA, otherwise installs Ollama `glm-ocr:bf16`; supported AMD GPUs accelerate Ollama and unsupported GPUs use CPU;
6. validates a real image request, starts Streamlit, and opens <http://localhost:8600>.

Setup pins `uv` 0.11.32, Python 3.12.10, GLM-OCR, PP-DocLayoutV3, and Ollama 0.32.0. GPU installs use both the `local-ocr` and `native` extras; CPU/AMD installs use `local-ocr-cpu` and `native`. The native extra installs `pdf-inspector`, Docling, and LangExtract. Lock hashes and readiness markers skip healthy dependencies. App-owned models live under `~/.local/share/grounded-docparse`; later launches are offline.

## Native document ingestion

For local native-document development on Windows or WSL, install the native extra:

```powershell
uv sync --locked --extra native
```

Native parsing is local and non-OCR: `pdf-inspector` extracts selectable-text PDF structure, while Docling converts DOCX, PPTX, XLSX, CSV, ODF, HTML, Markdown, and EPUB with OCR, VLM/model enrichments, remote services, and plugins disabled. Native embedded images are recorded as assets and are not OCRed. Optional LangExtract field extraction uses the OpenAI credentials described below.

The Streamlit app requires a compatible selection for each uploaded file. The CLI exposes the same contract through `ingest`: PDFs use `native-pdf`, `scanned-pdf`, or `mixed-pdf`; Office and open formats use `word`, `powerpoint`, `excel`, `csv`, or `other-native`; images use `image`. File signatures and Office/container structure are validated after selection.

```powershell
uv run grounded-docparse ingest .\invoice.pdf `
  --processing-type .\invoice.pdf=native-pdf `
  --output .\output
```

Mixed PDFs require a route for every page. The app shows `pdf-inspector` suggestions for review; the CLI receives the confirmed routes explicitly:

```powershell
uv run grounded-docparse ingest .\mixed.pdf `
  --processing-type .\mixed.pdf=mixed-pdf `
  --page-route .\mixed.pdf#1=native `
  --page-route .\mixed.pdf#2=ocr `
  --output .\output
```

Native results contain immutable `base_text`, character-to-source spans, and source anchors. A native PDF with pages that need OCR stops and asks for Mixed PDF rather than falling back automatically. The legacy `grounded-docparse parse` command remains available for PDF/image OCR batches.

### Build the installer

Install Inno Setup 6, then run:

```powershell
.\scripts\build-installer.ps1
```

The build creates `dist\GroundedDocParse-<version>-Setup.exe` and a SHA-256 file. The artifact is unsigned because no public-trusted signing certificate is configured; Windows SmartScreen may warn.

For later sessions:

```powershell
.\Launch-GLM-OCR.cmd
```

Use `.\Launch-PaddleOCR-VL-1.6.cmd` to start with Paddle selected. Both launchers open the same app. The dropdown can switch engines later; the manager serializes transitions, refuses unmanaged port owners, stops the old GPU service, and starts the selected one. Only one VLM service is resident on the supported 8 GB workstation profile.

To keep using the Windows launcher with custom parser/provider settings, add the required `export NAME=value` lines to the WSL user's `~/.profile`, then restart the affected managed process. `scripts/wsl/run-app.sh` forces local OCR on and uses the generated runtime configuration. Layout uses `cuda:0` with vLLM and `cpu` with Ollama.

## Manual WSL setup and launch

Run the following inside Ubuntu from the repository mounted under `/mnt/<drive>/...`:

```bash
bash scripts/wsl/setup-glmocr.sh
```

Set `DOCPARSE_LOCAL_OCR_BACKEND=vllm` or `ollama` to force one backend. Without it, setup chooses vLLM only when `nvidia-smi` succeeds inside WSL.

Then use two WSL terminals:

```bash
# Terminal 1a: vLLM on port 8080
bash scripts/wsl/serve-glmocr.sh
```

For Ollama instead:

```bash
bash scripts/wsl/serve-ollama.sh
```

```bash
# Terminal 2: Streamlit on port 8600
bash scripts/wsl/run-app.sh
```

Or start/reuse both detached services and wait for their health checks:

```bash
bash scripts/wsl/launch-stack.sh
```

For PaddleOCR-VL-1.6, provision its isolated runtime and select it at launch:

```bash
bash scripts/wsl/setup-paddleocr.sh
DOCPARSE_START_ENGINE=paddleocr-vl-1.6 bash scripts/wsl/launch-stack.sh
```

See [Local PaddleOCR-VL-1.6 runtime](docs/local-paddleocr-vl.md) for the dedicated installation guide, health checks, configuration, and troubleshooting.

The official full pipeline runs PaddleOCR-VL-1.6-0.9B behind `paddleocr genai_server` on `127.0.0.1:8118`, and PP-DocLayoutV3 plus document parsing behind PaddleX on `127.0.0.1:8119`. PP-DocLayoutV3 runs on CPU so the 8 GB GPU remains available to vLLM. The first successful setup downloads the VLM, layout model, and required visualization font into `${PADDLE_PDX_CACHE_HOME:-~/.paddlex}`. Later starts validate those files and pass their local paths to both services with offline mode enabled, so they do not download again. Startup then requires API discovery and an end-to-end `/layout-parsing` probe.

GLM-OCR declares 131072 maximum positions, but this 8GB workstation cannot provision one 128K request: at the verified 0.85 GPU fraction vLLM exposes about 62176 KV-cache tokens. The launcher therefore serves a deliberate 32768-token ceiling, which comfortably contains the SDK's 8192-token output allowance plus the cropped-region image/prompt tokens. Raising the server to 128K is unsupported on this profile.

The vLLM command serves the pinned GLM-OCR snapshot as `glm-ocr`, uses three-token MTP speculation, 85% GPU memory, throughput mode, and a 1GB multimodal processor cache. Multimodal startup profiling remains disabled because it previously exhausted the 18GB WSL memory limit; `launch-stack.sh` compensates by requiring a real image-recognition request before declaring vLLM ready. The source `config/glmocr.yaml` contains the complete task, label, layout, and formatter contract. The generated `.runtime/glmocr.yaml` changes only the pinned layout path and selected SDK worker count.

`scripts/wsl/serve-glmocr.sh` binds vLLM to `127.0.0.1`, and `scripts/wsl/run-app.sh` binds Streamlit to `127.0.0.1`. These launchers support the documented single-workstation deployment only. A cloud or shared deployment requires a separate security design with authentication, TLS termination, quotas, and tenant isolation.

## Luna configuration

GLM parsing does not require an OpenAI credential. Set user-level values only when Luna recovery or agentic features are required:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "...", "User")
# Optional custom compatible endpoint:
# [Environment]::SetEnvironmentVariable("OPENAI_BASE_URL", "https://.../v1", "User")
.\Launch-GLM-OCR.cmd
```

The Windows launcher reads user scope directly, so a newly saved value does not require reopening the terminal. It restarts a managed Streamlit process when either Luna value changes. An unmanaged process on port `8600` is never restarted or adopted. Never store a real key in `.env`, Markdown, scripts, commits, or issue reports. The model identifier is fixed in code as `gpt-5.6-luna`.

## Configuration reference

`ParserConfig.from_env()` reads these variables. Values shown are code defaults.

| Variable | Default | Purpose |
| --- | ---: | --- |
| `DOCPARSE_RENDER_DPI` | `200` | Raster DPI for PDF pages |
| `DOCPARSE_CROP_DPI` | `450` | Rerender DPI for source crops |
| `DOCPARSE_CROP_PADDING` | `0.1` | Fractional padding around a crop |
| `DOCPARSE_MAX_UPLOAD_BYTES` | `262144000` | Parser upload-byte limit |
| `DOCPARSE_MAX_PAGES` | `500` | Maximum pages or image frames |
| `DOCPARSE_MAX_PAGE_PIXELS` | `20000000` | Maximum rendered pixels per page |
| `DOCPARSE_LUNA_MAX_OUTPUT_TOKENS` | `128000` | Upper bound used by Luna calls; individual stages apply smaller caps |
| `DOCPARSE_MAX_VISUAL_RECOVERY_CROPS` | `64` | Absolute Luna recovery-crop ceiling per document |
| `DOCPARSE_PAGE_BATCH_SIZE` | `16` | Ordered page-window size |
| `DOCPARSE_MAX_PAGE_CONCURRENCY` | `8` | Page worker limit; cannot exceed batch size |
| `DOCPARSE_PROVIDER_CONCURRENCY` | `8` | Shared provider-call limit |
| `DOCPARSE_PROVIDER_RETRY_ATTEMPTS` | `3` | Total attempts for retryable provider failures |
| `DOCPARSE_PROVIDER_RETRY_BASE_SECONDS` | `0.5` | Exponential-backoff base |
| `DOCPARSE_PROVIDER_RETRY_CAP_SECONDS` | `8.0` | Backoff cap |
| `DOCPARSE_PROVIDER_COOLDOWN_SECONDS` | `1.0` | Minimum cooldown after HTTP 429 |
| `DOCPARSE_PROVIDER_SUCCESS_WINDOW` | `10` | Successes before reduced concurrency increases |
| `DOCPARSE_LOCAL_OCR_ENABLED` | `true` | Enables local GLM analysis |
| `DOCPARSE_OCR_ENGINE` | `glm-ocr` | `glm-ocr` or `paddleocr-vl-1.6` |
| `DOCPARSE_GLMOCR_CONFIG_PATH` | `config/glmocr.yaml` | GLM-OCR SDK configuration |
| `DOCPARSE_GLMOCR_LAYOUT_DEVICE` | `cuda:0` | Layout-model device |
| `DOCPARSE_PADDLEOCR_SERVICE_URL` | `http://127.0.0.1:8119` | Loopback-only full PaddleX document-parser API; remote origins are rejected because document bytes are posted here |
| `DOCPARSE_PADDLEOCR_TIMEOUT_SECONDS` | `900` | Local full-document request timeout |
| `DOCPARSE_PADDLE_VLLM_PORT` | `8118` | Loopback port for PaddleOCR-VL recognition |
| `DOCPARSE_PADDLE_API_PORT` | `8119` | Loopback port for the full PaddleX parser; launchers derive the service URL from it |
| `PADDLE_PDX_CACHE_HOME` | `~/.paddlex` | Persistent Paddle model/font cache; keep this path stable to avoid downloading assets again |

Additional application/runtime variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOCPARSE_PRELOAD_LOCAL_OCR` | `false` | Preloads GLM-OCR at Streamlit startup; WSL launcher sets `true` |
| `DOCPARSE_STUDIO_DB_PATH` | `data/document_studio.sqlite3` | Reusable schema database |
| `DOCPARSE_WSL_ENV` | `~/.local/share/grounded-docparse/.venv` | WSL virtual-environment path |
| `GLMOCR_GPU_MEMORY_UTILIZATION` | `0.85` | vLLM GPU-memory fraction |
| `GLMOCR_MAX_MODEL_LEN` | `32768` | vLLM context length; must accommodate the 8192-token OCR output allowance plus input tokens |
| `GLMOCR_PERFORMANCE_MODE` | `throughput` | vLLM runtime mode; measured about 13% faster than balanced on the representative form page |
| `GLMOCR_MM_PROCESSOR_CACHE_GB` | `1` | Per-process multimodal cache; matched 4GB performance within 1% while reducing WSL memory pressure |
| `GLMOCR_SDK_MAX_WORKERS` | `16` | Region-recognition workers written into the generated SDK config; 32 did not improve the measured workload |

Analysis thresholds use `DOCPARSE_ANALYSIS_<FIELD>`. These variables and defaults map directly to `AnalysisThresholds` in `src/grounded_docparse/config.py`:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `DOCPARSE_ANALYSIS_BLANK_FOREGROUND_RATIO` | `0.001` | Maximum foreground ratio for treating a page as blank |
| `DOCPARSE_ANALYSIS_SKEW_DEGREES` | `1.0` | Absolute rotation threshold for a skew warning |
| `DOCPARSE_ANALYSIS_MIN_EDGE_VARIANCE` | `80.0` | Minimum edge variance before blur is flagged |
| `DOCPARSE_ANALYSIS_MIN_CONTRAST_RANGE` | `40.0` | Minimum grayscale range before low contrast is flagged |
| `DOCPARSE_ANALYSIS_CLIPPING_BORDER_RATIO` | `0.05` | Border-foreground ratio above which clipping is flagged |
| `DOCPARSE_ANALYSIS_MIN_EFFECTIVE_DPI` | `150.0` | Minimum known effective DPI |
| `DOCPARSE_ANALYSIS_MIN_SHORT_EDGE_PIXELS` | `900` | Resolution fallback when effective DPI is unavailable |
| `DOCPARSE_ANALYSIS_TABLE_FORM_AREA_RATIO` | `0.25` | Page-area threshold for table/form complexity |
| `DOCPARSE_ANALYSIS_VISUAL_AREA_RATIO` | `0.35` | Page-area threshold for figure complexity |
| `DOCPARSE_ANALYSIS_UNKNOWN_AREA_RATIO` | `0.3` | Page-area threshold for unknown-region complexity |
| `DOCPARSE_ANALYSIS_COMPLEX_REGION_COUNT` | `10` | Region-count threshold for a complex page |

`DOCPARSE_FULL_PAGE_FALLBACK_FRACTION` remains accepted by `ParserConfig` for compatibility, but the current strict application path does not perform Luna full-page fallback.

Set `GLMOCR_*` variables and `DOCPARSE_WSL_ENV` inside WSL. The Windows launchers forward only `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and the repository path.

## Verification

Check the services:

```bash
# In WSL from the repository root:
source ~/.local/share/grounded-docparse/.venv/bin/activate
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python scripts/wsl/prepare_glmocr_runtime.py --offline
python scripts/wsl/check-glmocr-api.py
curl --fail --silent http://127.0.0.1:8600/_stcore/health
```

Reproduce the warm page benchmark without Luna or model-load time:

```bash
python scripts/wsl/benchmark_glmocr.py examples/synthetic-report.pdf \
  --page 1 --layout-device cuda:0 --warmups 1 --runs 5
```

Check the repository without live provider calls:

```powershell
uv sync --locked
uv run pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
```

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Ubuntu 24.04 is missing | Run `wsl --install -d Ubuntu-24.04`, finish first-login setup, then rerun the setup command |
| `nvidia-smi` fails inside WSL | Update the Windows NVIDIA driver and WSL; do not install a separate Linux display driver inside WSL |
| vLLM runs out of memory | Stop competing GPU processes and inspect `.runtime/vllm.log`; do not lower the 32768 context while `page_loader.max_tokens` remains 8192 |
| `/v1/models` works but recognition fails | Run `scripts/wsl/check-glmocr-api.py`; `launch-stack.sh` automatically restarts a managed server that fails this inference check |
| Port `8080` or `8600` is occupied | Stop the unrelated listener; the launcher refuses to take over unmanaged processes |
| Port `8118` or `8119` is occupied | Stop the unrelated listener; Paddle services are never adopted when ownership cannot be verified |
| Paddle startup fails | Inspect `.runtime/paddle-vllm.log` and `.runtime/paddle-api.log`; confirm NVIDIA compute capability 8.0+ and CUDA 12.6+ |
| GLM-OCR import fails | Rerun `scripts/wsl/setup-glmocr.sh`; do not use the native Windows environment for local OCR |
| A pinned snapshot is missing in offline mode | Connect once and rerun `scripts/wsl/setup-glmocr.sh`; normal launch never falls back to a network download |
| Luna controls are unavailable | Set `OPENAI_API_KEY` before starting Streamlit |
| Startup times out | Inspect `.runtime/vllm.log` and `.runtime/streamlit.log` |

Other Paddle recognition backends and standalone recognition-only modes are not implemented or managed by this repository.

The repository does not claim a minimum GPU VRAM, RAM, disk footprint, or first-download duration. Validate the locked stack on the target workstation; reduce the documented vLLM settings if it does not fit.

Setup is not automatically uninstalled. The known project-created environment is `${DOCPARSE_WSL_ENV:-~/.local/share/grounded-docparse/.venv}`, runtime files are under `.runtime/`, and pinned snapshots use the WSL Hugging Face cache under `~/.cache/huggingface/hub` unless the operator has configured another Hub cache. Inspect and remove those locations deliberately when decommissioning; stopping processes does not delete them.
