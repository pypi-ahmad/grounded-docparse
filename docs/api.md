# Python API

The package requires Python 3.12–3.14. Install the locked project environment with `uv sync --locked`. Actual parsing also requires a running GLM-OCR or PaddleOCR-VL-1.6 stack described in [setup](../SETUP.md).

## Exported names

`grounded_docparse.__all__` exports:

```text
AgenticAnalysis
ChatAnswer
ChatSource
ClassifierCategory
ClassifierProfile
Document
DocumentAgent
DocumentExtractor
DocumentParser
Element
EnhancementMetadata
ExtractionResult
FormClassificationResult
FormSegment
ParseMetadata
ParseResult
OcrEngine
ParserConfig
PreparedDocumentContext
SchemaProposal
RoutedExtractionResult
SegmentExtraction
StoredSchema
VisualRecoveryResult
render_combined_result
```

## Parsing

```text
DocumentParser(config: ParserConfig | None = None, *, gateway_factory=OpenAIDocumentGateway)

DocumentParser.parse(
    data: bytes,
    filename: str,
    progress_callback: ProgressCallback | None = None,
    *,
    refine_markdown: bool = True,
    visual_recovery: bool = True,
) -> ParseResult
```

```python
from pathlib import Path

from grounded_docparse import DocumentParser

source = Path("invoice.pdf")
result = DocumentParser().parse(
    source.read_bytes(),
    source.name,
    refine_markdown=False,
    visual_recovery=True,
)
```

`filename` must end in `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, or `.tiff`. Input validation raises `ValueError` for empty, oversized, invalid, unsupported, password-protected, over-page-limit, or over-pixel-limit input. If at least one page is nonblank and none of the nonblank pages contains a local OCR layout region, the default parser raises `RuntimeError`. Optional Luna failures otherwise fall back to the successful local OCR result or feature warning/status.

The Python parse API has no page-range argument. Slice a PDF before calling it or use the Streamlit range control.

`ProgressCallback` is the structural type `Callable[[ProgressEvent], None]`. `ProgressEvent` has `stage: str`, `current: int`, `total: int`, and `message: str`. These annotation helpers live in `grounded_docparse.models` but are not package-root exports. Worker events are replayed on the caller thread. Callbacks should return quickly and should not raise.

`ParseResult` is a dataclass containing:

```text
document: Document
markdown: str
json: str
input_tokens: int
output_tokens: int
annotated_pdf: bytes
base_markdown: str
usage: RunUsage | None
trace: list[AgentTraceEvent] | None
runtime_diagnostics: RuntimeDiagnostics | None
elements: list[Element]
metadata: ParseMetadata
recovery_log: list[VisualRecoveryResult]
```

`result.structured_json` parses `result.json` and returns a `dict`.

`RunUsage`, `AgentTraceEvent`, and `RuntimeDiagnostics` are nested Pydantic records from `grounded_docparse.models`, not package-root exports. `RunUsage` holds per-call agent/model token counts and computed totals. A trace event records agent, model, action, status, optional page/target IDs, duration, token/image metrics, repair round, prompt version, reasoning effort, and optional summary. Runtime diagnostics records model/HTTP call counts, retries, token totals, rate-limit and concurrency state, cooldown time, elapsed time, and wait/sleep durations. Treat their presence as diagnostic data rather than a stable direct-import API.

## Agentic features

`DocumentAgent` accepts the same optional `config` and keyword-only `gateway_factory` constructor arguments as `DocumentParser`.

```text
DocumentAgent(config: ParserConfig | None = None, *, gateway_factory=OpenAIDocumentGateway)
DocumentAgent.prepare(parse_result: ParseResult) -> PreparedDocumentContext
DocumentAgent.analyze(
    parse_result: ParseResult,
    *,
    classify: bool = True,
    generate_toc: bool = True,
    prepared_context: PreparedDocumentContext | None = None,
) -> AgenticAnalysis
DocumentAgent.extract(
    parse_result: ParseResult,
    schema: dict[str, Any],
    *,
    prepared_context: PreparedDocumentContext | None = None,
) -> ExtractionResult
DocumentAgent.classify_forms(
    parse_result: ParseResult,
    profile: ClassifierProfile,
    *,
    prepared_context: PreparedDocumentContext | None = None,
    confidence_threshold: float = 0.85,
) -> FormClassificationResult
DocumentAgent.extract_forms(
    parse_result: ParseResult,
    classification: FormClassificationResult,
    schemas_by_name: Mapping[str, dict[str, Any]],
) -> RoutedExtractionResult
DocumentAgent.chat(
    parse_result: ParseResult,
    question: str,
    history: list[dict[str, str]],
    *,
    prepared_context: PreparedDocumentContext | None = None,
) -> ChatAnswer
```

```python
from grounded_docparse import DocumentAgent

