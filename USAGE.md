# How to use Grounded DocParse

This guide shows Windows users how to process documents in the Streamlit studio, inspect source evidence, and download results. It also includes a basic CLI workflow. For installation details, see [SETUP.md](SETUP.md).

## Before you start

Use only documents you are authorized to process. You are responsible for provider selection, local and remote copies, output review, retention, and deletion. Read [DATA_RESPONSIBILITY.md](DATA_RESPONSIBILITY.md) and [SECURITY.md](SECURITY.md) before processing sensitive material.

The main application runs on Windows 11 22H2 or newer. WSL2 is needed only for the optional GLM-OCR and PaddleOCR-VL vLLM engines. Cloud AI features are optional.

## Start the application

From the repository root:

```powershell
.\Launch-Grounded-DocParse.cmd
```

The launcher checks Python, dependencies, layout weights, and Ollama models before opening <http://localhost:7137>. Keep the terminal open. It prints Streamlit, layout, OCR-region, WSL service, and Ollama logs.

Prepare an optional WSL engine only when you plan to use it:

```powershell
.\Setup-GLM-OCR.cmd
.\Setup-PaddleOCR-VL-1.6.cmd
```

## Process your first document

1. Upload a supported file.
2. Select its processing type.
3. Choose one extraction engine.
4. Leave optional AI features off for the first local parse.
5. Select **Parse document**.
6. Wait for the progress bar to complete.
7. Review Markdown, JSON, source evidence, and any annotated PDF.
8. Download the outputs you need.

For batches, choose a processing type for every file and select **Process documents**. Files run sequentially. One failure does not stop later files.

## Choose the processing type

| Input | Choose | Result |
| --- | --- | --- |
| Selectable-text PDF | Native PDF | PDF structure without OCR |
| Image-only PDF | Scanned PDF | Selected extraction engine |
| PDF with native and scanned pages | Mixed PDF | Reviewed native/OCR merge |
| DOCX | Word | Native Docling conversion |
| PPTX | PowerPoint | Native Docling conversion |
| XLSX | Excel | Native Docling conversion |
| CSV | CSV | Row and column structure |
| HTML, EPUB, Markdown, OpenDocument | Other Native | Native conversion |
| PNG, JPEG, TIFF | Image | Selected extraction engine |

The app validates extensions, signatures, and containers. It does not silently change an incompatible selection.

## Choose the extraction engine

- **Local Ollama** is the default local route. Choose GLM-OCR, PaddleOCR-VL, or DeepSeek-OCR.
- **GLM-OCR** and **PaddleOCR-VL-1.6** use optional WSL GPU services.
- **Docling + RapidOCR** runs on Windows CPU.
- **PDF Inspector** handles selectable PDFs without OCR.
- **AI ADE** sends the document to the selected cloud model for direct extraction.

Local Ollama uses PP-DocLayoutV3 to detect regions, then recognizes them one at a time. The context is 4,096 tokens. Region output is capped at 128, 256, or 512 tokens. A request can run for up to 120 seconds and a page for up to 300 seconds.

The progress label changes from layout detection to individual region recognition. If it appears slow, check the terminal for the current page, region number, model, timing, and error details.

## Configure optional AI

Set the Windows User environment key required by the selected model, then relaunch:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-key", "User")
[Environment]::SetEnvironmentVariable("GOOGLE_API_KEY", "your-key", "User")
[Environment]::SetEnvironmentVariable("AGNES_API_KEY", "your-key", "User")
```

Enable only the features you need:

- **AI enhancement for failed or <75% confidence regions** sends bounded crops for text repair.
- **Enhance Markdown with AI** refines presentation after parsing.
- Classification, table of contents, extraction, routing, and chat use recognized document context.

AI ADE fails visibly if a nonblank page returns no document regions. It does not produce a successful empty output.

## Select a content range

Each file can have an inclusive range in its natural unit, such as PDF pages, TIFF frames, slides, sheets, EPUB sections, document blocks, or CSV rows. Selected units keep their original source numbers.

For Mixed PDF, review the Native/OCR suggestion for each selected page. Confirm every route before processing.

## Monitor progress and logs

The UI reports overall batch progress and the current document stage. Local grounded OCR reports layout completion and each region request.

The native launcher follows:

- `streamlit.out.log` and `streamlit.err.log`
- WSL GLM and Paddle service logs under `.runtime/`
- managed Ollama stdout and stderr logs
- `%LOCALAPPDATA%\Ollama\server.log`

The launcher prints the exact managed log paths at startup.

## Review results

Check the available tabs for the selected document:

- **Overview** for status, quality, and warnings
- **Markdown** for readable content
- **JSON** for structured output and provenance
- **Source structure** or **Layout Tree** for grounded organization
- **Annotated PDF** for visual boxes when the route produces one
- **Extract** for schema-based values
- **Chat** when explicitly enabled

Treat refined Markdown as presentation. Confirm extracted values against their element box or exact native character span.

## Extract fields and route mixed forms

Open **Extract** after parsing. Create or import a schema, then run extraction. Native extraction uses immutable `base_text`; OCR extraction uses grounded document elements.

For packets containing several form types, enable custom form routing, choose a saved routing profile, review uncertain segments, approve the ranges, and extract eligible forms. Routing review is session-only.

## Download outputs

Download individual Markdown, JSON, extraction, or annotated-PDF files from the selected result. **Download all outputs** creates a batch archive containing the originals, manifest, and available generated artifacts.

Native nonvisual formats may not produce an annotated PDF.

## Understand saved state

Completed results, settings, failures, usage, schemas, and routing profiles are stored in SQLite. Source bytes and completed artifacts live in the sibling `workspaces` directory.

Incomplete `processing` or legacy `interrupted` work is reset to `pending` after restart. Partial progress and incomplete results are discarded. Start parsing again with **Parse document** or **Process documents**. The app has no Resume batch action.

Extraction review, routing review, and chat remain session-only. Download those results before ending the session.

Use **Clear saved workspace** to remove the active workspace after confirmation.

## Stop and restart

Use **Stop app** in the sidebar to stop Streamlit without deleting models or completed workspace results. Relaunch with `Launch-Grounded-DocParse.cmd`.

To stop all optional WSL OCR services:

```bash
bash scripts/wsl/manage-ocr-stack.sh stop all
```

## Basic command-line workflow

Inspect the command:

```powershell
uv run grounded-docparse ingest --help
```

Process a native PDF:

```powershell
uv run grounded-docparse ingest invoice.pdf `
  --processing-type invoice.pdf=native-pdf `
  --output results
```

The CLI uses the same signature validation and explicit routing rules as the UI. See [docs/api.md](docs/api.md) for batch, Mixed PDF, schema, and Python examples.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Browser does not open | Open <http://localhost:7137> and read `streamlit.err.log` |
| Ollama appears slow | Read the current region timing and `%LOCALAPPDATA%\Ollama\server.log` |
| Ollama request times out | Confirm the model is loaded and the machine has enough RAM or VRAM |
| WSL engine is unavailable | Run its setup command and inspect the matching `.runtime` log |
| AI controls are disabled | Set the selected provider key and relaunch |
| AI ADE returns no output | Read the visible nonblank-page failure and provider diagnostics |
| Old interrupted progress appears | Relaunch current code; incomplete records should normalize to pending |
| A value is uncertain | Compare it with the source box or native source anchor |

See [docs/run.md](docs/run.md), [docs/local-ollama.md](docs/local-ollama.md), and the [complete user guide](docs/complete-user-guide.md) for more detail.
