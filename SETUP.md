# Cross-platform local OCR setup

> Last verified: 2026-07-28. This guide sets up the complete local document-parsing pipelines for [GLM-OCR](https://github.com/zai-org/GLM-OCR) and [PaddleOCR-VL-1.6](https://paddlepaddle.github.io/PaddleX/3.7/en/pipeline_usage/tutorials/ocr_pipelines/PaddleOCR-VL.html). It uses a GPU when an officially supported route exists, then falls back to local CPU inference.

On Windows 11 with an NVIDIA GPU, `Setup-GLM-OCR.cmd` in the repo root automates
this guide's Windows 11 + vLLM route end to end (sections 1, 3-Windows, 4, 9, 10),
including weight downloads. Use the manual steps below for other platforms, SGLang,
MLX, Ollama, AMD ROCm, or PaddleOCR-VL.

## 1. Choose a route

Do this before installing anything. A VLM server is only the recognition component: the GLM-OCR SDK and PaddleX pipeline still run layout analysis, region handling, reading order, and result assembly.

| System and hardware | GLM-OCR recommended route | PaddleOCR-VL-1.6 recommended route | Status |
| --- | --- | --- | --- |
| Windows 11 + NVIDIA GPU | WSL2 Ubuntu, vLLM or SGLang | WSL2 Ubuntu, PaddleX + vLLM/SGLang | Recommended |
| Ubuntu/Fedora + NVIDIA GPU | vLLM or SGLang | PaddleX + vLLM/SGLang | Recommended |
| Ubuntu/Fedora + supported AMD ROCm GPU | vLLM or SGLang ROCm | PaddleX CPU fallback | GLM accelerated; Paddle GPU route not provided here |
| Apple Silicon Mac | MLX server | Use a supported Linux host for PaddleOCR-VL | GLM accelerated; no documented local PaddleX route |
| Intel Mac, Windows without WSL, or CPU-only Linux | Ollama | PaddleX CPU pipeline | Functional, slow |

`vLLM` does not support Windows natively; use WSL2 for its Windows route. vLLM's supported GPU setup is Linux and Python 3.9–3.12. See [vLLM GPU installation](https://docs.vllm.ai/en/v0.9.1/getting_started/installation/gpu.html). PaddleX documents detailed local installation for Linux; non-Linux PaddleX paths below are a best-effort CPU fallback and must be validated on the target machine. See [PaddleX installation](https://paddlepaddle.github.io/PaddleX/3.7/en/installation/installation.html).

## 2. Versions and conventions

Use Python 3.12 and isolated environments. These pins are reproducible installation baselines, not a claim that every combination is upstream-tested. Keep server and client environments separate.

| Component | Pin / source |
| --- | --- |
| GLM-OCR SDK | `glmocr==0.1.5` |
| Transformers | `transformers==5.14.1` |
| vLLM | `vllm==0.19.1` |
| SGLang | `sglang==0.5.16` |
| PaddlePaddle CPU | `paddlepaddle==3.3.1` |
| PaddlePaddle CUDA | `paddlepaddle-gpu==3.3.0` from Paddle's matching CUDA index |
| PaddleX | `paddlex==3.7.2` |

Install [uv](https://docs.astral.sh/uv/) once per operating system. Linux/macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

Windows PowerShell:

```powershell
winget install --id=astral-sh.uv -e
uv --version
```

Create a work directory. Keep Linux code and virtual environments in the Linux filesystem for best WSL performance; use `/mnt/d/...` only for documents you want shared with Windows.

```bash
mkdir -p ~/ai-doc-ocr/{input,output,glm-sdk,glm-server,paddle-client,paddle-server}
export OCR_HOME="$HOME/ai-doc-ocr"
```

For Windows-only CPU usage, use `D:\AI\ai-doc-ocr` as `OCR_HOME`. PowerShell paths do not work inside WSL; their equivalent is `/mnt/d/AI/ai-doc-ocr`.

Windows PowerShell CPU workspace and environment activation:

```powershell
$env:OCR_HOME = 'D:\AI\ai-doc-ocr'
New-Item -ItemType Directory -Force -Path "$env:OCR_HOME\input", "$env:OCR_HOME\output", "$env:OCR_HOME\glm-sdk", "$env:OCR_HOME\paddle-client"
Set-Location "$env:OCR_HOME\glm-sdk"
uv venv --python 3.12 --seed
.\.venv\Scripts\Activate.ps1
```

## 3. Platform prerequisites

### Windows 11

For NVIDIA GPU serving, run PowerShell as Administrator, install WSL2, restart if prompted, then perform the Ubuntu instructions in this guide:

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
wsl --list --verbose
```

Install the current Windows NVIDIA driver, not a Linux driver inside WSL. In Ubuntu, verify GPU visibility:

```bash
nvidia-smi
```

Microsoft documents [WSL installation](https://learn.microsoft.com/en-us/windows/wsl/install) and [GPU acceleration in WSL](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gpu-compute). For direct Windows CPU-only GLM-OCR, install Ollama using its [official installer](https://ollama.com/download).

### Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y git curl build-essential python3.12 python3.12-venv
```

For NVIDIA, install a current driver through Ubuntu or NVIDIA, reboot, then run `nvidia-smi`. For AMD, install the ROCm version required by the selected vLLM/SGLang release, reboot, then run `rocminfo`. Do not mix CUDA and ROCm packages in one environment.

### Fedora

```bash
sudo dnf upgrade --refresh -y
sudo dnf install -y git curl gcc gcc-c++ make python3.12 python3.12-devel
```

Install the NVIDIA or ROCm driver stack from its vendor documentation before creating Python environments. Verify with `nvidia-smi` or `rocminfo`. Fedora package and driver combinations change frequently; use the driver release supported by the chosen CUDA/ROCm backend.

### macOS

Apple Silicon users need macOS 14+ for GLM-OCR's upstream MLX guide. Install Xcode command-line tools and verify hardware:

```bash
xcode-select --install
uname -m
system_profiler SPDisplaysDataType
```

Expect `arm64` on Apple Silicon. Intel Macs use CPU fallback.

## 4. GLM-OCR: NVIDIA GPU with vLLM

Use this on Ubuntu, Fedora, or Ubuntu under WSL2 with an NVIDIA GPU. Start from the conservative 8 GiB profile, prove one document works, then raise limits only if VRAM permits.

```bash
cd "$OCR_HOME/glm-server"
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install "transformers==5.14.1" "vllm==0.19.1"

# Put only documents you intend the server to read under this directory.
export OCR_INPUT_ROOT="$OCR_HOME/input"

vllm serve zai-org/GLM-OCR \
  --host 127.0.0.1 \
  --port 8080 \
  --served-model-name glm-ocr \
  --dtype auto \
  --gpu-memory-utilization 0.80 \
  --max-model-len 8192 \
  --max-num-batched-tokens 8192 \
  --allowed-local-media-path "$OCR_INPUT_ROOT" \
  --speculative-config '{"method":"mtp","num_speculative_tokens":3}'
```

First startup downloads model files. Keep server terminal open. Do **not** use `--allowed-local-media-path /`: it unnecessarily exposes every readable local file to requests accepted by the server.

If startup fails because the selected vLLM wheel and driver do not match, recreate the environment and let uv select the torch backend:

```bash
uv pip install "vllm==0.19.1" --torch-backend=auto
```

The model's upstream guide requires vLLM `>=0.19.0` and documents MTP serving options. See [GLM-OCR self-hosting](https://github.com/zai-org/GLM-OCR#model-deployment).

## 5. GLM-OCR: NVIDIA GPU with SGLang

Use SGLang instead of vLLM, never in the same server environment. SGLang's current installation guide uses Python 3.10+ and recommends `uv`.

```bash
cd "$OCR_HOME/glm-server"
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install --prerelease=allow "sglang==0.5.16"

SGLANG_ENABLE_SPEC_V2=1 sglang serve \
  --model-path zai-org/GLM-OCR \
  --host 127.0.0.1 \
  --port 8080 \
  --served-model-name glm-ocr \
  --mem-fraction-static 0.80 \
  --context-len 8192 \
  --speculative-algorithm NEXTN \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4
```

If SGLang's CUDA default conflicts with an installed CUDA 12 stack, follow its documented CUDA 12 wheel procedure rather than mixing arbitrary Torch wheels. See [SGLang installation](https://docs.sglang.io/docs/get-started/install).

## 6. GLM-OCR: AMD ROCm GPU

Use native Linux only. vLLM currently documents Linux support for selected AMD GPUs with ROCm; SGLang provides an AMD build/Docker route. Neither is a substitute for installing ROCm correctly first.

- vLLM: use the [vLLM ROCm instructions](https://docs.vllm.ai/en/v0.9.1/getting_started/installation/gpu.html). Its documentation states that AMD pre-built wheels are unavailable for this route, so use the provided ROCm image or build from source.
- SGLang: use the [SGLang AMD guide](https://docs.sglang.io/docs/hardware-platforms/amd_gpu), then launch the GLM-OCR `sglang serve` command from section 5. The guide's Docker route exposes `/dev/kfd` and `/dev/dri`; never run it as privileged on an untrusted host.

Before serving, check `rocminfo` and confirm the GPU is among the supported ROCm architectures. Use `--mem-fraction-static 0.80` only as a starting point; VRAM needs vary by driver and model cache behavior.

## 7. GLM-OCR: Apple Silicon GPU with MLX

The official GLM-OCR MLX route uses **two** environments because its server and SDK can require incompatible Transformers versions.

Terminal 1, MLX server:

```bash
cd "$OCR_HOME/glm-server"
uv venv --python 3.12 --seed
source .venv/bin/activate

# Upstream currently directs GLM-OCR MLX users to source because architecture support may lead PyPI.
uv pip install "git+https://github.com/Blaizzy/mlx-vlm.git"
mlx_vlm.server --trust-remote-code --port 8080
```

Terminal 2, SDK setup follows section 9, then use the MLX config in section 10. The first request compiles Metal shaders and downloads `mlx-community/GLM-OCR-bf16`. Full details: [GLM-OCR Apple Silicon guide](https://github.com/zai-org/GLM-OCR/blob/main/examples/mlx-deploy/README.md).

SGLang has an Apple Metal backend, but this guide uses GLM-OCR's upstream MLX integration because it supplies the model-specific SDK configuration. See [SGLang Apple Metal](https://docs.sglang.io/docs/hardware-platforms/apple_metal) for experimental alternatives.

## 8. GLM-OCR: CPU-only with Ollama

Use Ollama where no supported accelerator route is available. It is slower than GPU serving and best for low-volume work.

Install Ollama from [ollama.com/download](https://ollama.com/download), then run:

```bash
ollama pull glm-ocr:latest
ollama serve
```

On Windows, Ollama normally starts as a background application; run `ollama serve` only when it is not already running. Use the Ollama config from section 10. GLM-OCR's upstream guide recommends Ollama's native `/api/generate` endpoint for vision requests. See [GLM-OCR Ollama deployment](https://github.com/zai-org/GLM-OCR/blob/main/examples/ollama-deploy/README.md).

## 9. Install GLM-OCR SDK

Install this separately from the selected server. On Linux/WSL use `--layout-device cpu` on 8 GiB GPUs so layout analysis does not compete with VLM VRAM. Complete section 10 before running `glmocr parse`.

```bash
cd "$OCR_HOME/glm-sdk"
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install "glmocr[selfhosted]==0.1.5"
```

## 10. GLM-OCR configuration

Create `config.yaml` in `$OCR_HOME/glm-sdk`. Use exactly one `ocr_api` block for the selected server.

### vLLM or SGLang

```yaml
pipeline:
  maas:
    enabled: false
  ocr_api:
    api_host: 127.0.0.1
    api_port: 8080
    model: glm-ocr
    api_path: /v1/chat/completions
    api_mode: openai
    request_timeout: 300
  layout:
    model_dir: PaddlePaddle/PP-DocLayoutV3_safetensors
    threshold: 0.3
    batch_size: 1
```

### MLX

```yaml
pipeline:
  maas:
    enabled: false
  ocr_api:
    api_host: localhost
    api_port: 8080
    model: mlx-community/GLM-OCR-bf16
    api_path: /chat/completions
    verify_ssl: false
    request_timeout: 300
```

### Ollama CPU fallback

```yaml
pipeline:
  maas:
    enabled: false
  ocr_api:
    api_host: localhost
    api_port: 11434
    api_path: /api/generate
    model: glm-ocr:latest
    api_mode: ollama_generate
    request_timeout: 600
```

### Check the selected GLM server and run

For vLLM or SGLang, after startup completes:

```bash
curl --fail --silent http://127.0.0.1:8080/v1/models
```

For MLX, use the upstream OpenAI-compatible request:

```bash
curl http://localhost:8080/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mlx-community/GLM-OCR-bf16","messages":[{"role":"user","content":[{"type":"text","text":"hello"}]}],"max_tokens":10}'
```

For Ollama:

```bash
ollama list
curl http://localhost:11434/api/generate -d '{"model":"glm-ocr:latest","prompt":"hello","stream":false}'
```

After the relevant request succeeds, run:

```bash
glmocr parse "$OCR_HOME/input/document.pdf" \
  --layout-device cpu \
  --config config.yaml \
  --output "$OCR_HOME/output/glm-ocr"
```

Python:

```python
from glmocr import GlmOcr

with GlmOcr(config_path="config.yaml", layout_device="cpu") as parser:
    result = parser.parse("/absolute/path/to/document.pdf")
    print(result.markdown_result)
    result.save("/absolute/path/to/output")
```

Windows PowerShell CPU run, after creating `config.yaml` from the Ollama block above:

```powershell
Set-Location "$env:OCR_HOME\glm-sdk"
.\.venv\Scripts\Activate.ps1
glmocr parse "$env:OCR_HOME\input\document.pdf" --layout-device cpu --config "$env:OCR_HOME\glm-sdk\config.yaml" --output "$env:OCR_HOME\output\glm-ocr"
```

## 11. PaddleOCR-VL-1.6 direct full pipeline

This section documents a standalone alternative pipeline, not wired into this repo's `src/grounded_docparse` code path: the app only uses GLM-OCR plus PP-DocLayout for layout. Use sections 11-13 only if you are running PaddleOCR-VL-1.6 independently of this codebase.

This is the simplest full-pipeline route and the CPU fallback. It runs PP-DocLayoutV3, cropping, reading order, VLM recognition, and assembly together.

### Linux/WSL NVIDIA GPU

```bash
cd "$OCR_HOME/paddle-client"
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install "paddlepaddle-gpu==3.3.0" \
  --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
uv pip install "paddlex[ocr]==3.7.2"

paddlex --pipeline PaddleOCR-VL-1.6 \
  --input "$OCR_HOME/input/document.pdf" \
  --save_path "$OCR_HOME/output/paddleocr-vl"
```

### CPU fallback

Use this on a CPU-only Linux machine. PaddlePaddle supplies CPU wheels for Windows and Apple Silicon, but PaddleX's current detailed local-install documentation is Linux-only; this guide does not claim a supported local PaddleOCR-VL route on macOS. For a Windows CPU experiment, use the PowerShell variant below and validate the direct smoke test before processing real documents.

```bash
cd "$OCR_HOME/paddle-client"
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install "paddlepaddle==3.3.1"
uv pip install "paddlex[ocr]==3.7.2"

paddlex --pipeline PaddleOCR-VL-1.6 \
  --input "/absolute/path/to/document.pdf" \
  --save_path "/absolute/path/to/output"
```

Windows PowerShell experiment:

```powershell
$env:OCR_HOME = 'D:\AI\ai-doc-ocr'
Set-Location "$env:OCR_HOME\paddle-client"
uv venv --python 3.12 --seed
.\.venv\Scripts\Activate.ps1
uv pip install "paddlepaddle==3.3.1"
uv pip install "paddlex[ocr]==3.7.2"
paddlex --pipeline PaddleOCR-VL-1.6 --input "$env:OCR_HOME\input\document.pdf" --save_path "$env:OCR_HOME\output\paddleocr-vl"
```

CPU inference can be impractically slow for long PDFs. Do not expect the CUDA performance profile on CPU or Apple Silicon. The pipeline accepts image/PDF paths, URLs, and image directories; directories containing PDFs are not supported. See [PaddleOCR-VL usage](https://paddlepaddle.github.io/PaddleX/3.7/en/pipeline_usage/tutorials/ocr_pipelines/PaddleOCR-VL.html).

## 12. PaddleOCR-VL-1.6 accelerated VLM service

Use this when direct pipeline inference works and you need faster VLM recognition. Keep a **PaddleX client** process: the server is not a replacement for the pipeline.

### A. Docker vLLM server, NVIDIA GPU

This is PaddleX's official Docker route. Run on Linux or WSL2 after Docker GPU support is working.

```bash
docker run --rm --gpus all --network host \
  ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddlex-genai-vllm-server:latest \
  paddlex_genai_server \
    --model_name PaddleOCR-VL-1.6-0.9B \
    --host 0.0.0.0 \
    --port 8118 \
    --backend vllm
```

Run this and its PaddleX client in the same trusted Linux/WSL environment. `--network host` plus `--host 0.0.0.0` makes port `8118` host-reachable; do not use it on an untrusted network or publish the machine without firewall controls. Docker Desktop networking differs from native Linux, so this exact command is not a macOS route.

For NVIDIA Blackwell, use `:latest-sm120` instead. See PaddleX's [server documentation](https://paddlepaddle.github.io/PaddleX/3.7/en/pipeline_usage/tutorials/ocr_pipelines/PaddleOCR-VL.html).

### B. Native PaddleX vLLM or SGLang server

Use a separate environment from the client. This is the documented SGLang route and an alternative to Docker vLLM.

```bash
cd "$OCR_HOME/paddle-server"
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install "paddlex[ocr]==3.7.2"

# Choose one backend.
paddlex --install genai-vllm-server
# paddlex --install genai-sglang-server

paddlex_genai_server \
  --model_name PaddleOCR-VL-1.6-0.9B \
  --backend vllm \
  --port 8118

# SGLang alternative:
# paddlex_genai_server --model_name PaddleOCR-VL-1.6-0.9B --backend sglang --port 8118
```

PaddleX may install backend-specific dependencies. If one backend installation changes the environment, discard and recreate it before installing the other.

## 13. Connect PaddleX client to VLM service

In the client environment, install the client plugin and generate a pipeline configuration:

```bash
cd "$OCR_HOME/paddle-client"
source .venv/bin/activate
paddlex --install genai-client
paddlex --get_pipeline_config PaddleOCR-VL-1.6
```

Edit generated `PaddleOCR-VL-1.6.yaml`. Set the VLM section to match the server:

```yaml
SubModules:
  VLRecognition:
    engine: genai_client
    engine_config:
      backend: vllm-server
      server_url: http://127.0.0.1:8118/v1
      max_concurrency: 1
```

For an SGLang server, use `backend: sglang-server` if the generated plugin configuration exposes that backend name; preserve the generated configuration's exact backend identifiers when they differ by PaddleX release.

Run complete parsing through the client:

```bash
paddlex --pipeline PaddleOCR-VL-1.6.yaml \
  --input "$OCR_HOME/input/document.pdf" \
  --save_path "$OCR_HOME/output/paddleocr-vl"
```

Use this command as the Paddle server smoke test: it proves the VLM service, client configuration, and full parsing pipeline work together. If the server exposes an OpenAI-compatible models endpoint, this optional fast check should return JSON before the full parse:

```bash
curl --fail --silent http://127.0.0.1:8118/v1/models
```

The official configuration example uses `max_concurrency: 200`; start at `1` on consumer GPUs, then increase only after sustained no-OOM testing.

## 14. Verification and troubleshooting

### Verify each layer

1. Platform: `nvidia-smi` or `rocminfo` returns device details. On WSL, `wsl --list --verbose` reports version 2.
2. Server: startup logs show the selected model and listening port. Keep `127.0.0.1` binding for local-only GLM serving.
3. GLM-OCR: run one-page image before a large PDF; confirm Markdown appears under `$OCR_HOME/output/glm-ocr`.
4. PaddleOCR-VL: run direct pipeline once before adding a VLM server; confirm output under `$OCR_HOME/output/paddleocr-vl`.
5. Accelerated Paddle: generated YAML points to port `8118` and uses model `PaddleOCR-VL-1.6-0.9B`, not the pipeline name.

### Common failures

| Symptom | Fix |
| --- | --- |
| `nvidia-smi` missing in WSL | Update Windows GPU driver and WSL; do not install a Linux NVIDIA driver over the WSL driver integration. |
| vLLM fails on native Windows | Use WSL2 Ubuntu. Native Windows is unsupported by vLLM. |
| CUDA/ROCm wheel conflict | Delete only the affected virtual environment and recreate it; do not install CUDA and ROCm packages together. |
| GPU OOM | Set GPU utilization to `0.75`, keep concurrency at `1`, keep layout on CPU for GLM-OCR, and reduce context length after validating output quality. |
| GLM-OCR returns Ollama `502` | Use `api_path: /api/generate` and `api_mode: ollama_generate`. |
| Paddle results miss layout structure | Run `PaddleOCR-VL-1.6` through PaddleX client; a standalone VLM server is recognition-only. |
| Connection refused | Match server bind/port and config: GLM `8080`; Paddle VLM `8118`. |

## 15. Performance profiles

| Setting | Conservative 8 GiB GPU starting point | Why |
| --- | --- | --- |
| GLM layout device | `cpu` | Keeps VLM VRAM available. |
| GPU memory fraction/utilization | `0.75–0.80` | Leave driver and allocator headroom. |
| Context length | `8192` | Practical starting point for common documents. |
| Concurrent work | `1` | Prove stability before batching. |
| Speculative decoding | GLM MTP enabled | Upstream-supported acceleration; benchmark on target GPU. |

Increase one setting at a time and keep the document set fixed when comparing speed or quality.

## References

- [GLM-OCR repository and self-hosting](https://github.com/zai-org/GLM-OCR)
- [GLM-OCR Apple Silicon MLX deployment](https://github.com/zai-org/GLM-OCR/blob/main/examples/mlx-deploy/README.md)
- [GLM-OCR Ollama deployment](https://github.com/zai-org/GLM-OCR/blob/main/examples/ollama-deploy/README.md)
- [vLLM GPU installation and support matrix](https://docs.vllm.ai/en/v0.9.1/getting_started/installation/gpu.html)
- [SGLang installation](https://docs.sglang.io/docs/get-started/install)
- [SGLang AMD GPU installation](https://docs.sglang.io/docs/hardware-platforms/amd_gpu)
- [SGLang Apple Metal installation](https://docs.sglang.io/docs/hardware-platforms/apple_metal)
- [PaddlePaddle installation](https://www.paddlepaddle.org.cn/documentation/docs/en/install/index_en.html)
- [PaddleX local installation](https://paddlepaddle.github.io/PaddleX/3.7/en/installation/installation.html)
- [PaddleOCR-VL pipeline and server configuration](https://paddlepaddle.github.io/PaddleX/3.7/en/pipeline_usage/tutorials/ocr_pipelines/PaddleOCR-VL.html)
- [Microsoft WSL installation](https://learn.microsoft.com/en-us/windows/wsl/install)
