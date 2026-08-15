# Using Grounded DocParse

Grounded DocParse is a workstation-oriented Streamlit studio for turning
native documents, scanned PDFs, and images into grounded Markdown, structured
JSON, and source evidence. Start with this page, then use the
[complete user guide](docs/complete-user-guide.md) for detailed workflows.

## Before you start

The primary application runs natively on Windows 11 22H2 or newer. Optional
GLM-OCR and PaddleOCR-VL-1.6 GPU services remain in Ubuntu 24.04 under WSL2;
PaddleOCR-VL-1.6 additionally requires supported NVIDIA hardware.

Optional AI features require the selected provider's `OPENAI_API_KEY`,
`GOOGLE_API_KEY`, or `AGNES_API_KEY`. Keep AI enhancement and other agentic
options disabled when document content must remain local.

## Start the application

Run the native launcher from the repository root:

```powershell
.\Launch-Grounded-DocParse.cmd
```

It repairs the native environment, CPU PP-DocLayoutV3 assets, and Windows
Ollama before opening <http://localhost:8600>. Use `Setup-GLM-OCR.cmd` or
`Setup-PaddleOCR-VL-1.6.cmd` only to provision and warm a WSL GPU service.

## Process a document

1. Upload one or more supported files.
2. Select a processing type independently for every file.
3. Select exactly one extraction engine and configure optional AI enhancement.
4. For Mixed PDF, review or override every suggested page route.
5. Select **Parse document**.
6. Review grounded output and source evidence before using extracted values.
7. Download the required Markdown, JSON, extraction, or annotated-PDF output.

The processing selector is authoritative. An incompatible extension,
signature, or container is blocked; the application never silently changes the
selected route.

| Input | Processing type | Behavior |
| --- | --- | --- |
| Selectable-text PDF | Native PDF | Non-OCR PDF extraction with page and bounding-box anchors |
| Image-only PDF | Scanned PDF | Selected pure-AI, vLLM, Docling/RapidOCR, or Ollama engine |
| PDF with native and scanned pages | Mixed PDF | Reviewed page-by-page native/OCR routing |
| DOCX | Word | OCR-disabled native conversion |
| PPTX | PowerPoint | OCR-disabled native conversion |
| XLSX | Excel | OCR-disabled native conversion |
| CSV | CSV | Deterministic row and column grounding |
| Supported HTML, EPUB, Markdown, or OpenDocument file | Other Native | OCR-disabled native conversion |
| PNG, JPEG, TIFF, or other supported image | Image | Selected extraction engine |

Embedded images in native Office and document formats are recorded as assets;
they are not OCRed in the native pipeline.

## Command line

Inspect the supported arguments:

```powershell
uv run grounded-docparse ingest --help
```

Every CLI input must receive a compatible `--processing-type`. The CLI uses the
same validation and one-route-only dispatch contract as the UI. See the
[Python and CLI API reference](docs/api.md) for examples and public result
models.

## Outputs and evidence

- `base_text` is immutable extraction evidence.
- Source spans map exact character intervals back to PDF regions, document
  structures, spreadsheet cells, or CSV rows and columns.
- Refined Markdown is a presentation view and is never accepted as extraction
  evidence.
- Native formats may not have an annotated PDF; their JSON and source-structure
  views carry the evidence instead.

## Persistence

The latest batch is restored after an app restart. Settings, progress, parse
checkpoints, analysis, failures, usage, reusable schemas, and routing profiles
live in `data/document_studio.sqlite3` or `DOCPARSE_STUDIO_DB_PATH`. Source
bytes and annotated PDFs live in the sibling `workspaces/` directory. Use
**Clear saved workspace** to delete that durable batch. Extraction, routing
review, and chat remain session-only; download those outputs before ending the
session.

## Troubleshooting

- Installation and runtime repair: [SETUP.md](SETUP.md)
- Service lifecycle and launcher logs: [docs/run.md](docs/run.md)
- GLM-OCR runtime: [docs/local-glmocr.md](docs/local-glmocr.md)
- PaddleOCR-VL runtime: [docs/local-paddleocr-vl.md](docs/local-paddleocr-vl.md)
- Full UI and workflow help: [docs/complete-user-guide.md](docs/complete-user-guide.md)

Do not expose ports `8600`, `8080`, `8118`, or `8119` to an untrusted network.
