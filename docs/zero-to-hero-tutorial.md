# Grounded DocParse: Zero-to-Hero Tutorial

This tutorial explains the repository from first principles through day-to-day use, Python integration, internal implementation, testing, and production deployment boundaries. It is written for a newcomer who has never used the application, but it also shows developers where each behavior lives in the code.

The short version is:

```text
required per-file processing type
  -> scanned PDF/image: one selected AI ADE, vLLM, Docling/RapidOCR, or Ollama engine
  -> Native PDF: pdf-inspector; Mixed PDF: reviewed page routes
  -> Office/open formats: OCR-disabled Docling conversion
  -> grounded OCR elements or immutable native source spans/anchors
  -> Markdown, JSON, optional annotated PDF, and optional extraction/chat
```

The most important grounded-path rule is that the selected local engine and deterministic code own document structure. Optional AI enhancement can reason over that structure, but cannot move evidence, invent a missing detector region, or replace source geometry. **AI ADE** is an explicit separate engine.

## 1. Choose your path through this tutorial

Use these reading paths if you do not need every section immediately:

- **First-time user:** Sections 2–10.
- **Medical-fax operator:** Sections 2–12, especially Section 11.
- **Python integrator:** Sections 2–6 and 13–15.
- **Repository contributor:** Sections 2–6 and 13–18.
- **Production or Azure owner:** Sections 16–19, then the dedicated [Azure bulk-fax runbook](azure-bulk-fax-deployment.md).

## 2. What problem does this project solve?

Ordinary OCR answers “what text appears in this image?” A business document system needs more:

- Which page and region produced a value?
- Is the text a heading, paragraph, table, form field, or visual?
- What is the reading order?
- Can a reviewer open the original source location?
- Can an extracted field be rejected when its evidence is missing?
- Can a mixed fax packet be split into form ranges before extraction?

Grounded DocParse converts native documents, scanned PDFs, and images into structured, reviewable document representations. It preserves source traceability for selectable text as well as visually complex scans.

The current application is a workstation-oriented Streamlit studio. It processes up to 20 uploaded files sequentially and restores one active local batch after restart. It is not an unattended batch service, REST API, multi-user system, or production job processor.

### 2.1 Core outputs

A successful parse can produce:

| Output | Purpose |
| --- | --- |
| Refined Markdown | Human-readable reconstruction with optional presentation improvements |
| Grounded `base_markdown` | Canonical Markdown to which source spans refer |
| Parse JSON v4.5.0 | Parse structure, elements, quality, provenance, usage, recovery, and OCR-comparison information |
| Full JSON v4.6.0 | Parse data plus optional analysis, routing, and extraction results |
| Extraction JSON v1.1.0 | One-schema scalar extraction with evidence and field confidence |
| Routed extraction JSON v2.0.0 | Per-form extraction results for approved eligible segments |
| Annotated PDF | Original pages with semantic boxes, reading order, and source highlighting |
| Native JSON v5.0.0 / combined v5.1.0 | Immutable `base_text`, source spans, anchors, and optional grounded extraction |

## 3. Essential concepts and vocabulary

Understanding these terms makes the rest of the repository much easier to follow.

### 3.1 Rasterization

Rasterization renders scanned PDF pages and image frames into pixels. Native PDFs do not enter this image-first pipeline: `pdf-inspector` extracts their selectable text, layout, tables, and positions. Mixed PDFs explicitly combine both routes page by page.

Why this matters: the user explicitly selects the evidence route. Native PDF text is traceable through page/bounding-box anchors, while scanned-page evidence remains visual/OCR based. Mismatches are blocked rather than silently rerouted.

### 3.2 Layout analysis and OCR

Layout analysis finds regions such as headings, paragraphs, tables, form areas, and images. OCR recognizes text inside those regions.

For grounded routes, the selected local engine owns:

- element identity;
- normalized bounding boxes;
- region type and hierarchy;
- OCR confidence;
- reading order; and
- initial text.

### 3.3 Grounding

Grounding means connecting an output back to known source evidence. The public `Element` contract contains:

```text
id, type, page, bbox, text, reading_order, confidence, source
```

An element ID is the stable bridge between the parsed document, extracted fields, chat citations, TOC links, and annotated-PDF highlighting.

Bounding boxes are normalized coordinates:

```text
[x0, y0, x1, y1], where every value is between 0 and 1
```

Normalized coordinates make the result independent of a particular rendered pixel size.

### 3.4 Recovery versus refinement versus extraction

These are three different operations:

| Operation | Input | Allowed result | Runs when |
| --- | --- | --- | --- |
| Visual recovery | Selected difficult image crops | Replacement text for an existing element | During parsing, if enabled |
| Markdown refinement | Grounded Markdown and element anchors | Presentation directives | During parsing, if enabled |
| Extraction | Parsed Markdown/layout plus a schema | Requested values with evidence | On demand after parsing |

Visual recovery does not perform a second full-document OCR pass. Markdown refinement does not replace canonical evidence. Extraction does not change the parsed document.

### 3.5 Document classification versus custom form routing

These features answer different questions:

- **Document classification:** “What kind of document is this overall?” It uses recognized content/layout from the first two pages.
- **Custom form routing:** “Which contiguous page ranges belong to which business categories, and which ranges should be extracted?” It can segment a mixed PDF into multiple forms.

For a fax packet containing a cover sheet, a new authorization, medical records, and an authorization update, document classification is too coarse. Custom form routing is the correct tool.

### 3.6 Evidence confidence

Extracted fields use four review-oriented states:

- `high`: strong evidence supports the value;
- `medium`: evidence exists, but the match is less certain;
- `inferred`: a cited nearby region exists, but the exact value-to-source match was not verified;
- `not_found`: no supportable value was found, so the result remains empty.

`inferred` is not equivalent to verified. Regulated or financially material values still require the organization’s review policy even when confidence is high.

## 4. Architecture at a glance

The supported local topology is deliberately small:

```text
Browser
  -> Streamlit studio on 127.0.0.1:7137
       -> ingest and rasterization
       -> selected engine
            -> Windows CPU PP-DocLayoutV3 + WSL GLM vLLM or Windows Ollama
            -> PaddleX/Paddle vLLM, Docling/RapidOCR, PDF Inspector, or AI ADE
       -> deterministic quality and recovery planning
       -> optional selected-provider requests
       -> renderers, tabs, highlighting, and downloads
```

