# Tutorial

1. Complete [setup](../SETUP.md) and open <http://localhost:8501>.
2. Optionally set `OPENAI_API_KEY` in the Windows user environment before launch. The Windows launcher refreshes it and optional `OPENAI_BASE_URL` from user scope each time.
3. Upload one PDF, PNG, JPEG, or TIFF. For a PDF, optionally enable **Page range** and choose inclusive start/end pages.
4. Choose an ADE mode:
   - **Fast**: classification only.
   - **Full**: Markdown refinement, classification, and TOC.
   - **Custom**: change individual refinement, classification, or TOC toggles.
   “ADE mode” is only a preset selector for optional Luna features; every mode runs the same core GLM parse.
5. Leave **Enable visual recovery on hard regions** on to allow bounded Luna crop repair. Enable document chat only if needed.
6. Select **Parse document** and wait for layout, recognition, recovery, assembly, annotation, enhancement, and analysis stages.
7. Use Overview for type, metrics, TOC, thumbnails, and original pages. Use Markdown for rendered or raw output, Annotated PDF for boxes, and Layout Tree for grounded elements and Luna badges.
8. Open Extract. In **Extraction keys**, create a schema name and fields of type `string`, `number`, `integer`, `boolean`, or `date`; load a saved schema; import JSON; or load the invoice example. Field names start with a letter or underscore and contain only letters, numbers, and underscores. Save if the schema should be reused, use **Export schema JSON** to download it, then select **Run extraction**.
9. For a mixed-form PDF, enable **Use custom form routing**. Create or import a routing profile, map extractable category keys to saved schemas, and select **Classify forms**. Review every segment below 85% confidence, correct page ranges/categories when necessary, then select **Extract eligible forms**. Non-eligible categories and the built-in `other` fallback are never sent to extraction.
10. Inspect field confidence and select **Show source** to open the cited GLM box. `not_found` values have no source; `inferred` values require review.
11. Enable Chat before or after parsing; changing this toggle does not rerun GLM. Ask a question. Cited responses expose **Show source**; answers without valid citations are low confidence.
12. TOC entries, annotated-page elements, and Layout Tree items also open their highlighted source box.
13. The bottom action bar downloads refined Markdown as `<stem>.md`, the annotated PDF as `<stem>.annotated.pdf`, Extract JSON as `<stem>.extract.json` when available, and current combined JSON as `<stem>.full.json`. Full JSON includes extraction whenever extraction has run.

Readable GLM text remains when Luna is unavailable or inconclusive. Luna recovery never changes element IDs, boxes, types, confidence, reading order, or structure.
