# Research Basis

Grounded Document Parser is an independent implementation. It does not call LlamaParse or LandingAI ADE and does not claim access to their proprietary internals. The comparisons below describe ideas visible in public documentation as of July 26, 2026.

## LlamaParse ideas retained

Current LlamaParse documentation describes an agentic, layout-aware parser for PDFs, scans, tables, and charts with Markdown, text, and JSON outputs. Relevant design ideas are:

- perform structural parsing upstream instead of repeatedly sending raw documents downstream;
- provide cost/quality tiers and bounded processing controls;
- preserve Markdown, structured items, metadata, images, and granular bounding boxes;
- cache identical requests while invalidating on option changes; and
- split oversized extraction work into smaller, targeted jobs.

Grounded Document Parser adopts the general principles of tiered processing, structured results, granular grounding, caching, and explicit failure handling. Its profiles, schemas, providers, and wire formats are unrelated implementations.

Sources:

- [LlamaParse overview](https://developers.llamaindex.ai/llamaparse/parse/)
- [Configuring Parse](https://developers.llamaindex.ai/llamaparse/parse/guides/configuring-parse/)
- [Retrieving results](https://developers.llamaindex.ai/llamaparse/parse/guides/retrieving-results/)
- [Service limitations](https://developers.llamaindex.ai/llamaparse/general/limitations/)

## LandingAI ADE ideas retained

LandingAI ADE documentation separates Parse, Extract, Classify, Section, and Split. Its Parse response includes Markdown, typed chunks, splits, grounding, and metadata; grounding connects chunk IDs to page coordinates.

Relevant design ideas are:

- represent text, tables, figures, form fields, and marginalia as typed regions;
- keep complete Markdown and structured chunks together;
- preserve reading order and hierarchical relationships;
- attach page and coordinate grounding for traceability;
- separate parsing from schema extraction, classification, sectioning, and splitting; and
- retain stable identifiers across content and grounding structures.

Grounded Document Parser uses its own Pydantic node types, citation model, hierarchy, verification states, and segmentation logic.

Sources:

- [ADE overview](https://docs.landing.ai/ade/ade-overview)
- [Parse JSON response](https://docs.landing.ai/ade/ade-json-response)
- [Chunk types](https://docs.landing.ai/ade/ade-chunk-types)

## OpenAI implementation basis

The production path uses the OpenAI Responses API through the official Python SDK:

- [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) is assigned the high-volume page-draft role.
- [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) is assigned the stronger visual-inspection role.
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) provide schema adherence through Pydantic-backed `responses.parse` calls.
- [Vision inputs](https://developers.openai.com/api/docs/guides/images-vision) carry full pages and selected source crops.
- [Reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning) supports low reasoning effort for bounded extraction decisions.
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) rewards exact reusable prefixes and stable cache keys.

Structured Outputs constrain shape, not factual correctness. A schema-valid transcription can still disagree with the image. Terra inspection, crop evidence, deterministic ID checks, and fail-closed exports address that separate risk.

## Prompt-cache correction

Earlier project documentation claimed 24-hour explicit retention for every GPT-5.6 request. Current OpenAI documentation distinguishes:

- `prompt_cache_key`, which improves routing and matching for repeated exact prefixes;
- GPT-5.6 `prompt_cache_options`, whose documented TTL currently defaults to and only supports a 30-minute minimum; and
- legacy `prompt_cache_retention`, which is deprecated for GPT-5.6 and later.

The current gateway still sends `prompt_cache_retention="24h"`. Documentation therefore describes stable cache keys but does not promise 24-hour retention. Migrating the gateway is a code change outside this documentation refresh.

## Project-specific design additions

The repository adds implementation choices that are not claims about either inspiration source:

- independent Terra inspection of Luna drafts;
- high-resolution rerendering from the original source rather than enlarged page screenshots;
- crop SHA-256 hashes alongside normalized, pixel, and PDF boxes;
- explicit verification states and fail-closed strict exports;
- deterministic document-tree construction after model calls;
- durable API jobs and separate realtime/batch Celery queues;
- content-addressed result reuse;
- corrected-tree evaluation across text, layout, hierarchy, citations, fields, tables, and forms; and
- human-review artifacts kept separate from model output.

## Accuracy and comparability

Vendor metrics are not directly comparable with this project. Dataset, metric definition, preprocessing, document mix, provider version, and post-processing all affect results.

This repository currently proves contract behavior with synthetic fixtures and fake providers. It does not publish a DocVQA score, field-level benchmark, cost curve, latency distribution, or million-page load result. Any production claim should be based on the repository's evaluation format and a representative labeled corpus.

## Research update policy

When changing provider behavior or research claims:

1. verify the current official source;
2. record the access date or release context when facts are time-sensitive;
3. distinguish public behavior from inference;
4. avoid copying vendor marketing claims into project guarantees; and
5. update implementation documentation and tests together when the actual contract changes.
