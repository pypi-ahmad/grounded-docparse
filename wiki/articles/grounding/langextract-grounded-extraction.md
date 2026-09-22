---
tags: langextract, extraction, grounding
sources: src/grounded_docparse/native_extraction.py, src/grounded_docparse/config.py, docs/spec.md
snapshot: content-0117589c51ef
status: working-tree
---

# LangExtract grounded extraction

The native extraction adapter sends immutable `base_text` and a translated saved schema to LangExtract. It accepts a candidate only when LangExtract supplies a character interval, the interval is valid, and the returned value exactly matches the corresponding source substring.

Accepted intervals are mapped through covering source spans to anchors. Candidates with missing intervals, mismatched text, gaps in span coverage, or unresolved evidence are rejected and retained only as diagnostics where appropriate. LangExtract performs no OCR.

See [[immutable-base-text]], [[schema-translation-and-value-validation]], and [[grounding-and-evidence-contract]].

## Current working-tree model changes

The configured GPT default is `gpt-6-sol`. The native adapter passes `reasoning_effort="medium"` to LangExtract's OpenAI provider, using `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` from the process environment. It records model and reasoning effort in extraction metadata and traces. It currently returns an empty `RunUsage`, so session estimates do not measure native extraction token cost.

## Evidence

`LangExtractNativeExtractor.extract`, interval coverage checks, coercion, and accepted-value construction are implemented in `src/grounded_docparse/native_extraction.py`.
