---
type: "query"
date: "2026-07-30T15:48:07.129133+00:00"
question: "Why does load_corpus_manifest() connect Evaluation Benchmarking to Source Artifact Schema and Evaluation Corpus Models?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["load_corpus_manifest()", "manifest-v1.schema.json", "CorpusManifest", "CorpusAnnotation", "CorpusDocument", "CorpusSource", "_live_report()", "evaluate_live_document()", "build_live_report()"]
---

# Q: Why does load_corpus_manifest() connect Evaluation Benchmarking to Source Artifact Schema and Evaluation Corpus Models?

## Answer

Expanded from the original query with graph vocabulary: [load, corpus, manifest, evaluation, source, schema, annotation, metrics, generated, reference, document]. `load_corpus_manifest()` adapts declarative corpus artifacts for benchmark execution. The graph traces `manifest-v1.schema.json` through documents/items/source/path to `load_corpus_manifest()`. The loader directly references `CorpusManifest` and `CorpusAnnotation`; `CorpusDocument` and `CorpusSource` share its `benchmark.py` module; and `_live_report()` calls the loader, `evaluate_live_document()`, and `build_live_report()`. Schema-shaped local sources and annotations become typed corpus models before benchmark metrics run. Tests connected to the loader cover local source and annotation validation, unsafe or inconsistent files, duplicate IDs, duplicate anchors, and reference provenance. The graph has no path from the loader to `annotation-v1.1.schema.json`, so it does not establish direct runtime validation against that JSON Schema.

## Outcome

- Signal: useful

## Source Nodes

- load_corpus_manifest()
- manifest-v1.schema.json
- CorpusManifest
- CorpusAnnotation
- CorpusDocument
- CorpusSource
- _live_report()
- evaluate_live_document()
- build_live_report()
