---
tags: evaluation, corpus, metrics
sources: src/grounded_docparse/benchmark.py, benchmarks/corpus-v1/manifest.json, benchmarks/schemas/annotation-v1.1.schema.json, scripts/generate_evaluation_corpus.py
snapshot: content-6684c0091b62
status: feature-branch
---

# Evaluation corpus and metrics

The evaluation corpus records document fixtures, processing expectations, annotations, and regression policy inputs. Native fixtures extend that corpus with source anchors, exact text intervals, route expectations, and format-specific evidence.

Evaluation should distinguish routing correctness from extraction quality. Native, scanned, and mixed fixtures must reach their selected pipelines without fallback; accepted extracted values must match exact source substrings and resolve to anchors.

See [[grounding-and-evidence-contract]], [[ocr-quality-and-recovery]], and [[testing-strategy]].

## Evidence

Benchmark models and reporting live in `src/grounded_docparse/benchmark.py`; corpus metadata and contracts live under `benchmarks/`; deterministic fixture generation is in `scripts/generate_evaluation_corpus.py`.