There are two AI execution boundaries:

1. **Local extraction:** native Windows components handle PP-DocLayoutV3, Ollama, Docling/RapidOCR, and PDF Inspector; GLM/Paddle vLLM recognition remains in WSL on loopback-only services.
2. **Optional AI:** selected crops or document context go to OpenAI, Google, or Agnes only when the associated feature is enabled and its key is available.

There is no open-ended agent loop. Optional features use bounded, typed requests followed by deterministic validation.

## 5. Install the supported local environment

### 5.1 Prerequisites

The supported primary setup is:

- Windows 11;
- optional WSL2 Ubuntu 24.04 and NVIDIA passthrough for the two vLLM engines;
- Git;
- network access during the first dependency/model download; and
- enough disk space for the WSL environment and model cache.

Python package metadata supports Python 3.12 through 3.14; the native launcher installs Python 3.12 under `%LOCALAPPDATA%\GroundedDocParse`.

The repository does not publish universal minimum RAM, VRAM, or disk figures because page size, model cache, and concurrency change the requirement. The checked-in workstation profile was tuned around an 8 GB GPU and an 18 GB WSL memory limit; treat that as a verified reference profile, not a guarantee for every document. Confirm GPU visibility and leave capacity for the WSL environment, Python packages, and pinned model snapshots before setup.

### 5.2 Clone and verify WSL/GPU access

Run in PowerShell:

```powershell
git clone https://github.com/pypi-ahmad/grounded-docparse.git
Set-Location grounded-docparse

wsl --install -d Ubuntu-24.04
wsl --update
wsl --list --verbose
wsl -d Ubuntu-24.04 -- nvidia-smi
```

Restart Windows if WSL requests it, then complete Ubuntu’s first-login setup.

### 5.3 Decide whether optional AI features are allowed

Local parsing does not require a cloud key. If enhancement, classification, refinement, TOC, extraction, routing, or chat are required, save the selected provider key in the Windows User environment:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-key", "User")
[Environment]::SetEnvironmentVariable("GOOGLE_API_KEY", "your-key", "User")
[Environment]::SetEnvironmentVariable("AGNES_API_KEY", "your-key", "User")

# Optional trusted OpenAI-compatible endpoint:
# [Environment]::SetEnvironmentVariable(
#     "OPENAI_BASE_URL",
#     "https://approved.example/v1",
#     "User"
# )
```

Do not place real credentials in `.env`, Markdown, scripts, source code, commits, logs, screenshots, or issue reports.

A configured custom base URL receives the same sensitive content as its default provider. Verify the destination before processing real documents.

### 5.4 Run first-time setup

From PowerShell in the repository root:

```powershell
.\Launch-Grounded-DocParse.cmd
```

The setup process:

1. installs or reuses Windows `uv` and Python 3.12;
2. synchronizes the locked native and `windows-layout` dependencies;
3. downloads pinned CPU PP-DocLayoutV3 assets;
4. installs or starts Windows Ollama;
5. starts native Streamlit on loopback; and
6. opens <http://localhost:7137>.

Later sessions use the same launcher. Use `Setup-GLM-OCR.cmd` or
`Setup-PaddleOCR-VL-1.6.cmd` only to provision and warm a WSL GPU backend.

```powershell
.\Launch-Grounded-DocParse.cmd
```

The generic launcher refreshes User-scope provider settings and opens the app. The UI keeps the two WSL GPU models mutually exclusive.

### 5.5 Manual WSL launch

Inside Ubuntu, setup and launch both services with:

```bash
bash scripts/wsl/setup-glmocr.sh
bash scripts/wsl/launch-stack.sh
```

For foreground development, use two WSL terminals:

```bash
# Terminal 1
bash scripts/wsl/serve-glmocr.sh
```

```bash
# Terminal 2
bash scripts/wsl/run-app.sh
```

Both managed services bind to loopback. Do not override that boundary on an untrusted network.

## 6. Your first successful parse

Open <http://localhost:7137>, then follow this minimal path:

1. Upload one supported document. For a safe OCR practice run, use the bundled `examples/synthetic-report.pdf`.
2. Select a compatible processing type. For a PDF choose Native, Scanned, or Mixed; for Mixed PDF confirm every Native/OCR page route.
3. For scanned PDFs and images, optionally enable **Page range**, select an OCR engine, then choose an ADE mode.
4. Decide whether visual recovery is allowed for OCR routes.
5. Select **Parse document**.
6. Review Markdown, JSON, source structure, and any available annotated PDF before running extraction.

### 6.1 ADE modes

“ADE mode” is only a UI preset for optional AI features. It is not an integration with an external ADE product.

| Mode | Markdown refinement | Document classification | TOC |
| --- | --- | --- | --- |
| Fast | Off | On | Off |
| Full | On | On | On |
| Custom | User-selected | User-selected | User-selected |

Visual recovery and chat are separate toggles. Extraction is never automatically run by an ADE mode.

Fast mode can make remote requests when classification is enabled and the selected provider key exists. AI enhancement defaults off. Disable every AI-related toggle for a local-only run.

### 6.2 What happens after selecting Parse document?

The progress UI reflects these major stages:

```text
selection -> validation -> selected native/OCR pipeline -> canonical evidence
          -> optional enhancement -> optional document analysis/extraction
