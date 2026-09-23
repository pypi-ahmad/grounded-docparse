---
type: operations
title: Runtimes, Configuration, and Operations
description: Maps the Windows application runtime, optional WSL OCR services, provider configuration, and the local Ollama request bounds.
tags: [operations, configuration, windows, wsl, runtimes]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-9c0e2a0f1945e5ef346f2b89
    resource: repo://scripts/windows/launch-native.ps1
  - id: openwiki-source-6c56f913a8e8b2996b98c356
    resource: repo://scripts/wsl/manage-ocr-stack.sh
  - id: openwiki-source-f76afd353d4c4b2a09b4efd7
    resource: repo://src/grounded_docparse/config.py
  - id: openwiki-source-54411f24a6eecf31adece354
    resource: repo://src/grounded_docparse/grounded_ocr.py
  - id: openwiki-source-a5ae8845517d02e9dd3b333e
    resource: repo://src/grounded_docparse/ollama_runtime.py
  - id: openwiki-source-40a8126adf38092fd7803452
    resource: repo://tests/test_launcher_contract.py
  - id: openwiki-source-420c019492dca611d7b51423
    resource: repo://tests/test_provider_runtime.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Runtime layout

The Streamlit application and package run on Windows. The native launcher starts Streamlit on loopback port `7137` and can manage the Windows Ollama process used by local OCR ([launcher](../../scripts/windows/launch-native.ps1)). Optional GLM-OCR and PaddleOCR-VL vLLM services run in WSL; the Paddle path also has a layout-parsing API. The service manager uses loopback endpoints, with GLM on `8080` and Paddle services on `8118` and `8119` ([WSL service manager](../../scripts/wsl/manage-ocr-stack.sh)). The launcher contract tests check the UI port and WSL service bindings ([tests](../../tests/test_launcher_contract.py)). These files describe intended endpoints; they do not establish that a service is installed or currently available on a particular machine.

Use the root launcher for the Windows app:

```powershell
.\Launch-Grounded-DocParse.cmd
```

For the optional WSL services, use the setup scripts documented in [SETUP.md](../../SETUP.md). Local OCR can also use Ollama on Windows. The local Ollama recognizer posts grounded region crops to `/api/chat`, uses a `4,096` token context, and bounds each request to `120` seconds; the grounded OCR runtime can apply a `300` second per-page deadline ([Ollama client](../../src/grounded_docparse/ollama_runtime.py), [grounded OCR runtime](../../src/grounded_docparse/grounded_ocr.py)).

## Configuration and provider boundaries

`ParserConfig.from_env()` maps `DOCPARSE_*` variables to engine, model, rendering, size, concurrency, timeout, and OCR settings. It validates configured Paddle and GLM endpoints as loopback services ([configuration](../../src/grounded_docparse/config.py)). Provider credentials are read from their configured environment-variable names; keep their values out of documentation, logs, and saved workspace data. Optional provider features require the corresponding provider configuration.

## Operational checks

- Check the selected processing route and engine in the UI or CLI before starting a document; see [ingestion and routing](../workflows/explicit-ingestion-and-routing.md).
- For local Ollama failures, check the Ollama service and selected model before retrying the document.
- For WSL engines, use the project setup and service-management scripts and confirm each readiness endpoint from the service manager.
- Review per-document errors and runtime diagnostics; an unavailable optional engine is not evidence that parsing succeeded.

The process and service configuration is intended for a local workstation. See [system boundaries](../architecture/system-overview.md) and [studio persistence](../interfaces/studio-and-workspace.md) for application and workspace limits.
