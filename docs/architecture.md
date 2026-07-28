# Architecture

```text
upload -> GLM-OCR layout + parallel region OCR -> deterministic draft
                                      \-> bounded Luna repair when justified
       -> deterministic validation -> Markdown + agentic JSON + annotated PDF
       -> schema proposal -> Luna extraction -> evidence validation
                                      \-> one Luna critic repair when needed
```

Streamlit runs the workflow synchronously in one local process. There is no API server, queue, worker, database, application cache, cost estimator, or artifact store.

Within that process, the parser schedules 16-page GLM-OCR windows and uses up to eight isolated page threads. GLM results stream out of order so Luna work can overlap region OCR. Page gateways share one provider-scoped runtime limiter and run budget. Worker progress is replayed on the caller thread; page results are sorted before cross-page hierarchy and final exports are built.

`ingest.py` validates inputs and renders every PDF page. It never reads embedded PDF text. `page_analysis.py` converts GLM-OCR layout and text into the initial structured draft. `gateways.py` owns strict Luna calls, usage accounting, image-scope/pixel telemetry, and the agent trace. `pipeline.py` permits one specialist and one repair round, assigns stable IDs, validates boxes and ordering, and builds the hierarchy. Luna receives localized spans, bounded context, and grounded crops. Unresolved blocks remain visible as `needs_review` and generate warnings. `extraction.py` validates editable schemas, excludes rejected audit nodes, and requires evidence for every non-null scalar. `render.py` emits agentic JSON v3.0.0, legacy JSON v2.0.0, and the annotated PDF.

Luna is not a mandatory second pass. The manager may request it only for risky targets, the deterministic quality gate may issue batches of up to eight crops, and extraction gets at most one critic repair after deterministic validation fails. GLM failure or an empty nonblank result permits a bounded full-page Luna fallback for at most 10% of pages, with a minimum allowance of one page.

Provider calls acquire the shared permit before each HTTP attempt and release it on
success, failure, timeout, or cancellation. Transient failures use bounded exponential
backoff with jitter. A 429 honors `Retry-After` when valid, records a throttle event, and
reduces effective concurrency; successful windows recover capacity gradually. Optional
run ceilings cover calls, HTTP attempts, input/output tokens,
elapsed time, and repair rounds. Exhaustion is recorded as a structured budget denial,
and affected evidence remains `needs_review` instead of continuing silently.

Routing remains evidence-driven: GLM-OCR drafts each page, deterministic checks identify
structural or literal risk, and Luna is used only for justified repair or extraction criticism. Exact low-confidence
spans use minimal context/crops where possible. Recovery blocks that repeat already
grounded content in the same location are rejected deterministically; any novel literal
keeps the recovery eligible for review. Cross-page table linking and the native-text
simple-page bypass are not present in the current implementation.

`scripts/evaluate_corpus.py` requires live visual evaluation and provides an
opt-in live mode. Live text scoring uses semantic block content rather than rendered
Markdown, counts table cells once, includes list markers, and aligns references with
explicit page breaks before edit-distance aggregation. Reports retain unavailable
grounding or rejection metrics with reasons, use dated optional rate cards, and expose
retry, throttle, budget, latency, call, token, and review telemetry. Results from the
small public/synthetic corpus are regression signals only; they are not external ADE or
LandingAI equivalence claims, and DocVQA answer rate is not extraction accuracy.

Annotation schema v1.1 distinguishes source-verified or exact synthetic references
from generated and legacy comparisons. Primary recognized-text metrics exclude
generative figure descriptions but retain literal atomic labels. The previous
`semantic_text` report field remains as a compatibility alias. Targeted live
experiments may select source pages without changing production parsing.

`DOCPARSE_TARGETED_REPAIR_CONTEXT_PADDING` is optional and disabled by default.
When set above the tight crop padding, span repair sends one additional surrounding
crop in the same Luna request. It does not widen repair eligibility, increase call
count, or authorize changes outside the supplied span.