```

The exact parser flow is:

1. Require a compatible processing type and validate file signatures/container structure.
2. Route scanned PDFs/images to OCR, Native PDF to `pdf-inspector`, Mixed PDF to confirmed page routes, and Office/open formats to Docling without OCR.
3. Apply local OCR quality/recovery only to OCR routes; native embedded images are recorded rather than OCRed.
4. Merge Mixed PDF pages in original order and build OCR elements or immutable native `base_text`, character spans, and anchors.
5. Generate Markdown, JSON, source structure, and an annotated PDF only when a visual artifact exists.
6. Optionally apply refinement, classification, TOC, extraction, and chat. Native LangExtract values must have exact intervals that resolve to source anchors.

For GLM-OCR, pages are prepared/finalized concurrently within ordered windows while the process-wide SDK runtime serializes model access. Default page concurrency is eight. PaddleOCR-VL submits the complete document to its local API.

The UI implements a page range by creating a new subset PDF before parsing. Output page 1 therefore means the first selected page, not necessarily page 1 of the original PDF. If downstream users need original-file page numbers, retain the selected start-page offset or another explicit mapping outside the current result.

### 6.3 Recovery invariants

AI enhancement may replace text on a failed or sub-75%-confidence existing element. It may not change:

- element ID;
- bounding box;
- type;
- hierarchy;
- reading order;
- local OCR confidence; or
- document structure.

AI additions, geometry changes, and structural changes are ignored. If the detector misses a source region entirely, enhancement does not synthesize it.

If at least one page is nonblank but no nonblank page contains any grounded layout region, the parser stops before enhancement. An isolated page failure can remain visible as partial output with warnings.

## 7. Learn the Streamlit studio

After parsing, the application exposes these views:

### 7.1 Overview

Use Overview to inspect document classification, page count, summary metrics, warnings, recovery activity, and the optional table of contents.

### 7.2 Markdown

The normal Markdown view renders the reconstructed document. The raw view is useful when inspecting headings, tables, comments, or exact text sent downstream.

Remember the distinction:

- `base_markdown` is the canonical grounded representation;
- `markdown` may include optional presentation refinements.

Source spans target `base_markdown`, not the presentation-refined string.

### 7.3 Annotated PDF

The annotated PDF overlays semantic boxes and reading-order labels on the original pages. Recovered elements receive a distinct dashed treatment. Source actions from other tabs open the corresponding highlighted page/box.

### 7.4 Extract

This tab appears only after parsing. It supports either:

- one schema against the whole parsed document; or
- custom form routing followed by per-segment extraction.

An OpenAI key is required for extraction.

### 7.5 Chat

Chat appears only when enabled. It sends no request until a question is submitted. Valid citations must resolve to known element IDs before **Show source** is exposed. Uncited answers receive low confidence.

### 7.6 Layout Tree

The Layout Tree shows page-by-page hierarchy and reading order. Selecting an element opens its original source region and exposes its ID, type, text, confidence, and provenance.

## 8. Define an extraction schema

Extraction is optional and always occurs after a successful parse. A schema tells the model exactly which business values to return.

### 8.1 Good field design

Each field should have:

- a unique machine-safe name;
- a precise business description; and
- an expected type.

Prefer:

```text
rendering_provider_npi
The NPI of the clinician who rendered the requested service, not the facility NPI.
```

Avoid:

```text
provider_number
Provider number.
```

The UI supports scalar types `string`, `number`, `integer`, `boolean`, and `date`. Field names must begin with a letter or underscore and then contain only letters, numbers, or underscores.

### 8.2 Build fields in the UI

In **Extract**:

1. Leave **Use custom form routing** off.
2. Expand **Extraction schemas**.
3. Choose **New schema** or load an existing saved schema.
4. Enter the schema name.
5. Add field rows with names, descriptions, and types.
6. Select **Save schema** for reuse.
7. Select **Run extraction**.

Saving writes the reusable definition to the local SQLite database. An unsaved valid draft can still be used for whole-document extraction.

### 8.3 Import an extraction schema from Markdown

Markdown is the easiest format for a business-owned field dictionary. Files must be UTF-8 `.md`, no larger than 1 MB, and use either a table or bullets—not both.

Table form:

```markdown
# New Authorization

| Field name | Description | Type |
| --- | --- | --- |
| patient_name | Full patient name on the authorization request | string |
| member_id | Health-plan member identifier | string |
| date_of_birth | Patient date of birth | date |
| requested_service | Service or procedure being requested | string |
| requesting_provider_npi | NPI of the requesting provider | string |
| urgent | Whether the request is marked urgent | boolean |
```

Bullet form:

```markdown
# New Authorization

- patient_name: Full patient name on the authorization request
- member_id: Health-plan member identifier
- date_of_birth (date): Patient date of birth
- requested_service: Service or procedure being requested
- requesting_provider_npi: NPI of the requesting provider
- urgent (boolean): Whether the request is marked urgent
```

The H1 becomes the schema name. Without an H1, the filename stem is used. An omitted type defaults to `string`.

Uploading Markdown loads an editable draft. It does not automatically save the schema or run extraction. Review the rows, then select **Save schema** if the definition should be reusable.

The exact click path is **Extract** → **Extraction schemas** → **Import schema Markdown, CSV, or XLSX** → choose the `.md` file. The upload itself populates the draft; there is no separate import button.

### 8.4 Import an extraction schema from CSV or XLSX

CSV and XLSX files use the same flat field columns:

```csv
Field name,Description,Type
patient_name,Full patient name,string
date_of_birth,Patient date of birth,date
urgent,Whether the request is marked urgent,boolean
```

The first XLSX worksheet is imported. The filename becomes the schema name, and an empty type defaults to `string`. Uploading the file loads an editable draft without saving it.

### 8.5 Import or export JSON

The UI’s schema import/export shape is an application definition, not compiled JSON Schema:

```json
{
  "version": 1,
  "name": "New Authorization",
  "fields": [
    {
      "name": "patient_name",
      "description": "Full patient name on the authorization request",
      "type": "string"
    }
  ]
}
```

Selecting **Import JSON** validates and immediately persists the definition. Markdown, CSV, and XLSX imports only populate the draft. **Export schema JSON** downloads the current valid draft.

### 8.6 What the UI compiles

The application converts every scalar field to a required but nullable JSON Schema property. A date becomes a nullable string whose description asks for ISO 8601 output.

Conceptually:

```json
{
  "type": "object",
  "properties": {
    "patient_name": {
      "type": ["string", "null"],
      "description": "Full patient name on the authorization request"
    }
  },
  "required": ["patient_name"],
  "additionalProperties": false
}
```

Required-but-nullable is deliberate: the response must mention every requested field, but it must use `null` instead of inventing a missing value.

## 9. Run and review whole-document extraction

When **Run extraction** is selected, the application reuses the prepared grounded context. Long scalar schemas can be evaluated across multiple bounded document contexts; the highest-confidence compatible values are merged, and equal-rank conflicts are arbitrated over implicated pages.

For each field, inspect:

- value;
- confidence;
- page;
- element ID;
- normalized bounding box; and
- source text.

Use **Show source** for every medium, inferred, important, or regulated value. A correct number from the wrong role or section is still a business error.

Recommended review policy:

1. Review every `inferred`, `medium`, and `not_found` field.
2. Always review critical identifiers, dates, totals, and compliance decisions.
3. Sample `high` fields according to the organization’s quality policy.
4. Reconcile related values, such as service dates and authorization periods.
5. Record unresolved values for manual follow-up.

## 10. Understand extraction validation

The extraction flow is more constrained than “send Markdown and hope for JSON”:

```text
schema validation
  -> bounded grounded context
  -> strict structured response
  -> JSON/evidence validation
  -> evidence resolution to known elements
  -> one semantic evidence-repair attempt if necessary
  -> deterministic exact/normalized/inferred/not-found decision
