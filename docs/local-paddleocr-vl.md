# Local PaddleOCR-VL-1.6 runtime

The PaddleOCR-VL vLLM runtime remains in Ubuntu 24.04 under WSL2 while the app runs natively on Windows 11. It requires an NVIDIA GPU with compute capability 8.0 or newer and CUDA 12.6 or newer.

PaddleOCR-VL uses a separate locked Python 3.12.10 environment so its PaddlePaddle and vLLM dependencies do not conflict with the main GLM environment. The default path is `~/.local/share/grounded-docparse/.paddle-venv`; override it with `DOCPARSE_PADDLE_WSL_ENV`.

## Recommended Windows installation

Launch the native app from PowerShell, then provision Paddle when needed:

```powershell
.\Launch-Grounded-DocParse.cmd
```

Then launch PaddleOCR-VL:

```powershell
.\Setup-PaddleOCR-VL-1.6.cmd
```

The first Paddle setup creates the isolated WSL environment, downloads the PaddleOCR-VL-1.6-0.9B model, PP-DocLayoutV3, and required font, starts both Paddle services, and performs an end-to-end image probe. The native Streamlit process remains separate. Later starts validate and reuse cached assets.

The launcher fails closed if WSL, the GPU runtime, model assets, health checks, or required ports are unavailable. It does not silently switch the parse to GLM-OCR.

## Manual WSL installation

From the repository mounted inside Ubuntu 24.04:

```bash
bash scripts/wsl/setup-paddleocr.sh
bash scripts/wsl/manage-ocr-stack.sh ensure paddleocr-vl-1.6
```

The setup uses `paddle-runtime/pyproject.toml` and `paddle-runtime/uv.lock`. The locked runtime includes PaddleOCR 3.7.0, PaddlePaddle 3.3.1, PaddleX 3.7.0, and their compatible vLLM server stack. Do not install these packages into the main project environment.

By default, model and font assets are stored under `~/.paddlex`. Set `PADDLE_PDX_CACHE_HOME` before the first setup to use another persistent location:

```bash
export PADDLE_PDX_CACHE_HOME=/path/to/persistent/paddlex-cache
bash scripts/wsl/setup-paddleocr.sh
```

Keep that setting stable. Later launches run with Hugging Face and Transformers offline modes enabled and require the cached assets to be complete.

## Runtime architecture

The managed stack runs:

- PaddleOCR-VL-1.6-0.9B recognition through `paddleocr genai_server` on `127.0.0.1:8118`;
- PP-DocLayoutV3 and the full PaddleX document parser on CPU at `127.0.0.1:8119`; and
- Streamlit at <http://localhost:7137>.

Keeping layout on CPU reserves the supported 8 GB GPU profile for vLLM recognition. The generated pipeline configuration is `.runtime/paddleocr-vl-1.6.yaml`; vLLM settings are defined in `config/paddle-vllm.yaml`.

The application submits each complete document to the local PaddleX API. Paddle owns recognized regions, geometry, types, confidence, and reading order. For PDF checkbox tables with missing states, local recovery accepts a state only when independent 190 and 200 DPI parses agree.

Only one managed VLM backend is kept resident. Selecting GLM-OCR or PaddleOCR-VL-1.6 in the application stops the previous managed GPU service before starting the requested one. An unmanaged process occupying a required port is never adopted or terminated.

## Health checks

Inside WSL, verify the two services:

```bash
curl --fail http://127.0.0.1:8118/health
curl --fail http://127.0.0.1:8118/v1/models
curl --fail http://127.0.0.1:8119/openapi.json
```

The model response must identify PaddleOCR-VL-1.6, and the PaddleX OpenAPI document must expose `/layout-parsing`. Run the repository's end-to-end probe with:

```bash
DOCPARSE_PADDLEOCR_SERVICE_URL=http://127.0.0.1:8119 \
  "${DOCPARSE_PADDLE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.paddle-venv}/bin/python" \
  scripts/wsl/check-paddleocr-api.py
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOCPARSE_PADDLE_WSL_ENV` | `~/.local/share/grounded-docparse/.paddle-venv` | Isolated Paddle Python environment |
| `PADDLE_PDX_CACHE_HOME` | `~/.paddlex` | Persistent model and font cache |
| `DOCPARSE_PADDLE_VLLM_PORT` | `8118` | Loopback recognition-service port |
| `DOCPARSE_PADDLE_API_PORT` | `8119` | Loopback PaddleX parser port |
| `DOCPARSE_PADDLEOCR_SERVICE_URL` | `http://127.0.0.1:8119` | Application-facing parser endpoint |
| `DOCPARSE_PADDLEOCR_TIMEOUT_SECONDS` | `120` | Full-document request timeout |

When launching from Windows, set port overrides as Windows user environment variables before running the launcher. Both values must be distinct integers from 1 through 65535.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `uv is unavailable in WSL` | Rerun `.\Setup-PaddleOCR-VL-1.6.cmd`; its provisioner installs missing WSL prerequisites. |
| CUDA or compute-capability check fails | Update the NVIDIA Windows driver and confirm `nvidia-smi` works inside Ubuntu 24.04. Paddle recognition has no CPU fallback. |
| Cache is incomplete | Run `.\Setup-PaddleOCR-VL-1.6.cmd` once while online. Keep `PADDLE_PDX_CACHE_HOME` unchanged afterward. |
| Port `8118` or `8119` is occupied | Stop the process deliberately or configure two unused ports. The manager refuses unmanaged listeners. |
| Recognition service does not become healthy | Inspect `.runtime/paddle-vllm.log`. |
| PaddleX starts but parsing fails | Inspect `.runtime/paddle-api.log`, then run `scripts/wsl/check-paddleocr-api.py`. |
| Streamlit does not open | Inspect `%LOCALAPPDATA%\GroundedDocParse\logs\streamlit.err.log` and check <http://127.0.0.1:7137/_stcore/health>. |

Runtime PID files and generated configurations live under `.runtime/`. Model assets remain in `PADDLE_PDX_CACHE_HOME`, and the isolated environment remains at `DOCPARSE_PADDLE_WSL_ENV`; stopping services does not remove either location.
