# Business User Workflow for Extracting Large Field Sets

## Purpose

Document Parse Studio turns scanned PDFs, faxed documents, images, and complex forms into structured information that business teams can review and export. A healthcare claims team might use it to capture Patient NPI, Rendering Provider NPI, service dates, diagnosis codes, claim totals, and policy numbers. The same workflow applies to invoices, contracts, bank statements, onboarding packets, certificates, reports, applications, compliance forms, and many other document types.

The process has two goals:

1. Make the document readable and navigable while preserving its original page locations.
2. Extract the requested business fields and show where each value came from.

The app processes one uploaded document and one extraction schema at a time. A business requirement may contain more than 100 fields, but the app does not automatically split or merge oversized schemas. Teams should validate the complete schema against their configured endpoint and divide it into stable business groups when provider limits or reviewability require multiple extraction runs.

## The Workflow at a Glance

| Phase | What the user does | What the user receives |
|---|---|---|
| Prepare | Define the fields and their business meaning | An approved field dictionary |
| Upload | Select a PDF or image and relevant options | A document ready for parsing |
| Parse | Select **Parse document** | Searchable Markdown, page structure, and an annotated PDF |
| Review | Check document coverage and difficult regions | Confidence that the source was read correctly |
| Configure | Build, import, or select the extraction schema | A reusable extraction template |
| Extract | Select a schema and run extraction | Values linked to source pages and regions |
| Validate | Review missing, inferred, and important values | An approved business result |
| Export | Download the required outputs | Markdown, annotated PDF, extraction JSON, or full JSON |

## 1. Define the Business Fields First

For a small request, a short field list may be enough. For 100 or more fields, begin with a field dictionary agreed upon by the business team. Do this before processing documents so that similar-looking values are not confused.

Organize fields into logical groups. For example:

- Document and submission details
- Customer, member, patient, or account details
- Organization and provider details
- Policy, contract, or coverage details
- Dates and service periods
- Financial totals and adjustments
- Codes, classifications, and statuses
- Approvals, signatures, and declarations

Each field should have:

- A short, unique name
- A precise business description
- The expected value type, such as text, number, whole number, yes/no, or date
- A clear distinction from similar fields

For example, “Patient NPI” and “Rendering Provider NPI” should be separate fields with descriptions explaining whose identifier is required. Avoid vague names such as “provider number” when several provider numbers may appear.

For repeating information, decide in advance how the business wants it represented. If a fixed number of positions is required, define separate fields such as primary, secondary, and tertiary codes. The current in-app builder is designed for individually named values, not an unlimited collection of repeating rows. When the number of line items, transactions, or codes varies widely, use an agreed summary or a separate downstream process designed for repeating records.

## 2. Upload the Document

Use **Upload document** to select one supported PDF or image. Multi-page PDFs and multi-frame image files are handled as one document.

Before parsing:

- Confirm that the file is the intended document.
- Use the optional page range when only part of a large PDF is relevant.
- Check that pages are not missing, upside down, or visibly cut off.
- Prefer the clearest available scan when several copies exist.

A poor source can still be processed, but missing or unreadable content cannot always be recovered reliably.

## 3. Choose the Processing Options

For a comprehensive first parse, use **Full** ADE mode. It produces refined Markdown, document classification, and a table of contents in addition to the core parse; it does not run schema extraction. **Fast** mode is useful when speed matters and the document pattern is already familiar. **Custom** mode allows the optional features to be selected individually.

For scanned, faxed, blurred, or irregular documents, leave **Enable visual recovery on hard regions** turned on. The app first relies on GLM-OCR for the complete document. Luna is used only for selected existing GLM regions that show evidence of OCR difficulty, such as low confidence, an empty detected text box, broken structure, clipping, or a recognizable OCR ambiguity. Clean, high-confidence content is left untouched. Luna does not create a region that GLM-OCR failed to detect.

Visual recovery is not a second full-document OCR pass. It is a limited repair step for difficult regions.

Visual recovery and field extraction are separate choices. Turning visual recovery off does not turn extraction off; it means extraction will use the GLM-OCR result without Luna image repair. Luna must still be available when the user later selects **Run extraction**.

## 4. Parse the Document

Select **Parse document**. The progress area shows the major stages while the app:

1. Finds the page layout and reading order.
2. Reads text, tables, fields, and other document regions.
3. Checks existing detected regions for weak, empty, or malformed OCR output.
4. Uses Luna on eligible hard regions when visual recovery is enabled.
5. Builds layout-aware Markdown and the annotated PDF.
6. Runs the selected optional classification, refinement, and table-of-contents features.

The source locations and reading order remain fixed. Luna may repair eligible text, but it does not move content to a different place on the page.

If an optional Luna feature is unavailable or inconclusive, the core GLM-OCR parse remains available. Schema extraction itself requires Luna to be available.

## 5. Review the Parse Before Extracting

Do not begin with the field values. First confirm that the source document was captured well enough to support extraction.

Use the available views:

- **Overview**: Check the detected document type, page count, recovery count, summary statistics, and table of contents.
- **Markdown**: Read the reconstructed document in a clean view. Use **Show raw Markdown** when the exact text representation matters.
- **Annotated PDF**: Compare extracted regions with the original page and inspect highlighted source areas.
- **Layout Tree**: Review the page-by-page reading order and select individual regions to open their highlighted location.

Look especially for:

- Missing pages or sections
- Text placed in the wrong reading order
- Tables that lost rows, columns, or labels
- Values cut off at page edges
- Fax noise mistaken for characters
- Important handwritten, stamped, or faint regions