```

Accepted evidence must point to existing parsed elements. The final box comes from the local-OCR-owned element, not from a new model-generated coordinate.

The UI builder supports scalar schemas. The direct Python `DocumentExtractor` API also supports nested objects and arrays, but nested schemas use one direct extraction path rather than the long-document scalar partition/merge strategy.

## 11. Mixed medical faxes: extract only new authorizations

This is the canonical use case for custom form routing.

Use the bundled `examples/synthetic-medical-fax.pdf` for a safe walkthrough, or suppose a representative packet contains:

```text
pages 1-2   fax cover sheet + new authorization
pages 3-6   medical records
pages 7-8   authorization update
pages 9-10  another new authorization
```

The goal is not to extract from the whole packet. The goal is:

1. parse all pages once;
2. classify contiguous form segments;
3. review uncertain boundaries/categories;
4. mark only `newauth` as extractable; and
5. run the New Authorization schema only against approved `newauth` ranges.

### 11.1 Save the extraction schema first

Create and save the `New Authorization` extraction schema from Section 8. Routing profiles can only reference extraction schemas that already exist in the local schema store.

### 11.2 Create a routing profile in the UI

In **Extract**:

1. Enable **Use custom form routing**.
2. Expand **Routing profile**.
3. Name the profile, for example `Medical fax routing`.
4. Add categories and descriptions.
5. Check **Extract** only for `newauth`.
6. Assign the saved `New Authorization` schema to `newauth`.
7. Save the routing profile.

Example category design:

| Category | Description | Extract? | Schema |
| --- | --- | --- | --- |
| `newauth` | Initial request for a new authorization | Yes | `New Authorization` |
| `authupdate` | Update to an existing authorization | No | — |
| `behavioral_health` | Behavioral-health form that is not a new authorization | No | — |
| `medical_records` | Medical records without a new authorization request | No | — |
| `other` | Built-in fallback when supplied categories do not apply | Never | — |

`other` is reserved and automatically added. Do not define it in the profile.

### 11.3 Import a routing profile from Markdown

Routing Markdown must also be UTF-8 `.md`, no larger than 1 MB, and use a table or bullets.

Table form:

```markdown
# Medical fax routing

> Treat fax cover sheets as part of the following form when the pages clearly belong together.

| Category | Description | Extract | Schema |
| --- | --- | --- | --- |
| newauth | Initial request for a new authorization | yes | New Authorization |
| authupdate | Update to an existing authorization | no | |
| behavioral_health | Behavioral-health form that is not a new authorization | no | |
| medical_records | Medical records without an authorization request | no | |
```

Bullet form:

```markdown
# Medical fax routing

> Treat fax cover sheets as part of the following form when the pages clearly belong together.

- newauth [extract=New Authorization]: Initial request for a new authorization
- authupdate: Update to an existing authorization
- behavioral_health: Behavioral-health form that is not a new authorization
- medical_records: Medical records without an authorization request
```

Blockquote lines become optional routing instructions. In bullet format, `[extract=Schema Name]` makes that category eligible and assigns its schema.

Markdown upload loads an editable draft. JSON import validates and persists the profile. Missing referenced schemas prevent the profile from becoming usable.

### 11.4 Classify and segment the packet

Select **Classify forms**. The routing implementation:

1. walks bounded prepared contexts across the parsed document;
2. overlaps a boundary page between windows;
3. requires contiguous, valid page coverage;
4. validates category keys and evidence element IDs;
5. retries one invalid structured response;
6. reconciles window boundaries; and
7. assigns extraction eligibility from the saved profile—not from the model.

Each segment records both predicted and effective page range/category. “Predicted” here means the classifier result after deterministic window reconciliation: ranges may already be clipped to the current context, invalid evidence IDs filtered, and same-category boundary segments merged. It is not an untouched copy of the provider’s raw response. Effective values may then reflect user review.

Segments at or above `0.85` confidence are normally auto-approved. Lower-confidence segments require review. A same-category segment merged across a classifier-window boundary also requires review, regardless of confidence.

### 11.5 Review before extraction

The UI allows a reviewer to edit:

- start page;
- end page;
- category; and
- approval.

It keeps confidence, reasoning, eligibility, and schema assignment read-only. Eligibility is always recalculated from the profile.

Review every uncertain segment and select **Apply routing review**. The UI enables **Extract eligible forms** only when:

- every segment is approved;
- at least one segment is eligible; and
- the routing profile is unchanged since classification.

Approving an ineligible `medical_records` or `other` segment confirms the routing decision; it does not make that segment extractable.

Once every segment is approved and the profile is unchanged, select **Download split documents**. The `.segments.zip` exports every segment, including ineligible and repeated categories, as its own original-page PDF, Markdown, and canonical parsed-document JSON. `manifest.json` maps each segment's routing metadata to those files. Markdown and JSON keep parsed page numbers, element IDs, and source boxes.

### 11.6 Extract only eligible forms

Select **Extract eligible forms**. For each eligible segment, the code creates an in-memory `ParseResult` subset containing only the segment’s original pages and elements, then runs its assigned schema.

The subset preserves:

- page numbers from the parsed document;
- element IDs;
- GLM bounding boxes; and
- source traceability.

Non-eligible segments are skipped. One segment’s extraction failure is recorded on that segment without deleting successful results from other segments.

If the user parsed a UI page-range subset, these are the subset’s renumbered pages rather than the page numbers of the original full PDF.

## 12. Persistence, downloads, and session behavior

### 12.1 What persists

Reusable extraction schemas, routing profiles, and the active batch workspace persist in:

```text
data/document_studio.sqlite3
```

Override the path with `DOCPARSE_STUDIO_DB_PATH`. SQLite uses WAL mode and case-insensitive definition names. Saving the same name updates the existing mutable definition. The sibling `workspaces/` directory stores uploaded source bytes, parse checkpoints, and annotated PDFs. The latest batch is restored after an app restart. The managed Windows launcher replaces the verified prior Streamlit process and clears transient Streamlit cache/session state, but preserves this durable batch and any warm WSL OCR service. Use **Clear saved workspace** to delete the durable batch.

### 12.2 What does not persist

Extraction, routing review, and chat remain in Streamlit process/session state. Ending the session or restarting the process can lose them. Parse results stay in the local workspace until the batch is replaced or cleared.

Download required artifacts before ending the session:

- `<stem>.md`;
- `<stem>.annotated.pdf`;
- `<stem>.extract.json` when extraction ran; and
- `<stem>.full.json`.

The active UI keeps only the latest whole-document or routed extraction result. It does not merge multiple schema runs into a single business record.

## 13. Use the public Python API

The repository installs `grounded-docparse`. Use `grounded-docparse ingest` for explicit native/OCR routing and `grounded-docparse parse` for legacy PDF/image OCR batches. Programmatic reuse is also available through the Python package.

The snippets below are incremental: later examples assume the `result` produced in Section 13.1 unless they explicitly parse a different example. Save the combined imports and statements as `scratch.py` in the repository root.

GLM recognition requires the setup-created WSL vLLM service, while the parser and CPU layout stage run on Windows. Legacy evaluation commands still run in the WSL environment:

```bash
source "${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}/bin/activate"
python scratch.py
```

Native Windows `uv run python scratch.py` can parse after `uv sync --locked --extra native --extra windows-layout`; GLM and Paddle vLLM additionally require their WSL services.

### 13.1 Parse a document

```python
from pathlib import Path

