# Grounded DocParse Complete User Guide

This guide explains Grounded DocParse in simple language for business users, reviewers, technical users, and administrators. It covers what the application can do, what it cannot do, every major screen and feature, and how to complete common document-processing workflows safely.

You do not need to understand AI or write code to use the application. Technical notes are included for readers who need to understand data flow, privacy, outputs, or integration behavior.

## 1. Start here

Grounded DocParse reads PDFs and images and turns each one into:

- readable Markdown;
- structured document data;
- an annotated copy of the source;
- optional document classification and table of contents;
- optional extracted business fields linked to source regions;
- optional form classification and segmentation for mixed PDF packets; and
- optional document chat with source links.

The basic workflow is:

```text
Upload one or more documents
  -> choose processing options
  -> parse the document
  -> review the source coverage
  -> optionally classify forms
  -> optionally extract fields
  -> validate important results
  -> download the outputs
```

### 1.1 Which type of user are you?

| User | Start with | Main responsibility |
| --- | --- | --- |
| Business operator | Sections 2–16, 18, and 20–22 | Upload, parse, route, extract, review, download, and understand session handling |
| Business reviewer | Sections 8–16, 18, and 20 | Check source evidence, routing decisions, critical values, and retained outputs |
| Technical administrator | Sections 3, 4, 14, 15, and 18 | Setup, credentials, privacy, runtime, troubleshooting |
| Developer or integrator | Sections 14, 15, 17, and 19 | Understand contracts, limits, persistence, and integration options |

## 2. What the application can and cannot do

### 2.1 What it can do

Grounded DocParse can:

- process native, scanned, and mixed PDFs; Word, PowerPoint, Excel, CSV, ODF, HTML, Markdown, and EPUB documents; and PNG, JPEG, and TIFF images;
- process up to 20 files sequentially in one durable local workspace;
- handle multi-page PDFs and multi-frame images;
- process an optional continuous page range from a PDF;
- detect document regions such as text, headings, tables, forms, figures, formulas, and seals;
- reconstruct the document in reading order;
- show every known region on an annotated page;
- create human-readable Markdown and structured JSON;
- identify difficult OCR regions and optionally repair their text;
- optionally classify the document as a whole;
- optionally create a source-linked table of contents;
- extract a controlled list of business fields;
- show where an extracted value came from;
- segment a mixed PDF into contiguous business forms;
- extract only selected categories, such as `newauth` forms;
- answer questions about the parsed document; and
- provide timing, token, warning, and provenance information for review.

### 2.2 What it cannot currently do

The current application does not provide:

- folder upload;
- a production batch queue;
- a production job queue or unattended worker service;
- a public HTTP API;
- multi-user authentication or tenant isolation;
- automatic human-review audit records;
- automatic merging of results from several schemas;
- repeating rows or variable-length arrays in the Streamlit schema builder;
- guaranteed recovery of a source region that OCR never detected; or
- permission to use the output without business or regulatory review.

It processes up to 20 uploaded files sequentially in one active local workspace, with restart recovery, per-file failure isolation, and ZIP export. This is workstation recovery, not an unattended production queue. A separate [Azure bulk-fax deployment design](azure-bulk-fax-deployment.md) describes production bulk processing.

### 2.3 Core parsing versus optional AI features

The application has two broad layers:

1. **Document parsing:** the user selects one compatible processing type and one of six exclusive engines. Grounded choices include WSL vLLM, native Docling/RapidOCR, PDF Inspector, and Windows Ollama; **AI ADE** is the explicit direct-agentic option.
2. **Optional AI features:** GPT 5.6 Luna, Gemini 3.5 Flash Lite, Gemini Flash 3.7, or Agnes 2.5 Flash can enhance failed/sub-75%-confidence regions or reason over parsed content.

Local parsing can run without a cloud key. Optional features require the key for the selected provider and may send document content to it.

## 3. Before you use the application

### 3.1 Business-user checklist

Ask the technical owner to confirm:

- the application is running at an approved URL;
- you are using the correct environment;
- the selected AI provider and any custom destination are approved;
- the document is allowed to be processed in that environment;
- your extraction schema and routing profile are approved; and
- you know where approved outputs must be stored.

Do not upload real personal, financial, confidential, or health information into a development or unapproved environment.

### 3.2 Technical setup summary

The primary app, CPU layout detector, native parsers, and Ollama run on Windows 11. Optional GLM-OCR and PaddleOCR-VL GPU services remain in WSL2 Ubuntu 24.04.

For first-time setup from the repository root in PowerShell:

```powershell
.\Launch-Grounded-DocParse.cmd
```

For later sessions:

```powershell
.\Launch-Grounded-DocParse.cmd
```

The application normally opens at <http://localhost:7137>. GLM-OCR uses loopback port `8080`; PaddleOCR-VL uses loopback ports `8118` and `8119`.

The native launch terminal remains open and follows labeled Streamlit, GLM-OCR, PaddleOCR, and Ollama logs. It waits for a keypress after the app stops so the last messages remain visible.

The sidebar **Session cost** view summarizes total input tokens, cache tokens, output tokens, and estimated synchronous API cost for the current app launch. It provides one row per model and a combined Total row. Restarting the app resets the ledger even when the durable document workspace is restored.

For complete setup, GPU, environment, and service instructions, read [SETUP.md](../SETUP.md).

### 3.3 Optional AI-provider configuration

Local parsing does not need a cloud key. Optional enhancement, refinement, classification, TOC, routing, extraction, and chat require the selected provider key.

