from __future__ import annotations

import argparse

from .grounded_ocr import ensure_layout_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare native Windows model assets")
    parser.add_argument("--download-layout", action="store_true")
    args = parser.parse_args()
    if args.download_layout:
        ensure_layout_model(download=True)


if __name__ == "__main__":
    main()
