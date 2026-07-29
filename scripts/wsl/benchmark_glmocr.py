#!/usr/bin/env python3
"""Measure warm GLM-OCR page latency without Luna or application overhead."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import fitz
from glmocr import GlmOcr

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _page_image(source: Path, page_number: int, directory: Path) -> Path:
    if source.suffix.casefold() != ".pdf":
        return source
    document = fitz.open(source)
    try:
        if not 1 <= page_number <= document.page_count:
            raise SystemExit(
                f"ERROR: page {page_number} is outside 1..{document.page_count}."
            )
        target = directory / f"page-{page_number}.png"
        document[page_number - 1].get_pixmap(dpi=200, alpha=False).save(target)
        return target
    finally:
        document.close()


def _content(result: Any) -> str:
    items = getattr(result, "json_result", result)
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            return items
    if isinstance(items, list):
        return "\n".join(_content(item) for item in items)
    if not isinstance(items, dict):
        return ""
    own = (
        str(items.get("content", items.get("text", "")) or "")
        if any(key in items for key in ("bbox_2d", "bbox", "coordinate"))
        else ""
    )
    children = [
        _content(value)
        for value in items.values()
        if isinstance(value, (dict, list))
    ]
    return "\n".join(
        part for part in [own, *children] if part
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / ".runtime" / "glmocr.yaml",
    )
    parser.add_argument("--layout-device", default="cuda:0")
    args = parser.parse_args()
    if args.warmups < 0 or args.runs < 1:
        parser.error("--warmups must be nonnegative and --runs must be positive")

    with tempfile.TemporaryDirectory(prefix="glmocr-benchmark-") as temporary:
        image = _page_image(args.input.resolve(), args.page, Path(temporary))
        initialization_started = time.perf_counter()
        runtime = GlmOcr(
            config_path=str(args.config.resolve()),
            layout_device=args.layout_device,
        )
        initialization_seconds = time.perf_counter() - initialization_started
        durations: list[float] = []
        warmup_durations: list[float] = []
        content = ""
        for index in range(args.warmups + args.runs):
            started = time.perf_counter()
            result = runtime.parse(str(image))
            duration = time.perf_counter() - started
            content = _content(result)
            if index < args.warmups:
                warmup_durations.append(duration)
            else:
                durations.append(duration)

    report = {
        "input": str(args.input),
        "page": args.page,
        "layout_device": args.layout_device,
        "runs": args.runs,
        "initialization_seconds": round(initialization_seconds, 3),
        "cold_parse_seconds": (
            round(warmup_durations[0], 3) if warmup_durations else None
        ),
        "median_seconds": round(statistics.median(durations), 3),
        "min_seconds": round(min(durations), 3),
        "max_seconds": round(max(durations), 3),
        "pages_per_second": round(1 / statistics.median(durations), 3),
        "characters": len(content),
        "table_tags": content.casefold().count("<table"),
        "headings": sum(line.startswith("#") for line in content.splitlines()),
    }
    print("BENCHMARK " + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
