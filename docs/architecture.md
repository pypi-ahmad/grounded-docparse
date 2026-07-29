# Architecture

```text
upload -> GLM-OCR layout + parallel region OCR -> deterministic draft
                                      \-> bounded Luna visual recovery when justified
       -> deterministic validation -> grounded base Markdown + annotated PDF
       -> optional text-only Luna presentation plan -> refined Markdown + JSON v4.4
       -> parallel Luna classification + TOC generation
       -> on-demand grounded extraction / optional cited chat
```

Streamlit runs the workflow synchronously in one local process. There is no API server, queue, worker, application cache, cost estimator, or artifact store. A small SQLite database at `data/document_studio.sqlite3` stores reusable extraction schemas only.

Within that process, the parser schedules 16-page GLM-OCR windows and uses up to eight isolated page threads. Once GLM finishes, document-wide recovery candidates are ranked before page work starts. Page gateways share one provider-scoped runtime limiter. Worker progress is replayed on the caller thread; page results are sorted before cross-page hierarchy and final exports are built.

`ingest.py` validates inputs and renders every PDF page. It never reads embedded PDF text. `page_analysis.py` converts GLM-OCR layout and text into the initial structured draft. `gateways.py` owns strict Luna recovery and structured agentic calls. `agentic.py` builds compact contexts and runs classification, TOC, extraction, and chat without images. `pipeline.py` ranks recovery candidates, validates recovery decisions, assigns stable IDs, and builds the hierarchy. `base_markdown` remains the grounded evidence surface. Luna refinement returns only presentation directives keyed by existing IDs. `render.py` emits flat JSON v4.4 and annotations; PDF bytes remain a separate artifact.

Luna is not a mandatory second pass. The parser ranks broken tables, actual OCR confidence below 0.55, empty large GLM regions, low character density, and high garbage ratio across the document. It sends at most eight recovery requests by default and at most three region crops per page. Only corrections with confidence at or above 0.85 are applied, and only textual fields may change. Luna cannot add elements, reject GLM elements, or change geometry, type, confidence, reading order, or structure. Image requests use high reasoning effort; text-only requests use medium. Extraction gets at most one critic repair after deterministic validation fails. If all nonblank pages contain no usable GLM elements, the parser fails before recovery and agentic stages; isolated failed pages remain partial with warnings.

Provider calls acquire the shared permit before each HTTP attempt and release it on
success, failure, timeout, or cancellation. Transient failures use bounded exponential
backoff with jitter. A 429 honors `Retry-After` when valid, records a throttle event, and
reduces effective concurrency; successful windows recover capacity gradually.

Routing remains evidence-driven: GLM-OCR drafts each page, deterministic checks identify
structural or literal risk, and Luna is used only for justified repair or extraction criticism. Exact low-confidence
spans use minimal context/crops where possible. Cross-page table linking is not present in the
current implementation; selectable PDF text is never parser evidence.

`scripts/evaluate_corpus.py` requires live visual evaluation and provides an
opt-in live mode. Live text scoring uses semantic block content rather than rendered
Markdown, counts table cells once, includes list markers, and aligns references with
explicit page breaks before edit-distance aggregation. Reports retain unavailable
grounding or rejection metrics with reasons, use dated optional rate cards, and expose
retry, throttle, latency, call, token, and review telemetry. Results from the
small public/synthetic corpus are regression signals only; they are not external ADE or
LandingAI equivalence claims, and DocVQA answer rate is not extraction accuracy.

Annotation schema v1.1 distinguishes source-verified or exact synthetic references
from generated comparisons. Primary recognized-text metrics exclude
generative figure descriptions but retain literal atomic labels. The previous
`semantic_text` report field remains as a compatibility alias. Targeted live
experiments may select source pages without changing production parsing.
