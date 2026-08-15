from __future__ import annotations

from types import SimpleNamespace

from docling_core.types.doc import BoundingBox, CoordOrigin, ProvenanceItem, Size
from docling_core.types.doc.page import BoundingRectangle
from PIL import Image

from grounded_docparse.rapidocr_runtime import (
    DoclingRapidOcrRuntime,
    RapidOcrCropRuntime,
)


def test_rapidocr_crop_runtime_normalizes_order_and_geometry(tmp_path) -> None:
    image_path = tmp_path / "crop.png"
    Image.new("RGB", (200, 100), "white").save(image_path)
    engine = lambda _path: SimpleNamespace(
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


def test_docling_rapidocr_runtime_preserves_layout_order_tables_and_confidence(
    tmp_path,
) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (200, 100), "white").save(image_path)
    size = Size(width=200, height=100)
    text = SimpleNamespace(
        label=SimpleNamespace(value="text"),
        text="First line",
        prov=[
            ProvenanceItem(
                page_no=1,
                bbox=BoundingBox(
                    l=20,
                    t=90,
                    r=180,
                    b=70,
                    coord_origin=CoordOrigin.BOTTOMLEFT,
                ),
                charspan=(0, 10),
            )
        ],
    )
    table = SimpleNamespace(
        label=SimpleNamespace(value="table"),
        text=None,
        export_to_html=lambda _doc, add_caption=False: (
            "<table><tr><td>A</td><td>B</td></tr></table>"
        ),
        prov=[
            ProvenanceItem(
                page_no=1,
                bbox=BoundingBox(
                    l=20,
                    t=60,
                    r=180,
                    b=20,
                    coord_origin=CoordOrigin.BOTTOMLEFT,
                ),
                charspan=(11, 12),
            )
        ],
    )
    document = SimpleNamespace(
        pages={1: SimpleNamespace(size=size)},
        iterate_items=lambda **_kwargs: iter(((text, 0), (table, 0))),
    )
    cells = [
        SimpleNamespace(
            text="First line",
            confidence=0.92,
            from_ocr=True,
            rect=BoundingRectangle(
                r_x0=20,
                r_y0=10,
                r_x1=180,
                r_y1=10,
                r_x2=180,
                r_y2=30,
                r_x3=20,
                r_y3=30,
                coord_origin=CoordOrigin.TOPLEFT,
            ),
        ),
        SimpleNamespace(
            text="A B",
            confidence=0.8,
            from_ocr=True,
            rect=BoundingRectangle(
                r_x0=20,
                r_y0=40,
                r_x1=180,
                r_y1=40,
                r_x2=180,
                r_y2=80,
                r_x3=20,
                r_y3=80,
                coord_origin=CoordOrigin.TOPLEFT,
            ),
        ),
    ]
    conversion = SimpleNamespace(
        document=document,
        pages=[
            SimpleNamespace(
                parsed_page=SimpleNamespace(textline_cells=cells, word_cells=[])
            )
        ],
    )
    converter = SimpleNamespace(convert=lambda *_args, **_kwargs: conversion)

    result = next(DoclingRapidOcrRuntime(converter).parse_many([image_path]))

    assert result.error is None
    assert [region.label for region in result.regions] == ["text", "table"]
    assert [region.content for region in result.regions] == [
        "First line",
        "<table><tr><td>A</td><td>B</td></tr></table>",
    ]
    assert result.regions[0].bbox == (0.1, 0.1, 0.9, 0.3)
    assert result.regions[0].confidence == 0.92
    assert result.regions[1].confidence == 0.8
