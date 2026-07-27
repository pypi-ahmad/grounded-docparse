from __future__ import annotations

import argparse
import json
from pathlib import Path

from grounded_docparse.benchmark import (
    accuracy_threshold_failures,
    compare_markdown,
    evaluate_result,
)
from grounded_docparse.pipeline import DocumentParser

DEFAULT_EXPECTATIONS = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "public_water_expectations.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PublicWaterMassMailing live benchmark")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--reference", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/public-water-benchmark"),
    )
    args = parser.parse_args()
    expectations = json.loads(args.expectations.read_text(encoding="utf-8"))
    result = DocumentParser().parse(
        args.pdf.read_bytes(),
        args.pdf.name,
        progress_callback=lambda event: print(event.message, flush=True),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "PublicWaterMassMailing.md").write_text(
        result.markdown, encoding="utf-8"
    )
    (args.output_dir / "PublicWaterMassMailing.json").write_text(
        result.json, encoding="utf-8"
    )
    failures = evaluate_result(result.document, result.markdown, expectations)
    accuracy = None
    if args.reference is not None:
        accuracy = compare_markdown(
            result.markdown,
            args.reference.read_text(encoding="utf-8"),
            text_dominant_pages=[
                int(page)
                for page in expectations.get("text_dominant_pages", [])
            ],
        )
        failures.extend(
            accuracy_threshold_failures(
                accuracy,
                expectations.get("accuracy_thresholds", {}),
            )
        )
    report = {
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "accuracy": accuracy,
    }
    (args.output_dir / "benchmark-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if failures:
        print("Benchmark failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Benchmark passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
