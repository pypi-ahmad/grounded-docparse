# Layout-Aware Workflow for Extracting Large Field Sets

## Purpose

This guide explains how business and technical users can extract a large, predefined set of fields from scanned, faxed, multi-page, or structurally complex documents with Document Parse Studio.

A healthcare workflow might request Patient NPI, Rendering Provider NPI, service dates, diagnosis codes, claim totals, and policy numbers. The same approach applies to invoices, contracts, bank statements, applications, onboarding packets, certificates, compliance forms, reports, and other document families.

The central principle is:

> Parse the source document once, then perform extraction against the resulting Markdown and layout structure—not directly against the PDF or image.

## Current Capability and Proposed Extension

| Capability | Status |
| --- | --- |
| Upload PDF, PNG, JPEG, or TIFF source documents | Implemented |
| Convert the source into grounded Markdown and structured layout elements | Implemented |
| Define scalar fields in the Extract tab | Implemented |
| Import and export reusable schema JSON | Implemented |
| Extract structured values from parsed Markdown and layout context | Implemented |
| Return page, element ID, source text, confidence, and normalized bounding box | Implemented when evidence can be grounded |
| Upload a Markdown file containing field descriptions | Proposed optional feature; not currently available in the UI |
| Automatically split, run, and merge multiple schemas for 100+ fields | Proposed extension; not currently implemented |

Yes, a Markdown field-specification upload can be integrated cleanly as an optional feature. It should create or propose an extraction schema after parsing; it should not become a new document parser or bypass the existing grounding rules.

## The Two Inputs Must Remain Separate

The workflow has two conceptually different inputs:

1. **Source document:** The PDF or image containing the facts to extract.
2. **Field specification:** The names, descriptions, types, and business rules describing what the user wants returned.

The source document is evidence. The field specification is an instruction set. A field-specification Markdown file must never be treated as evidence for an extracted value.

### Plain-language terms

- **GLM-OCR:** The local system that detects page regions and reads the source document.
- **Luna:** The optional model used for selected visual repair and document-level tasks such as extraction.
- **Layout tree:** An ordered list of parsed document regions with their page, type, text, and identifier.
- **Schema:** The approved list of output fields, descriptions, and data types.
- **Scalar field:** One value such as a name, date, amount, identifier, or yes/no answer.
- **Bounding box:** The rectangular source location of a parsed region, stored as normalized page coordinates.
- **Deterministic validation:** Fixed application rules that check schema shape, known identifiers, and source associations without asking the model to decide whether those rules passed.

```text
PDF or image
  -> GLM-OCR parse
  -> grounded Markdown + layout tree + element IDs + bounding boxes

Field definitions
  -> approved extraction schema

Parsed document + approved schema
  -> Luna extraction
  -> deterministic evidence validation
  -> structured JSON with grounding metadata
```

## Workflow for a Business User

### 1. Define the business outcome

Begin with the decision or process the extracted data will support. A list of 100 fields without clear meaning usually produces avoidable ambiguity.

For each field, define:

- a unique name;
- a plain-language description;
- the expected type, such as text, number, whole number, yes/no, or date;
- whether the field is mandatory, optional, or conditionally applicable;
- how it differs from similar fields;
- whether multiple occurrences are expected; and
- the review priority if the value is uncertain.

“Mandatory” is a business-review designation: a missing value must be resolved before the business process completes. In the extraction JSON, every schema key is present but may contain `null`; JSON-required therefore means “include the key,” not “invent a value.”

For example, Patient NPI, Billing Provider NPI, Facility NPI, and Rendering Provider NPI must be separate fields with role-specific descriptions. A numerically valid NPI taken from the wrong role is still a business error. The current UI is scalar-only, so a fixed set of repeated values should use explicitly numbered fields such as `diagnosis_code_1`, `diagnosis_code_2`, and `diagnosis_code_3`. Variable-length rows require a separate nested-schema or downstream workflow.

### 2. Organize large field sets

Group fields by stable business meaning, for example:

- document and submission details;
- patient, member, customer, or account details;
- provider, vendor, employer, or organization details;
- policy, contract, or coverage details;
- service dates and event periods;
- codes, classifications, and statuses;
- financial totals and adjustments; and
- declarations, signatures, and approvals.

The current app runs one extraction schema at a time and retains only the latest extraction result in the active session. For a very large field set, use several approved schemas when endpoint limits, review effort, or repeating data make one schema impractical. There is no universal field-count threshold because it depends on descriptions, document length, and the configured endpoint. Prefer stable business groups with unique field names, validate them on representative documents, download each result before running the next schema, and merge approved outputs in the downstream business process.

