---
type: "query"
date: "2026-07-27T08:18:50.772500+00:00"
question: "Can every page be processed in parallel in batches of 20 for a 100-page PDF?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["DocumentParser", "Page", "PageEvidence", "OpenAIDocumentGateway"]
---

# Q: Can every page be processed in parallel in batches of 20 for a 100-page PDF?

## Answer

Expanded via graph vocab: [page, batch, document, evidence, gateway, hierarchy, ingest, inspection, order, parser]. Yes, page-local drafting and verification can run concurrently in 20-page windows, but batch size should be separate from API concurrency. Recommended: ingest once; schedule pages 1-20 with a semaphore initially allowing 5 concurrent page workers; keep each page's draft, manager, specialist repairs, and crop checks sequential; collect results by page number; then perform document hierarchy/order finalization deterministically; continue with pages 21-40. Use isolated per-page gateway state or synchronized usage/trace aggregation, per-page retries, and rate-limit backoff. This preserves accuracy while improving throughput.

## Outcome

- Signal: useful

## Source Nodes

- DocumentParser
- Page
- PageEvidence
- OpenAIDocumentGateway