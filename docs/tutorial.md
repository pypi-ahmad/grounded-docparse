# Tutorial

1. Complete [setup](../SETUP.md) and open <http://localhost:7137>.
2. Optionally set `OPENAI_API_KEY`, `GOOGLE_API_KEY`, or `AGNES_API_KEY` in the Windows User environment for the selected AI model. The native launcher imports these values on each start.
3. Upload a supported PDF, Word, PowerPoint, Excel, CSV, ODF, HTML, Markdown, EPUB, or image file. Each file has its own required **Processing type** selection.
4. Select **Native PDF**, **Scanned PDF**, or **Mixed PDF** for a PDF; select the matching Word, PowerPoint, Excel, CSV, Image, or Other Native type for every other file. The app validates the choice and blocks mismatches.
5. For **Mixed PDF**, review the Native/OCR suggestion for every page, override if necessary, and confirm the complete table. A Native PDF with unusable pages asks you to use Mixed PDF instead of falling back automatically.
6. Select exactly one extraction engine. Local Ollama additionally offers GLM-OCR, PaddleOCR-VL, and DeepSeek-OCR. Choose an ADE mode for optional AI tasks:
   - **Fast**: classification only.
   - **Full**: Markdown refinement, classification, and TOC.
   - **Custom**: change individual refinement, classification, or TOC toggles.
   “ADE mode” is only a preset selector for optional AI features.
7. Optionally select a format-specific content range. For every engine except **AI ADE**, enable **AI enhancement for failed or <75% confidence regions** only when remote crop repair is wanted. **Enhance Markdown with AI** uses the same selected model for presentation refinement without rerunning OCR. There is no separate visual-recovery switch. Enable document chat only if needed.
8. Select **Parse document**. Native results expose Markdown, JSON, and **Source Structure**; an **Annotated PDF** tab appears only when the selected route produces one.
9. Open Extract. Native extraction uses immutable `base_text` and accepts only values with exact intervals that resolve to source anchors. OCR extraction continues to use existing element evidence.
10. For a mixed-form scanned PDF, enable **Use custom form routing**. Create or import a routing profile, review the suggested segments, and extract only approved eligible categories.
11. Inspect field evidence and select **Show source** where available. Native values resolve through character spans and source anchors; OCR values resolve to local-engine elements and page boxes.
12. Enable Chat before or after parsing. Cited responses expose **Show source**; answers without valid citations are low confidence.
13. Download Markdown and Full JSON. Download Extract JSON when extraction has run, source structure for native documents, and an annotated PDF only when available.

Readable local-engine text remains when AI enhancement is unavailable or inconclusive. Enhancement never changes element IDs, boxes, types, confidence, reading order, or structure.
