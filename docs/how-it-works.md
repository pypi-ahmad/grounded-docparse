# How it works

1. The upload is size/page limited and rendered locally.
2. Pages are scheduled in ordered windows of 100, with up to 50 isolated page workers by default.
3. Luna drafts ordered typed regions and atomic evidence.
4. A Luna manager reviews the complete page manifest and chooses only the layout/text, table/form, visual, or evidence specialist needed. Delegation is capped at two specialists per round and two repair rounds.
5. Luna specialists inspect only risky targets. Deterministic code validates corrections, additions, coordinates, ordering, and evidence.
6. Completed pages are restored to source order before cross-page hierarchy, usage, traces, and exports are finalized.
7. The app emits Markdown, agentic JSON v2, legacy JSON, an agent trace, actual token totals, and an annotated PDF labeled with stable block IDs.
8. For extraction, Luna proposes an editable strict JSON Schema and extracts values plus evidence; invalid or missing evidence triggers one bounded Luna critic repair, after which unresolved values become `null` with warnings.

This is agentic because a bounded manager chooses specialist work based on document state and can adapt after feedback. It is deliberately not an open-ended autonomous loop.
