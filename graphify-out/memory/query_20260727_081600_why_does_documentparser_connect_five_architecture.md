---
type: "query"
date: "2026-07-27T08:16:00.365561+00:00"
question: "Why does DocumentParser connect five architecture communities?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["DocumentParser", "Document", "OpenAIDocumentGateway", "Block", "RunUsage", "DocumentExtractor", "ingest_document"]
---

# Q: Why does DocumentParser connect five architecture communities?

## Answer

Expanded from original query via graph vocab: [document, parser, model, benchmark, gateway, openai, schema, extraction, ingest, evidence, pipeline, config]. DocumentParser is the orchestration bridge. It is contained in pipeline.py, which imports ingest_document (EXTRACTED); it uses Document and OpenAIDocumentGateway (INFERRED); it reaches benchmark.py through the shared Block model; and reaches DocumentExtractor through shared RunUsage. The structural ingestion edge is strongest; uses edges are architectural inferences rather than proven runtime calls.

## Outcome

- Signal: useful

## Source Nodes

- DocumentParser
- Document
- OpenAIDocumentGateway
- Block
- RunUsage
- DocumentExtractor
- ingest_document