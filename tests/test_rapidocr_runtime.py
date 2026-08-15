from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from grounded_docparse.rapidocr_runtime import RapidOcrCropRuntime


def test_rapidocr_crop_runtime_normalizes_order_and_geometry(tmp_path) -> None:
    image_path = tmp_path / "crop.png"
    Image.new("RGB", (200, 100), "white").save(image_path)
    engine = lambda _path: SimpleNamespace(  # noqa: E731 - compact test double
        txts=("First", "Second"),
        scores=(0.9, 0.8),
        boxes=(
            ((20, 10), (100, 10), (100, 30), (20, 30)),
            ((20, 40), (180, 40), (180, 70), (20, 70)),
        ),
    )

    regions = RapidOcrCropRuntime(engine).parse(image_path)

    assert [region.content for region in regions] == ["First", "Second"]
    assert regions[0].bbox == (0.1, 0.1, 0.5, 0.3)
    assert regions[1].confidence == 0.8
