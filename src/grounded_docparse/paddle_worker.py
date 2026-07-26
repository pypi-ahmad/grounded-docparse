from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def emit(event: str, **values: object) -> None:
    print(json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--total-pages", type=int, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=16384)
    parser.add_argument("--window-size", type=int, default=10)
    parser.add_argument("--chart-recognition", action="store_true")
    parser.add_argument("--image-ocr", action="store_true")
    args = parser.parse_args()

    from paddleocr import PaddleOCRVL

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    emit("start", total=args.total_pages)
    pipeline = PaddleOCRVL(
        pipeline_version="v1.6",
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
        use_layout_detection=True,
    )
    try:
        iterator = pipeline.predict_iter(
            args.input,
            use_queues=False,
            use_chart_recognition=args.chart_recognition,
            use_ocr_for_image_block=args.image_ocr,
            temperature=0,
            max_new_tokens=args.max_new_tokens,
        )
        for index, result in enumerate(iterator, start=1):
            before = set(output_dir.rglob("*.json"))
            result.save_to_json(save_path=output_dir)
            created = sorted(set(output_dir.rglob("*.json")) - before)
            if not created:
                raise RuntimeError(f"No JSON result saved for page {index}")
            target = output_dir / f"page-{index:04d}.json"
            shutil.move(str(created[-1]), target)
            emit("page", page=index, total=args.total_pages)
            if index % args.window_size == 0 or index == args.total_pages:
                emit(
                    "window",
                    start=index - ((index - 1) % args.window_size),
                    end=index,
                    total=args.total_pages,
                )
        emit("done", total=args.total_pages)
    except Exception as exc:
        emit("error", message=str(exc))
        raise


if __name__ == "__main__":
    main()
