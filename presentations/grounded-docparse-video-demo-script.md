# Grounded DocParse five-minute video script

## Purpose

This package is designed for an **Accelerate with AI — Applied Learning in Action** contest submission. The audience is leadership. The goal is to explain the business problem, show what was built, demonstrate the major workflow features, and close with credible validation evidence.

Target duration: **4:45–5:00**  
Narration voice: **first-person builder**  
Presentation: `grounded-docparse-video-demo.pptx`  
Demo document: `D:\AI\Project\data\pdf\PublicWaterMassMailing.pdf`

The demo document is publicly available, but still avoid dwelling on addresses, phone numbers, email addresses, or other unnecessary contact details.

## Core message

> I applied the Accelerate with AI learning to build a grounded document workflow that parses once, reuses evidence across classification, routing, extraction, chat, and export, and keeps a human-review path back to the source.

## Prepare the application before recording

Do this preparation before opening the screen recorder. The video deliberately starts from a completed session so processing waits do not consume the five-minute limit.

### 1. Prepare the browser and environment

1. Start the application with `Launch-GLM-OCR.cmd` and confirm `http://localhost:8501` is ready.
2. Use a clean browser window. Hide bookmarks, downloads, extensions, notifications, and unrelated tabs.
3. Use full-screen browser mode. Start at 90% browser zoom, then adjust only if labels are too small.
4. Confirm no API key, private endpoint, local username, file-picker path, or unrelated document is visible.
5. Close messaging and email applications and enable Windows **Do not disturb**.

### 2. Parse the public demo packet

1. Upload `PublicWaterMassMailing.pdf` before recording.
2. Select **Full** mode.
3. Enable:
   - visual recovery;
   - document classification;
   - table of contents; and
   - document chat.
4. Parse all eight pages.
5. Confirm Overview, Markdown, Annotated PDF, Layout Tree, Extract, and Chat are available.

### 3. Save the extraction schema

Create and save a schema named **Collection Form Demo** with these fields:

| Field | Type | Description |
| --- | --- | --- |
| `order_number` | string | Order number printed on the Environmental Sample Collection Form |
| `pws_id` | string | Public Water System ID printed on the form |
| `sample_category` | string | Sample category printed on the form |
| `county` | string | County printed on the form |
| `evidence_of_tampering_yes` | boolean | Whether the Yes checkbox is selected for Evidence of Tampering |
| `evidence_of_cooling_yes` | boolean | Whether the Yes checkbox is selected for Evidence of Cooling |

Expected source values for rehearsal:

- order number: `984`;
- PWS ID: `MO1010001`;
- sample category: `Bacterial`;
- county: `BATES`;
- Evidence of Tampering — Yes: `false`;
- Evidence of Cooling — Yes: `false`.

Do not force these values into the result. If a field is shown as uncertain or not found, use that to explain the review workflow.

### 4. Save the routing profile

Create and save **Public Water Packet Demo**:

| Category | Description | Extract | Schema |
| --- | --- | --- | --- |
| `announcement` | Announcement pages describing form, portal, and implementation changes | No | — |
| `collection_form` | Environmental Sample Collection Form and its populated form fields | Yes | Collection Form Demo |
| `instructions` | Sample collection, form-completion, and shipping instructions | No | — |

The application supplies `other` as the non-extractable fallback.

1. Select **Classify forms**.
2. Review the segments against the packet. A reasonable reviewed result is announcement pages 1–3, collection form page 4, and instructions pages 5–8.
3. Correct boundaries if the model returns a different valid segmentation.
4. Approve every segment and select **Apply routing review**.
5. Select **Extract eligible forms**.
6. Confirm that only the `collection_form` segment was extracted.

### 5. Prepare the chat result

Ask this question before recording:

> When should the new forms begin being used?

Expected answer: **December 16, 2015**. Confirm the answer has a valid source citation and that **Show source** opens the supporting page.

### 6. Position the session

Before starting the app portion of the recording:

1. Return to **Overview**.
2. Scroll to a position that shows the document summary and table of contents.
3. Keep the routing, extraction, and chat results in the active session.
4. Rehearse each click so no searching or long scrolling appears in the final video.

