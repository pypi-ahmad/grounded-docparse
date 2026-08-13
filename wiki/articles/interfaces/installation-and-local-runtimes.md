---
tags: installation, runtime, windows, wsl
sources: scripts/wsl/setup-glmocr.sh, installer/Install-GroundedDocParse.ps1, SETUP.md
snapshot: content-f03a0de2c1a2
status: released
---

# Installation and local runtimes

Grounded DocParse targets a Windows workstation with WSL-backed local OCR services. The installer prepares Python dependencies, OCR runtimes, model assets, launchers, and hardware-appropriate fallbacks.

The native optional dependency set adds PDF Inspector, Docling, and LangExtract. Their integration remains non-OCR: local GLM-OCR or PaddleOCR-VL services continue to handle only scanned PDFs, images, and OCR-selected mixed pages.

See [[scanned-pdf-and-image-pipeline]], [[docling-native-conversion]], and [[security-privacy-and-trust-boundaries]].

## Evidence

Dependency installation is implemented in `scripts/wsl/setup-glmocr.sh`; Windows orchestration is in `installer/Install-GroundedDocParse.ps1`; supported setup paths are described in `SETUP.md`.
