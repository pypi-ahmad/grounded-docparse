# Extraction quality research

## Scope and interpretation

The July 2026 app runs completed all 41 Masked Amerigroup pages and all eight
Public Water pages. Their reported word accuracies (71.61% and 82.40%) measure
agreement with supplied Markdown references, not independently verified source
accuracy. The Amerigroup reference records a LandingAI ADE model version and
contains generated artifacts, including a numeric sequence that is not visible
on page 8. Public Water's reference also appears model-generated. These values
remain useful regression diagnostics but do not establish production accuracy or
equivalence with ADE, LandingAI, or another benchmark.

No Amerigroup source text or document content belongs in the repository. Reports
may retain aggregate metrics and page numbers only.

## Findings

- Public Water pages 4–6 mix literal OCR with generative figure prose. Page 4's
  output is longer than the reference while retaining most reference tokens, so
  strict WER penalizes description style. Page 6's expected visual facts are
  present in atomic visual labels but were invisible to the legacy evaluator.
- Public Water page 4 previously required `Order # 984` inside the barcode visual
  even though the parser correctly represented it as nearby text. Barcode
  detection and nearby literal extraction are separate contracts.
- Amerigroup page 32 contains a full-page recovery that repeats already grounded
  nested content. After Unicode and punctuation normalization, the two copies
  have identical word tokens. This is a deterministic hierarchy/deduplication
  defect, not an OCR-model limitation.
- Amerigroup pages 3–4 contain small rotated card images. Targeted crops can help
  model perception, but the source raster is only roughly 128–155 effective DPI;
  rendering at 450 DPI mostly upsamples existing pixels.
- Amerigroup page 11 is severely degraded. Correct behavior is explicit review or
  unresolved evidence, not agreement with asserted reference values.
- The historical runs used 372 model calls and 116 repair calls without retries or throttles.
  Increasing calls or concurrency is therefore not the first accuracy lever.

## Evaluation policy

Corpus annotation v1.1 records a reference basis. Only `source_verified` and
`synthetic_exact` references populate primary text metrics. Generated references
populate `legacy_reference_agreement`; the existing `semantic_text`
field remains as a compatibility alias. Figure descriptions are excluded from
recognized-text scoring, while literal visual atoms remain eligible. Public Water
pages 4–6 use source-checked literal anchors rather than an invented full-page
transcription.

This follows the separation used by
[OmniDocBench](https://arxiv.org/abs/2412.07626), which evaluates text, reading
order, tables, and layout separately and does not treat generative figure prose as
text-recognition ground truth. Table structure should continue to use a structural
metric such as [TEDS](https://arxiv.org/abs/1911.10683), not WER alone.

## Changes and experiments

1. Search atomic visual labels during source-anchor validation and test barcode
   presence separately from nearby order text.
2. Compare recovery blocks with spatially overlapping nested descendants before
   accepting them. Suppress only normalized, order-preserving duplicates; preserve
   novel critical literals and text at distinct locations.
3. Test a tight span crop plus one larger context crop in the same Luna call without
   sending the whole page or permitting adjacent-text replacement.

The crop experiment is motivated by coarse-to-fine document parsing research
([Cui et al., CVPR 2026](https://arxiv.org/abs/2603.24326)) and
[OpenAI's image-input guidance](https://help.openai.com/en/articles/8400551-image-inputs-for-chatgpt-faq)
to enlarge text without cropping away relevant context. The experiment was removed
after it failed the promotion gates below; production always sends the tight crop.

### July 2026 targeted result

Three live A/B runs of Public Water source pages 4–6 did not justify enabling the
context crop. Median source-checked anchor coverage increased from 95.24% to 100%,
but generated-reference word agreement decreased from 72.10% to 69.28%, insertion
diagnostics increased from 5.29% to 7.32%, and median calls increased from 18 to 19.
Median latency increased from 131.96 seconds to 134.45 seconds. The generated
reference metrics are diagnostic rather than ground truth, but the hallucination
and call-count gates independently failed, so the option was removed.

An isolated live parse of local Amerigroup source page 32 emitted one copy of the
two diagnostic phrases used to detect the prior full-page duplication. This is a
targeted regression observation, not a document-wide accuracy result.

## Acceptance and limitations

Targeted A/B evaluation uses Public Water pages 4–6 and local Amerigroup pages 3,
4, 11, and 32. A candidate context setting must fix at least one verified literal,
keep all source-verified metrics non-regressing, leave illegible page 11 in review,
add no forbidden literals, keep call counts unchanged, and stay within the
configured 10% median-latency allowance. One complete run of each document follows
only after those gates pass.

Three-page anchor coverage and one private local document are regression evidence,
not a representative production benchmark. DocVQA answer rate is not character,
field, table-cell, or grounding accuracy.
