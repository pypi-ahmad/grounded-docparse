---
type: feature-workflow
title: Agentic Document Features
description: Describes optional document analysis and extraction, custom form routing, provider execution, and feature-specific result states.
tags: [agentic-features, extraction, classification, chat]
verified:
  - by: openwiki/0.5.2
    at: 2026-09-23T14:49:53.692Z
sources:
  - id: openwiki-source-54727760005a94b97203d9ec
    resource: repo://src/grounded_docparse/agentic.py
  - id: openwiki-source-83737120952115ec6f38de20
    resource: repo://src/grounded_docparse/pipeline.py
  - id: openwiki-source-8d72a770f70ca94d001e77ec
    resource: repo://tests/test_agentic_features.py
  - id: openwiki-source-4b8325c7f104115e246dbb8f
    resource: repo://tests/test_form_routing.py
  - id: openwiki-source-d6099bfea9b6f8804dbf9235
    resource: repo://tests/test_simple_pipeline.py
generated: { by: "codex", at: "2026-09-23T14:49:53.692Z" }
---

# Feature groups

`DocumentAgent` exposes post-parse classification, table-of-contents generation, custom form classification and routing, schema-based extraction, and document chat. These features consume a parsed result and use configured provider gateways; they are separate from choosing the primary parsing engine. See [source grounding](../evidence/source-grounding.md) for how native extraction values and chat citations are checked.

## Direct AI ADE and post-parse features

AI ADE is a primary parse route. When the page analyzer has no local OCR analysis, `DocumentParser` asks the selected gateway to draft the page directly. The parser raises an error when a nonblank page returns no regions ([page processing](../../src/grounded_docparse/pipeline.py)). A focused test makes local OCR fail if called and confirms the AI ADE path returns elements ([test](../../tests/test_simple_pipeline.py)).

By comparison, `DocumentAgent` methods operate on an existing parse result. Its `prepare` method groups page text and layout into bounded contexts that can be reused across feature calls ([context preparation](../../src/grounded_docparse/agentic.py)). `analyze` sends the first two pages to document classification and walks all prepared contexts for the table of contents. Classification and TOC run as separate jobs; a feature error is recorded independently, and TOC falls back to detected headings when generation fails. Tests check the first-two-page classification boundary and grounded TOC output ([feature tests](../../tests/test_agentic_features.py)).

## Form classification and routed extraction

Custom form classification validates the provider's segments against the prepared document context, associates supported categories with configured schemas, and marks a segment for automatic approval only when its confidence reaches the requested threshold and it did not cross a classifier-window boundary. Other segments remain for review ([classification flow](../../src/grounded_docparse/agentic.py)). Before extraction, reviewed segments must cover every document page once, be approved, and still match the classifier profile's eligibility and schema mapping. An extraction exception is recorded on that segment so the loop can continue. Tests cover approval state, invalid grounding repair, and the approved/eligible extraction gate ([routing tests](../../tests/test_form_routing.py)).

## Schema-based extraction and chat

For flat scalar schemas, extraction can run over separate bounded contexts and reconcile field candidates; nested objects and arrays use a whole-document extractor call because partial nested values are not merged across windows. Provider results still pass the extraction and evidence contracts described in [source grounding](../evidence/source-grounding.md) ([extractor](../../src/grounded_docparse/agentic.py)). Chat uses a bounded working set when the prepared document is too large for one context, then maps only known element IDs into returned sources.

Features are opt-in at their call sites and can be unavailable when the selected provider is not configured. Check each feature's status, warnings, usage, and trace in its result before treating the operation as successful.
