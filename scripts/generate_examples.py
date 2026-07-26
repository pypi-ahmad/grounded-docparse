from __future__ import annotations

import io
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def digital_report() -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((54, 60), "Synthetic Clinical Operations Report", fontsize=20)
    page.insert_text((54, 95), "1. Summary", fontsize=15)
    page.insert_textbox(
        pymupdf.Rect(54, 115, 558, 180),
        "This synthetic document contains no patient information. It exists only "
        "to exercise document parsing and reading-order behavior.",
        fontsize=11,
    )
    page.insert_text((54, 220), "Metric", fontsize=11)
    page.insert_text((220, 220), "January", fontsize=11)
    page.insert_text((360, 220), "February", fontsize=11)
    page.insert_text((54, 245), "Reviewed forms", fontsize=11)
    page.insert_text((220, 245), "128", fontsize=11)
    page.insert_text((360, 245), "141", fontsize=11)
    page.insert_text((54, 270), "Average pages", fontsize=11)
    page.insert_text((220, 270), "4.2", fontsize=11)
    page.insert_text((360, 270), "4.5", fontsize=11)
    document.save(EXAMPLES / "synthetic-report.pdf")


def fax_document() -> None:
    image = Image.new("L", (1728, 2200), "white")
    draw = ImageDraw.Draw(image)
    draw.text((100, 90), "SYNTHETIC MEDICAL FAX - NO PHI", fill="black")
    draw.text((100, 150), "FAX DATE: 2026-07-24    PAGES: 1", fill="black")
    draw.line((100, 205, 1628, 205), fill="black", width=3)
    lines = [
        "DOCUMENT TYPE: Referral test fixture",
        "Priority: Routine",
        "Requested service: Imaging review",
        "Clinical note: Synthetic text created for OCR evaluation.",
        "Medication list: None supplied",
        "Signature: [synthetic mark]",
    ]
    for index, line in enumerate(lines):
        draw.text((120, 300 + index * 150), line, fill="black")
    image = image.rotate(1.3, fillcolor="white")
    image = image.filter(ImageFilter.GaussianBlur(0.8))
    image = ImageEnhance.Contrast(image).enhance(0.72)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=38)
    degraded = Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")
    degraded.save(EXAMPLES / "synthetic-medical-fax.pdf", "PDF", resolution=200)


def main() -> None:
    EXAMPLES.mkdir(exist_ok=True)
    digital_report()
    fax_document()
    print(f"Generated examples in {EXAMPLES}")


if __name__ == "__main__":
    main()
