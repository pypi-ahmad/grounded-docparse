# Grounded DocParse Onboarding

> **Freshness note:** This guide was generated from the repository knowledge graph at commit `2c95dc4ab71dddfb134b0bb3555103dd5166c6cc`. The working tree contained source and documentation changes, so rerun `/understand` and refresh this guide after those changes are committed or stabilized.

## Project overview

Grounded DocParse is a Python 3.12+ document parser that produces grounded Markdown, structured JSON, document elements, and annotated PDFs.

Its main stack is Streamlit, Pydantic, and Pytest. Local OCR uses GLM-OCR or PaddleOCR-VL. Optional OpenAI processing performs bounded visual recovery and document-level analysis without replacing local layout evidence.

## Architecture layers

### Core document processing

The main processing library lives under `src/grounded_docparse/`:

- `models.py` defines shared evidence, document, extraction, and result contracts.
- `config.py` validates parser, OCR, provider, and recovery settings.
- `ingest.py` rasterizes PDFs and images into page evidence.
- `local_ocr.py` and `paddle_ocr.py` adapt OCR engines into common models.
- `page_analysis.py` handles layout, reading order, and visual analysis.
- `quality.py` performs quality checks and selects recovery candidates.
- `pipeline.py` coordinates the end-to-end workflow.
- `render.py` produces Markdown, JSON, elements, and annotated PDFs.
- `agentic.py` and `extraction.py` provide classification, extraction, TOC, and chat workflows.
- `schema_store.py` and `workspace_store.py` persist reusable schemas and workspaces.

### Streamlit interface

`streamlit_app.py` provides interactive upload, parsing, review, extraction, and workspace workflows.

### Testing

The `tests/` suite covers parser contracts, OCR, recovery, provider runtime, Streamlit behavior, schemas, persistence, evaluation, and installers.

### Evaluation data

`benchmarks/` contains corpus annotations, manifests, JSON schemas, rate cards, baselines, and regression policies.

### Documentation

Source guides live under `docs/`. The generated static site lives under `docs-site/`. Root Markdown files cover setup, contribution, security, releases, and project purpose.

### Operations and configuration

Root launchers, `scripts/`, `installer/`, runtime YAML files, and project manifests manage setup, packaging, WSL OCR services, and application startup.

## Key concepts

- Local OCR owns layout, geometry, element IDs, confidence, element types, and reading order.
- PDFs become raster evidence; embedded PDF text is not trusted extraction evidence.
- Luna recovery may replace text only on an existing element above the confidence threshold.
- Structural additions, deletions, geometry changes, type changes, and reading-order changes fail closed.
- Pydantic models define contracts shared across pipeline stages.
- OCR implementations normalize engine-specific output into common region and page models.
- Quality analysis separates deterministic acceptance from optional AI recovery.
- Agentic features consume grounded outputs instead of bypassing the evidence model.
- The runtime layer controls concurrency, retries, budgets, and provider diagnostics.

## Guided tour

1. Read `README.md` for project purpose, evidence boundaries, and setup.
2. Read `streamlit_app.py` and `src/grounded_docparse/cli.py` for user entry points.
3. Read `src/grounded_docparse/models.py` for shared contracts.
4. Read `config.py` and `runtime.py` for settings and provider execution.
5. Read `ingest.py`, `local_ocr.py`, and `paddle_ocr.py` for source conversion and OCR.
6. Read `page_analysis.py` and `quality.py` for grounded layout and validation.
7. Read `pipeline.py` for orchestration.
8. Read `render.py`, `agentic.py`, and `extraction.py` for outputs and higher-level features.
9. Read WSL launch scripts and `docs/architecture.md` for runtime operation and system structure.

## File map

```text
streamlit_app.py / cli.py
  pipeline.py
    ingest.py
    local_ocr.py / paddle_ocr.py
    page_analysis.py
    quality.py
    gateways.py + runtime.py
    render.py
  agentic.py / extraction.py
```

Supporting modules:

- `batch.py` builds batch outputs and archives.
- `benchmark.py` implements evaluation metrics and regression reports.
- `enhancement.py` builds page chunks and combines enhanced Markdown.
- `ocr_disagreement.py` compares OCR outputs.
- `ocr_services.py` activates managed OCR services.
- `prompts.py` contains versioned secure prompts.
- `schema_store.py` manages extraction schemas and classifier profiles.
- `workspace_store.py` saves sessions and reconstructs parse results.

## Complexity hotspots

- `pipeline.py`: broad orchestration and high dependency fan-out.
- `models.py`: central contracts used across most modules.
- `page_analysis.py`: layout and OCR heuristics.
- `quality.py`: acceptance and repair policy.
- `render.py`: several output representations and transformations.
- `agentic.py`: multiple document-level workflows.
- `gateways.py`: provider requests, validation, and usage tracking.
- `runtime.py`: concurrency, retries, and budgets.
- `schema_store.py` and `workspace_store.py`: persistence and compatibility.
- `benchmark.py`: evaluation and regression policy logic.
