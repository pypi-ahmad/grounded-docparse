<div align="center">

# Grounded DocParse

Turn PDFs, images, Office files, and structured documents into reviewable Markdown, JSON, and source-linked evidence.

[![CI](https://github.com/pypi-ahmad/grounded-docparse/actions/workflows/ci.yml/badge.svg)](https://github.com/pypi-ahmad/grounded-docparse/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12--3.14-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.60%2B-FF4B4B?logo=streamlit&logoColor=white)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Repository: [github.com/pypi-ahmad/grounded-docparse](https://github.com/pypi-ahmad/grounded-docparse)

[Quick start](#quick-start) · [How it works](#how-it-works) · [Usage](#use-the-studio) · [Documentation](#documentation-index)

</div>

![Grounded DocParse application](docs/images/document-parse-studio-full.png)

## Index

- [What the project does](#what-the-project-does)
- [How it works](#how-it-works)
- [Features](#features)
- [Extraction engines](#extraction-engines)
- [Supported inputs](#supported-inputs)
- [Quick start](#quick-start)
- [Use the studio](#use-the-studio)
- [Command line](#command-line)
- [Python API](#python-api)
- [Outputs and evidence](#outputs-and-evidence)
- [Privacy and deployment boundary](#privacy-and-deployment-boundary)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Documentation index](#documentation-index)

## What the project does

Grounded DocParse is a local-first document processing studio for Windows. It handles scanned and selectable-text PDFs, images, Office files, spreadsheets, HTML, EPUB, Markdown, and OpenDocument formats. Every file receives an explicit processing type. The app validates that choice and never silently moves a document to another pipeline.

The output is designed for review. OCR results retain page geometry, element identity, reading order, confidence, and source boxes. Native documents retain immutable text spans and anchors that point back to pages, paragraphs, slides, shapes, sheets, cells, tables, or CSV rows. Optional AI features operate on that evidence rather than replacing it.

Use the project when you need:

- Markdown and structured JSON from mixed document formats
- Local OCR with visible source geometry
- Exact source links for extracted fields
- Manual routing for PDFs that mix native and scanned pages
- Optional classification, table of contents, extraction, routing, or chat
- A Windows UI, batch CLI, or synchronous Python API

## How it works

```text
upload or CLI input
  -> choose a processing type for each file
  -> validate extension, signature, and container
  -> run the selected native, OCR, or AI engine
  -> build grounded elements or immutable source spans
  -> render Markdown, JSON, and available visual evidence
  -> optionally run bounded AI features
  -> review and export
```

For grounded OCR, the selected engine owns layout, element IDs, geometry, type, confidence, and reading order. AI enhancement may repair text on an existing failed or low-confidence element, but it cannot create a region, move a box, or reorder the page.

For native inputs, extraction uses immutable `base_text`. A value is accepted only when its exact character interval resolves through source spans to one or more `SourceAnchor` records.

## Features

- Six exclusive extraction engines for local, native, and direct AI processing
- Explicit Native PDF, Scanned PDF, and Mixed PDF routes
- Reviewed per-page routing for mixed PDFs
- Natural-unit content ranges that retain original source indices
- Grounded Markdown, versioned JSON, source structure, and annotated PDFs
- Reusable extraction schemas and mixed-form routing profiles
- Optional AI enhancement, classification, table of contents, extraction, and chat
- Sequential batch processing with per-file failure isolation
- Durable completed results and launch-scoped AI cost reporting
- Terminal diagnostics for app, layout, OCR region, Ollama, and WSL services

## Extraction engines

| Engine | Runtime | Best suited for |
| --- | --- | --- |
| AI ADE | Selected cloud provider | Direct AI document extraction |
| PaddleOCR-VL-1.6 | WSL vLLM and PaddleX | Full Paddle layout and recognition |
| GLM-OCR | WSL vLLM plus Windows CPU layout | PP-DocLayoutV3-grounded recognition |
| Docling + RapidOCR | Native Windows CPU | OCR-enabled Docling parsing |
| PDF Inspector | Native Windows | Selectable-text PDFs without OCR |
| Local Ollama | Windows Ollama plus CPU layout | Local GLM-OCR, PaddleOCR-VL, or DeepSeek-OCR |

Local Ollama uses the multimodal chat API with a 4,096-token context. Output is bounded by region size at 128, 256, or 512 tokens. Each request has a 120-second timeout and each page has a 300-second deadline. The UI reports layout and region progress instead of remaining at the page-level status.

The default fresh-workspace choice is Local Ollama with `AuditAid/PaddleOCR-VL-1.6-0.9B:latest`. The launcher also prepares `glm-ocr:latest` and `deepseek-ocr:latest`.

## Supported inputs

| Input | Processing type | Pipeline |
| --- | --- | --- |
| Selectable PDF | Native PDF | PDF Inspector |
| Scanned PDF | Scanned PDF | Selected extraction engine |
| Mixed native/scanned PDF | Mixed PDF | Confirmed page-by-page merge |
| DOCX | Word | OCR-disabled Docling |
| PPTX | PowerPoint | OCR-disabled Docling |
| XLSX | Excel | OCR-disabled Docling |
| CSV | CSV | Deterministic row and column structure |
| HTML, EPUB, Markdown, ODT, ODP, ODS | Other Native | Native or Docling conversion |
| PNG, JPEG, TIFF | Image | Selected extraction engine |

## Quick start

Requirements: Windows 11 22H2 or newer. WSL2 and a supported NVIDIA GPU are needed only for the optional GLM-OCR and PaddleOCR-VL vLLM services.

```powershell
git clone https://github.com/pypi-ahmad/grounded-docparse.git
Set-Location grounded-docparse
.\Launch-Grounded-DocParse.cmd
```

The launcher installs or reuses `uv`, Python 3.12, the locked native environment, PP-DocLayoutV3 assets, and Windows Ollama. It opens <http://localhost:7137> and follows labeled logs in the terminal.

To prepare the optional WSL GPU services:

```powershell
.\Setup-GLM-OCR.cmd
.\Setup-PaddleOCR-VL-1.6.cmd
```

Cloud keys are optional. Keep AI features disabled for a local-only workflow. See [SETUP.md](SETUP.md) for supported environment variables.

## Use the studio

1. Upload one or more files.
2. Choose a compatible processing type for every file.
3. For Mixed PDF, review and confirm every selected page route.
4. Choose one extraction engine. Local Ollama also requires an OCR model choice.
5. Enable only the AI features you want to use.
6. Select **Parse document** or **Process documents**.
7. Review Markdown, JSON, evidence, source structure, and any annotated PDF.
8. Run extraction, routing, or chat only when needed.
9. Download individual results or the batch archive.

Completed results can be restored after an app restart. Incomplete processing is reset to pending and must be started again. There is no Resume batch action.

Read [USAGE.md](USAGE.md) for the complete task-oriented workflow.

## Command line

The `ingest` command requires one processing type per input:

```powershell
uv run grounded-docparse ingest invoice.pdf `
  --processing-type invoice.pdf=native-pdf `
  --output results
```

Mixed PDFs also require a route for each selected page. The legacy `parse` command remains available for synchronous PDF and image OCR.

```powershell
uv run grounded-docparse ingest --help
uv run grounded-docparse parse --help
```

## Python API

```python
from pathlib import Path

from grounded_docparse import ProcessingType, UniversalDocumentParser

source = Path("invoice.pdf")
result = UniversalDocumentParser().parse(
    source.read_bytes(),
    source.name,
    processing_type=ProcessingType.NATIVE_PDF,
)

print(result.markdown)
```

The public API is synchronous. See [docs/api.md](docs/api.md) for processing ranges, OCR parsing, agentic features, models, and result contracts.

## Outputs and evidence

- Grounded OCR Markdown and presentation-refined Markdown
- Immutable native `base_text` and source spans
- Parse JSON `4.5.0` and Full JSON `4.6.0`
- Native JSON `5.0.0` and combined native/extraction JSON `5.1.0`
- Extraction values with element or exact character-interval evidence
- Annotated PDFs when the selected route produces a visual artifact
- Runtime diagnostics, usage, trace, warnings, and recovery records

AI ADE fails when a nonblank page returns no document regions. It does not report a successful empty result.

## Privacy and deployment boundary

The application is designed for a trusted local workstation. Streamlit, Ollama, CPU layout, Docling, RapidOCR, and PDF Inspector run on Windows. Optional GLM and Paddle vLLM services run in WSL and bind to loopback.

Enabled cloud features may send selected crops, recognized context, schemas, or questions to the chosen provider. Review [DATA_RESPONSIBILITY.md](DATA_RESPONSIBILITY.md), [SECURITY.md](SECURITY.md), and the [threat model](grounded-docparse-threat-model.md) before processing sensitive documents.

The app has no multi-user authentication or tenant isolation. Do not publish it unchanged as a shared confidential-document service.

## Architecture

Grounded DocParse is a modular Python monolith with one Streamlit application process and optional local model services. The main architectural contracts are explicit routing, deterministic evidence ownership, bounded optional AI work, and fail-closed validation.

See the [definitive architecture guide](docs/architecture.md) and [technical overview](TECHNICAL.md).

## Repository layout

```text
streamlit_app.py                 Streamlit application
src/grounded_docparse/          Package, pipelines, models, and APIs
scripts/windows/                Native launcher and setup lifecycle
scripts/wsl/                    Optional WSL OCR services
config/                         OCR runtime configuration
tests/                          Offline behavior and contract tests
docs/                           User, operator, architecture, and API docs
wiki/                           Generated codebase knowledge wiki
```

## Documentation index

### Start here

- [How to use Grounded DocParse](USAGE.md)
- [Complete user guide](docs/complete-user-guide.md)
- [Tutorial](docs/tutorial.md)
- [Zero-to-hero tutorial](docs/zero-to-hero-tutorial.md)
- [How it works](docs/how-it-works.md)

### Setup and operation

- [Setup](SETUP.md)
- [Run locally](docs/run.md)
- [Local Ollama](docs/local-ollama.md)
- [Local GLM-OCR](docs/local-glmocr.md)
- [Local PaddleOCR-VL](docs/local-paddleocr-vl.md)
- [Azure bulk fax deployment](docs/azure-bulk-fax-deployment.md)
- [Testing](TESTING.md)
- [Support](SUPPORT.md)

### Architecture and reference

- [Technical overview](TECHNICAL.md)
- [Architecture](docs/architecture.md)
- [Product specification](docs/spec.md)
- [Python API](docs/api.md)
- [How Grounded DocParse is agentic](docs/how-grounded-docparse-is-agentic.md)
- [Agentic document extraction comparison](docs/agentic-document-extraction-comparison.md)
- [Contributor onboarding](docs/ONBOARDING.md)
- [Codebase stack](docs/codebase/STACK.md)
- [Codebase structure](docs/codebase/STRUCTURE.md)
- [Codebase conventions](docs/codebase/CONVENTIONS.md)
- [Codebase integrations](docs/codebase/INTEGRATIONS.md)
- [Codebase testing](docs/codebase/TESTING.md)
- [Codebase concerns](docs/codebase/CONCERNS.md)
- [Codebase architecture pointer](docs/codebase/ARCHITECTURE.md)

### Workflows and research

- [Business extraction workflow](docs/business-user-extraction-workflow.md)
- [Large-field extraction workflow](docs/layout-aware-large-field-extraction-workflow.md)
- [Private evaluation](docs/private-evaluation.md)
- [Research notes](docs/research.md)
- [Extraction quality research](docs/extraction-quality-research.md)
- [IDP and ADE classification](docs/idp-vs-ade-classification.html)
- [Native ingestion diagram](docs/native-document-ingestion.html)
- [Native ingestion workflow source](docs/native-document-ingestion.workflow.json)

### Project policy and planning

- [Data responsibility](DATA_RESPONSIBILITY.md)
- [Security policy](SECURITY.md)
- [Threat model](grounded-docparse-threat-model.md)
- [Security review](security_best_practices_report.md)
- [Contributing](CONTRIBUTING.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Changelog](CHANGELOG.md)
- [Modernization plan](MODERNIZATION_PLAN.md)
- [Knowledge wiki](wiki/index.md)

<p align="center">Made with ❤️ by Ahmad Mujtaba</p>
