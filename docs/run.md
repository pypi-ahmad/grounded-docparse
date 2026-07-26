# Run Commands

## PowerShell

### Install

```powershell
uv sync --python 3.12 --locked
ollama pull glm-ocr
docker pull ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
uv run grounded-docparse-paddle-setup
```

### Verify local providers

```powershell
docker info
docker image inspect ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
ollama list
uv run grounded-docparse --help
```

### Run Streamlit locally

```powershell
uv run streamlit run streamlit_app.py
```

### Configure OpenAI cloud profiles

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) { throw "OPENAI_API_KEY is not set" }
$env:OPENAI_BASE_URL = "https://us.api.openai.com/v1"
```

### Run Streamlit with cloud profiles available

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) { throw "OPENAI_API_KEY is not set" }
$env:OPENAI_BASE_URL = "https://us.api.openai.com/v1"
uv run streamlit run streamlit_app.py
```

### Parse locally

```powershell
uv run grounded-docparse examples/synthetic-report.pdf --output output
uv run grounded-docparse document.pdf --output output --profile local-only
```

### Parse with hybrid verification

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) { throw "OPENAI_API_KEY is not set" }
$env:OPENAI_BASE_URL = "https://us.api.openai.com/v1"
uv run grounded-docparse document.pdf --output output --profile hybrid
```

### Parse with maximum accuracy

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) { throw "OPENAI_API_KEY is not set" }
$env:OPENAI_BASE_URL = "https://us.api.openai.com/v1"
uv run grounded-docparse document.pdf --output output --profile maximum-accuracy
```

### Select a document profile

```powershell
uv run grounded-docparse invoice.pdf --output output --document-profile invoice
uv run grounded-docparse paper.pdf --output output --document-profile scientific-paper
uv run grounded-docparse form.pdf --output output --document-profile healthcare-form
```

### Control segmentation

```powershell
uv run grounded-docparse batch.pdf --output output --segmentation auto
uv run grounded-docparse document.pdf --output output --segmentation off
```

### Run schema extraction

```powershell
uv run grounded-docparse invoice.pdf --output output --document-profile invoice --schema examples/schemas/invoice.schema.json
```

### Run evaluation

```powershell
uv run grounded-docparse document.pdf --output output --gold-json labels/document.gold.json
```

### Run tests

```powershell
uv run pytest -q
uv run python -m compileall -q src streamlit_app.py scripts tests
uv run python scripts/generate_examples.py
```

## Bash

### Install

```bash
uv sync --python 3.12 --locked
ollama pull glm-ocr
docker pull ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
uv run grounded-docparse-paddle-setup
```

### Verify local providers

```bash
docker info
docker image inspect ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl:latest-nvidia-gpu@sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db
ollama list
uv run grounded-docparse --help
```

### Run Streamlit locally

```bash
uv run streamlit run streamlit_app.py
```

### Configure OpenAI cloud profiles

```bash
: "${OPENAI_API_KEY:?OPENAI_API_KEY is not set}"
export OPENAI_BASE_URL="https://us.api.openai.com/v1"
```

### Run Streamlit with cloud profiles available

```bash
: "${OPENAI_API_KEY:?OPENAI_API_KEY is not set}"
export OPENAI_BASE_URL="https://us.api.openai.com/v1"
uv run streamlit run streamlit_app.py
```

### Parse locally

```bash
uv run grounded-docparse examples/synthetic-report.pdf --output output
uv run grounded-docparse document.pdf --output output --profile local-only
```

### Parse with hybrid verification

```bash
: "${OPENAI_API_KEY:?OPENAI_API_KEY is not set}"
export OPENAI_BASE_URL="https://us.api.openai.com/v1"
uv run grounded-docparse document.pdf --output output --profile hybrid
```

### Parse with maximum accuracy

```bash
: "${OPENAI_API_KEY:?OPENAI_API_KEY is not set}"
export OPENAI_BASE_URL="https://us.api.openai.com/v1"
uv run grounded-docparse document.pdf --output output --profile maximum-accuracy
```

### Select a document profile

```bash
uv run grounded-docparse invoice.pdf --output output --document-profile invoice
uv run grounded-docparse paper.pdf --output output --document-profile scientific-paper
uv run grounded-docparse form.pdf --output output --document-profile healthcare-form
```

### Control segmentation

```bash
uv run grounded-docparse batch.pdf --output output --segmentation auto
uv run grounded-docparse document.pdf --output output --segmentation off
```

### Run schema extraction

```bash
uv run grounded-docparse invoice.pdf --output output --document-profile invoice --schema examples/schemas/invoice.schema.json
```

### Run evaluation

```bash
uv run grounded-docparse document.pdf --output output --gold-json labels/document.gold.json
```

### Run tests

```bash
uv run pytest -q
uv run python -m compileall -q src streamlit_app.py scripts tests
uv run python scripts/generate_examples.py
```
