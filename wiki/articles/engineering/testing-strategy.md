---
tags: testing, regression, contracts
sources: tests/test_native_models.py, tests/test_docling_native_parser.py, tests/test_native_extraction.py, docs/codebase/TESTING.md
snapshot: content-338dd11260b6
status: released
---

# Testing strategy

Tests protect routing, validation, evidence, persistence, and regression boundaries. Native model tests cover immutable text and spans; Docling tests cover format-to-anchor mapping without OCR; extraction tests reject missing or mismatched character intervals.

UI and CLI contracts verify that manual selections reach exactly one pipeline. Existing scanned and image tests remain unchanged and must continue to pass, while mixed-PDF tests verify review overrides and original page order.

See [[processing-types-and-manual-routing]], [[evaluation-corpus-and-metrics]], and [[security-privacy-and-trust-boundaries]].

## Evidence

Feature contracts are exercised in `tests/test_native_models.py`, `tests/test_docling_native_parser.py`, and `tests/test_native_extraction.py`; repository-wide test conventions are documented in `docs/codebase/TESTING.md`.
