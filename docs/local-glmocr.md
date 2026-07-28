# Local GLM-OCR runtime

Run parser and UI inside WSL2 Ubuntu 24.04. Recognition uses only GLM-OCR;
PP-DocLayout-V3 is its bundled layout stage. PDF pages are always rendered to
images. Selectable PDF text is never read.

```bash
bash scripts/wsl/setup-glmocr.sh
# terminal 1
bash scripts/wsl/serve-glmocr.sh
# terminal 2
bash scripts/wsl/run-app.sh
```

CUDA 12.8 wheels are intentional: vLLM 0.19.1 requires PyTorch 2.10, which has
no compatible CUDA 13.2 wheel. Lower `GLMOCR_GPU_MEMORY_UTILIZATION` from 0.75
or `GLMOCR_MAX_MODEL_LEN` from 8192 if an 8 GB GPU runs out of memory.

Analysis thresholds use `DOCPARSE_ANALYSIS_<FIELD>` names. Foreground, clipping,
table/form, visual, and unknown thresholds are page-area ratios. Edge variance
and grayscale p95-p05 measure blur and contrast. Effective resolution uses DPI
when known and shortest rendered edge otherwise. Skew is degrees from region
polygon baselines. All thresholds are defined in `AnalysisThresholds`.
