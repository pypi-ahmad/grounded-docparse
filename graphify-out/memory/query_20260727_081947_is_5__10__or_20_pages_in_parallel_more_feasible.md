---
type: "query"
date: "2026-07-27T08:19:47.289027+00:00"
question: "Is 5, 10, or 20 pages in parallel more feasible?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["DocumentParser", "OpenAIDocumentGateway", "PageInspection", "ParserConfig"]
---

# Q: Is 5, 10, or 20 pages in parallel more feasible?

## Answer

Use 5 concurrent pages as the production default, with a 20-page scheduling window. Each page may trigger draft, manager, up to four specialist inspections across two repair rounds, and crop verification, so 10 or 20 page workers multiply API pressure and image memory substantially. Benchmark 10 only after measuring rate-limit errors, p95 latency, memory, token usage, and grounding accuracy. Do not use 20 concurrent pages initially; reserve 20 for queue/window size.

## Outcome

- Signal: useful

## Source Nodes

- DocumentParser
- OpenAIDocumentGateway
- PageInspection
- ParserConfig