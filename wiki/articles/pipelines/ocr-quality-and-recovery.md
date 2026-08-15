---
tags: ocr, quality, recovery
sources: src/grounded_docparse/quality.py, src/grounded_docparse/page_analysis.py, src/grounded_docparse/pipeline.py
snapshot: content-c93637e72f7d
status: existing-and-preserved
---

# OCR quality and recovery

The OCR path performs deterministic quality analysis over recognized elements and page evidence. Risk signals can trigger bounded recovery while the selected local OCR engine continues to own layout and geometry.

Optional visual recovery may replace text only within existing elements and only under its confidence contract. It cannot create or delete elements, change bounding boxes or types, or reorder content. Native-processing libraries do not participate in this recovery path.

See [[scanned-pdf-and-image-pipeline]], [[grounding-and-evidence-contract]], and [[evaluation-corpus-and-metrics]].

## Evidence

Quality metrics live in `src/grounded_docparse/quality.py`; page analysis is in `src/grounded_docparse/page_analysis.py`; orchestration and recovery boundaries are enforced in `src/grounded_docparse/pipeline.py`.