agent = DocumentAgent()
schema = {
    "type": "object",
    "properties": {
        "total": {
            "type": ["number", "null"],
            "description": "Final amount payable",
        }
    },
    "required": ["total"],
    "additionalProperties": False,
}
prepared = agent.prepare(result)  # -> PreparedDocumentContext

analysis = agent.analyze(
    result,
    classify=True,
    generate_toc=True,
    prepared_context=prepared,
)  # -> AgenticAnalysis

extraction = agent.extract(
    result,
    schema,
    prepared_context=prepared,
)  # -> ExtractionResult

answer = agent.chat(
    result,
    "What is the total?",
    history=[
        {"role": "user", "content": "Who issued this?"},
        {"role": "assistant", "content": "Example Corp."},
    ],
    prepared_context=prepared,
)  # -> ChatAnswer
```

`history` is required and may be an empty list. Only the last eight user/assistant turn pairs are sent. `DocumentAgent.extract` always enables deterministic inferred grounding after the evidence-repair attempt; use direct `DocumentExtractor.extract(..., allow_inferred=False)` when unresolved leaves must become `null` instead.

`AgenticAnalysis` contains optional `classification`, optional `toc`, per-feature status metadata, usage, and trace. `DocumentAgent.classify_forms` accepts a `ClassifierProfile` and returns grounded contiguous `FormSegment` records. `DocumentAgent.extract_forms` accepts reviewed routing plus compiled schemas by saved name and returns per-segment results; ineligible segments are never extracted.

## Direct schema proposal and extraction

`DocumentExtractor` accepts optional `config` and keyword-only `gateway_factory` arguments.

```text
DocumentExtractor(config: ParserConfig | None = None, *, gateway_factory=OpenAIDocumentGateway)
DocumentExtractor.propose_schema(instruction: str, parse_result: ParseResult) -> SchemaProposal
DocumentExtractor.extract(
    parse_result: ParseResult,
    schema: dict[str, Any],
    *,
    allow_inferred: bool = False,
) -> ExtractionResult
```

```python
from grounded_docparse import DocumentExtractor