### 3. Upload and parse the source document

Upload one supported PDF or image. For PDFs, select an inclusive page range when only part of the document is relevant.

Choose the required parse options and select **Parse document**. GLM-OCR reads the complete page layout and produces:

- ordered document Markdown;
- page and element structure;
- stable element IDs;
- normalized bounding boxes;
- OCR confidence and review state; and
- an annotated PDF for visual inspection.

Optional Luna visual recovery can inspect a limited number of weak existing GLM regions. It can repair eligible text but cannot create a missing region or alter canonical IDs, geometry, type, confidence, or reading order.

### 4. Review the parse before extraction

Use the Markdown, Annotated PDF, Overview, and Layout Tree views to confirm that important content was captured correctly.

Check especially for:

- missing pages or sections;
- wrong reading order;
- damaged tables;
- faint or clipped identifiers;
- fax noise interpreted as characters;
- similar labels assigned to the wrong value; and
- regions marked for review.

Extraction cannot reliably recover facts that are absent from the parsed evidence. If important content is missing or unreadable, stop extraction, obtain a clearer source or adjust the selected page range, and parse again. If reparsing still cannot recover it, route the field for manual completion rather than asking extraction to infer the source fact.

### 5. Select or prepare the field schema

Today, users can build scalar fields in the Extract tab or import an existing schema JSON file. The available UI field types are string, number, integer, boolean, and date. “Approved schema” means the business owner has reviewed these names, descriptions, and types; the current UI does not implement a separate approval gate.

With the proposed optional feature, a user could instead upload a Markdown field specification. The app would convert it into a draft schema, show the draft for review, and require approval before extraction begins.

### 6. Run extraction

Select **Run extraction**. The extraction stage reasons over the parsed document representation:

- refined Markdown supplies readable document content;
- the compact layout tree supplies element IDs, page numbers, types, reading order, and text; and
- the approved schema defines the required output fields and types.

The extraction stage does not reread the source PDF or image. This keeps extraction separate from OCR and ensures every accepted source reference points back to the existing parse result.

### 7. Review the results

Interpret each field according to its confidence and evidence:

- **High:** The serialized value appears directly in the cited source text.
- **Medium:** A valid source citation exists, but normalized formatting means the serialized value is not a direct text substring.
- **Inferred:** The value was proposed from context and linked to a candidate nearby region. That region is a review pointer, not verified supporting evidence; manual confirmation is required.
- **Not found:** The parsed evidence does not support the field, so the value remains null.

Use **Show source** when a result has a citation. A not-found field has no source to open. Review every inferred, medium-confidence, or not-found field, plus all high-impact identifiers, dates, totals, and compliance fields. These are recommended business controls; the application does not enforce completion of the review.

Extraction confidence describes the value-to-evidence relationship. It is distinct from GLM-OCR confidence, which describes the original recognition result for a page region.

### 8. Export and use the result

Download the extraction JSON for downstream processing and the annotated PDF for evidence review. Full JSON also contains the parse structure and current extraction result.

The output should enter a business system only after the organization applies its normal validation, approval, privacy, and retention controls.

## Workflow for a Technical User

### Stage 1: Source ingestion and visual parsing

The source PDF or image is validated and rasterized. PP-DocLayout supplies detected geometry and GLM-OCR supplies recognized region content within the local parse stage. Deterministic pipeline code normalizes the result, assigns block IDs, and may correct dense-form reading order. In this guide, “GLM-owned” means owned by this complete local parse stage rather than by Luna.

The result is a `ParseResult` containing both presentation Markdown and grounded base Markdown, structured document pages and blocks, public elements, metadata, and annotated PDF bytes. Block IDs are canonical within that parse result. They are not durable business identifiers and are not guaranteed to remain unchanged after reparsing, selecting a different page range, or upgrading the parser.

### Stage 2: Optional bounded visual recovery

Deterministic quality signals identify weak existing GLM regions. If enabled and credentialed, Luna receives only selected crops. Accepted recovery can replace text on an existing element, while geometry and identity remain GLM-owned.

### Stage 3: Extraction context preparation

Extraction filters out rejected or non-rendered blocks and constructs two model inputs:

- `document_markdown`: the refined Markdown; and
- `layout_tree`: compact records containing block ID, type, page, reading order, text, and atomic text IDs.

The raw PDF or page image is not part of this extraction request.

### Stage 4: Schema-constrained extraction

Luna returns data that conforms to the approved schema plus evidence references to known block or atom IDs. Structured output controls the JSON shape, while deterministic validation checks the field values and evidence relationships.

