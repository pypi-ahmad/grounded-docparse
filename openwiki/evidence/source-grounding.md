---
type: evidence-contract
title: Evidence and Source Grounding
description: Compares OCR element evidence with native source spans and describes the checks applied to extracted values and chat citations.
tags: [evidence, grounding, source-anchors, extraction]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-54727760005a94b97203d9ec
    resource: repo://src/grounded_docparse/agentic.py
  - id: openwiki-source-ecb3a52154b3889e13c5aa06
    resource: repo://src/grounded_docparse/native_extraction.py
  - id: openwiki-source-8d72a770f70ca94d001e77ec
    resource: repo://tests/test_agentic_features.py
  - id: openwiki-source-b7010ba82c29ac515b800280
    resource: repo://tests/test_native_extraction.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Two evidence models

Grounded DocParse keeps separate evidence contracts for OCR and native conversion.

OCR results use `Element` records with an ID, page, reading order, optional normalized bounding box, text, confidence, and producing source ([model](../../src/grounded_docparse/models.py)). Visual recovery can update text on an element the primary engine already produced, but it does not create new geometry or reorder elements. See [the grounded OCR pipeline](../pipelines/grounded-ocr.md) for the detection and recognition path.

Native results retain immutable `base_text`. Each `SourceSpan` maps a half-open character interval in that text to an element and a format-specific `SourceAnchor`, such as a PDF page and box, a structural path, a spreadsheet range, or CSV row and column coordinates ([native model](../../src/grounded_docparse/native.py)). The `NativeDocument` validator checks that IDs are unique, spans fit inside `base_text`, and anchors refer to known source units. Rendering or refined Markdown does not replace the text used as native evidence.

## Native extraction acceptance

Native extraction sends `base_text` to LangExtract. The returned candidate is accepted only when its extraction class is known, its interval is valid, the interval exactly matches the source substring, all non-whitespace characters resolve through source spans, and the literal value passes schema coercion. A rejected field adds a warning while other candidates can continue ([candidate validation](../../src/grounded_docparse/native_extraction.py)). Tests cover unknown classes, non-exact text, and intervals that are only partly anchored ([native extraction tests](../../tests/test_native_extraction.py)).

## OCR chat citations

Document chat builds bounded text-and-layout context from parsed elements. Before citations become `ChatSource` records, the agent drops any provider citation whose element ID is not present in the parsed document. If no valid sources remain, the returned confidence is set to `low` ([chat implementation](../../src/grounded_docparse/agentic.py)). The focused test checks that only known element IDs map to citations ([agentic feature tests](../../tests/test_agentic_features.py)). Other extraction and routing features apply their own evidence checks; see [agentic document features](../features/agentic-document-tools.md).

## What these checks establish

The checks establish source linkage and schema constraints for accepted records. They do not establish that an OCR transcript or model-selected value is complete or semantically correct; review the source document for those judgments.