extractor = DocumentExtractor()
proposal = extractor.propose_schema("Extract invoice number and total", result)
extraction = extractor.extract(result, proposal.json_schema)
```

The root schema must be an object. Every property is required but accepts `null`, every object sets `additionalProperties: false`, and arrays declare `items`. Supported non-null types are `object`, `array`, `string`, `number`, `integer`, and `boolean`. The caller contract uses only `type`, `enum`, `properties`, `required`, `items`, `additionalProperties`, and `description`. Validation explicitly rejects `allOf`, `not`, `dependentRequired`, `dependentSchemas`, `if`, `then`, `else`, `patternProperties`, `pattern`, `minLength`, `maxLength`, `minimum`, `maximum`, `multipleOf`, `minItems`, and `maxItems`.

`DocumentAgent.extract` partitions and merges long-document extraction only for scalar root properties. A schema containing nested objects or arrays follows the direct `DocumentExtractor` path and is not split and merged by page context.

The Streamlit schema builder intentionally exposes only scalar `string`, `number`, `integer`, `boolean`, and `date` fields. `date` compiles to a nullable string with an ISO 8601 instruction.

Schema import/export uses the `StoredSchema` shape, not compiled JSON Schema:

```json
{
  "version": 1,
  "name": "Invoice",
  "fields": [
    {
      "name": "invoice_number",
      "description": "Official invoice ID",
      "type": "string"
    }
  ]
}
```

Names contain 1–100 characters. Each field name matches `^[A-Za-z_][A-Za-z0-9_]*$`, field names are unique case-insensitively, and at least one field is required.

`ExtractionResult` is a dataclass with `data`, evidence by JSON Pointer, serialized `json`, warnings, token counts, usage, trace, and top-level `fields`. Field confidence is `high`, `medium`, `inferred`, or `not_found`.

## Exported result models

The most frequently consumed exported models have these fields:

| Model | Fields |
| --- | --- |
| `Element` | `id`, `type`, `page`, normalized `bbox`, `text`, one-based `reading_order`, optional OCR `confidence`, `source` (`glm-ocr`, `paddleocr-vl-1.6`, or `luna-recovery`) |
| `ChatSource` | `element_id`, `page`, `text` |
| `ChatAnswer` | `answer`, `sources`, `confidence` (`high`, `medium`, `low`), `usage`, `trace` |
| `SchemaProposal` | `instruction`, `json_schema`, `usage` |
| `StoredSchema` | `version` (`1`), `name`, `fields` |
| `VisualRecoveryResult` | `region_id`, `page`, `original_element_id`, `status` (`recovered`), `recovered_text`, `confidence`, `notes` |
| `EnhancementMetadata` | `enabled`, `status`, `model`, chunk totals, warnings |
| `AgenticAnalysis` | optional `classification`, optional `toc`, `features`, `usage`, `trace` |
| `ExtractionResult` | `data`, `evidence`, `json`, `warnings`, token counts, `usage`, `trace`, `fields` |
| `ParseResult` | domain document, both Markdown forms, JSON string, token counts, PDF bytes, usage, trace, runtime diagnostics, elements, metadata, recovery log |

Pydantic models reject unknown fields. Verification values inside the domain tree are `not_checked`, `verified`, `rejected`, or `needs_review`; agentic feature status is `off`, `unavailable`, `succeeded`, `partial`, or `failed`.

## Combined JSON

```text
render_combined_result(
    parse_result: ParseResult,
    analysis: AgenticAnalysis | None = None,
    extraction: ExtractionResult | None = None,
    *,
    custom_classification: FormClassificationResult | None = None,
    routed_extraction: RoutedExtractionResult | None = None,
) -> str
```

```python
from grounded_docparse import render_combined_result

full_json = render_combined_result(
    result,
    analysis=analysis,
    extraction=extraction,
)
```

The returned string is Full JSON v4.5.0 (parse JSON remains v4.4.0):

```json
{
  "schema_version": "4.5.0",
  "markdown": "...",
  "base_markdown": "...",
  "document_type": null,
  "sections": [],
  "extracted_fields": {},
  "custom_classification": null,
  "form_extractions": [],
  "recovery_log": [],
  "metadata": {},
  "elements": [],
  "document": {"id": "document", "pages": []}
}
```

`render_combined_result` fills the three optional agentic fields and merges their usage, trace, timing, and status into metadata. Markdown source spans use Unicode-codepoint offsets into `base_markdown`. Element boxes are normalized `[x0, y0, x1, y1]` coordinates in `[0, 1]`. Annotated PDF bytes remain in `ParseResult.annotated_pdf`, outside JSON.

Extraction serialization uses schema version `1.1.0`:

```json
{
  "schema_version": "1.1.0",
  "schema": {},
  "data": {},
  "evidence": {},
  "fields": {},
  "warnings": [],
  "metadata": {"usage": {}, "trace": []}
}
```

These examples define the stable top-level envelopes, not complete JSON Schemas for every nested domain object. The repository currently publishes no standalone JSON Schema for Full JSON v4.5.0, extraction v1.1.0, or routed extraction v2.0.0; the Pydantic models and named versions are authoritative.

## Configuration and test doubles

Pass an explicit `ParserConfig` to override environment-derived settings. Otherwise constructors call `ParserConfig.from_env()`. `DOCPARSE_LOCAL_OCR_ENABLED` treats `0`, `false`, and `no` as false and every other value as true. Invalid numeric values or invalid bounds fail during configuration construction.

`gateway_factory` is a test/compatibility seam rather than a published protocol. The constructor signatures show its internal `OpenAIDocumentGateway` default for fidelity; normal callers should omit this argument. A custom factory receives `ParserConfig` and must provide the methods exercised by the selected workflow, so requirements depend on enabled features. The package does not promise thread-safe reuse of parser/agent instances; create them per workflow. The process-wide `GlmOcrRuntime` serializes SDK model access.

See [setup](../SETUP.md) for environment variables and [architecture](architecture.md) for ownership and failure rules.