For long documents, the current agent can split the **document context** for one scalar schema and merge the strongest grounded result for each field. This does not split a 100-field schema into smaller field groups. Nested object or array schemas use the direct extraction path and do not receive this scalar context merge.

### Stage 5: Evidence validation and repair

Deterministic code verifies that:

- the returned data conforms to the schema;
- cited block and atom IDs exist;
- evidence pointers target real output values;
- cited source text supports the extracted value; and
- cited page and bounding-box metadata come from the same canonical block or atom source; and
- every non-null leaf has validated evidence, unless it is explicitly downgraded to inferred review status.

If validation fails, the extraction layer performs one evidence-repair request. Unresolved values become null unless the on-demand agent path supplies an explicitly inferred candidate region. Inferred association is retained for human investigation but does not satisfy the verified-evidence rule.

### Stage 6: Grounding and serialization

The application resolves each accepted field back to the original parse structure. The extraction JSON uses schema version `1.1.0` and can include:

- extracted value;
- page number;
- normalized bounding box `[x0, y0, x1, y1]`;
- confidence;
- canonical element ID;
- source text;
- evidence records;
- warnings; and
- usage and trace metadata.

Bounding boxes are normalized coordinates between 0 and 1 and must be ordered so `x0 ≤ x1` and `y0 ≤ y1`. The canonical parse models validate these invariants. Extraction then copies the page and box from the resolved block or atom citation into both evidence and the flattened field view; it does not accept provider-supplied geometry. Evidence records use `block_id` or `atom_id` and object-form coordinates. The flattened `fields` view exposes the parent block as `element_id` and the same box as a four-number array for UI and consumer convenience.

## Representative Extraction Output

The following is a representative shape for one schema result:

```json
{
  "schema_version": "1.1.0",
  "schema": {
    "type": "object",
    "properties": {
      "patient_npi": {"type": ["string", "null"]},
      "claim_total": {"type": ["number", "null"]},
      "policy_number": {"type": ["string", "null"]}
    },
    "required": ["patient_npi", "claim_total", "policy_number"],
    "additionalProperties": false
  },
  "data": {
    "patient_npi": "1234567890",
    "claim_total": 15480.5,
    "policy_number": null
  },
  "evidence": {
    "/patient_npi": [
      {
        "block_id": "p1-b12",
        "atom_id": null,
        "page": 1,
        "span": null,
        "bbox": {
          "x0": 0.23,
          "y0": 0.18,
          "x1": 0.51,
          "y1": 0.22
        }
      }
    ],
    "/claim_total": [
      {
        "block_id": "p4-b31",
        "atom_id": null,
        "page": 4,
        "span": null,
        "bbox": {
          "x0": 0.67,
          "y0": 0.74,
          "x1": 0.91,
          "y1": 0.79
        }
      }
    ]
  },
  "fields": {
    "patient_npi": {
      "value": "1234567890",
      "page": 1,
      "bbox": [0.23, 0.18, 0.51, 0.22],
      "confidence": "high",
      "element_id": "p1-b12",
      "source_text": "Patient NPI: 1234567890"
    },
    "claim_total": {
      "value": 15480.5,
      "page": 4,
      "bbox": [0.67, 0.74, 0.91, 0.79],
      "confidence": "medium",
      "element_id": "p4-b31",
      "source_text": "Claim Total: $15,480.50"
    },
    "policy_number": {
      "value": null,
      "page": null,
      "bbox": null,
      "confidence": "not_found",
      "element_id": null,
      "source_text": null
    }
  },
  "warnings": [],
  "metadata": {
    "usage": {},
    "trace": []
  }
}
```

Token counts and trace details in the example are abbreviated. A live export records the actual provider calls and trace events.

## Optional Markdown Field-Specification Feature

### Recommended user experience

After a document has been parsed, the Extract tab could offer **Import field specification (.md)** alongside the existing schema JSON import.

The flow should be:

1. Upload a UTF-8 Markdown file containing field definitions and business rules.
2. Validate file type, size, encoding, and content length.
3. Convert the instructions into one or more draft scalar schemas.
4. Show field names, descriptions, types, grouping, and validation errors.
5. Require the user to approve or edit the draft.
6. Save the approved schema only when requested.
7. Run the existing extraction workflow against the current `ParseResult`.
8. Return the normal grounded extraction JSON.

The Markdown file should never replace the parsed document Markdown. It is schema-authoring input only.

### Suggested field-specification content

A useful field specification would state, for every field:

- field name;
- business description;
- scalar type;
- role or section qualifiers;
- formatting expectations;
- null/not-found behavior;
- repeating-value policy; and
- validation or reconciliation notes.

