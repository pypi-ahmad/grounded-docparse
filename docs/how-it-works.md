# How it works

1. The app requires a processing type for every uploaded file, then validates its extension, signature, and Office/container structure. Invalid combinations stop; nothing is silently rerouted.
2. **Scanned PDF** and **Image** use the existing local OCR path. Pages or image frames are rasterized, GLM-OCR uses ordered 16-page windows, and PaddleOCR-VL submits the document to its local API.
3. **Native PDF** uses `pdf-inspector` for selectable text, layout, tables, and positions. A native PDF with unusable pages stops and asks the user to select Mixed PDF.
4. **Mixed PDF** shows a Native/OCR suggestion for every page. The user confirms or overrides every route; native and OCR pages merge in original page order.
5. **Word**, **PowerPoint**, **Excel**, **CSV**, and **Other Native** formats use Docling with OCR, VLM/model enrichments, remote services, and plugins disabled. Embedded images are assets, not OCR input.
6. Native parsing produces immutable `base_text`, character spans, and `SourceAnchor` evidence. OCR parsing retains local-engine-owned elements, boxes, confidence, and reading order.
7. An optional inclusive content range selects the format's natural units: pages, TIFF frames, slides, sheets, EPUB sections, document blocks, or CSV rows. Selected units keep their original source indices.
8. The Streamlit batch progress bar reports both the current stage and a whole-number completion percentage.
7. Optional AI enhancement applies only to failed or sub-75%-confidence grounded regions and never changes existing geometry, types, order, or structure.
8. Optional classification, TOC, refinement, and chat use the parsed result. Their failures do not invalidate a successful parse.
9. Native extraction sends immutable `base_text`, never refined Markdown, to LangExtract. An accepted value needs an exact `char_interval` that resolves through source spans to one or more anchors; fuzzy, mismatched, partial, and unanchored values are rejected.
10. The app downloads Markdown, full JSON, extraction JSON when present, source structure for native results, and an annotated PDF only when a visual artifact exists.

There is no open-ended autonomous loop. Native parsing and local engines remain usable without a cloud provider; every optional remote feature is isolated from the core parse.
