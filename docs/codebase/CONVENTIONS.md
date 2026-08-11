# Conventions

## Core Sections (Required)

### 1) Naming

- Domain classes use descriptive nouns: `DocumentParser`, `DocumentAgent`, `DocumentExtractor`, `ParseResult`
- OCR engines selected via `OcrEngine` / `ParserConfig`
- JSON schema versions are explicit strings (`4.4.0` parse, `4.5.0` full, extraction `1.1.0` / `2.0.0`)

### 2) Contracts and validation

- Pydantic models in `models.py` define API result shapes
- Extraction schemas validated before use (`validate_extraction_schema`)
- Evidence must resolve to known block/atom IDs; unsupported values become null/not_found or inferred when allowed

### 3) Error handling posture

- Agentic feature failures are isolated; parse can remain valid
- Structured features get one schema-invalid repair attempt
- Extraction may perform one evidence-repair call then deterministic fallback
- Missing `OPENAI_API_KEY` marks optional features unavailable rather than failing local parse

### 4) Grounding rules

- Grounding targets `base_markdown`, not refined presentation Markdown
- Geometry always local-OCR-owned
- Luna recovery text acceptance threshold documented as ≥ `0.85`

### 5) Evidence

- `src/grounded_docparse/models.py`
- `src/grounded_docparse/extraction.py`
- `docs/architecture.md`
- `CONTRIBUTING.md` (evidence ownership notes)

## Notes

- [TODO] Expand style rules from ruff config if/when project config is centralized beyond defaults.