## Timed recording script

### 00:00–00:12 — Slide 1: opening

**On screen:** Slide 1, full-screen slideshow.

**Narration:**

> I built Grounded DocParse by applying my Accelerate with AI learning to a practical workplace problem: turning complex scanned documents into structured information without losing the path back to the source.

### 00:12–00:32 — Slide 2: issue

**On screen:** Advance to Slide 2. Let the audience read the four steps.

**Narration:**

> Document-heavy work often repeats the same four steps. Someone reads the packet, sorts the content, re-keys the required values, and then returns to the source to verify them. The process is slow to review and difficult to trace when the document contains mixed layouts, forms, tables, or checkboxes.

### 00:32–00:55 — Slide 3: solution

**On screen:** Advance to Slide 3. Point to the grounded parse, then the reusable outcomes.

**Narration:**

> My approach is to parse the document once and create grounded evidence: reading order, element IDs, page numbers, and bounding boxes. That same parse can then support classification, form routing, field extraction, grounded chat, visual review, and structured export. Optional AI reasoning consumes the evidence; it does not replace its geometry.

### 00:55–01:10 — Slide 4: validation

**On screen:** Advance to Slide 4. Pause briefly on each accuracy row.

**Narration:**

> In practitioner manual source review, parsing, extraction, and grounded chat each exceeded ninety-five percent correctness across six anonymous PDFs and ninety-seven pages. The review included checkbox states where they appeared. This is a project validation result, not an independently audited production benchmark.

### 01:10–01:25 — Switch to the prepared app

**On screen:** Cut directly to the preprocessed Overview. Do not show the file picker or processing wait.

**Narration:**

> To demonstrate the workflow, I have preprocessed this publicly available eight-page packet. I am starting from the completed session so the demo focuses on the result rather than model wait time.

### 01:25–01:50 — Overview, classification, and table of contents

**Cursor actions:**

1. Point to the page and element metrics.
2. Point to the document classification.
3. Move through two or three table-of-contents entries without clicking every entry.

**Narration:**

> The Overview confirms the document scope and detected structure. Full mode also produces a document classification and a table of contents. These are optional reasoning features built on the reusable parse, so I can navigate the packet without rereading every page.

### 01:50–02:12 — Markdown and annotated evidence

**Cursor actions:**

1. Open **Markdown** and show headings, lists, and form text.
2. Open **Annotated PDF**.
3. Navigate to page 4 and point to the form fields and checkbox regions.

**Narration:**

> The Markdown view reconstructs the document in reading order. The annotated view preserves the page itself and overlays the detected regions. On this form page, the system identifies individual fields and the four Yes-or-No checkbox elements instead of flattening the page into untraceable text.

### 02:12–02:32 — Layout Tree

**Cursor actions:**

1. Open **Layout Tree**.
2. Expand page 4.
3. Point to one form field and one checkbox entry.

**Narration:**

> The Layout Tree exposes the structured evidence behind the preview. Each element retains its page, type, reading order, and location. That is what lets later features cite a known source region rather than inventing a location after the answer is produced.

### 02:32–03:02 — Custom form routing

**Cursor actions:**

1. Open **Extract** with custom form routing enabled.
2. Show the loaded `Public Water Packet Demo` profile.
3. Show the reviewed segment table.
4. Point to the eligible `collection_form` segment and the non-extractable announcement/instruction segments.

**Narration:**

> This packet mixes an announcement, a collection form, and several instruction pages. I defined those categories in a reusable routing profile. The classifier proposes contiguous page ranges, but the user can correct and approve them. Only the collection-form category is eligible for extraction, so unrelated pages do not continue into that stage.

### 03:02–03:37 — Extraction and Show source

**Cursor actions:**

1. Show the completed `Collection Form Demo` extraction.
2. Point to order number, PWS ID, sample category, county, and checkbox results.
3. Select **Show source** for `order_number` or `pws_id`.
4. Pause on the highlighted source region.

**Narration:**

> The saved schema requests only the business fields I need. The result returns values, confidence, and supporting evidence. It also treats checkbox states as explicit structured values. When I select Show source, the application returns to the exact page region supporting the value, keeping review fast and accountable.

