# Private confidence calibration and regression evaluation

The bundled corpus is useful for deterministic regressions. It is not broad
accuracy evidence. Use source-verified private documents that represent the
actual operating population before choosing a confidence threshold or making a
production claim.

## Keep two external sets

Store the private corpus outside this repository under one user-controlled root:

```text
D:\secure-docparse-evaluation\
├── calibration\
│   ├── manifest.json
│   ├── documents\
│   └── annotations\
└── holdout\
    ├── manifest.json
    ├── documents\
    └── annotations\
```

Use the calibration set to choose the operational review threshold. Freeze the
holdout set and use it only for regression decisions. The two sets must not
share source documents, templates, near-duplicates, customers, or generated
variants of the same document.

Each set should cover every document type used in production and the important
layout, language, scanner, image-quality, page-count, and source-system strata.
Record those strata in each corpus entry's existing `features` list. Use opaque
document IDs and independently verify `expected_document_type` against one of:
`Invoice`, `Contract`, `Bank Statement`, `Report`, `Form`, `Certificate`,
`Letter`, or `Other`. A manifest using this field has `schema_version` `1.1`;
the evaluator continues to accept unlabeled v1.0 manifests.

```json
{
  "id": "private-0001",
  "source": {
    "kind": "local",
    "path": "calibration/documents/private-0001.pdf",
    "sha256": "<64 lowercase hexadecimal characters>"
  },
  "annotation_path": "calibration/annotations/private-0001.json",
  "features": ["scanner-a", "degraded-scan", "english"],
  "synthetic": false,
  "expected_document_type": "Invoice"
}
```

Documents without `expected_document_type` still receive parse/OCR evaluation,
but they are excluded from classification and calibration scores. Reports expose
labeled, unlabeled, and scored counts so a regression policy can reject
insufficient coverage.

## Calibrate the review threshold

Run the calibration manifest at candidate thresholds. Confidence below the
threshold requires review; the default is `0.85`.

```powershell
uv run python scripts/evaluate_corpus.py --live `
  --repository-root D:\secure-docparse-evaluation `
  --manifest D:\secure-docparse-evaluation\calibration\manifest.json `
  --review-threshold 0.85 `
  --output D:\secure-docparse-evaluation\reports\calibration.json
```

Compare classification accuracy, macro F1, the confusion matrix, ten-bin
expected calibration error, top-label Brier score, review rate, and
auto-approved accuracy. Select the threshold using the calibration set only.
Do not tune it against holdout results.

## Gate the locked holdout set

Capture an accepted holdout report as the baseline. On later runs, apply a
policy containing absolute bounds and permitted deterioration:

```powershell
uv run python scripts/evaluate_corpus.py --live `
  --repository-root D:\secure-docparse-evaluation `
  --manifest D:\secure-docparse-evaluation\holdout\manifest.json `
  --review-threshold 0.85 `
  --thresholds benchmarks\policies\live-evaluation.example.json `
  --baseline D:\secure-docparse-evaluation\reports\holdout-baseline.json `
  --output D:\secure-docparse-evaluation\reports\holdout-candidate.json
```

Policy paths are JSON Pointers into the candidate report. A rule may specify an
absolute `minimum`, `maximum`, `max_regression`, or a combination. Baseline
comparisons require matching corpus IDs, evaluation modes, and review
thresholds. Missing or nonnumeric required metrics fail closed. The report is
written with rule-by-rule evidence before the process returns exit code `1`.

Tune the example policy to the approved calibration and holdout evidence; its
sample values are not production guarantees.

## Privacy boundary

Do not commit private PDFs, annotations, manifests, reports, or artifacts.
Evaluation reports omit source paths and document content, but contain document
IDs; keep those IDs opaque. `--artifacts-dir` writes candidate Markdown and
parse JSON containing document content, so use it only inside an approved secure
location with the required retention controls.