An administrator can save the key in the Windows user environment:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-key", "User")
[Environment]::SetEnvironmentVariable("GOOGLE_API_KEY", "your-key", "User")
[Environment]::SetEnvironmentVariable("AGNES_API_KEY", "your-key", "User")
```

An optional `OPENAI_BASE_URL` redirects the same sensitive requests to another compatible endpoint. Only use an approved destination.

Never store real credentials in the repository, a Markdown file, `.env`, screenshots, issue reports, or shared chat messages.

## 4. Understand where document data goes

This is important for business, privacy, and technical users.

| Feature | Runs locally? | What may be sent remotely when enabled? |
| --- | --- | --- |
| Native parsing and grounded layout/OCR | Yes | Nothing to a cloud provider |
| AI enhancement | Candidate selection is local; provider inspection is remote | Failed or sub-75%-confidence region crops and context |
| Markdown enhancement | No | Grounded Markdown and compact layout information |
| Document classification | No | Recognized content/layout from the first two parsed pages |
| Table of contents | No | Recognized content/layout across the document |
| Custom form routing | No | Recognized content/layout plus routing categories/instructions |
| OCR field extraction | No | Recognized content/layout plus the extraction schema |
| Native field extraction | No | Immutable `base_text` plus the extraction schema |
| Document chat | No | Question, recent chat history, and relevant document context |

Stop if the selected provider or a configured custom destination is unexpected.

**Important:** Fast mode is not automatically local-only when classification is enabled. AI enhancement is a separate toggle and defaults off.

For a local-only run, avoid **AI ADE** and turn off:

- **AI enhancement for failed or <75% confidence regions**;
- **Classify document type**;
- **Generate table of contents**; and
- **Enable document chat**.

Do not run AI extraction or custom form routing in a local-only workflow.

## 5. Upload a document

### 5.1 Supported files

Use the **Upload document** area in the left sidebar. Supported file types are:

- PDF (`.pdf`) as Native PDF, Scanned PDF, or Mixed PDF;
- Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`), and CSV (`.csv`);
- OpenDocument, HTML, Markdown, and EPUB as Other Native; and
- PNG (`.png`), JPEG (`.jpg` or `.jpeg`), and TIFF (`.tif` or `.tiff`) as Image.

The UI accepts up to 20 files, limits each file to 250 MB, and limits the batch to 1 GB. Files run sequentially. Default parser limits are 500 pages/frames and 20,000,000 rendered pixels per page. Administrators can lower or raise parser limits through configuration, but the UI uploader keeps its own limits. The parser also checks validity and password protection.

For a safe practice run, use:

- `examples/synthetic-report.pdf`; or
- `examples/synthetic-medical-fax.pdf` for custom routing.

In the Windows file picker, open the cloned `grounded-docparse` repository folder, then open its `examples` folder and select the file.

### 5.2 Page range

For PDFs, enable **Page range** and choose **Start** and **End** if only one continuous section is needed.

Use a page range when:

- a large PDF contains irrelevant appendices;
- only one known form is required;
- cost and processing time should be reduced; or
- a user is testing a small part of a document.

The application creates a new temporary PDF containing only the selected pages. Parsed page 1 therefore means the first selected page, not necessarily page 1 of the original file. Keep the original start-page offset if downstream users need original PDF page numbers.

**Download before changing scope:** choosing a different upload or changing the page range resets the current parse, extraction, routing, and chat state.

### 5.3 Show reading order

**Show reading order** controls whether annotated pages display the sequence in which the application reads regions.

Keep it on when reviewing:

- multi-column pages;
- tables and forms;
- headers and footers;
- pages with side notes; or
- text that appears out of sequence in Markdown.

Turn it off only when the labels make visual review difficult.

## 6. Choose processing options

### 6.1 Processing type

Every uploaded file requires a compatible **Processing type**. This selection is authoritative; the application still validates the file signature and container structure, but it never silently changes the selected route.

- **Native PDF** uses `pdf-inspector` for selectable text, layout, tables, and positions.
- **Scanned PDF** and **Image** use the existing local OCR pipeline.
- **Mixed PDF** shows a Native/OCR suggestion for every page. Review or override each route, then confirm the entire table before parsing.
- **Word**, **PowerPoint**, **Excel**, **CSV**, and **Other Native** use Docling/native structure conversion with OCR disabled.

A Native PDF with pages that need OCR stops and asks you to select Mixed PDF. Embedded images in native documents are recorded but are not OCRed.

### 6.2 ADE mode

ADE mode is a group of presets for optional AI features. It is not a connection to an external ADE product.

| Mode | What it enables | Good for |
| --- | --- | --- |
| Fast | Document classification; no Markdown enhancement or TOC | Familiar documents and faster review |
| Full | Markdown enhancement, document classification, and TOC | First review of complex or long documents |
| Custom | Any user-selected combination | Controlled privacy, cost, or feature testing |

Changing one of the preset-controlled switches can move the mode to **Custom**.

ADE presets do not change the selected extraction engine. Grounded routes preserve their engine-owned structure before optional document features run; **AI ADE** remains its own explicit engine.

Changing Markdown enhancement or visual-recovery settings changes the parse identity and resets current document results. Download anything needed before changing them. Changing classification or TOC settings reruns optional document analysis against the reusable parse. Switching **Use custom form routing** resets current whole-document and routed extraction results.

### 6.3 Enhance with gpt-5.6-luna

This feature improves Markdown presentation. It can adjust how existing elements are presented as headings, paragraphs, list items, or captions.

Use it when:

- the document needs cleaner headings or lists;
- the output is primarily for human reading; or
- a complex report needs improved Markdown structure.

It does not replace the source text, change element locations, or reorder the canonical document.

### 6.4 Enable AI enhancement for failed or low-confidence regions

AI enhancement is optional and defaults off. It runs after the selected grounded engine and considers recognition failures or regions below 75% confidence.

Candidates can include:

- low-confidence OCR;
- a large detected region with missing text;
- unusual character noise;
- weak table structure;
- clipped content; or
- a likely OCR ambiguity.

The selected AI model may propose replacement text only for an existing grounded region; provider output is validated before acceptance.

It cannot change:

- element ID;
- location or bounding box;
- type;
- reading order;
- hierarchy; or
- the existence of a missing region.

Use it for scans, faxes, faint text, and irregular layouts. It is not a full second OCR pass.

### 6.5 Classify document type

This feature predicts the overall document type from recognized content and layout on the first two parsed pages.

Use it when you need a quick label such as an invoice, report, or authorization request.

Do not use this single label to decide which pages to extract from a mixed packet. Use custom form routing for that task.

### 6.6 Generate table of contents

This feature creates a hierarchical list of sections. When a section is linked to a known element, selecting it opens the corresponding highlighted source region.

Use it for:

- reports;
- contracts;
- policy documents;
- manuals; or
- any long document with headings.

