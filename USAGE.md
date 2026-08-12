# Using Grounded DocParse

Grounded DocParse is a workstation-oriented Streamlit studio for turning
native documents, scanned PDFs, and images into grounded Markdown, structured
JSON, and source evidence. Start with this page, then use the
[complete user guide](docs/complete-user-guide.md) for detailed workflows.

## Before you start

The supported local environment is Windows 10 22H2 or Windows 11 x64 with WSL2
and Ubuntu 24.04. Complete [setup](SETUP.md) before launching the application.
PaddleOCR-VL-1.6 additionally requires supported NVIDIA hardware; GLM-OCR can
use its documented Ollama fallback.

Optional Luna features require `OPENAI_API_KEY` in the Windows user
environment. Keep all Luna options disabled when document content must remain
local. See the [security policy](SECURITY.md) before processing sensitive data.

## Start the application

Choose one launcher from the repository root:

```powershell
.\Launch-GLM-OCR.cmd
```

```powershell
.\Launch-PaddleOCR-VL-1.6.cmd
```

The launcher starts the selected local OCR stack and Streamlit, then opens
<http://localhost:8600>. Both launchers use the same application; the selected
OCR engine changes only scanned-PDF and image processing.

## Process a document

1. Upload one or more supported files.
2. Select a processing type independently for every file.
3. Configure page range and optional Luna features.
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
| Image-only PDF | Scanned PDF | Selected GLM-OCR or PaddleOCR-VL pipeline |
| PDF with native and scanned pages | Mixed PDF | Reviewed page-by-page native/OCR routing |
| DOCX | Word | OCR-disabled native conversion |
| PPTX | PowerPoint | OCR-disabled native conversion |
| XLSX | Excel | OCR-disabled native conversion |
| CSV | CSV | Deterministic row and column grounding |
| Supported HTML, EPUB, Markdown, or OpenDocument file | Other Native | OCR-disabled native conversion |
| PNG, JPEG, TIFF, or other supported image | Image | Selected local OCR pipeline |

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

## Troubleshooting

- Installation and runtime repair: [SETUP.md](SETUP.md)
- Service lifecycle and launcher logs: [docs/run.md](docs/run.md)
- GLM-OCR runtime: [docs/local-glmocr.md](docs/local-glmocr.md)
- PaddleOCR-VL runtime: [docs/local-paddleocr-vl.md](docs/local-paddleocr-vl.md)
- Full UI and workflow help: [docs/complete-user-guide.md](docs/complete-user-guide.md)

Do not expose ports `8600`, `8080`, `8118`, or `8119` to an untrusted network.
