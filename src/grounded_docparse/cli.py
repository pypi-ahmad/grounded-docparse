from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import evaluate_tree, load_gold_tree
from .models import DocumentProfile, ProcessingProfile, SegmentationMode
from .pipeline import DocumentParser


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a document into Markdown and JSON")
    parser.add_argument("document", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument(
        "--profile",
        choices=[item.value for item in ProcessingProfile],
        default=None,
        help="Processing profile (default: local-only)",
    )
    parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Deprecated alias for --profile maximum-accuracy",
    )
    parser.add_argument(
        "--gold-json",
        type=Path,
        help="Corrected document-tree JSON to evaluate after parsing",
    )
    parser.add_argument(
        "--document-profile",
        choices=[item.value for item in DocumentProfile],
        default=DocumentProfile.AUTO.value,
        help="Document type profile (default: auto)",
    )
    parser.add_argument(
        "--segmentation",
        choices=[item.value for item in SegmentationMode],
        default=SegmentationMode.AUTO.value,
        help="Automatic multi-document segmentation (default: auto)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        help="Draft 2020-12 JSON extraction schema",
    )
    args = parser.parse_args()
    if args.allow_cloud and args.profile:
        parser.error("--allow-cloud cannot be combined with --profile")
    profile = (
        ProcessingProfile.MAXIMUM_ACCURACY
        if args.allow_cloud
        else ProcessingProfile(args.profile or ProcessingProfile.LOCAL_ONLY)
    )
    extraction_schema = None
    if args.schema:
        if args.schema.stat().st_size > 256 * 1024:
            parser.error("--schema exceeds 256 KB")
        try:
            raw_schema = json.loads(args.schema.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            parser.error(f"Cannot read --schema: {exc}")
        if not isinstance(raw_schema, dict):
            parser.error("--schema must contain a JSON object")
        extraction_schema = raw_schema
    result = DocumentParser().parse_path(
        args.document,
        profile=profile,
        document_profile=DocumentProfile(args.document_profile),
        segmentation=SegmentationMode(args.segmentation),
        extraction_schema=extraction_schema,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    stem = args.document.stem
    (args.output / f"{stem}.md").write_text(result.markdown, encoding="utf-8")
    (args.output / f"{stem}.llm.md").write_text(
        result.llm_markdown, encoding="utf-8"
    )
    (args.output / f"{stem}.json").write_text(result.json, encoding="utf-8")
    (args.output / f"{stem}.audit.json").write_text(
        result.audit_json, encoding="utf-8"
    )
    (args.output / f"{stem}.failures.jsonl").write_text(
        result.failures_jsonl, encoding="utf-8"
    )
    (args.output / f"{stem}.quality.json").write_text(
        result.quality_json, encoding="utf-8"
    )
    (args.output / f"{stem}.annotated.pdf").write_bytes(result.annotated_pdf)
    (args.output / f"{stem}.zip").write_bytes(result.bundle)
    (args.output / f"{stem}.batch.manifest.json").write_text(
        result.batch_manifest_json, encoding="utf-8"
    )
    if result.extraction_json:
        (args.output / f"{stem}.extraction.json").write_text(
            result.extraction_json, encoding="utf-8"
        )
    for relative_path, content in result.table_exports.items():
        target = args.output / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    segments_dir = args.output / f"{stem}.subdocuments"
    if result.subdocuments:
        segments_dir.mkdir(exist_ok=True)
    for subdocument in result.subdocuments:
        safe_name = Path(subdocument.tree.source_name).stem
        (segments_dir / f"{safe_name}.pdf").write_bytes(subdocument.source_pdf)
        (segments_dir / f"{safe_name}.zip").write_bytes(subdocument.bundle)
        (segments_dir / f"{safe_name}.failures.jsonl").write_text(
            subdocument.failures_jsonl, encoding="utf-8"
        )
        (segments_dir / f"{safe_name}.quality.json").write_text(
            subdocument.quality_json, encoding="utf-8"
        )
        (segments_dir / f"{safe_name}.annotated.pdf").write_bytes(
            subdocument.annotated_pdf
        )
    if args.gold_json:
        report = evaluate_tree(result.tree, load_gold_tree(args.gold_json.read_bytes()))
        (args.output / f"{stem}.evaluation.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