If AI TOC generation fails, the application may fall back to headings already found by the grounded engine.

### 6.7 Enable document chat

This feature adds a **Chat** tab. Enabling the switch alone does not send a chat request; a request is sent only after a user submits a question.

Use chat for investigation, not controlled repeatable extraction. A saved extraction schema is the better tool when the same fields must be collected consistently.

## 7. Parse the document

After selecting each file's processing type and any applicable options, choose **Parse document**.

For OCR routes, the progress area shows stages such as:

1. Layout detection
2. Region recognition
3. Optional AI enhancement
4. Base Markdown
5. Annotated PDF when a visual artifact is available
6. AI Markdown refinement
7. Document classification
8. Table of contents

Features that are disabled may still appear in the stage list but do not make a remote request.

### 7.1 What happens technically

In simple terms:

```text
Validate file and selected processing type
  -> route to Native PDF, scanned/image OCR, Mixed PDF, or Docling
  -> native: preserve base_text, spans, and source anchors
  -> OCR: find/read page regions and optionally recover difficult text
  -> Mixed PDF: merge confirmed Native/OCR page results in source order
  -> build Markdown, JSON, and available visual artifacts
  -> run selected optional document features
```

Native PDFs preserve selectable-text evidence through page and bounding-box anchors. Scanned PDFs and images use visible page pixels as OCR evidence.

### 7.2 What happens when an optional feature fails

Optional AI failures normally do not erase a successful local parse. The application displays warnings or an unavailable/failed feature status.

Parsing can stop if the source is invalid, password protected, over a configured limit, or if all nonblank pages lack usable local OCR regions. One failed page does not by itself trigger this document-wide empty-layout failure; isolated page failures can remain visible as warnings/partial output.

### 7.3 Tab map

After a successful parse:

| Tab | When it appears |
| --- | --- |
| Overview | Always |
| Markdown | Always |
| Annotated PDF | When the selected route produces a visual artifact |
| Extract | After a successful parse |
| Chat | Only when **Enable document chat** is on |
| Layout Tree | Always |
| Source Structure | Native results |

The Extract tab switches between whole-document extraction and custom form routing based on **Use custom form routing**.

## 8. Use the Overview tab

Overview is the best first review screen.

### 8.1 Summary metrics

The top metrics show:

- **Pages:** parsed page count;
- **Regions:** known document elements;
- **Tables:** detected table regions;
- **Figures:** detected figures, images, or charts;
- **Time:** total processing time; and
- **Recovered:** elements whose text was repaired by AI enhancement.

These metrics describe the parse; they do not by themselves prove accuracy.

### 8.2 Document type

When classification was enabled and succeeded, Overview shows:

- predicted document type;
- confidence percentage; and
- optional reasoning.

Confirm the label against the source before using it for a business decision.

### 8.3 Table of contents

When TOC generation was enabled, Overview shows numbered sections. Select a linked section to open its highlighted source element in the **Annotated PDF** tab.

### 8.4 Page thumbnails and original page viewer

The page gallery shows thumbnails in groups of up to 12. Select a page button to open the original page below the thumbnails.

Use this view to check:

- missing pages;
- blank pages;
- rotation;
- clipping;
- fax artifacts;
- unexpected attachments; and
- whether the selected page range was correct.

## 9. Use the Markdown tab

The Markdown tab presents the reconstructed document as readable content.

Use it to check:

- whether headings are sensible;
- whether paragraphs follow the correct order;
- whether table content is present;
- whether important values are readable; and
- whether sections are missing.

Enable **Show raw Markdown** to inspect or copy the exact text representation.

### 9.1 Refined Markdown versus grounded Markdown

The displayed/downloaded Markdown may include optional AI presentation improvements. The application also retains `base_markdown`, a canonical version tied to source elements.

Technical users should use the Full JSON when they need both representations and provenance.

### 9.2 What to do when Markdown looks wrong

Use **Annotated PDF** and **Layout Tree** to determine whether:

- the OCR text is wrong;
- the reading order is wrong;
- a region was missed;
- the source scan is unreadable; or
- only the Markdown presentation is confusing.

Extraction should not be trusted for a critical section that is missing or unreadable in the parse.

## 10. Use the Annotated PDF tab

The Annotated PDF is the main evidence-review tool.

### 10.1 Annotation colors

The legend identifies common region groups:

- blue: text and titles;
- green: tables and forms;
- orange: figures;
- violet: formulas;
- red: seals; and
- dashed orange: AI-recovered text.

### 10.2 Page controls

Use **Previous**, **Next**, or the page-number control to navigate.

Enable or disable **Show annotations** to compare the overlaid view with a clean page. The downloaded annotated PDF always includes the canonical annotations.

### 10.3 Selected regions

When you choose **Show source** from extraction, chat, TOC, the page-element list, or Layout Tree, the app opens this tab and highlights the selected element.

The **Page elements** expander lists elements on the current page in reading order. Select one to highlight it.

### 10.4 Reviewer checklist

For a critical value, verify:

1. the highlighted box surrounds the correct source region;
2. the source text supports the value;
3. the value belongs to the correct business role or section;
4. no nearby label changes its meaning; and
5. the page is complete and readable.

A correct number from the wrong box is not a correct business result.

## 11. Use the Layout Tree tab

The Layout Tree displays the document hierarchy by page and reading order.

Each item shows:

- reading-order number;
- element type;
- a text preview; and
- an AI-recovery badge when the text was recovered.

Select an item to open its highlighted annotated page. Use **Clear selection** to remove the current highlight.

Use Layout Tree when:

- Markdown order looks wrong;
- a page has columns or nested sections;
- you need an element ID for technical review;
- a table or form seems incomplete; or
- you want to see which text was recovered.

## 12. Extract business fields from the whole document

Extraction is optional and runs only after parsing. It asks for a defined set of fields and returns values with review information.

### 12.1 When to use extraction

Use extraction when you need repeatable fields such as:

- invoice number and total;
- patient/member identifiers;
- provider identifiers;
- service dates;
- contract dates and parties;
- claim or authorization details;
- policy numbers;
- approval status; or
- report findings.

Use chat instead when the question is exploratory and will not be repeated consistently.

