# Local GLM-OCR runtime

The primary app and PP-DocLayoutV3 detector run natively on Windows. GLM-OCR recognition remains a WSL2 Ubuntu 24.04 vLLM service on loopback port `8080`. Windows renders each page, detects ordered regions on CPU, and sends only grounded crops to vLLM; selectable PDF text is never OCR evidence.

```bash
bash scripts/wsl/setup-glmocr.sh

# Terminal 1
bash scripts/wsl/serve-glmocr.sh

# Windows PowerShell
.\Launch-Grounded-DocParse.cmd
```

The WSL recognition environment uses Python 3.12.10 and `vllm==0.19.1`; its virtual environment defaults to `~/.local/share/grounded-docparse/.venv`. The Windows `windows-layout` extra pins Torch/Transformers and the PP-DocLayoutV3 revision in the native cache.

The model architecture declares 131072 positions. The supported RTX 4060 profile deliberately serves 32768 because its verified 0.85 GPU allocation provides only about 62176 KV-cache tokens, insufficient for a 128K request. Cropped-region OCR stays well within 32K, including the SDK's 8192-token output allowance.

vLLM serves the pinned snapshot as `glm-ocr` on port `8080` with throughput mode, three-token MTP speculation, a 1GB multimodal cache, and 0.85 GPU-memory fraction. The server skips vLLM's synthetic multimodal startup profile to fit the WSL memory cap; the launcher therefore requires `scripts/wsl/check-glmocr-api.py` to complete a real image-recognition request. Local July 2026 measurements informed the throughput, worker, and cache defaults, but raw benchmark results are not versioned and the numbers are not hardware-independent guarantees. Reproduce a target-machine comparison with `scripts/wsl/benchmark_glmocr.py` before changing them.

The native parser defaults to:

```text
DOCPARSE_GLM_VLLM_BASE_URL=http://127.0.0.1:8080/v1
DOCPARSE_GROUNDED_OCR_TIMEOUT_SECONDS=900
DOCPARSE_LAYOUT_DETECTION_THRESHOLD=0.3
```

`GroundedOcrRuntime` preserves detector geometry, confidence, labels, and order. Recognition failure is recorded on that region rather than deleting or reordering it. Crop padding is bounded to the page, and detector-box overlap candidates are deduplicated deterministically.

Geometry remains PP-DocLayout-owned. Textual detector regions are sent through GLM recognition; pure chart/image regions can remain non-text evidence. AI enhancement cannot change detector geometry or order.

For a live GLM-only regression run, activate the setup-created WSL environment, disable AI-provider processing explicitly, and retain candidate/provenance artifacts:

```bash
source "${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}/bin/activate"
python scripts/evaluate_corpus.py --live --glm-only \
  --document synthetic-report \
  --artifacts-dir output/synthetic-report-glm-only \
  --output output/synthetic-report-glm-only.eval.json
```

`--glm-only` disables AI recovery, Markdown refinement, and extraction, then fails the run if AI-provider usage, time, or recovery entries are present.

Analysis thresholds use `DOCPARSE_ANALYSIS_<FIELD>`. Ratio thresholds use rendered page area; blur/contrast checks use edge variance and grayscale range; effective-resolution checks use known DPI or the rendered short edge; skew uses layout polygon baselines. Defaults live in `AnalysisThresholds` in `src/grounded_docparse/config.py`.
