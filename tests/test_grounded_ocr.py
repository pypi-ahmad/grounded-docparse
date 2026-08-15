from __future__ import annotations

from pathlib import Path
from io import BytesIO
import json

from PIL import Image

from grounded_docparse.grounded_ocr import (
    GroundedOcrRuntime,
    GlmVllmRecognizer,
    LayoutRegion,
    crop_region,
)


class Detector:
    def detect(self, _image_path: Path) -> list[LayoutRegion]:
        return [
            LayoutRegion(4, "table", 0.91, (0.1, 0.2, 0.5, 0.4)),
            LayoutRegion(9, "text", 0.82, (0.5, 0.6, 0.9, 0.8)),
        ]


class Recognizer:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, int]]] = []

    def recognize(self, image_bytes: bytes, region_type: str) -> str:
        from io import BytesIO

        with Image.open(BytesIO(image_bytes)) as image:
            self.calls.append((region_type, image.size))
        if region_type == "text":
            raise RuntimeError("recognition failed")
        return "A | B"


def test_grounded_runtime_preserves_detector_geometry_and_failures(tmp_path: Path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (1000, 500), "white").save(image_path)
    recognizer = Recognizer()

    result = next(
        GroundedOcrRuntime(Detector(), recognizer).parse_many([image_path])
    )

    assert [region.index for region in result.regions] == [4, 9]
    assert result.regions[0].bbox == (0.1, 0.2, 0.5, 0.4)
    assert result.regions[0].content == "A | B"
    assert result.regions[0].confidence == 0.91
    assert result.regions[0].recognition_attempted is True
    assert result.regions[1].bbox == (0.5, 0.6, 0.9, 0.8)
    assert result.regions[1].content == ""
    assert result.regions[1].recognition_failed is True
    assert recognizer.calls == [("table", (440, 110)), ("text", (440, 110))]


def test_crop_padding_never_changes_detector_box_or_crosses_page_edges() -> None:
    image = Image.new("RGB", (100, 50), "white")
    region = LayoutRegion(0, "text", 0.8, (0.0, 0.0, 0.2, 0.2))

    cropped = crop_region(image, region, padding=0.05)

    assert cropped.size == (21, 11)
    assert region.bbox == (0.0, 0.0, 0.2, 0.2)


def test_glm_vllm_recognizer_posts_only_the_grounded_crop() -> None:
    captured = {}

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def opener(request, *, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response(b'{"choices":[{"message":{"content":"```text\\nValue\\n```"}}]}')

    recognizer = GlmVllmRecognizer(
        "http://127.0.0.1:8080/v1", timeout_seconds=12, opener=opener
    )

    assert recognizer.recognize(b"crop", "table") == "Value"
    assert captured["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert captured["timeout"] == 12
    payload = captured["payload"]
    assert payload["model"] == "glm-ocr"
    assert payload["messages"][0]["content"][0]["text"] == "Table Recognition:"
    assert payload["messages"][0]["content"][1]["image_url"]["url"].endswith(
        "Y3JvcA=="
    )
