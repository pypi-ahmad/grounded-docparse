# Run Local Ollama OCR

This guide explains how to run and troubleshoot the Local Ollama extraction engine on Windows.

## What Local Ollama uses

Local Ollama combines native Windows components:

- CPU PP-DocLayoutV3 for page regions and reading order
- Ollama for crop recognition
- GLM-OCR, PaddleOCR-VL, or DeepSeek-OCR as the recognizer
- Streamlit for progress and review

It does not require WSL. The optional GLM and Paddle vLLM engines are separate choices.

## Start the app

```powershell
.\Launch-Grounded-DocParse.cmd
```

The launcher installs or reuses Ollama, checks `http://127.0.0.1:11434`, and prepares:

- `glm-ocr:latest`
- `AuditAid/PaddleOCR-VL-1.6-0.9B:latest`
- `deepseek-ocr:latest`

It also prepares the CPU PP-DocLayoutV3 weights. Existing model caches are reused.

## Parse with Local Ollama

1. Upload a scanned PDF or image.
2. Choose the correct processing type.
3. Select **Local Ollama**.
4. Choose GLM-OCR, PaddleOCR-VL, or DeepSeek-OCR.
5. Select **Parse document**.
6. Watch layout and per-region progress.
7. Review the output against the annotated source.

Fresh workspaces default to Local Ollama with PaddleOCR-VL.

## Request limits

Each detected crop is sent through Ollama's multimodal `/api/chat` endpoint.

| Limit | Value |
| --- | ---: |
| Context | 4,096 tokens |
| Small region output | 128 tokens |
| Large region output | 256 tokens |
| Table output | 512 tokens |
| Request timeout | 120 seconds |
| Page deadline | 300 seconds |

Requests are sequential. This avoids overlapping large multimodal requests on a local machine.

DeepSeek-OCR retries one failed region with a stricter prompt. An isolated failed region can be skipped, but repeated consecutive failures stop the page.

## Progress

The UI reports:

1. layout detection;
2. the current OCR region and total regions;
3. later page assembly and rendering stages.

The terminal logs the page, region label, model, image size, context, output limit, elapsed time, prompt tokens, output tokens, done reason, and returned character count. It does not log the crop or recognized text.

## Logs

The launcher prints the exact managed paths and follows them in the terminal:

- `%LOCALAPPDATA%\GroundedDocParse\logs\streamlit.out.log`
- `%LOCALAPPDATA%\GroundedDocParse\logs\streamlit.err.log`
- `%LOCALAPPDATA%\GroundedDocParse\logs\ollama.out.log`
- `%LOCALAPPDATA%\GroundedDocParse\logs\ollama.err.log`
- `%LOCALAPPDATA%\Ollama\server.log`

The final path is Ollama's own server log. Managed stdout and stderr files are populated when the launcher starts Ollama itself.

## Change the Ollama endpoint

`OLLAMA_BASE_URL` defaults to `http://127.0.0.1:11434`. Only loopback origins are accepted.

```powershell
[Environment]::SetEnvironmentVariable(
  "OLLAMA_BASE_URL",
  "http://127.0.0.1:11434",
  "User"
)
```

Relaunch the application after changing the value.

## Restart safely

Use **Stop app** to stop Streamlit. The launcher does not delete Ollama weights. Relaunching checks the existing cache before downloading anything.

Completed results can be restored. Incomplete OCR is reset to pending and must be started again. The app does not offer Resume batch.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Model is missing | Relaunch and let model preparation finish |
| Progress stays on one region | Read the current request timing in `streamlit.out.log` |
| Request reaches 120 seconds | Check Ollama server health, memory use, and model load |
| Page reaches 300 seconds | Retry after confirming the selected model works on a small image |
| Output is empty | Read the region completion and character count, then try another model |
| Connection reset appears | Check the surrounding log lines; browser transport resets are not OCR failures by themselves |
| Ollama is unreachable | Open `http://127.0.0.1:11434/api/tags` locally and inspect `server.log` |

For launcher and service details, see [Run locally](run.md). For the complete UI workflow, see [How to use Grounded DocParse](../USAGE.md).