### 12.2 Open the extraction builder

After parsing:

1. Open **Extract**.
2. Leave **Use custom form routing** off for whole-document extraction.
3. Expand **Extraction schemas**.
4. Create, import, or load a schema.
5. Review the field definitions.
6. Select **Run extraction**.

### 12.3 Create a schema manually

Choose **New schema**, enter a schema name, and add rows.

Each row has:

| Column | Meaning |
| --- | --- |
| Field name | Machine-safe unique identifier, for example `patient_name` |
| Description | Exact business meaning of the field |
| Type | `string`, `number`, `integer`, `boolean`, or `date` |

Field names must begin with a letter or underscore and contain only letters, numbers, and underscores.

Good descriptions distinguish similar concepts:

```text
rendering_provider_npi
NPI of the clinician who rendered the requested service, not the facility NPI.
```

Avoid vague definitions:

```text
provider_number
Provider number.
```

Available actions:

- **Save schema:** persist the current definition for reuse;
- **Load example:** load an invoice example into the editor;
- **Clear:** remove the current draft rows; and
- **Export schema JSON:** download the current valid definition.

### 12.4 Import schema JSON

The application JSON format is:

```json
{
  "version": 1,
  "name": "Invoice",
  "fields": [
    {
      "name": "invoice_number",
      "description": "Official invoice identifier",
      "type": "string"
    }
  ]
}
```

Exact steps:

1. Use **Import schema JSON** to choose a `.json` file.
2. Select **Import JSON**.
3. The application validates and saves the imported schema.
4. Load or edit it as required.

JSON import persists the definition immediately.

Use JSON exported by this application or validate the shape before import. In the current UI, malformed or schema-invalid extraction JSON may raise an uncaught validation error instead of showing the controlled inline message used by routing-profile import. If that happens, reload the app, correct the file, and retry; use the editable builder or Markdown import when a business user needs safer correction.

### 12.5 Import schema Markdown

Markdown is useful when business teams own the field dictionary.

Use a UTF-8 `.md` file no larger than 1 MB. Use a table or bullets, not both.

Table example:

```markdown
# Invoice

| Field name | Description | Type |
| --- | --- | --- |
| invoice_number | Official invoice identifier | string |
| total_amount | Final amount payable | number |
| due_date | Payment due date | date |
```

Bullet example:

```markdown
# Invoice

- invoice_number: Official invoice identifier
- total_amount (number): Final amount payable
- due_date (date): Payment due date
```

Exact steps:

1. Use **Import schema Markdown** to choose the `.md` file.
2. The application automatically loads it into the editable draft.
3. Review names, descriptions, and types.
4. Select **Save schema** if it should be reusable.

Markdown upload does not automatically save the schema or run extraction. An H1 becomes the schema name; otherwise, the filename becomes the name. An omitted type defaults to `string`.

### 12.6 Import schema CSV or XLSX

CSV and XLSX imports use these columns in order:

```csv
Field name,Description,Type
invoice_number,Official invoice identifier,string
total_amount,Final amount payable,number
due_date,Payment due date,date
```

Use **Import schema Markdown, CSV, or XLSX** to choose the file. XLSX imports read the first worksheet. The filename becomes the schema name, and an empty type defaults to `string`. The fields load into the editable draft; review them before selecting **Save schema**.

### 12.7 Load a saved schema

Choose a name under **Saved schema**, then select **Load selected schema**. Saving the same name later updates that reusable definition.

### 12.8 Review extraction results

Each field displays:

- field name;
- value;
- confidence; and
- **Show source** when grounded source evidence is available.

Confidence meanings:

| Confidence | Meaning | Required action |
| --- | --- | --- |
| `high` | Strong source support | Review according to business policy |
| `medium` | Evidence exists, but match is less certain | Review the highlighted source |
| `inferred` | Nearby cited context exists, but exact support is unresolved | Manually confirm value and meaning |
| `not_found` | No supported value was found | Leave empty or complete manually |

The app does not fill a missing field merely because the schema requires it. Missing values remain `null`/`not_found`.

### 12.9 Large field sets

The application can accept a large scalar schema, but it does not automatically split schemas. The UI runs one schema at a time and keeps the latest result in the active session.

The Streamlit builder does not define variable-length arrays or repeating table rows. If a document contains an unknown number of procedures, diagnoses, transactions, or line items, use a fixed business representation, a separately approved direct-API schema, or a downstream repeating-record workflow. Do not assume the scalar builder will return every row.

For a very large requirement:

1. create one approved field dictionary;
2. group related fields if business review becomes unmanageable;
3. create stable schemas by group;
4. run and download each result before running the next schema; and
5. merge approved outputs in a controlled downstream process.

The application does not perform the cross-schema merge.

## 13. Classify mixed forms and extract selected categories

Use **custom form routing** when one PDF contains several forms or document types.

Example medical fax packet:

```text
pages 1-2   new authorization
pages 3-5   medical records
pages 6-7   authorization update
pages 8-9   another new authorization
```

If the business needs only new authorizations, the app can classify every contiguous range and extract only the approved `newauth` segments.

### 13.1 Understand the routing terms

- **Category:** business label such as `newauth` or `medical_records`.
- **Segment:** one continuous page range assigned to a category.
- **Eligible:** the profile says this category should be extracted.
- **Approved:** the classification decision has passed automatic or user review.
- **Routing profile:** reusable category definitions and extraction rules.
- **Extraction schema:** fields collected from an eligible segment.

### 13.2 Prepare extraction schemas first

Every extractable routing category must reference an already saved extraction schema.

For example, save a schema called `New Authorization` before creating a `newauth` category that uses it.

### 13.3 Create a routing profile manually

In **Extract**:

1. Enable **Use custom form routing**.
2. Expand **Extraction schemas** and confirm required schemas are saved.
3. Expand **Routing profile**.
4. Choose **New routing profile**.
5. Enter a name and optional instructions.
6. Add category rows.
7. Check **Extract** only for categories that should be extracted.
8. Assign a saved schema to every extractable category.
9. Select **Save routing profile**.

Example:

