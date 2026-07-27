---
type: "query"
date: "2026-07-27T08:17:10.766051+00:00"
question: "How many agents are there now, and will increasing agents and subagents improve speed while keeping accuracy?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["DocumentParser", "AgentRole", "AgentDelegation", "OpenAIDocumentGateway", "DocumentExtractor"]
---

# Q: How many agents are there now, and will increasing agents and subagents improve speed while keeping accuracy?

## Answer

Expanded via graph vocab: [agent, agentic, manager, specialist, luna, terra, delegation, inspection, repair, page, schema, extraction]. The app defines 9 logical agent identities: draft_parser, document_manager, four specialist roles, schema_architect, extractor, and extraction_critic. They are request roles, not concurrent workers. DocumentParser currently processes pages, repair rounds, and up to two delegations sequentially, so adding roles alone will not improve speed. Prefer bounded concurrency across pages and non-overlapping same-round delegations, with deterministic merge, evidence validation, rate-limit control, and unchanged Terra escalation. More overlapping agents likely increase cost and conflicts without improving accuracy.

## Outcome

- Signal: useful

## Source Nodes

- DocumentParser
- AgentRole
- AgentDelegation
- OpenAIDocumentGateway
- DocumentExtractor