If a major section is unreadable, use a clearer source document where possible. Extraction cannot safely supply information that is absent from the readable source.

## 6. Build and Save the Extraction Schema

The field dictionary is prepared before processing begins, but the in-app schema is created or selected after the first document has been parsed. Open **Extract** and expand **Extraction keys**.

Add the approved field names, descriptions, and types. For a large schema:

- Assign one owner to consolidate the field dictionary before data entry.
- Add and check fields group by group rather than entering an unreviewed list.
- Keep the same order and naming used in the approved business groups.
- Give similar fields descriptions that clearly state the expected person, organization, date, amount, or section.
- Avoid asking one field to represent several different concepts.

For the first large schema, the fields must be entered and reviewed in the schema builder unless an authorized exported schema JSON file already exists. The current app does not bulk-import a spreadsheet or CSV field list. Once a schema is complete, save it so this setup is not repeated for every document.

The current UI runs one schema at a time and keeps only the latest extraction result in the active session. For a field set that must be split, create stable schemas by business group—for example, member details, provider details, service lines, and financial totals. Run and download each group before starting the next one, then merge the approved outputs in the downstream business process. The repository does not perform that cross-schema merge.

Give the schema a meaningful name, such as the process and document family it supports. It can be exported as a schema file, shared with another authorized user, and imported later.

Treat the saved schema as a business template. When requirements change, use a clearly named updated schema so users know which field definition set produced a result.

## 7. Run the Field Extraction

Open **Extract**, select or load the schema, and choose **Run extraction**. If the approved field dictionary uses multiple schemas, complete and download each schema result separately.

The app reviews the parsed Markdown and page structure for every requested field. It attempts to associate each non-empty value with the document region that supports it. The result is not just a list of values; it is a list of values with review information and, where available, a direct source location.

The fields may come from different pages, tables, headers, footers, or form sections. The user does not need to process each page separately.

## 8. Interpret and Validate the Results

Review extracted fields according to their business importance and result status.

- **High confidence**: Strong supporting document evidence was found. Important or regulated fields should still follow the organization’s normal review policy.
- **Medium confidence**: The value may be correct, but the source or match is less certain. Review it against the document.
- **Inferred**: The app proposed a value from the document context but could not confirm an exact value-to-source match. Both the value and its highlighted source require manual confirmation; inferred is not the same as verified support.
- **Not found**: The app could not support a value from the document. The value remains empty rather than being invented.

Use **Show source** to open the cited page and highlighted region. Confirm both the value and its meaning. A correct number taken from the wrong role or section is still a business error—for example, a facility NPI returned as a rendering provider NPI.

For a schema with more than 100 fields, use a risk-based review process:

1. Always review business-critical identifiers, dates, totals, and compliance fields.
2. Review every inferred, medium-confidence, or not-found result.
3. Sample high-confidence results according to the organization’s quality policy.
4. Reconcile related values, such as line totals against claim totals or service dates against the covered period.
5. Record unresolved fields for manual completion or source-document follow-up.

The confidence label supports review prioritization; it does not replace accountable business validation.

## 9. Use Chat for Follow-up Questions

If document chat was enabled, use the **Chat** tab for questions that are easier to express conversationally, such as asking which page contains a policy number or whether a particular clause appears.

When the answer has a valid citation, use **Show source** to inspect it. If the document does not contain the answer, the app should say so rather than treating outside knowledge as document evidence.

Chat is useful for investigation and review. The saved schema remains the repeatable method for extracting a controlled set of fields.

## 10. Export the Results

After review, download the outputs needed by the business process:

- **Download Markdown** for the readable reconstructed document
- **Download annotated PDF** for visual review and source tracing
- **Download Extract JSON** for the extracted field result
- **Download Full JSON** for the combined parse, layout, grounding, metadata, and extraction result

The extraction output is suitable for a downstream workflow only after the organization applies its required validation and approval controls.

## 11. Repeat Consistently

For additional documents:

1. Upload the next document.
2. Reuse the approved schema for the same business process.
3. Parse and review the source coverage.
4. Run extraction.
5. Validate exceptions and critical fields.
6. Export the approved result.

Consistency matters more than continually changing field instructions. Reuse the same names and definitions when the business meaning has not changed. Update the schema deliberately when document formats or requirements change.

## Applying the Workflow Beyond Healthcare

The healthcare field examples are only one use case. The same workflow can be applied wherever information must be captured from documents while retaining a path back to the source.

Examples include:

- Invoice numbers, purchase orders, tax, document totals, payment terms, and fixed-position line items defined in the schema
- Contract parties, effective dates, obligations, renewal dates, and signatures
- Bank account details, statement periods, opening balances, and closing balances
- Applicant details, employment history, declarations, and approvals
- Certificate numbers, issuing authorities, validity periods, and conditions
- Report findings, measurements, recommendations, and sign-offs
- Shipping references, delivery dates, receiving details, and fixed-position item values defined in the schema

The field names change, but the business pattern remains the same: define the required information, parse the entire document, review source coverage, extract against a reusable schema, validate exceptions, and export grounded results.

## What a Successful Run Looks Like

A successful run does not mean every field is populated. It means:

- The document was reconstructed in a readable form.
- Important page regions can be traced back to the original document.
- Requested values are either directly supported by a source or clearly marked as inferred, uncertain, or not found.
- Missing or uncertain values are clearly identified for review.
- The same approved schema can be reused consistently.
- The exported result is ready for the organization’s normal quality and approval process.

This combination of automation, source highlighting, and exception-based review allows business teams to handle large field sets without treating the output as an unaudited black box.