| Category | Description | Extract | Extraction schema |
| --- | --- | --- | --- |
| `newauth` | Initial request for a new authorization | Yes | `New Authorization` |
| `authupdate` | Update to an existing authorization | No | — |
| `behavioral_health` | Behavioral-health form that is not a new authorization | No | — |
| `medical_records` | Records without a new authorization request | No | — |

The application always adds `other` as a non-extractable fallback. Do not define a category named `other`.

A routing profile supports at most 50 categories. Profile and schema names are limited to 100 characters; routing instructions to 4,000 characters; and each category description to 1,000 characters.

**Load routing example** creates a sample medical-fax profile. **Clear routing profile** resets the draft. **Export routing profile JSON** downloads a valid profile.

To load an existing saved profile, choose it under **Saved routing profile**, then select **Load routing profile**.

### 13.4 Import routing profile JSON

Use **Import routing profile JSON**, then select **Import routing JSON**.

The imported profile is validated and saved. Import fails if an extractable category references a missing saved extraction schema.

Expected JSON shape:

```json
{
  "version": 1,
  "name": "Medical fax routing",
  "instructions": "Treat supported cover sheets as part of the following form.",
  "categories": [
    {
      "key": "newauth",
      "description": "Initial request for a new authorization",
      "extract": true,
      "schema_name": "New Authorization"
    },
    {
      "key": "medical_records",
      "description": "Records without an authorization request",
      "extract": false,
      "schema_name": null
    }
  ]
}
```

Unknown fields are rejected. Keys must be unique machine-safe names, and `other` is reserved. An extractable category requires a schema name; a non-extractable category must use `null`/omit the optional schema in the validated model rather than naming one.

### 13.5 Import routing profile Markdown

Routing Markdown can use a table:

```markdown
# Medical fax routing

> Treat fax cover sheets as part of the following form when supported by the pages.

| Category | Description | Extract | Schema |
| --- | --- | --- | --- |
| newauth | Initial request for a new authorization | yes | New Authorization |
| authupdate | Update to an existing authorization | no | |
| medical_records | Records without an authorization request | no | |
```

Or bullets:

```markdown
# Medical fax routing

> Treat fax cover sheets as part of the following form when supported by the pages.

- newauth [extract=New Authorization]: Initial request for a new authorization
- authupdate: Update to an existing authorization
- medical_records: Records without an authorization request
```

Blockquote lines become optional routing instructions. `[extract=Schema Name]` marks a bullet category as extractable and assigns its schema.

Exact steps:

1. Use **Import routing profile Markdown**.
2. Choose a UTF-8 `.md` file under 1 MB.
3. The application loads an editable draft automatically.
4. Confirm every extractable category has an available saved schema.
5. Select **Save routing profile** if it should be reusable.

### 13.6 Classify forms

Select **Classify forms**. The selected AI model receives grounded Markdown/layout plus category definitions and returns contiguous page segments.

The application validates:

- page coverage;
- range order;
- category keys;
- source element references; and
- boundary behavior across long-document windows.

Invalid structured classification receives one repair attempt. Unresolved invalid routing stops before extraction.

### 13.7 Review classified segments

The **Classified form segments** table contains:

| Column | Editable? | Meaning |
| --- | --- | --- |
| Segment | No | Identifier within the current reviewed result |
| Start page | Yes | First page in effective range |
| End page | Yes | Last page in effective range |
| Category | Yes | Effective business category |
| Confidence | No | Classifier confidence |
| Reasoning | No | Classification explanation |
| Approved | Yes | Reviewer accepts the effective decision |
| Eligible | No | Profile allows extraction for this category |
| Extraction schema | No | Schema assigned by the profile |

Segments at or above `0.85` confidence are normally auto-approved by the application. Lower-confidence segments require review. A segment merged across a long-document window boundary also requires review.

Auto-approved does not mean human-reviewed. The app can enable extraction without recording a person’s confirmation of an unchanged high-confidence segment. If the organization requires human review of every form, the reviewer must inspect every segment and record that attestation in the approved downstream process; the current UI does not create a durable human-attestation record for unchanged auto-approved rows.

To review:

1. compare each segment with Overview/Annotated PDF;
2. correct the start and end page if necessary;
3. correct the category if necessary;
4. check **Approved** only after confirmation;
5. ensure every page is covered exactly once; and
6. select **Apply routing review**.

Every segment—including non-extractable `other` or `medical_records` segments—must be approved before routed extraction. Approval confirms the routing decision; it does not make an ineligible category extractable.

Segment IDs are not durable business identifiers. Applying review sorts segments and can renumber them as `form-001`, `form-002`, and so on. Do not use them to join records across classification runs or substantial review edits.

When every segment is approved and the routing profile is unchanged, select **Download split documents**. The dedicated `.segments.zip` contains a PDF, Markdown file, and canonical parsed-document JSON for every segment, including non-extractable and repeated categories. `manifest.json` records the source identity, full routing metadata, and generated paths. The PDF uses original source pages without annotations; Markdown and JSON retain parsed page numbers, element IDs, and bounding boxes.

### 13.8 Extract eligible forms

**Extract eligible forms** becomes available only when:

- all segments are approved;
- at least one segment is eligible; and
- the routing profile has not changed since classification.

These are application gates, not proof of human review. Apply the organization’s review policy before selecting the button.

The application creates an in-memory subset for each eligible segment and runs its assigned schema. It preserves parsed page numbers, element IDs, and source boxes. If the original upload used a page-range subset, those page numbers are relative to the subset.

Non-eligible categories are never sent to extraction. A failed eligible segment is shown as failed without deleting successful results for other segments.

If the routing profile changes, rerun **Classify forms** before extraction.

### 13.9 Review routed results

Each extracted form displays:

- segment ID;
- category;
- page range;
- status;
- schema name;
- field values and confidence; and
- **Show source** actions.

Treat every form as a separate business result. Confirm that the page range belongs to the correct form before validating its fields.

## 14. Use document chat

Enable **Enable document chat** before or after parsing. Changing the chat toggle does not rerun local OCR parsing.

In the **Chat** tab:

1. enter a question in **Ask about this document**;
2. wait for the answer;
3. review the displayed confidence;
4. use **Show source** for each citation; and
5. confirm consequential answers against the source.

Good questions:

