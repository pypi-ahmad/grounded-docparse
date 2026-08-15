---
tags: ocr, scanned-pdf, image
sources: src/grounded_docparse/pipeline.py, src/grounded_docparse/ingest.py, docs/architecture.md
snapshot: content-988eedb6f7e0
status: existing-and-preserved
---

# Scanned PDF and image pipeline

Scanned PDFs and standalone images use the existing raster-and-OCR path. PDF pages are rendered to pixels, images are normalized, and the selected GLM-OCR or PaddleOCR-VL engine owns layout, recognition, confidence, bounding boxes, element types, and reading order.

Native PDF inspection is not invoked for this mode. That isolation is a regression boundary: adding native formats must not change scanned-document behavior, provider selection, or recovery semantics.

See [[ocr-quality-and-recovery]], [[processing-types-and-manual-routing]], and [[grounding-and-evidence-contract]].

## Evidence

Raster ingestion is implemented in `src/grounded_docparse/ingest.py`; orchestration and OCR ownership are implemented in `src/grounded_docparse/pipeline.py` and described in `docs/architecture.md`.
