---
tags: product, architecture, overview
sources: README.md, docs/architecture.md
snapshot: content-a3c6bf27aca5
status: released
---

# System overview

Grounded DocParse is a workstation-oriented document parsing studio. A user explicitly selects how each file should be processed, after which the system produces structured Markdown, JSON, source evidence, and format-appropriate previews. The design combines local OCR for visual documents with native extraction for files whose embedded structure is authoritative.

The central boundary is evidence ownership. Scanned PDFs and images remain owned by the existing GLM-OCR or PaddleOCR-VL pipeline. Native PDFs use PDF inspection, while Word, PowerPoint, spreadsheet, CSV, HTML, EPUB, and selected native formats use a non-OCR Docling path. Mixed PDFs route pages individually and preserve original page order.

See [[processing-types-and-manual-routing]], [[grounding-and-evidence-contract]], and [[repository-architecture]].

## Evidence

The product description is grounded in `README.md`; component boundaries and result flow are defined in `docs/architecture.md`.