from grounded_docparse import DocumentParser

source = Path("examples/synthetic-report.pdf")
result = DocumentParser().parse(
    source.read_bytes(),
    source.name,
    refine_markdown=False,
    visual_recovery=True,
)

print(result.markdown)
print(result.structured_json["schema_version"])
result_path = source.with_suffix(".annotated.pdf")
result_path.write_bytes(result.annotated_pdf)
```

`DocumentParser.parse` is synchronous for legacy OCR. `UniversalDocumentParser.parse` is synchronous for manually selected native, scanned, mixed, and image routes.

The Python parse API has no page-range parameter. Slice the PDF before calling it or use the Streamlit page-range control.

### 13.2 Observe progress

```python
from pathlib import Path

from grounded_docparse import DocumentParser


def progress(event) -> None:
    print(f"{event.stage}: {event.current}/{event.total} - {event.message}")


source = Path("examples/synthetic-report.pdf")
result = DocumentParser().parse(
    source.read_bytes(),
    source.name,
    progress_callback=progress,
)
```

Callbacks run on the caller thread after worker events are queued and replayed. Keep them fast and do not raise exceptions.

### 13.3 Reuse prepared context for optional features

```python
from grounded_docparse import DocumentAgent, render_combined_result

agent = DocumentAgent()
prepared = agent.prepare(result)

analysis = agent.analyze(
    result,
    classify=True,
    generate_toc=True,
    prepared_context=prepared,
)

schema = {
    "type": "object",
    "properties": {
        "invoice_number": {
            "type": ["string", "null"],
            "description": "Official invoice identifier",
        },
        "total": {
            "type": ["number", "null"],
            "description": "Final amount payable",
        },
    },
    "required": ["invoice_number", "total"],
    "additionalProperties": False,
}

extraction = agent.extract(result, schema, prepared_context=prepared)

answer = agent.chat(
    result,
    "Which page contains the total?",
    history=[],
    prepared_context=prepared,
)

full_json = render_combined_result(result, analysis, extraction)
```

Prepared context avoids rebuilding the same flattened elements and bounded document contexts for each feature.

### 13.4 Route mixed forms in Python

```python
from pathlib import Path

from grounded_docparse import (
    ClassifierCategory,
    ClassifierProfile,
    DocumentAgent,
    DocumentParser,
    FormSegment,
    render_combined_result,
)

fax_source = Path("examples/synthetic-medical-fax.pdf")
result = DocumentParser().parse(
    fax_source.read_bytes(),
    fax_source.name,
    refine_markdown=False,
    visual_recovery=True,
)

newauth_schema = {
    "type": "object",
    "properties": {
        "patient_name": {
            "type": ["string", "null"],
            "description": "Full patient name",
        },
        "member_id": {
            "type": ["string", "null"],
            "description": "Health-plan member identifier",
        },
    },
    "required": ["patient_name", "member_id"],
    "additionalProperties": False,
}

profile = ClassifierProfile(
    name="Medical fax routing",
    instructions="Treat a cover sheet as part of the following form when supported.",
    categories=[
        ClassifierCategory(
            key="newauth",
            description="Initial request for a new authorization",
            extract=True,
            schema_name="New Authorization",
        ),
        ClassifierCategory(
            key="authupdate",
            description="Update to an existing authorization",
        ),
        ClassifierCategory(
            key="medical_records",
            description="Medical records without an authorization request",
        ),
    ],
)

agent = DocumentAgent()
prepared = agent.prepare(result)
classification = agent.classify_forms(
    result,
    profile,
    prepared_context=prepared,
    confidence_threshold=0.85,
)

# Display predicted segments in a trusted review UI and collect decisions there.
# This example shows one possible reviewed-decision payload. Omit automatically
# approved segments; include every segment that a reviewer confirms or corrects.
review_decisions = {
    # "form-002": {
    #     "start_page": 3,
    #     "end_page": 6,
    #     "category": "medical_records",
    #     "approved": True,
    # },
}

