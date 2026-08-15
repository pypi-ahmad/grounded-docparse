from __future__ import annotations

import argparse

from .docling_native import ensure_docling_models
from .grounded_ocr import ensure_layout_model
from .ollama_runtime import OllamaOcrModel, ensure_model


def prepare_models() -> None:
    print("Checking native CPU PP-DocLayoutV3 weights...")
    ensure_layout_model()
    for model in OllamaOcrModel:
        print(f"Checking Local Ollama OCR model: {model.value}")
        ensure_model(model)
    print("Checking persistent Docling layout, TableFormer, and RapidOCR weights...")
    ensure_docling_models()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare native Windows model assets")
    parser.add_argument("--prepare-models", action="store_true")
    args = parser.parse_args()
    if args.prepare_models:
        prepare_models()


if __name__ == "__main__":
    main()
