from pathlib import Path

from PIL import Image, ImageDraw

from grounded_docparse.raster_regions import discover_raster_regions


def test_discovers_visual_regions_without_pdf_text(tmp_path: Path) -> None:
    page = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle((40, 80, 560, 180), fill="black")
    draw.rectangle((40, 600, 560, 720), fill="black")
    source = tmp_path / "page.png"
    page.save(source)

    regions = discover_raster_regions(source, tmp_path / "regions")

    assert len(regions) == 2
    assert all(region.path.exists() for region in regions)
    assert regions[0].bbox[1] < regions[1].bbox[1]
    assert sum((region.bbox[3] - region.bbox[1]) for region in regions) < 0.35


def test_blank_page_requires_no_model_draft(tmp_path: Path) -> None:
    source = tmp_path / "blank.png"
    Image.new("RGB", (300, 400), "white").save(source)

    assert discover_raster_regions(source, tmp_path / "regions") == []
