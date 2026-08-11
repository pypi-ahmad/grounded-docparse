# Changelog

All notable changes to this project are documented in this file.

Entries below **Unreleased** describe historical releases and may reference architectures or interfaces that are no longer present.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Opt-in selective local-OCR disagreement checks that audit only uncertain crops, preserve primary OCR output, persist evidence, and flag disagreements for review.
- Document-type accuracy and confidence calibration, OCR and classification review-rate reporting, JSON regression gates, and an external private calibration/holdout workflow.
- Selectable PaddleOCR-VL-1.6 local parsing with an isolated locked runtime, Windows launcher, loopback-only PaddleX API, and exclusive GPU service switching.
- Session-scoped batches of up to 20 files with sequential processing, per-file failure isolation, retry/skip behavior, and ZIP export.

### Changed

- Made Luna recovery scale from eight to 64 prioritized crops with document length while retaining the three-per-page guard.
- Kept local GLM form recovery independent from the Luna crop budget and standardized every Luna request on medium reasoning effort.
- Generalized evidence ownership and recovery quality gates across GLM-OCR and PaddleOCR-VL-1.6.

## [0.5.0] - 2026-07-31

### Added

- A per-user Windows installer, resumable WSL/Ubuntu provisioning, dependency repair, NVIDIA vLLM selection, and Ollama BF16 CPU/AMD fallback.
- Reusable Markdown/JSON extraction definitions and custom form-routing profiles for classifying mixed PDF packets, reviewing page segments, and extracting only selected categories.
- Business, technical, and Azure bulk-fax guides, plus a sanitized application preview.
- A responsive dark multipage documentation website generated from the repository's non-security Markdown files.

## [0.4.0] - 2026-07-30

### Added

- Functional GLM-OCR startup validation and a provenance-producing `--glm-only` live benchmark mode.
- `Setup-GLM-OCR.cmd`: one-time Windows 11 bootstrap that installs WSL2 + Ubuntu-24.04, checks GPU passthrough, installs `uv` inside WSL, and runs the existing launch stack to download weights and start the app.
- Optional text-only Luna Markdown refinement with grounded presentation directives.
- Unified JSON v4.4.0 with element provenance, split recovery/agentic timing, flat classification, sections, extraction, and recovered-only recovery-log fields; annotated PDF bytes remain outside JSON.
- Extraction JSON v1.1 with canonical `element_id`, source text, and GLM-owned normalized boxes.
- Deterministic recovery scoring from OCR confidence, empty-region area, character density, garbage ratio, and table quality.
- Document-wide prioritization for up to eight high-effort Luna recovery requests, capped at three regions per page, with dashed orange annotations, recovered-region badges, and counts.
- Structured Luna classification, hierarchical TOC generation, grounded document chat, and on-demand extraction.
- Fast/Full/Custom ADE presets with Fast as the default; extraction keys now live in the post-parse Extract tab and Chat remains off by default.
- Reusable compact document context, versioned Luna prompts, and one schema-format repair retry while GLM IDs and boxes remain authoritative.
- SQLite-backed schema builder with JSON import/export and native annotated-page source navigation.

### Changed

- Pinned GLM-OCR and PP-DocLayoutV3 snapshots for cached-offline startup, restored the SDK's task/label mappings while retaining document boilerplate, and selected measured WSL throughput defaults.
- Corrected GLM's 0–1000 coordinates, dense-form reading order, vLLM context sizing, and WSL multimodal startup memory behavior.
- Refreshed all repository documentation for the GLM-first pipeline, current Streamlit workflow, Python API, configuration, security boundaries, and locked WSL runtime.
- Enabled evidence-triggered Luna visual recovery by default with a sidebar opt-out while allowing GLM-only parsing without an OpenAI key.
- Removed the API-key requirement from the Windows/WSL launcher.
- Kept GLM parsing reusable when only agentic options change, avoiding unnecessary OCR reruns.
- Restricted Luna recovery to high-confidence text-only corrections of existing GLM elements; additions, rejections, geometry changes, reading-order changes, and full-page fallback are ignored or disabled.
- Made complete nonblank GLM failure terminal before Luna while retaining isolated failed pages as partial output with warnings.

