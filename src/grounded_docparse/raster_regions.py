from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .models import PageAnalysis


@dataclass(frozen=True, slots=True)
class RasterRegion:
    path: Path
    bbox: tuple[float, float, float, float]


def materialize_analysis_regions(
    image_path: Path, output_dir: Path, analysis: PageAnalysis
) -> list[RasterRegion]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    output: list[RasterRegion] = []
    for index, region in enumerate(analysis.regions, 1):
        box = region.bbox.normalized
        left, top = int(box.x0 * image.width), int(box.y0 * image.height)
        right = max(left + 1, int(box.x1 * image.width))
        bottom = max(top + 1, int(box.y1 * image.height))
        path = output_dir / f"region-{index:02d}.png"
        image.crop((left, top, min(image.width, right), min(image.height, bottom))).save(path, "PNG")
        output.append(RasterRegion(path, (box.x0, box.y0, box.x1, box.y1)))
    return output


def discover_raster_regions(
    image_path: Path,
    output_dir: Path,
    *,
    max_regions: int = 8,
) -> list[RasterRegion]:
    """Split visible page content into bounded horizontal crops using pixels only."""

    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    width, height = image.size
    sample_width = min(width, 512)
    sample_height = max(1, round(height * sample_width / width))
    sample = image.resize((sample_width, sample_height), Image.Resampling.BILINEAR).convert(
        "L"
    )
    pixels = sample.load()
    active = [
        sum(pixels[x, y] < 245 for x in range(sample_width)) >= max(1, sample_width // 500)
        for y in range(sample_height)
    ]
    rows = [index for index, value in enumerate(active) if value]
    if not rows:
        return []

    groups: list[list[int]] = [[rows[0]]]
    gap_limit = max(2, sample_height // 100)
    for row in rows[1:]:
        if row - groups[-1][-1] <= gap_limit:
            groups[-1].append(row)
        else:
            groups.append([row])

    bands: list[tuple[float, float]] = []
    max_height = 0.32
    for group in groups:
        y0 = max(0.0, group[0] / sample_height - 0.01)
        y1 = min(1.0, (group[-1] + 1) / sample_height + 0.01)
        cursor = y0
        while y1 - cursor > max_height:
            bands.append((cursor, cursor + max_height))
            cursor += max_height - 0.02
        bands.append((cursor, y1))

    while len(bands) > max_regions:
        gaps = [bands[index + 1][0] - bands[index][1] for index in range(len(bands) - 1)]
        index = min(range(len(gaps)), key=gaps.__getitem__)
        bands[index : index + 2] = [(bands[index][0], bands[index + 1][1])]

    regions: list[RasterRegion] = []
    for index, (y0, y1) in enumerate(bands, 1):
        top = max(0, int(y0 * height))
        bottom = min(height, max(top + 1, int(y1 * height)))
        crop_path = output_dir / f"region-{index:02d}.png"
        image.crop((0, top, width, bottom)).save(crop_path, "PNG")
        regions.append(RasterRegion(crop_path, (0.0, top / height, 1.0, bottom / height)))
    return regions
