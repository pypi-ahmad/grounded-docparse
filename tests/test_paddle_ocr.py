from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest
from PIL import Image

from grounded_docparse.ingest import PageEvidence
from grounded_docparse.paddle_ocr import PaddleOcrRuntime, paddle_regions


def _page(tmp_path: Path, number: int = 1) -> PageEvidence:
    path = tmp_path / f"page-{number}.png"
    Image.new("RGB", (1000, 2000), "white").save(path)
    return PageEvidence(
        number=number,
        width=1000,
        height=2000,
        dpi=200,
        image_path=path,
        render_width_pixels=1000,
        render_height_pixels=2000,
        source_width=1000,
        source_height=2000,
    )


def test_paddle_regions_normalize_ordered_official_blocks() -> None:
    result = {
        "parsing_res_list": [
            {
                "block_id": 8,
                "block_order": 2,
                "block_label": "text",
                "block_content": "Second",
                "block_bbox": [100, 400, 900, 500],
            },
            {
                "block_id": 3,
                "block_order": 1,
                "block_label": "table",
                "block_content": "<table><tr><td>[x] Yes</td></tr></table>",
                "block_bbox": [50, 100, 950, 350],
                "block_polygon": [[50, 100], [950, 100], [950, 350], [50, 350]],
                "score": 0.97,
            },
        ]
    }

    regions = paddle_regions(result, width=1000, height=2000)

    assert [region.content for region in regions] == [
        "<table><tr><td>[x] Yes</td></tr></table>",
        "Second",
    ]
    assert regions[0].bbox == (0.05, 0.05, 0.95, 0.175)
    assert regions[0].polygon[2] == (0.95, 0.175)
    assert regions[0].confidence == 0.97


def test_paddle_runtime_posts_document_once_and_maps_pages(
    tmp_path: Path, monkeypatch
) -> None:
    pages = [_page(tmp_path, 1), _page(tmp_path, 2)]
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF-test")
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "errorCode": 0,
                    "result": {
                        "layoutParsingResults": [
                            {
                                "prunedResult": {
                                    "parsing_res_list": [
                                        {
                                            "block_order": 1,
                                            "block_label": "text",
                                            "block_content": "Page one",
                                            "block_bbox": [0, 0, 1000, 100],
                                        }
                                    ]
                                }
                            },
                            {
                                "prunedResult": {
                                    "parsing_res_list": [
                                        {
                                            "block_order": 1,
                                            "block_label": "text",
                                            "block_content": "Page two",
                                            "block_bbox": [0, 0, 1000, 100],
                                        }
                                    ]
                                }
                            },
                        ]
                    },
                }
            ).encode()

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return Response()

    monkeypatch.setattr("grounded_docparse.paddle_ocr.urlopen", fake_urlopen)
    runtime = PaddleOcrRuntime("http://127.0.0.1:8119", timeout_seconds=20)

    results = runtime.parse_document(source, pages)

    assert len(calls) == 1
    assert calls[0][0].full_url.endswith("/layout-parsing")
    assert [result.regions[0].content for result in results] == [
        "Page one",
        "Page two",
    ]


def test_paddle_runtime_recovery_posts_deterministic_image_without_preparing(
    tmp_path: Path, monkeypatch
) -> None:
    page = _page(tmp_path)
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "errorCode": 0,
                    "result": {
                        "layoutParsingResults": [
                            {
                                "prunedResult": {
                                    "parsing_res_list": [
                                        {
                                            "block_order": 1,
                                            "block_label": "table",
                                            "block_content": "<table>Recovered</table>",
                                            "block_bbox": [0, 0, 1000, 100],
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                }
            ).encode()

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return Response()

    monkeypatch.setattr("grounded_docparse.paddle_ocr.urlopen", fake_urlopen)
    runtime = PaddleOcrRuntime("http://127.0.0.1:8119", timeout_seconds=20)

    result = runtime.parse_recovery_image(page.image_path)

    payload = json.loads(calls[0][0].data)
    assert payload["fileType"] == 1
    assert payload["useLayoutDetection"] is True
    assert payload["formatBlockContent"] is True
    assert payload["temperature"] == 0.0
    assert payload["topP"] == 1.0
    assert result.regions[0].content == "<table>Recovered</table>"
    assert runtime._prepared == {}


def test_paddle_runtime_fails_closed_on_service_error(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "page.png"
    source.write_bytes(b"image")

    def fail(*_args, **_kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr("grounded_docparse.paddle_ocr.urlopen", fail)

    with pytest.raises(RuntimeError, match="PaddleOCR-VL service request failed"):
        PaddleOcrRuntime("http://127.0.0.1:8119").parse_document(
            source, [_page(tmp_path)]
        )


def test_paddle_runtime_rejects_remote_document_destination() -> None:
    with pytest.raises(ValueError, match="HTTP loopback origin"):
        PaddleOcrRuntime("https://example.com:8119")