### Removed

- Legacy JSON and v1 annotation compatibility.
- Manager/specialist arbitration in favor of one direct evidence-critic inspection pass.
- Disabled-by-default provider ceilings and optional targeted-repair context crops.

## [0.3.0] - 2026-07-28

### Added

- Full self-hosted GLM-OCR pipeline with PP-DocLayout-V3, parallel region OCR, WSL2/vLLM launch scripts, and a Windows launcher.
- Unified engine-neutral parse results with normalized elements, runtime metadata, and structured JSON v4.
- Document Parse Studio with page-range parsing, live stages, thumbnails, rendered Markdown, annotated PDF viewing, and a selectable layout tree.
- Semantic PDF annotation colors, one-based reading-order labels, and selected-region highlighting.
- Reproducible evaluation corpus, schemas, benchmark reports, rate cards, and source-grounded quality metrics.

### Changed

- Made GLM-OCR the primary local recognition engine and `gpt-5.6-luna` the only remote verification model.
- Reduced deployment to a synchronous local Streamlit application backed by the high-performance WSL2 stack.
- Added shared provider budgets, bounded retries, concurrent page processing, and detailed runtime diagnostics.
- Made Markdown and structured JSON lossless and span-exact while retaining legacy backend compatibility.

### Fixed

- Rebased confidence spans after text normalization and preserved source evidence for low-confidence atoms and table cells.
- Prevented rejected content from entering extraction prompts through v4 flat elements or audit metadata.
- Corrected GLM-OCR normalized bounding-box conversion for strict Pydantic validation.
- Hardened arbitration, recovery, visual enrichment, and incomplete-structure handling.

## [0.2.0] - 2026-07-26

### Added

- Luna page drafting and Terra visual inspection with typed Structured Outputs.
- Fast, Balanced, and Maximum production profiles.
- Source-rerendered 450-DPI crop inspection with bounded attempts and crop hashes.
- Verification states and fail-closed strict Markdown and schema extraction.
- Durable FastAPI jobs with realtime and batch Celery queues.
- PostgreSQL job state, Redis delivery, and local or S3-compatible artifact storage.
- Submission idempotency and content-addressed result reuse.
- Review and corrected-tree evaluation endpoints.
- Annotated PDFs, quality reports, failure JSONL, segmentation manifests, and audit bundles.
- Production Dockerfile and Compose stack with PostgreSQL, Redis, MinIO, API, workers, and Streamlit.
- Docker-free local Streamlit parsing through `OPENAI_BASE_URL` and `OPENAI_API_KEY`.
- Compose credential validation and local secret rotation without secret-value logging.

### Changed

- Added asynchronous API submission and polling to Streamlit while retaining an explicit in-process local testing backend.
- Set the production full-page default to 200 DPI and crop rendering to 450 DPI with 5% padding.
- Restricted Balanced and Maximum extraction to independently verified evidence.
- Reorganized public documentation around the production service while retaining the Paddle/GLM CLI as a compatibility path.
- Corrected prompt-cache documentation to avoid promising unsupported GPT-5.6 retention behavior.
- Propagated host OpenAI credentials explicitly and gated stateful Compose services on configuration validation.
- Made the published API port configurable without changing internal service discovery.

### Security

- Disabled OpenAI response storage for production vision calls.
- Added bearer authentication to job, artifact, review, evaluation, and purge routes.
- Preserved bounded errors and content hashes for auditability.
- Documented the single-tenant authentication model and current processing-cache deletion limitation.

## [0.1.0] - 2026-07-26

### Added

- Initial public release of Grounded Document Parser.
- Layout-aware document parsing with PaddleOCR-VL, GLM-OCR, optional cloud verification, and a Streamlit review UI.
