"""Versioned prompts for Luna's document-level tasks."""

from __future__ import annotations

PROMPT_VERSION = "2026-07-29.4"

SCHEMA_REPAIR_INSTRUCTION = (
    "The previous response did not satisfy the required output schema. "
    "Return exactly one schema-valid result with no prose outside it."
)

MARKDOWN_REFINEMENT_PROMPT = (
    "Improve Markdown presentation without producing or editing document text. "
    "Do not add information, remove content, correct OCR text, or change page order. "
    "Return every supplied element ID exactly once under its original page. You may "
    "adjust heading levels, text-like presentation roles, "
    "list depth, and paragraph grouping. Preserve supplied page and element order, "
    "tables, and page breaks. Use "
    "render_as=source when no change is justified. Never omit, duplicate, or invent an ID."
)

CLASSIFICATION_PROMPT = (
    "Classify the grounded document using only the supplied Markdown and compact layout. "
    "Use Invoice, Contract, Bank Statement, Report, Form, Certificate, Letter, or Other "
    "as primary_type. Keep reasoning short and do not infer facts absent from the document."
)

TOC_PROMPT = (
    "Build a hierarchical table of contents using only headings actually present in the "
    "supplied document. Preserve page and reading order. Use the heading's exact title and "
    "cite its supplied element ID when possible; otherwise use null. Never invent a section, "
    "page, or identifier."
)

CHAT_PROMPT = (
    "Answer strictly from the supplied document Markdown and compact layout. Cite only "
    "supplied element IDs. If the answer is not present, say so clearly and return no "
    "citations. Set confidence to high only for direct unambiguous support, medium for "
    "partial support, and low when unsupported or uncertain. Do not use outside knowledge."
)

EXTRACTION_PROMPT = (
    "Extract only values supported by the grounded document context. Prefer exact or "
    "near-exact source text. Return null when a value is absent or ambiguous. For every "
    "non-null scalar, include evidence at its RFC 6901 JSON Pointer within the returned "
    "data object (for example /invoice_number), never a pointer into the supplied document "
    "or layout tree. Use block_ids and atom_ids only to identify source evidence. Never "
    "invent identifiers, values, or bounding boxes."
)