- “Which page contains the policy number?”
- “What date is shown for the requested service?”
- “Does the document mention an urgent request?”
- “Where is the termination clause?”

Chat is limited to the parsed document. It is not a general-purpose research assistant. Long documents use deterministic retrieval of relevant elements and nearby context. Only citations to known element IDs are shown.

The app retains chat history only in the active session and sends at most the recent bounded history required by the feature.

## 15. Download and understand outputs

Download buttons appear below the tabs after parsing.

### 15.1 Download Markdown

File name:

```text
<document-name>.md
```

Use it for human reading, search, document review, or a downstream text workflow.

### 15.2 Download annotated PDF

File name:

```text
<document-name>.annotated.pdf
```

Use it for review, audit support, and source tracing when available. Native nonvisual formats do not produce an annotated PDF; use their **Source Structure** view and source anchors instead.

### 15.3 Download Extract JSON

This button appears after whole-document or routed extraction.

File name:

```text
<document-name>.extract.json
```

For normal extraction, it contains the schema, data, evidence, field records, warnings, usage, and trace information.

For custom routing, it contains classification and per-form extraction results.

### 15.4 Download Full JSON

File name:

```text
<document-name>.full.json
```

Use Full JSON when technical consumers need the complete parse plus current optional results. It can include:

- refined and base Markdown for OCR results, or immutable `base_text` and source spans for native results;
- document structure and source anchors;
- OCR elements and normalized boxes when the selected route has visual evidence;
- quality and recovery information;
- document classification and TOC;
- whole-document extraction;
- custom form classification;
- routed form extraction;
- usage, trace, timing, and status metadata.

Annotated PDF bytes are not embedded in JSON; download the PDF separately.

### 15.5 Footer diagnostics

The footer summarizes:

- GLM-OCR time;
- Luna recovery time;
- Luna agentic time;
- parsed page count;
- recovery crop/region activity; and
- Luna input/output token counts.

These values help technical users investigate performance and provider usage. They are not an accuracy score.

## 16. Business operating model

Reliable use requires more than clicking **Run extraction**.

### 16.1 Recommended roles

| Role | Responsibility |
| --- | --- |
| Business definition owner | Approves field names, descriptions, categories, and rules |
| Operator | Uploads, parses, applies approved definitions, and downloads outputs |
| Reviewer | Resolves routing uncertainty and validates critical fields |
| Technical administrator | Maintains environment, credentials, storage, access, and logs |
| Risk/compliance owner | Approves data use, provider, retention, and review policy |

One person may perform several roles in a small team, but the responsibilities should remain clear.

### 16.2 Recommended standard operating procedure

1. Approve the field dictionary and routing categories before production use.
2. Confirm the environment and provider destination.
3. Upload the documents and verify each document's page completeness.
4. Parse with the approved feature settings.
5. Review source coverage before extraction.
6. For mixed packets, review every routing segment.
7. Run only the approved extraction schema.
8. Review every uncertain or critical result.
9. Download outputs to an approved location.
10. Record exceptions in the organization’s downstream review process.

### 16.3 Risk-based field review

Always review:

- identity numbers;
- dates that affect eligibility or deadlines;
- totals and financial values;
- clinical or authorization decisions;
- signatures and approval status;
- every `medium`, `inferred`, or `not_found` field; and
- any field used for an automated consequential action.

Sample high-confidence fields according to the organization’s quality policy.

### 16.4 What a successful result means

A successful run does not mean every requested value is populated. It means:

- the source was reconstructed well enough to review;
- important values can be traced to source evidence;
- missing or uncertain values are visible;
- routing decisions are approved;
- the correct schema was used; and
- the result is ready for the organization’s normal validation process.

## 17. Technical behavior in simple terms

### 17.1 Source ownership

For grounded scanned-PDF and image routes, the selected local engine and deterministic code own:

- element IDs;
- normalized bounding boxes;
- page structure;
- element types;
- reading order; and
- initial OCR confidence.

AI models can reason about existing elements, but do not own their geometry. For native results, immutable `base_text` and `SourceAnchor` values own the evidence: PDF page/bounding-box positions, document paragraphs/shapes, sheet cells, table cells, or CSV rows/columns.

### 17.2 Grounding

Grounding connects a value or answer to existing source evidence. OCR evidence uses an element ID, page, text, type, reading order, and optional box. Native evidence uses an exact Unicode-codepoint interval in immutable `base_text`, mapped through source spans to one or more anchors.

When **Show source** works, the app follows an OCR element ID back to an annotated page or shows the native source anchor and character interval.

### 17.3 Structured output and validation

Optional features request typed structured output. Invalid schema-shaped output receives one repair attempt where supported.

Extraction then checks that evidence refers to known elements. If exact support cannot be resolved, a field becomes `inferred` or `not_found` rather than receiving a newly invented box.

### 17.4 Long documents

The parser processes ordered windows of pages and restores source order before building final output. Agentic features use bounded contexts rather than one unlimited request.

Whole-document scalar extraction can merge results from multiple contexts. Custom form routing overlaps a boundary page between classifier contexts and requires review when a boundary merge creates uncertainty.

### 17.5 Result versions

Current output versions are:

| Result | Version |
| --- | --- |
| Parse JSON | `4.5.0` |
| Full JSON | `4.6.0` |
| Whole-document extraction JSON | `1.1.0` |
| Routed extraction JSON | `2.0.0` |
| Native document JSON | `5.0.0` |
| Combined native/extraction JSON | `5.1.0` |

Consumers should use the version field instead of assuming every JSON file has the same shape.

## 18. Persistence, privacy, and security

### 18.1 What is saved by the app

Reusable extraction schemas, routing profiles, and active-batch metadata are intentionally stored in SQLite at:

```text
data/document_studio.sqlite3
```

An administrator can override this location with `DOCPARSE_STUDIO_DB_PATH`.

The database's sibling `workspaces` directory stores the active batch's source bytes, selected-page source, annotated PDF, and parse checkpoint. The app restores its settings, progress, failures, analysis, and usage after restart. A document interrupted during OCR retries OCR; a document with a completed parse checkpoint reuses that result and retries only unfinished analysis. **Clear saved workspace** removes the active batch after confirmation.

