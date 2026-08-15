---
tags: schema, validation, extraction
sources: src/grounded_docparse/native_extraction.py, src/grounded_docparse/schema_store.py
snapshot: content-0724dc478444
status: released
---

# Schema translation and value validation

Saved extraction schemas are translated into flat field and group specifications that LangExtract can request while preserving JSON pointers, field types, descriptions, and required structure. The adapter later reconstructs the requested object shape from individually grounded values.

String values must match source text exactly before type coercion. Numeric, boolean, date-like, array, and nested values are set only through their translated schema locations, and ungrounded candidates never enter the accepted result.

See [[langextract-grounded-extraction]], [[native-document-model]], and [[cli-and-python-api]].

## Evidence

Schema translation, JSON-pointer helpers, coercion, and result assembly live in `src/grounded_docparse/native_extraction.py`; persisted schema contracts live in `src/grounded_docparse/schema_store.py`.