category_by_key = {category.key: category for category in profile.categories}
reviewed_segments = []
for original in classification.segments:
    decision = review_decisions.get(original.id)
    if decision is None:
        reviewed_segments.append(original)
        continue

    start_page = int(decision["start_page"])
    end_page = int(decision["end_page"])
    category_key = str(decision["category"])
    approved = bool(decision["approved"])
    if category_key != "other" and category_key not in category_by_key:
        raise ValueError(f"Unknown reviewed category: {category_key}")
    if not 1 <= start_page <= end_page <= len(result.document.pages):
        raise ValueError(f"Invalid reviewed range: {start_page}-{end_page}")

    category = category_by_key.get(category_key)
    eligible = bool(category and category.extract)
    changed = (start_page, end_page, category_key) != (
        original.start_page,
        original.end_page,
        original.category,
    )
    reviewed_segments.append(
        FormSegment(
            id=original.id,
            predicted_start_page=original.predicted_start_page,
            predicted_end_page=original.predicted_end_page,
            predicted_category=original.predicted_category,
            start_page=start_page,
            end_page=end_page,
            category=category_key,
            confidence=original.confidence,
            reasoning=original.reasoning,
            evidence_element_ids=original.evidence_element_ids,
            approved=approved,
            review_status=(
                "user_corrected" if approved and changed
                else "user_confirmed" if approved
                else "needs_review"
            ),
            eligible=eligible,
            schema_name=category.schema_name if eligible else None,
        )
    )

reviewed_segments.sort(key=lambda segment: (segment.start_page, segment.end_page))
covered_pages = [
    page
    for segment in reviewed_segments
    for page in range(segment.start_page, segment.end_page + 1)
]
if covered_pages != list(range(1, len(result.document.pages) + 1)):
    raise ValueError("Reviewed segments must cover every page exactly once")

classification = classification.model_copy(
    update={"segments": reviewed_segments},
    deep=True,
)

unapproved = [segment.id for segment in classification.segments if not segment.approved]
if unapproved:
    raise RuntimeError(f"Human routing review required: {unapproved}")

routed = agent.extract_forms(
    result,
    classification,
    schemas_by_name={"New Authorization": newauth_schema},
)

full_json = render_combined_result(
    result,
    custom_classification=classification,
    routed_extraction=routed,
)
```

The package intentionally does not provide a command-line review manager or durable review store. The Streamlit app implements this review in `_apply_routing_review`; another application must collect the equivalent decisions before resuming `extract_forms`. In production, store predicted and corrected values plus reviewer identity instead of mutating review state invisibly.

### 13.5 Direct extraction API

`DocumentExtractor` exposes lower-level schema proposal and extraction:

```python
from grounded_docparse import DocumentExtractor

extractor = DocumentExtractor()
proposal = extractor.propose_schema(
    "Extract invoice number, due date, and total",
    result,
)
extraction = extractor.extract(
    result,
    proposal.json_schema,
    allow_inferred=False,
)
```

Use `allow_inferred=False` when unresolved fields must remain `null`. `DocumentAgent.extract` enables deterministic inferred grounding after its evidence-repair attempt.

## 14. Read the code from the outside in

The fastest way to understand the implementation is to follow the user request through these files:

| File | Responsibility |
| --- | --- |
| `streamlit_app.py` | Upload, modes, progress, tabs, schema/profile editors, review, downloads |
| `src/grounded_docparse/config.py` | Engine/model selection, endpoints, parser limits, and thresholds |
| `src/grounded_docparse/ingest.py` | Input validation, page rasterization, crop rerendering |
| `src/grounded_docparse/local_ocr.py` | Process-wide GLM-OCR runtime and SDK normalization |
| `src/grounded_docparse/page_analysis.py` | Page signals and GLM region conversion |
| `src/grounded_docparse/quality.py` | Deterministic quality, verification, and recovery selection helpers |
| `src/grounded_docparse/pipeline.py` | `DocumentParser`, page orchestration, recovery, hierarchy, output assembly |
| `src/grounded_docparse/gateways.py` | OpenAI Responses calls, structured output, usage, and trace collection |
| `src/grounded_docparse/prompts.py` | Versioned prompts and untrusted-document boundaries |
| `src/grounded_docparse/enhancement.py` | Markdown chunks and presentation-directive application |
| `src/grounded_docparse/agentic.py` | Prepared contexts, document analysis, routing, extraction, chat |
| `src/grounded_docparse/extraction.py` | Schema validation, evidence resolution, confidence decisions |
| `src/grounded_docparse/models.py` | Pydantic domain and result contracts |
| `src/grounded_docparse/schema_store.py` | Markdown parsers, JSON Schema compilation, SQLite stores |
| `src/grounded_docparse/render.py` | Markdown, JSON, public elements, quality, and PDF annotations |
| `src/grounded_docparse/runtime.py` | Provider concurrency, retry, cooldown, and diagnostics |

### 14.1 Main UI call path

```text
streamlit_app.py
  -> DocumentParser().parse(...)
  -> DocumentAgent.prepare(result)
  -> DocumentAgent.analyze(...)              # optional
  -> DocumentAgent.extract(...)              # optional whole document
  -> DocumentAgent.classify_forms(...)       # optional routing
  -> user routing review
  -> DocumentAgent.extract_forms(...)        # optional routed extraction
  -> render_combined_result(...)
```

### 14.2 Parse call path

At a conceptual level, `DocumentParser.parse` coordinates:

```text
ingest_document
  -> page analysis / local GLM runtime
  -> deterministic quality and candidate selection
  -> optional OpenAIDocumentGateway crop inspection
  -> deterministic correction validation
  -> cross-page hierarchy
  -> renderers and ParseResult
```

The parser restores source ordering before hierarchy and export, even when page work completes concurrently.

### 14.3 Optional feature call path

`DocumentAgent.prepare` converts the canonical result into compact contexts. Each normal context is limited to eight pages and 48,000 characters.

`DocumentAgent.analyze` can run document classification and TOC generation concurrently. Each feature fails independently. TOC failure can fall back to grounded GLM headings.

`DocumentAgent.classify_forms` validates contiguous segments, known categories, page bounds, and evidence IDs. Eligibility comes from `ClassifierProfile`, never from model output.

`DocumentAgent.extract_forms` creates page subsets and calls normal extraction sequentially for each eligible segment.

## 15. Data contracts and invariants

### 15.1 Canonical hierarchy

The core domain is broadly:

```text
Document
  -> Page[]
       -> Block[]
            -> child Block[]
            -> text/table/form/visual details
