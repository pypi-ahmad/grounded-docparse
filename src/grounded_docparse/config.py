from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParserConfig:
    terra_model: str = "gpt-5.6-terra"
    luna_model: str = "gpt-5.6-luna"
    render_dpi: int = 200
    crop_dpi: int = 450
    crop_padding: float = 0.05
    max_upload_bytes: int = 250 * 1024 * 1024
    max_pages: int = 500
    max_page_pixels: int = 20_000_000
    luna_max_output_tokens: int = 128_000
    terra_max_output_tokens: int = 128_000
    page_batch_size: int = 20
    max_page_concurrency: int = 10

    def __post_init__(self) -> None:
        for name in (
            "render_dpi",
            "crop_dpi",
            "max_upload_bytes",
            "max_pages",
            "max_page_pixels",
            "luna_max_output_tokens",
            "terra_max_output_tokens",
            "page_batch_size",
            "max_page_concurrency",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 <= self.crop_padding <= 0.5:
            raise ValueError("crop_padding must be between 0 and 0.5")
        if self.max_page_concurrency > self.page_batch_size:
            raise ValueError("max_page_concurrency cannot exceed page_batch_size")

    @classmethod
    def from_env(cls) -> ParserConfig:
        defaults = cls()
        return cls(
            terra_model=os.getenv("DOCPARSE_TERRA_MODEL", defaults.terra_model),
            luna_model=os.getenv("DOCPARSE_LUNA_MODEL", defaults.luna_model),
            render_dpi=int(os.getenv("DOCPARSE_RENDER_DPI", str(defaults.render_dpi))),
            crop_dpi=int(os.getenv("DOCPARSE_CROP_DPI", str(defaults.crop_dpi))),
            crop_padding=float(
                os.getenv("DOCPARSE_CROP_PADDING", str(defaults.crop_padding))
            ),
            max_upload_bytes=int(
                os.getenv("DOCPARSE_MAX_UPLOAD_BYTES", str(defaults.max_upload_bytes))
            ),
            max_pages=int(os.getenv("DOCPARSE_MAX_PAGES", str(defaults.max_pages))),
            max_page_pixels=int(
                os.getenv("DOCPARSE_MAX_PAGE_PIXELS", str(defaults.max_page_pixels))
            ),
            luna_max_output_tokens=int(
                os.getenv("DOCPARSE_LUNA_MAX_OUTPUT_TOKENS", str(defaults.luna_max_output_tokens))
            ),
            terra_max_output_tokens=int(
                os.getenv("DOCPARSE_TERRA_MAX_OUTPUT_TOKENS", str(defaults.terra_max_output_tokens))
            ),
            page_batch_size=int(
                os.getenv("DOCPARSE_PAGE_BATCH_SIZE", str(defaults.page_batch_size))
            ),
            max_page_concurrency=int(
                os.getenv(
                    "DOCPARSE_MAX_PAGE_CONCURRENCY",
                    str(defaults.max_page_concurrency),
                )
            ),
        )