### 03:37–04:02 — Grounded chat

**Cursor actions:**

1. Open **Chat**.
2. Show the prepared question and answer.
3. Point to the confidence and citation.
4. Use **Show source** if it can be completed smoothly within the time.

**Narration:**

> Chat uses the same grounded document context. I asked when the new forms should begin being used. The answer is December sixteenth, twenty-fifteen, and the response includes a citation to the supporting document element. Chat is for investigation; the reusable extraction schema remains the controlled method for repeatable fields.

### 04:02–04:22 — Downloads

**Cursor actions:**

1. Scroll to the download area.
2. Point to Markdown, annotated PDF, extraction JSON, and full JSON.

**Narration:**

> The reviewed result can be downloaded as readable Markdown, an annotated PDF, extraction JSON, or full grounded JSON. This supports both human review and downstream integration without removing the evidence needed to validate the output.

### 04:22–04:32 — Return to Slide 5

**On screen:** Cut back to the slideshow on Slide 5.

No narration during the first second of the cut. Let the closing statement settle.

### 04:32–04:55 — Closing

**Narration:**

> This project shows how I turned AI learning into a reusable accelerator: less repeated document work, a faster path to structured data, and evidence that keeps people in control. Grounded DocParse is still a project-inspired prototype, but it demonstrates a practical pattern that can be adapted to many document-heavy workflows.

Hold the final slide for two seconds, then fade out.

## Recording and editing guidance

### Capture settings

- Record at **1920×1080**, **30 fps**, landscape 16:9.
- Use the same resolution for PowerPoint and the browser.
- Record microphone audio at 48 kHz when available.
- Keep the cursor visible and move it deliberately; avoid circles and rapid movement.
- Record the slideshow and app demo as separate clips. This makes clean cuts easier and prevents application notifications from appearing over slides.

### Privacy and security check

Before recording, verify that the frame contains none of the following:

- API keys, tokens, or environment-variable values;
- a private or client endpoint;
- local usernames or file-system paths;
- private validation filenames;
- unrelated browser tabs, messages, or notifications;
- real confidential, personal, financial, or health information.

The demo PDF is public, but avoid highlighting public contact details because they do not help the story.

### Editing rules

- Use hard cuts or a very short cross-fade between the slideshow and app.
- Remove waiting, dead air, file selection, typing mistakes, and cursor searching.
- Do not artificially speed up cursor movement or the spoken narration.
- Add captions for accessibility. Check the captions for `Grounded DocParse`, `GLM-OCR`, `PWS ID`, and `JSON`.
- Keep background music absent or very low. Leadership must be able to understand every word.
- Export MP4 using H.264 at 1080p. Review the exported file once from beginning to end.

## Recovery options during rehearsal

- **Routing boundaries differ:** Correct them on screen and say, “The classifier proposes the ranges; the reviewer controls the final decision.” This strengthens the human-control story.
- **A field is uncertain or not found:** Do not hide it. Say, “The application marks unsupported values for review rather than presenting them as verified.” Then use a field with valid evidence for **Show source**.
- **Chat lacks a citation:** Use the alternative question, “Which details must the collector provide for the sampling site?” The expected answer is Facility ID, Sample Collection Point ID, and Location.
- **A service is unavailable:** Do not record a failed live call. Restore the prepared successful session and record that section separately.
- **The video exceeds five minutes:** Shorten navigation pauses first. Do not remove the manual-validation qualification or the source-review demonstration.

## Final rehearsal checklist

- [ ] Total duration is between 4:45 and 5:00.
- [ ] The opening explains the problem within 20 seconds.
- [ ] The demo begins from a completed, stable session.
- [ ] Every major workflow feature is shown once, not repeatedly.
- [ ] At least one extraction value and one chat answer show source evidence.
- [ ] Checkbox elements are visible on page 4 or in the Layout Tree.
- [ ] The `>95%` result is described as practitioner manual review.
- [ ] No production accuracy, independently audited benchmark, or realized labor-savings claim is made.
- [ ] No credentials, private endpoints, local paths, or private files are visible.
- [ ] The final MP4 has clear audio, readable UI text, and accurate captions.