```

`build_elements` flattens the canonical hierarchy into the public `Element` list used by agentic features and source highlighting.

### 15.2 ParseResult

`DocumentParser.parse` returns a `ParseResult` containing:

```text
document
markdown
base_markdown
json
annotated_pdf
elements
metadata
recovery_log
usage and trace
runtime diagnostics
```

### 15.3 Routing contracts

`ClassifierProfile` supports 1–50 unique category keys. `other` is reserved. An extractable category must have a schema name; a non-extractable category may not have one.

`FormSegment` preserves:

- predicted range/category;
- effective range/category;
- confidence and reasoning;
- evidence element IDs;
- approval and review status;
- eligibility; and
- assigned schema name.

`RoutedExtractionResult` contains the reviewed classification, per-segment succeeded/failed records, serialized JSON, usage, and trace.

### 15.4 Schema restrictions

Direct extraction schemas must have an object root. Supported value types are object, array, string, number, integer, boolean, and nullability expressed through type arrays. Every non-root field must accept `null`; every object property must appear in that object’s `required` list; and every object must set `additionalProperties` to `false`.

The strict caller subset uses:

```text
type, enum, properties, required, items, additionalProperties, description
```

Constraints such as `pattern`, length/range bounds, conditional schemas, and composition keywords are intentionally rejected. Business constraints belong in clear descriptions and downstream deterministic validation.

## 16. Configuration and performance controls

`ParserConfig.from_env()` supplies defaults. The most operationally important variables are:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `DOCPARSE_RENDER_DPI` | `200` | Full-page render resolution |
| `DOCPARSE_CROP_DPI` | `450` | Source-crop rerender resolution |
| `DOCPARSE_MAX_UPLOAD_BYTES` | `262144000` | Parser upload limit |
| `DOCPARSE_MAX_PAGES` | `500` | Page/frame limit |
| `DOCPARSE_MAX_PAGE_PIXELS` | `20000000` | Per-page pixel limit |
| `DOCPARSE_MAX_VISUAL_RECOVERY_CROPS` | `64` | Absolute Luna recovery-crop ceiling per document |
| `DOCPARSE_PAGE_BATCH_SIZE` | `16` | Ordered page-window size |
| `DOCPARSE_MAX_PAGE_CONCURRENCY` | `8` | Page worker limit |
| `DOCPARSE_PROVIDER_CONCURRENCY` | `8` | Shared provider-call limit |
| `DOCPARSE_PROVIDER_RETRY_ATTEMPTS` | `3` | Total retryable attempts |
| `DOCPARSE_OCR_ENGINE` | `glm-ocr` | `glm-ocr` or `paddleocr-vl-1.6` |
| `DOCPARSE_LOCAL_OCR_ENABLED` | `true` | Local OCR analysis enabled |
| `DOCPARSE_GLMOCR_CONFIG_PATH` | `config/glmocr.yaml` | GLM SDK configuration |
| `DOCPARSE_GLMOCR_LAYOUT_DEVICE` | `cuda:0` | Layout device |
| `DOCPARSE_PADDLEOCR_SERVICE_URL` | `http://127.0.0.1:8119` | Loopback PaddleX document-parser API |
| `DOCPARSE_STUDIO_DB_PATH` | `data/document_studio.sqlite3` | Reusable-definition database |

The managed vLLM profile uses a deliberate 32,768-token ceiling for the verified workstation rather than attempting the model’s theoretical maximum context. Change runtime limits only after measuring GPU memory, WSL memory, representative pages, and failure behavior.

Provider calls use bounded jittered exponential backoff. HTTP 429 responses reduce effective concurrency and apply `Retry-After` or the configured cooldown. Runtime diagnostics expose calls, retries, tokens, concurrency, cooldown, and wait durations.

## 17. Security and privacy model

The supported repository boundary is a trusted local workstation. It has no multi-user authentication or tenant isolation.

### 17.1 Treat every document as untrusted

Uploaded bytes, filenames, PDF structures, recognized text, model output, schemas, and routing profiles are untrusted inputs. Document text is data, not an instruction to the system. Prompt construction explicitly separates untrusted document content from application instructions.

### 17.2 Understand feature egress

| Feature | Potential remote content |
| --- | --- |
| Visual recovery | Selected image crops and existing-region context |
| Markdown refinement | Anchored Markdown and compact layout records |
| Document classification | Recognized content/layout from the first two pages |
| TOC | Recognized content/layout across bounded contexts |
| Custom routing | Recognized content/layout across bounded form-classifier contexts plus profile |
| Extraction | Recognized content/layout plus extraction schema |
| Chat | Question, recent history, and bounded/retrieved document context |

Requests use `store=False`. This application setting does not replace contractual, organizational, retention, or compliance review of the provider.

### 17.3 Keep local services local

The managed scripts bind Streamlit and vLLM to `127.0.0.1`. Do not expose ports `7137` or `8080` to an untrusted network.

### 17.4 Know the residual data

Normal parse completion removes parser temporary directories, but abnormal process termination and storage recovery are outside that guarantee. Operators remain responsible for:

- downloaded outputs;
- browser/session data;
- backups;
- runtime logs;
- model caches;
- the SQLite database and WAL sidecars; and
- any source files copied outside the app.

Do not use public issues for real documents, credentials, personal data, PHI, or result bundles. Follow [SECURITY.md](../SECURITY.md).

## 18. Test and contribute safely

### 18.1 Install the locked development environment

From PowerShell:

```powershell
uv sync --locked
```

Native Windows installs the core, native, and CPU-layout dependencies. GLM and Paddle recognition use the WSL services created by their setup commands; Ollama recognition remains native.

### 18.2 Run the standard checks

```powershell
uv run pytest -q
uvx ruff check src streamlit_app.py tests scripts
uv run python -m compileall -q src streamlit_app.py tests scripts
git diff --check
```

