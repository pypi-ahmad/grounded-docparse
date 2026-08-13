from __future__ import annotations

import base64
import io
import json
import os
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw


def build_probe_png() -> bytes:
    image = Image.new("RGB", (640, 160), "white")
    ImageDraw.Draw(image).text((40, 55), "PADDLE OCR READY", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> int:
    service_url = os.environ.get(
        "DOCPARSE_PADDLEOCR_SERVICE_URL", "http://127.0.0.1:8119"
    ).rstrip("/")
    request = Request(
        f"{service_url}/layout-parsing",
        data=json.dumps(
            {
                "file": base64.b64encode(build_probe_png()).decode("ascii"),
                "fileType": 1,
                "useLayoutDetection": True,
                "formatBlockContent": True,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        payload = json.loads(response.read())
    if payload.get("errorCode") != 0 or "result" not in payload:
        raise SystemExit(f"PaddleOCR-VL inference probe failed: {payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
