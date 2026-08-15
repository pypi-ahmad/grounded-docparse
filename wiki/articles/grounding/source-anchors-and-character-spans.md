---
tags: anchors, spans, provenance
sources: src/grounded_docparse/native.py, src/grounded_docparse/docling_native.py
snapshot: content-7e6cbb56ddf0
status: released
---

# Source anchors and character spans

Source anchors describe where text came from in the original format. PDF anchors carry page and bounding-box coordinates; structural anchors identify paragraphs or shapes; cell anchors identify sheet and cell; CSV anchors identify row and column; text anchors cover other native structures.

`SourceSpan` connects a half-open character interval in `base_text` to one or more anchors. When an extraction returns a character interval, the system selects the covering spans and therefore recovers exact source evidence without searching rendered Markdown.

See [[native-document-model]], [[langextract-grounded-extraction]], and [[office-and-native-formats]].

## Evidence

Anchor unions and span validation are defined in `src/grounded_docparse/native.py`; format-specific anchor construction is implemented in `src/grounded_docparse/docling_native.py`.