Automated tests use fake gateways and do not require paid requests. Important suites include:

| Test area | File |
| --- | --- |
| Core parse behavior and recovery | `tests/test_simple_pipeline.py` |
| Public contracts | `tests/test_simple_contract.py` |
| Form routing and gated extraction | `tests/test_form_routing.py` |
| Agent extraction and evidence | `tests/test_agentic_extraction.py` |
| Schema/profile persistence and Markdown | `tests/test_schema_store.py` |
| Streamlit controls and state | `tests/test_simple_streamlit.py` |
| Gateway structured requests | `tests/test_openai_vision_gateway.py` |
| Provider retry/concurrency | `tests/test_provider_runtime.py` |
| Quality decisions | `tests/test_quality.py` |

When behavior changes, test the public contract rather than private implementation details. A bug fix should begin with a reproducing test.

### 18.3 Optional live evaluation

Live evaluation runs inside the setup-created WSL environment while the local GLM service is healthy. A GLM-only example is:

```bash
source "${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}/bin/activate"
python scripts/evaluate_corpus.py --live --glm-only \
  --document synthetic-report \
  --artifacts-dir output/synthetic-report-glm-only \
  --output output/synthetic-report-glm-only.eval.json
```

The bundled corpus is a regression suite. It is not proof of broad production accuracy or equivalence with another document product.

## 19. Current limitations and production path

The repository intentionally does not currently provide:

- a folder-upload workflow;
- an HTTP application API;
- queues or workers;
- durable job/artifact state;
- document/chat persistence;
- multi-user authentication or authorization;
- tenant isolation;
- human-review audit storage;
- automatic cross-schema result merging; or
- safe shared-service deployment.

Do not place a loop around Streamlit session calls and call it production batch processing. For 100 medical faxes, the recommended production architecture separates the web process from GPU workers and adds durable, idempotent orchestration.

The repository’s production design uses:

```text
authenticated web/review UI
  -> malware-scanned Blob intake
  -> Service Bus work queue
  -> PostgreSQL job, definition, review, and audit state
  -> GPU VMSS workers with local GLM-OCR
  -> optional approved AI provider
  -> immutable Blob outputs
```

Required changes include immutable versioned Markdown definitions, per-document job state, idempotency keys, review pauses, output manifests, download brokers, role-based access, retention, monitoring, disaster recovery, and synthetic-data acceptance gates.

Read [Deploy Grounded DocParse on Azure for bulk medical faxes](azure-bulk-fax-deployment.md) before planning any shared or PHI deployment. The current repository is not deployable unchanged as a production PHI service.

## 20. Troubleshooting guide

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Browser does not open | Streamlit did not start or health check failed | Open <http://localhost:7137>; inspect `.runtime/streamlit.log` |
| GLM parse fails before layout | Local service/model unavailable | Check `.runtime/vllm.log`, `nvidia-smi`, and `http://127.0.0.1:8080/v1/models` |
| AI controls are disabled | Selected model key unavailable to Streamlit | Save it in Windows User scope and rerun `Launch-Grounded-DocParse.cmd` |
| Unexpected remote destination | Custom `OPENAI_BASE_URL` is configured | Stop; verify/remove the environment value before processing documents |
| Extraction tab says key required | AI extraction needs the selected provider | Configure its approved key or remain local-only |
| Markdown schema is rejected | Mixed table/bullets, invalid field, encoding, or size | Use one supported format, UTF-8 `.md`, under 1 MB |
| Routing profile is unusable | Extractable category references an unsaved schema | Save the named extraction schema first |
| Extract eligible forms is disabled | Unapproved segment, no eligible segment, or changed profile | Apply review to every segment or rerun classification |
| Segment requires review | Confidence below `0.85` or window-boundary merge | Verify pages/category and approve or correct it |
| Extracted field is inferred | Exact evidence match failed | Inspect source; do not treat it as verified |
| Block is `needs_review` | Deterministic quality/verification concern | Compare text with its highlighted source region |
| Page content is missing | The selected detector did not find the region | Use a clearer source; AI enhancement cannot create missing regions |
| Saved schemas disappeared | Different SQLite path/process environment | Check `DOCPARSE_STUDIO_DB_PATH` and database permissions |
| Provider request fails | Rate limit, endpoint, schema, or network error | Use displayed request/stage diagnostics; inspect safe logs without document text |

## 21. A practical learning sequence

Use this sequence to move from beginner to confident contributor:

1. Run a GLM-only parse and inspect every tab.
2. Repeat with visual recovery and compare recovered elements.
3. Import a three-field Markdown schema and run whole-document extraction.
4. Trace each field from JSON to element ID to annotated source.
5. Build the medical routing profile and classify a mixed synthetic fax.
6. Correct a low-confidence segment and extract only `newauth`.
7. Reproduce the same parse/extract workflow with the Python API.
8. Read `models.py`, then `render.py`, then `pipeline.py`, then `agentic.py`.
9. Run the routing, schema-store, extraction, and Streamlit tests.
10. Read the Azure runbook before proposing batch or shared deployment.

## 22. Completion checklist

You are ready to use the app when you can answer “yes” to these questions:

- Can I explain why GLM owns IDs and geometry?
- Do I know when document content leaves the workstation?
- Can I distinguish visual recovery, Markdown refinement, classification, routing, extraction, and chat?
- Can I build/import a schema and interpret every confidence state?
- Can I classify a mixed packet, review every segment, and extract only eligible categories?
- Can I trace an output value to an element and annotated source box?
- Do I understand what persists and what disappears with the session?
- Do I know the current 20-file session-batch and trusted-workstation limits?
- Can I run the offline verification suite before changing code?
- Will I use the production runbook rather than exposing the local app directly?

## Further reading

- [Project overview](../README.md)
- [Setup and configuration](../SETUP.md)
- [Architecture](architecture.md)
- [Python API](api.md)
- [Business extraction workflow](business-user-extraction-workflow.md)
- [Extraction quality research](extraction-quality-research.md)
- [Azure bulk medical fax deployment](azure-bulk-fax-deployment.md)
- [Security policy](../SECURITY.md)
