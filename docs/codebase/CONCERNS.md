# Concerns

## Core Sections (Required)

### 1) Product taxonomy risk (mislabeling)

- Calling the product “enterprise IDP” overstates platform scope (no connectors, queues, SoR, multi-user ops).
- Calling it “LandingAI ADE” is incorrect; only the pattern and UI preset naming overlap.
- **Preferred label:** ADE-pattern / grounded agentic document workstation with partial IDP outcomes.
- Evidence: `docs/architecture.md`, `docs/agentic-document-extraction-comparison.md`, this classification brief.

### 2) Architectural limits

- Single Streamlit process: not multi-tenant production IDP.
- Logical form routing does not export separate sub-document files (partial Split).
- Optional Luna quality depends on external API availability and cost.
- Session parse reuse is not durable across sessions.

### 3) Security / privacy

- Documents are rasterized and may be sent as crops/context to OpenAI when Luna features are enabled.
- Threat model document exists: `grounded-docparse-threat-model.md`.
- Local-only mode reduces remote exposure but still processes sensitive document pixels locally.

### 4) Accuracy and evaluation caution

- Repo explicitly avoids ADE/LandingAI equivalence claims from the bundled corpus.
- Markdown prettiness ≠ field accuracy; grounding/review are intentional mitigations.

### 5) High-complexity modules

- Large orchestration files (`pipeline.py`, `agentic.py`, Streamlit app) concentrate recovery and feature policy — higher change risk.
- Dual OCR engines increase configuration surface (WSL services, ports, exclusive GPU selection).

### 6) Evidence

- `docs/architecture.md`
- `docs/research.md`
- `docs/agentic-document-extraction-comparison.md`
- `grounded-docparse-threat-model.md`
- `src/grounded_docparse/pipeline.py`
- `src/grounded_docparse/agentic.py`

## Intent vs reality

| Intent signal | Reality in code/docs |
|---------------|----------------------|
| “Agentic document parser” (`pyproject.toml`) | Matches: specialized roles + bounds |
| UI label “ADE mode” | Preset only; not LandingAI product integration |
| IDP-like extraction/routing | Present as features, not full IDP platform |

## [ASK USER]

1. Should public messaging say **“ADE workstation”**, **“agentic document intelligence”**, or **“lightweight IDP”** as the primary category label?
2. Is enterprise connector/queue scope intentionally out forever, or a future roadmap item?
3. Should `docs/idp-vs-ade-classification.html` be linked from README / docs-site index?
