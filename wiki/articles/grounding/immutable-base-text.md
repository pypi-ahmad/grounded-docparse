---
tags: base-text, immutability, extraction
sources: src/grounded_docparse/native.py, src/grounded_docparse/native_parsers.py
snapshot: content-2ae93e3d37db
status: feature-branch
---

# Immutable base text

`base_text` is the canonical character sequence assembled during native parsing. Its offsets are stable for the lifetime of the result and form the coordinate system for every `SourceSpan` and grounded extraction interval.

Rendered Markdown and source-structure views may organize the same evidence differently, but they are downstream presentations. They are never fed back into grounded extraction because formatting changes would invalidate offsets or introduce text not present in the source.

See [[source-anchors-and-character-spans]], [[docling-native-conversion]], and [[langextract-grounded-extraction]].

## Evidence

Immutability and span lookup are enforced by `NativeDocument` in `src/grounded_docparse/native.py`; parsers assemble the original text and mappings in `src/grounded_docparse/native_parsers.py`.
