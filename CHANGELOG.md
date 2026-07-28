# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