Starting the managed Windows launcher deliberately replaces any verified native or legacy WSL Streamlit app process and clears Streamlit's transient cache. This starts a fresh UI session but does not delete the SQLite workspace, stored source/result artifacts, models, or warm WSL OCR services.

### 18.2 What is session-only

The current Streamlit app keeps these in process/session state only:

- current whole-document extraction;
- custom classification and routing review;
- routed extraction;
- chat history; and
- current selected source region.

These can disappear when the session or process ends. Parse results remain in the active local workspace until it is replaced or explicitly cleared. Download required outputs promptly.

Uploaded bytes and generated results may remain in the browser session and active Streamlit process while the workflow is open. The parser also uses temporary storage during processing and removes its normal temporary directory after successful completion. Abnormal termination and storage recovery are outside that cleanup guarantee.

Do not treat closing a browser tab, refreshing, or restarting the app as deletion. Use **Clear saved workspace**, then apply the administrator's approved browser, host-storage, backup, and retention procedures for sensitive documents.

The app also uses process-wide Streamlit data caches for page counts, selected-page PDFs, single-page views, thumbnails, and annotation variants. Cached document derivatives can outlive one browser session while the Streamlit process remains running. The managed Windows launcher stops the verified prior process and clears this cache on every launch. This is not durable-data deletion: the administrator must still use **Clear saved workspace** and handle browser, host-storage, and backup remnants under the approved procedure.

### 18.3 Other residual data

Operators remain responsible for:

- downloaded documents;
- browser state;
- source files;
- runtime logs;
- backups;
- model caches; and
- SQLite database sidecar files.

Normal parsing removes temporary parser storage, but abnormal termination and storage recovery are outside that cleanup guarantee.

### 18.4 Local-workstation boundary

The current application is intended for a trusted local workstation. The managed launch scripts bind Streamlit and vLLM to loopback. Do not expose ports `7137` or `8080` to an untrusted network.

The application has no multi-user login or tenant isolation. It must not be published unchanged as a shared PHI or confidential-document service.

Read the [security policy](../SECURITY.md) before processing sensitive information.

## 19. Technical integration and extension

### 19.1 Python API

Developers can use the Python package directly through:

- `DocumentParser` for parsing;
- `DocumentAgent` for analysis, routing, extraction, and chat;
- `DocumentExtractor` for direct schema proposal/extraction;
- `ParserConfig` for configuration; and
- `render_combined_result` for Full JSON.

The Python API is synchronous and does not provide a page-range argument. WSL is required only when the selected engine is GLM-OCR or PaddleOCR-VL vLLM; native and Ollama engines run on Windows.

Read the [Python API guide](api.md) and [zero-to-hero technical tutorial](zero-to-hero-tutorial.md) for examples.

### 19.2 Current integration limits

The installed package includes a synchronous local batch command:

```powershell
grounded-docparse ingest input.pdf --processing-type input.pdf=native-pdf --schema invoice.json --output results
grounded-docparse ingest report.docx --processing-type report.docx=word --schema invoice.md --output results --overwrite
```

`ingest` accepts files and non-recursive directories, requires one processing type per discovered file, applies one optional schema to every document, isolates per-document failures, and writes a root manifest plus per-document Markdown, Full JSON, and optional extraction JSON. It writes an annotated PDF only for routes that produce one. Mixed PDFs additionally require a confirmed route for every page. `grounded-docparse parse` remains the legacy PDF/image OCR command. Exit code `1` means at least one document failed; exit code `2` means arguments or preflight validation failed. Existing non-empty output directories require `--overwrite`, which replaces matching generated paths without deleting unrelated files.

The repository still has no application HTTP API, worker process, or production job queue. The CLI is synchronous workstation automation, not a durable unattended service.

Do not create production batch processing by driving 100 files through one Streamlit session. A production design needs durable jobs, idempotency, per-document failure handling, secure storage, review state, and access control.

### 19.3 Azure bulk processing

For bulk medical faxes, the recommended design separates:

- authenticated upload/review UI;
- malware-scanned Blob intake;
- Service Bus queues;
- PostgreSQL job and audit state;
- GPU workers running local GLM-OCR;
- approved optional AI provider; and
- immutable outputs and authorized downloads.

The required changes and acceptance gates are documented in [Deploy Grounded DocParse on Azure for bulk medical faxes](azure-bulk-fax-deployment.md).

## 20. Common workflows

### 20.1 Simple invoice extraction

1. Upload the invoice.
2. Choose Fast or Full.
3. Parse and review Markdown/Annotated PDF.
4. Open Extract with custom routing off.
5. Load the invoice example or approved invoice schema.
6. Select **Run extraction**.
7. Review invoice number, date, vendor, and total against source.
8. Download Extract JSON, Full JSON, and annotated PDF.

### 20.2 Extract only new authorizations from a medical fax

1. Upload the mixed fax PDF.
2. Parse the whole packet.
3. Confirm all pages are present.
4. Save the `New Authorization` extraction schema.
5. Enable custom form routing.
6. Under **Saved routing profile**, select the medical routing profile and choose **Load routing profile**.
7. Select **Classify forms**.
8. Review/correct every segment and approve all decisions.
9. Select **Apply routing review** to commit the edits.
10. Select **Extract eligible forms**.
11. Review each `newauth` form and its source evidence.
12. Download the routed Extract JSON, Full JSON, and annotated PDF.

A starter `New Authorization` schema can include `patient_name`, `member_id`, `date_of_birth`, `requested_service`, and `requesting_provider_npi`. The business definition owner should approve the exact fields and descriptions before real use.

### 20.3 Process a sensitive document with no remote AI

1. Confirm the document is approved for the local workstation.
2. Select Custom mode.
3. Disable every AI feature.
4. Parse with local GLM-OCR.
5. Review Markdown, Annotated PDF, and Layout Tree.
6. Download Markdown, annotated PDF, and Full JSON. Extract JSON will not appear because extraction was not run.
7. Do not use extraction, routing, or chat.

### 20.4 Review a long report

1. Upload the report.
2. Use Full mode if remote features are approved.
3. Generate a TOC.
4. Review thumbnails and source coverage.
5. Navigate through TOC links and Layout Tree.
6. Use a schema for repeatable facts or chat for exploratory questions.
7. Download Full JSON when technical provenance is required.

