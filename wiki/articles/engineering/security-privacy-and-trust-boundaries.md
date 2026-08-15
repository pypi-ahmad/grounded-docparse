---
tags: security, privacy, trust-boundaries
sources: SECURITY.md, docs/spec.md, src/grounded_docparse/native_extraction.py
snapshot: content-338dd11260b6
status: released
---

# Security, privacy, and trust boundaries

Uploaded documents are untrusted. File extensions are only hints; signatures, package structure, page limits, size limits, and parser-specific validation must succeed before content is processed. A user-selected mode never authorizes silent interpretation by another pipeline.

Native evidence is also untrusted input to models. LangExtract output is accepted only through exact character intervals and source-span resolution. PDF Inspector and Docling cannot invoke OCR or create authoritative text outside their native source contracts.

Local OCR services and workstation persistence reduce unnecessary data movement, while optional remote reasoning remains bounded by the product's explicit recovery and extraction interfaces.

See [[grounding-and-evidence-contract]], [[langextract-grounded-extraction]], and [[installation-and-local-runtimes]].

## Evidence

Project security reporting is defined in `SECURITY.md`; feature trust boundaries are in `docs/spec.md`; ungrounded extraction rejection is implemented in `src/grounded_docparse/native_extraction.py`.
