# Changelog

## Unreleased

- Replaced the production parse path with Luna page drafting and Terra visual inspection.
- Added strict typed Structured Outputs, 450-DPI crop inspection, fail-closed verification states, and crop-hash grounding.
- Added Fast, Balanced, and Maximum cost/accuracy profiles.
- Added durable FastAPI jobs, Celery execution, PostgreSQL state, Redis delivery, MinIO artifacts, idempotency, and content-addressed result caching.
- Converted Streamlit to asynchronous submit/poll behavior.
- Added review and evaluation endpoints plus auditable result bundles.
- Added a production Docker Compose stack and 24-hour explicit model prompt caching.

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-26

### Added

- Initial public release of Grounded Document Parser.
- Layout-aware document parsing with PaddleOCR-VL, GLM-OCR, optional cloud verification, and a Streamlit review UI.
