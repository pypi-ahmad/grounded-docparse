# Setup

> Last verified against this repository: 2026-07-30.

The supported local runtime is Windows 11 with Ubuntu 24.04 under WSL2 and an NVIDIA GPU. GLM-OCR and PP-DocLayout run inside WSL; Streamlit is launched from the same locked Linux environment. Native Windows does not install the `local-ocr` dependency because its package markers are Linux-only.

## Prerequisites

- Windows 11 with WSL support
- NVIDIA Windows driver with WSL GPU passthrough
- Network access during first setup for Python packages and model weights
- Enough disk space for the WSL virtual environment and model cache
- Git for obtaining the repository

Obtain the repository from PowerShell:

```powershell
git clone https://github.com/pypi-ahmad/grounded-docparse.git
Set-Location grounded-docparse
```

Check WSL and GPU visibility from PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
wsl --list --verbose
wsl -d Ubuntu-24.04 -- nvidia-smi
```

Restart Windows if WSL installation requests it. The first Ubuntu launch may ask for a UNIX username and password.

## Automated Windows setup

From the repository root, run:

```powershell
.\Setup-GLM-OCR.cmd
```

The script:

1. checks for `wsl.exe` and Ubuntu 24.04;
2. requests elevation only when the distribution must be installed;
3. verifies `nvidia-smi` inside WSL;
4. refreshes `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` from the Windows user environment, then passes them and the repository path into WSL;
5. runs `scripts/wsl/launch-stack.sh`;
6. opens <http://localhost:8501> after vLLM and Streamlit are healthy.

If `uv` is not already available inside WSL, the first run installs `uv` 0.11.32 after verifying the installer checksum; otherwise it uses the existing executable. It then installs Python 3.12.10, creates `~/.local/share/grounded-docparse/.venv`, and runs `uv sync --locked --extra local-ocr`. Setup downloads exact GLM-OCR and PP-DocLayoutV3 revisions into the WSL Hugging Face cache and generates `.runtime/glmocr.yaml` with the resolved local layout-model path. Later launches are cache-only and fail instead of silently accessing the network.

For later sessions:

```powershell
.\Launch-GLM-OCR.cmd
```

Both launchers reuse healthy processes. Runtime logs and PID files are stored under the ignored `.runtime/` directory.

To keep using the Windows launcher with custom parser/provider settings, add the required `export NAME=value` lines to the WSL user's `~/.profile`, then restart the affected managed process. The launcher enters WSL through `bash -lc`, so login-profile exports are inherited. `scripts/wsl/run-app.sh` forces local OCR on and uses the generated runtime configuration; `DOCPARSE_GLMOCR_LAYOUT_DEVICE` remains overridable and defaults to `cuda:0`.

## Manual WSL setup and launch

Run the following inside Ubuntu from the repository mounted under `/mnt/<drive>/...`:

```bash
bash scripts/wsl/setup-glmocr.sh
```

Then use two WSL terminals:

```bash
# Terminal 1: vLLM on port 8080
bash scripts/wsl/serve-glmocr.sh
```

```bash
# Terminal 2: Streamlit on port 8501
bash scripts/wsl/run-app.sh
```

Or start/reuse both detached services and wait for their health checks:

```bash
bash scripts/wsl/launch-stack.sh
```

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

The Windows launcher reads user scope directly, so a newly saved value does not require reopening the terminal. It restarts a managed Streamlit process when either Luna value changes. An unmanaged process on port `8501` is never restarted or adopted. Never store a real key in `.env`, Markdown, scripts, commits, or issue reports. The model identifier is fixed in code as `gpt-5.6-luna`.

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
| `DOCPARSE_MAX_VISUAL_RECOVERY_CROPS` | `8` | Document-wide recovery-crop limit |
| `DOCPARSE_PAGE_BATCH_SIZE` | `16` | Ordered page-window size |
| `DOCPARSE_MAX_PAGE_CONCURRENCY` | `8` | Page worker limit; cannot exceed batch size |
| `DOCPARSE_PROVIDER_CONCURRENCY` | `8` | Shared provider-call limit |
| `DOCPARSE_PROVIDER_RETRY_ATTEMPTS` | `3` | Total attempts for retryable provider failures |
| `DOCPARSE_PROVIDER_RETRY_BASE_SECONDS` | `0.5` | Exponential-backoff base |
| `DOCPARSE_PROVIDER_RETRY_CAP_SECONDS` | `8.0` | Backoff cap |
| `DOCPARSE_PROVIDER_COOLDOWN_SECONDS` | `1.0` | Minimum cooldown after HTTP 429 |
| `DOCPARSE_PROVIDER_SUCCESS_WINDOW` | `10` | Successes before reduced concurrency increases |
| `DOCPARSE_LOCAL_OCR_ENABLED` | `true` | Enables local GLM analysis |
| `DOCPARSE_GLMOCR_CONFIG_PATH` | `config/glmocr.yaml` | GLM-OCR SDK configuration |
| `DOCPARSE_GLMOCR_LAYOUT_DEVICE` | `cuda:0` | Layout-model device |

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
curl --fail --silent http://127.0.0.1:8501/_stcore/health
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
| Port `8080` or `8501` is occupied | Stop the unrelated listener; the launcher refuses to take over unmanaged processes |
| GLM-OCR import fails | Rerun `scripts/wsl/setup-glmocr.sh`; do not use the native Windows environment for local OCR |
| A pinned snapshot is missing in offline mode | Connect once and rerun `scripts/wsl/setup-glmocr.sh`; normal launch never falls back to a network download |
| Luna controls are unavailable | Set `OPENAI_API_KEY` before starting Streamlit |
| Startup times out | Inspect `.runtime/vllm.log` and `.runtime/streamlit.log` |

Other serving backends and standalone PaddleOCR pipelines are not implemented or managed by this repository.

The repository does not claim a minimum GPU VRAM, RAM, disk footprint, or first-download duration. Validate the locked stack on the target workstation; reduce the documented vLLM settings if it does not fit.

Setup is not automatically uninstalled. The known project-created environment is `${DOCPARSE_WSL_ENV:-~/.local/share/grounded-docparse/.venv}`, runtime files are under `.runtime/`, and pinned snapshots use the WSL Hugging Face cache under `~/.cache/huggingface/hub` unless the operator has configured another Hub cache. Inspect and remove those locations deliberately when decommissioning; stopping processes does not delete them.