For example:

```markdown
# Claims Header Fields

## patient_npi

- Type: string
- Description: Ten-digit NPI for the patient when explicitly labeled as Patient NPI.
- Do not use: Billing, facility, referring, or rendering provider NPI.
- If absent: Return null.

## service_from_date

- Type: date
- Description: Earliest explicitly stated service start date.
- Output: ISO 8601 date.
- If ambiguous: Return null and flag for review.
```

This is a field-definition document, not a prompt that may override system behavior. The system should compile it into the same controlled schema representation already used by extraction.

### Recommended first version

The smallest reliable implementation should:

- accept one Markdown field-specification file after parsing;
- support only the existing scalar UI types;
- generate a reviewable draft schema;
- require explicit user approval;
- run one approved schema at a time; and
- emit the existing extraction JSON `1.1.0` contract.

Automatic schema grouping and merged multi-schema exports can be added later if real documents demonstrate a need. Keeping the first version scalar and approval-driven minimizes ambiguity and reuses the existing extraction and grounding pipeline.

### Extension for 100+ fields

For very large specifications, a later optional orchestration layer could:

1. divide fields into deterministic business groups;
2. run each approved group against the same parsed Markdown and layout tree;
3. preserve a unique field name across groups;
4. merge results without changing individual evidence records;
5. report per-group success, failure, token usage, and warnings; and
6. allow failed groups to be retried without reparsing the document.

This layer should orchestrate extraction only. It must not rerun GLM-OCR, modify canonical elements, or synthesize bounding boxes. A merged export should label incomplete groups and must not present partial data as a complete result. Group identity should be derived from the parse-result identity, approved schema content, and group name so retries do not duplicate fields or usage records. Conflicting field names should fail before provider calls. These concerns are intentionally deferred from the recommended single-schema first version.

## Safety and Governance Requirements

Both the source document and field-specification Markdown are untrusted inputs. An optional Markdown-upload feature should enforce these boundaries:

- Treat field-specification text as data, not system instructions.
- Do not allow it to disable grounding, validation, null handling, or safety rules.
- Never accept a bounding box, page number, or element ID from the field specification.
- Use only IDs and geometry already present in the current parse result.
- Require schema preview and approval before a provider request.
- Limit file size, field count per run, description length, and output budget.
- Preserve the approved schema in the extraction result, as the current `1.1.0` output does; a future grouped export may also record an explicit schema hash.
- Avoid placing real patient, customer, financial, or regulated values in reusable field descriptions.
- Keep consequential outputs subject to human review.

Visible source-document text can also contain instructions intended to manipulate a model. Treat it only as document content. Structured output and citation validation limit the result shape but cannot prove semantic truth, so source review remains necessary.

For the proposed Markdown uploader, parse the file as UTF-8 field-definition text. Do not fetch remote links or embedded resources, and do not render raw HTML from the uploaded specification. Display a sanitized preview before schema approval.

When Luna features are used, selected recovery crops or recognized Markdown/layout context leave the workstation for the configured OpenAI-compatible endpoint. Operators must use an approved endpoint and verify its retention, residency, and access policies. Application requests set `store=False`, but that setting does not control intermediary proxies or a custom endpoint. Provider timeout or credential failure should leave the completed GLM parse intact and mark the optional extraction attempt as failed rather than fabricating a result.

## General Applicability

The pipeline is not specific to healthcare. The same pattern applies whenever a user needs repeatable, structured values with a path back to the source document:

- invoices and purchase orders;
- contracts and legal notices;
- bank and financial statements;
- insurance forms and correspondence;
- applications and onboarding packets;
- certificates and licenses;
- logistics and shipping documents;
- compliance questionnaires;
- technical reports; and
- public-sector or administrative forms.

The core sequence remains: parse once, review the grounded document, extract against an approved schema, validate evidence, and export structured results. Field definitions, repeating-data design, validation rules, privacy controls, and required human review still vary by domain.

## Recommended Decision

Add Markdown field-specification upload as an optional post-parse schema-authoring feature, not as another source-document format. The uploaded Markdown should be converted into an approved schema, after which the existing extraction pipeline should operate on the parsed document Markdown and layout tree.

This design preserves the current architecture:

- The local GLM-OCR/PP-DocLayout parse remains the source of document structure and geometry.
- Luna interprets the approved field requirements and extracts from structured text context.
- Deterministic code validates evidence and supplies bounding boxes.
- The source PDF or image is never reread during schema extraction.

The result is a reusable workflow for both business and technical users without weakening grounding or coupling extraction to raw document images.
