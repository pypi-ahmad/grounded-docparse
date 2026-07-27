# Changelog

## Unreleased

- Reduced the product to one synchronous Streamlit page: upload, extract, inspect Markdown/JSON, and download.
- Replaced persisted jobs, review/evaluation workflows, annotated artifacts, and the CLI with a direct Luna-draft/Terra-verification pipeline.
- Removed SQLite, local artifact/cache code, the custom Streamlit component, and their dependencies.
- Enforced fail-closed visual grounding for invalid or missing bounding boxes.
- Left legacy `.docparse/` data untouched and ignored.

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Replaced the multi-service deployment with one local Streamlit process, SQLite WAL metadata, and filesystem artifacts.
- Removed Docker, Compose, FastAPI, Celery, Redis, PostgreSQL, MinIO/S3, PaddleOCR-VL, GLM-OCR, and Ollama integration.
- Rebuilt the UI around persistent Workspace, Runs, Review, Export, and Evaluation workflows.
- Made the Luna/Terra grounded vision pipeline the only extraction path.
- Raised Luna and Terra output budgets to their documented 128,000-token limit and added provider-stage diagnostics for incomplete structured responses.
- Allow a fresh submission after an identical prior run failed while retaining idempotency for active and successful runs.
- Removed explicit OpenAI prompt-cache fields for compatibility with configured API endpoints.

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