### 20.5 Handle a poor scan

1. Prefer a clearer source if available.
2. Keep visual recovery on if remote crop inspection is approved.
3. Review the Recovered metric and AI-recovery badges.
4. Compare difficult text with the annotated source.
5. Treat unreadable or missing source content as a manual exception.

## 21. Troubleshooting

| Problem | What it usually means | What to do |
| --- | --- | --- |
| Browser is blank | Streamlit did not start or is unhealthy | Open the exact local URL and inspect `.runtime/streamlit.log` |
| Parse fails before layout | Local GLM service/model is unavailable | Check `.runtime/vllm.log`, WSL GPU access, and service health |
| AI controls are disabled | The selected model's API key is unavailable | Configure it in approved User scope and relaunch |
| AI destination is unexpected | A custom provider base URL is active | Stop and verify/remove the value |
| Extraction says a key is required | Extraction needs the selected AI provider | Configure its approved key or remain local-only |
| File is rejected | Invalid, unsupported, encrypted, oversized, or over configured limits | Use a valid supported source or reduce/split it outside the app |
| Markdown has missing content | OCR missed or could not read a source region | Check annotated source and use a clearer scan |
| Reading order is wrong | Complex layout or hierarchy problem | Inspect reading-order labels and Layout Tree |
| Schema file is invalid | Wrong headers, invalid type/name, encoding, workbook, or size | Use a supported `.md`, `.csv`, or `.xlsx` file under 1 MB |
| Routing profile is incomplete | Extractable category lacks a saved schema | Save the named extraction schema first |
| Classify forms fails validation | Invalid page coverage/category/evidence remains after repair | Review profile and retry; escalate persistent failures |
| Extract eligible forms is disabled | Unapproved segment, no eligible segment, or changed profile | Apply review to all segments or rerun classification |
| Field is `inferred` | Exact value-to-source support was unresolved | Manually confirm the value and highlighted context |
| Field is `not_found` | No supportable value exists | Leave empty or complete through approved manual process |
| Saved definitions disappeared | App is using another database path | Check `DOCPARSE_STUDIO_DB_PATH` and file permissions |
| Provider request fails | Rate limit, endpoint, network, schema, or provider issue | Review safe diagnostics and retry according to policy |

## 22. Frequently asked questions

### Does Fast mode mean no external API calls?

No. Fast enables document classification when a provider is configured. Use Custom mode and disable all AI options for a local-only run.

### Is extraction automatic after parsing?

No. Open Extract, define or load a schema, and explicitly run extraction.

### Can I upload a field list?

Yes. Use **Import schema Markdown, CSV, or XLSX**. The file populates an editable draft; review and save it before reuse.

### Can I upload a Markdown routing definition?

Yes. Use **Import routing profile Markdown**. Referenced extraction schemas must already be saved.

### Can one PDF contain several forms?

Yes. Custom form routing can segment contiguous page ranges and extract only eligible categories.

### Can I extract only `newauth` and ignore medical records?

Yes. Mark only `newauth` as extractable and assign its schema. Keep `medical_records` non-extractable.

### Does approval make every category extractable?

No. Approval confirms the routing decision. Eligibility comes only from the saved profile.

### Can AI enhancement change a bounding box?

No. GLM/deterministic code owns element identity, location, type, and order.

### Can the app recover a region local OCR never found?

Not in the default workflow. Visual recovery repairs text only on an existing region.

### Does a high-confidence field require review?

Follow the organization’s policy. Critical and regulated fields should still be reviewed or sampled appropriately.

### Can the UI process 100 PDFs at once?

No. The current UI processes at most 20 files sequentially in one durable local workspace. A 100-file production workflow requires the architecture described in the Azure runbook.

### Are schemas and results both saved?

Schemas and routing profiles are saved in SQLite. The active batch's sources, parse results, progress, analysis, failures, and usage are also saved locally. Extraction, routing review, and chat results remain session-only unless downloaded.

## 23. Glossary

| Term | Plain-language meaning |
| --- | --- |
| ADE mode | UI preset for optional AI features |
| Annotated PDF | Source document with detected-region overlays |
| Bounding box | Normalized location of a page region |
| Category | Business label used for form routing |
| Classification | Predicted document or form type |
| Element | Known document region with ID, text, page, type, and optional box |
| Eligible | Routing profile allows this category to be extracted |
| Extraction | Collecting requested fields from parsed content |
| GLM-OCR | Local layout and text-recognition system |
| Grounding | Linking a result to known source evidence |
| AI model | Selectable GPT 5.6 Luna, Gemini, or Agnes model used for enhancement and document reasoning |
| Markdown | Readable text format produced by the parser |
| Routing profile | Reusable form categories and extraction rules |
| Schema | Field names, descriptions, and types to extract |
| Segment | Continuous page range assigned to one category |
| Source element ID | Stable reference used for highlighting evidence |
| TOC | Table of contents linked to document sections |
| Visual recovery | Optional text repair on selected existing regions |

## 24. Final checklist

Before ending a document session, confirm:

- [ ] The correct file and page range were processed.
- [ ] The selected AI provider, destination, and feature settings were approved.
- [ ] All expected pages and important regions are present.
- [ ] Markdown and reading order are usable.
- [ ] Every routed segment is reviewed and approved.
- [ ] Only intended categories are eligible for extraction.
- [ ] Critical, medium, inferred, and not-found fields were reviewed.
- [ ] Source highlights support the accepted values.
- [ ] Required Markdown, PDF, Extract JSON, and Full JSON files were downloaded.
- [ ] Outputs were moved to the approved storage location.
- [ ] Any exception was recorded in the downstream business process.

## Further reading

- [Project overview](../README.md)
- [Setup and configuration](../SETUP.md)
- [Short tutorial](tutorial.md)
- [Zero-to-hero technical tutorial](zero-to-hero-tutorial.md)
- [Business extraction workflow](business-user-extraction-workflow.md)
- [Architecture](architecture.md)
- [Python API](api.md)
- [Security policy](../SECURITY.md)
- [Azure bulk medical fax deployment](azure-bulk-fax-deployment.md)
