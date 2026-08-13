#!/usr/bin/env python3
"""Run one real multimodal request against the local GLM-OCR endpoint."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(
    os.environ.get(
        "DOCPARSE_GLMOCR_CONFIG_PATH", PROJECT_ROOT / "config" / "glmocr.yaml"
    )
)


def main() -> int:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["pipeline"]
    ocr_api = config["ocr_api"]
    image = Image.new("RGB", (640, 160), "white")
    ImageDraw.Draw(image).text((40, 55), "GLM OCR READY", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    if ocr_api.get("api_mode", "openai") == "ollama_generate":
        payload = {
            "model": ocr_api["model"],
            "prompt": "Text Recognition:",
            "images": [image_base64],
            "stream": False,
            "options": {"temperature": 0, "num_predict": 256},
        }
        url = f"http://{ocr_api['api_host']}:{ocr_api['api_port']}/api/generate"
    else:
        image_url = "data:image/png;base64," + image_base64
        payload = {
            "model": ocr_api["model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "OCR this image."},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": config["page_loader"]["max_tokens"],
        }
        url = f"http://{ocr_api['api_host']}:{ocr_api['api_port']}/v1/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"GLM-OCR inference check failed: HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"GLM-OCR inference check failed: {exc}", file=sys.stderr)
        return 1
    if ocr_api.get("api_mode", "openai") == "ollama_generate":
        recognized = result.get("response")
    else:
        choices = result.get("choices", [])
        recognized = choices[0].get("message", {}).get("content") if choices else None
    if not recognized:
        print("GLM-OCR inference check returned no recognized text.", file=sys.stderr)
        return 1
    print("GLM-OCR inference check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
