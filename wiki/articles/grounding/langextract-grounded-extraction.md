---
tags: langextract, extraction, grounding
sources: src/grounded_docparse/native_extraction.py, docs/spec.md
snapshot: content-2ae93e3d37db
status: feature-branch
---

# LangExtract grounded extraction

The native extraction adapter sends immutable `base_text` and a translated saved schema to LangExtract. It accepts a candidate only when LangExtract supplies a character interval, the interval is valid, and the returned value exactly matches the corresponding source substring.

Accepted intervals are mapped through covering source spans to anchors. Candidates with missing intervals, mismatched text, gaps in span coverage, or unresolved evidence are rejected and retained only as diagnostics where appropriate. LangExtract performs no OCR.

See [[immutable-base-text]], [[schema-translation-and-value-validation]], and [[grounding-and-evidence-contract]].

## Evidence

`LangExtractNativeExtractor.extract`, interval coverage checks, coercion, and accepted-value construction are implemented in `src/grounded_docparse/native_extraction.py`.
