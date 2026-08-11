# Architecture

## Core Sections (Required)

### 1) Architectural Style

- Primary style: **parse-then-reason agentic document pipeline** (ADE pattern) on a **workstation Streamlit + local OCR** boundary
- Classification for product taxonomy: **primarily ADE**, with **partial IDP-like outcomes**
- Why this classification:
  - Docs and package description call it a grounded/agentic document parser
  - Local OCR owns evidence geometry; Luna performs specialized goal-directed tasks under deterministic validation
  - Missing enterprise IDP platform edges (connectors, multi-user queues, SoR write-back, worker fleets)
- Primary constraints:
  1. Raster-only evidence (ignore selectable PDF text)
  2. Local OCR owns IDs/geometry/order; models may not freely rebuild structure
  3. Optional agentic features are finite, isolated, and human-controllable

### 2) System Flow

```text
upload -> ingest/raster -> local OCR -> quality/recovery plan
  -> optional Luna crop recovery -> hierarchy/Markdown/JSON/PDF
  -> optional DocumentAgent (classify/TOC/route)
  -> optional DocumentExtractor / chat -> review downloads
```

Steps with evidence:

1. `ingest.py` validates and rasterizes pages.
2. `local_ocr.py` or `paddle_ocr.py` produces layout regions.
3. `page_analysis.py` / `quality.py` score weak regions.
4. `pipeline.py` (`DocumentParser`) applies recovery rules and builds parse artifacts.
5. `agentic.py` (`DocumentAgent`) prepares contexts and runs classify/TOC/routing/chat.
6. `extraction.py` (`DocumentExtractor`) extracts against schema with evidence resolution.

### 3) Layer/Module Responsibilities

| Layer or module | Owns | Must not own | Evidence |
|-----------------|------|--------------|----------|
| Local OCR engines | Text, boxes, types, order, confidence, element identity source | Business schema policy | `local_ocr.py`, `paddle_ocr.py`, ownership table in `docs/architecture.md` |
| `DocumentParser` | End-to-end parse orchestration, recovery acceptance, hierarchy | Open-ended planning | `pipeline.py` |
| `DocumentAgent` | Prepared contexts, classify/TOC/route/chat orchestration | Free rewrite of geometry | `agentic.py` |
| `DocumentExtractor` | Schema validation, extract draft, evidence resolve/repair | Invent unsupported values without marking | `extraction.py` |
| Streamlit UI | Batch UX, ADE presets, review tabs, downloads | Durable multi-user workflow | `streamlit_app.py`, `docs/architecture.md` |
| `schema_store` | Saved schemas/profiles in SQLite | Parse result durability across sessions | `schema_store.py` |

### 4) Reused Patterns

| Pattern | Where found | Why it exists |
|---------|-------------|---------------|
| Ownership split (OCR evidence vs model judgment) | architecture ownership table; recovery rules | Auditability and anti-hallucination |
| Structured Outputs + one repair retry | `gateways.py`, agentic/extraction | Finite contracts, stop conditions |
| Prepared bounded contexts | `DocumentAgent.prepare` | Cost/latency control for long docs |
| Feature isolation | classify/TOC concurrent; failures don't erase parse | Resilience of core parse |
| Human review gates | form routing confidence thresholds | Controlled autonomy |

### 5) Known Architectural Risks

- Optional Luna path depends on external OpenAI key/network; local parse remains usable without it.
- Single-process Streamlit boundary limits multi-user production IDP deployment.
- Logical form split does not emit separate sub-document files (partial Split).
- Accuracy claims vs commercial ADE products are explicitly out of scope for bundled corpus.

### 6) IDP vs ADE decision record

| Question | Answer | Evidence |
|----------|--------|----------|
| Is this classic OCR only? | No | Markdown hierarchy, extraction, agentic roles |
| Is this full enterprise IDP? | No | No connectors/queues/SoR/RPA; workstation boundary |
| Is this ADE-pattern? | **Yes (primary)** | Parse-then-reason, grounded IR, specialized goals, validation, uncertainty, review |
| Does it implement some IDP outcomes? | Yes (partial) | Schema extract, routing profiles, HITL review |

See also: `docs/idp-vs-ade-classification.html` (human-readable classification brief).

### 7) Evidence

- `docs/architecture.md`
- `docs/how-grounded-docparse-is-agentic.md`
- `docs/agentic-document-extraction-comparison.md`
- `docs/research.md`
- `README.md`
- `pyproject.toml`
- `src/grounded_docparse/pipeline.py`
- `src/grounded_docparse/agentic.py`
- `src/grounded_docparse/extraction.py`
- `docs/idp-vs-ade-classification.html`
