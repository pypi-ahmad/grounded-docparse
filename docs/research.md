# Research basis

Public product internals are incomplete. Design choices below use documented
behavior, not assumptions about proprietary implementations.

## LlamaParse ideas retained

- Layout-aware, agentic parsing with Markdown/JSON outputs.
- Tiered escalation: cheaper processing for simple pages, stronger reasoning for
  difficult pages.
- Granular bounding boxes, image extraction, and configurable failure tolerance.
- Sources: [Parse overview](https://developers.llamaindex.ai/llamaparse/parse/),
  [configuration](https://developers.llamaindex.ai/llamaparse/parse/guides/configuring-parse/),
  [results](https://developers.llamaindex.ai/llamaparse/parse/guides/retrieving-results),
  and [limitations](https://developers.llamaindex.ai/llamaparse/general/limitations/).

## LandingAI ADE ideas retained

- Vision-first typed chunks rather than flattened OCR text.
- Visual grounding, cell-level coordinates, confidence signals, and auditability.
- Separate parsing from downstream extraction and preserve page relationships.
- Sources: [ADE overview](https://docs.landing.ai/ade/ade-overview),
  [JSON response](https://docs.landing.ai/ade/ade-json-response), and
  [chunk types](https://docs.landing.ai/ade/ade-chunk-types).

## Improvements attempted

- Two independent local OCR paths for scanned content.
- Literal provenance and alternative candidates on every uncertain node.
- Deterministic Markdown/JSON rendering from a validated intermediate model.
- Explicit rejection of unsupported model text.
- Bounded retries and partial-page output instead of silent document failure.
- Cross-page relationships without allowing the reasoning model to rewrite text.

## Model and framework facts

- [PaddleOCR-VL 1.6](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL.md)
  uses layout analysis followed by VLM recognition and exposes ordered regions.
- [GLM-OCR](https://ollama.com/library/glm-ocr) supports document image OCR.
- [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
  and [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
  support image inputs and structured outputs.
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
  enforce schema shape, not factual correctness; evidence validation remains
  necessary.
