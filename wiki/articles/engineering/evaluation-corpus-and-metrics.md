---
tags: evaluation, corpus, metrics
sources: src/grounded_docparse/benchmark.py, src/grounded_docparse/usage_costs.py, benchmarks/rate-cards/openai-standard-2026-09-23.json, benchmarks/corpus-v1/manifest.json, benchmarks/schemas/annotation-v1.1.schema.json, scripts/generate_evaluation_corpus.py
snapshot: content-0117589c51ef
status: working-tree
---

# Evaluation corpus and metrics

The evaluation corpus records document fixtures, processing expectations, annotations, and regression policy inputs. Native fixtures extend that corpus with source anchors, exact text intervals, route expectations, and format-specific evidence.

Evaluation should distinguish routing correctness from extraction quality. Native, scanned, and mixed fixtures must reach their selected pipelines without fallback; accepted extracted values must match exact source substrings and resolve to anchors.

See [[grounding-and-evidence-contract]], [[ocr-quality-and-recovery]], and [[testing-strategy]].

## Current working-tree cost changes

`live_telemetry_record` includes per-request `usage_calls` as well as aggregate `model_usage`. `summarize_telemetry` checks their agreement and uses `estimate_call_cost` to apply cache-read, cache-write, and long-context rates before aggregation. Sol evaluations use `benchmarks/rate-cards/openai-standard-2026-09-23.json`.

Sol aggregate records without request-level usage cannot produce `cost_per_page`. Unavailable usage, inconsistent totals, and missing required rates also produce a null cost with `cost_unavailable_reason`. Historical rate cards and older non-Sol aggregate records remain supported.

## Evidence

Benchmark models and reporting live in `src/grounded_docparse/benchmark.py`; corpus metadata and contracts live under `benchmarks/`; deterministic fixture generation is in `scripts/generate_evaluation_corpus.py`.
