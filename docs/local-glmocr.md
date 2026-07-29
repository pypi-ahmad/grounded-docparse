# Local GLM-OCR runtime

The supported parser runtime is WSL2 Ubuntu 24.04. Recognition uses GLM-OCR; PP-DocLayout-V3 is its layout stage. PDF pages are always rendered to images, and selectable PDF text is never read as evidence.

```bash
bash scripts/wsl/setup-glmocr.sh

# Terminal 1
bash scripts/wsl/serve-glmocr.sh

# Terminal 2
bash scripts/wsl/run-app.sh
```

The locked project uses Python 3.12.10, `glmocr[selfhosted]==0.1.5`, `vllm==0.19.1`, Transformers 5.x, and the explicit PyTorch CUDA 12.8 package index declared in `pyproject.toml`. The virtual environment defaults to `~/.local/share/grounded-docparse/.venv`; override it with `DOCPARSE_WSL_ENV`. Setup resolves exact GLM-OCR and PP-DocLayoutV3 commits into the WSL Hugging Face cache. Runtime sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, so a missing snapshot is an actionable startup failure rather than a network fallback.

The model architecture declares 131072 positions. The supported RTX 4060 profile deliberately serves 32768 because its verified 0.85 GPU allocation provides only about 62176 KV-cache tokens, insufficient for a 128K request. Cropped-region OCR stays well within 32K, including the SDK's 8192-token output allowance.

vLLM serves the pinned snapshot as `glm-ocr` on port `8080` with throughput mode, three-token MTP speculation, a 1GB multimodal cache, and 0.85 GPU-memory fraction. The server skips vLLM's synthetic multimodal startup profile to fit the WSL memory cap; the launcher therefore requires `scripts/wsl/check-glmocr-api.py` to complete a real image-recognition request. Local July 2026 measurements informed the throughput, worker, and cache defaults, but raw benchmark results are not versioned and the numbers are not hardware-independent guarantees. Reproduce a target-machine comparison with `scripts/wsl/benchmark_glmocr.py` before changing them.

`scripts/wsl/run-app.sh` sets:

```text
DOCPARSE_LOCAL_OCR_ENABLED=true
DOCPARSE_GLMOCR_CONFIG_PATH=.runtime/glmocr.yaml
DOCPARSE_GLMOCR_LAYOUT_DEVICE=cuda:0
DOCPARSE_PRELOAD_LOCAL_OCR=true
```

`GlmOcrRuntime` is process-wide and serialized because the loaded SDK/model state is expensive. `parse_many` streams unordered SDK results, maps them back to their original page paths, and converts SDK failures into page-level evidence for the pipeline. GLM's 0–1000 box coordinates are scaled into normalized, rendered-pixel, and source coordinates. Dense form pages use deterministic spatial reading order when the native GLM order alternates between columns; ordinary pages retain native GLM order.

The source SDK configuration includes the task prompts, PP-DocLayout label IDs, overlap handling, and output normalization used by this repository. Unlike the SDK's stock pruning policy, textual headers, footers, page numbers, footnotes, references, and asides are sent through text recognition; only pure chart/image regions skip recognition. Geometry remains PP-DocLayout-owned. Reading order begins with the GLM/PP-DocLayout result and may be deterministically corrected for dense forms; Luna cannot change it.

For a live GLM-only regression run, activate the setup-created WSL environment, disable Luna explicitly, and retain candidate/provenance artifacts:

```bash
source "${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}/bin/activate"
python scripts/evaluate_corpus.py --live --glm-only \
  --document synthetic-report \
  --artifacts-dir output/synthetic-report-glm-only \
  --output output/synthetic-report-glm-only.eval.json
```

`--glm-only` disables visual recovery, Markdown refinement, and extraction, then fails the run if Luna usage, time, or recovery entries are present.

Analysis thresholds use `DOCPARSE_ANALYSIS_<FIELD>`. Ratio thresholds use rendered page area; blur/contrast checks use edge variance and grayscale range; effective-resolution checks use known DPI or the rendered short edge; skew uses layout polygon baselines. Defaults live in `AnalysisThresholds` in `src/grounded_docparse/config.py`.
