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
    page_batch_size: int = 100
    max_page_concurrency: int = 50
    provider_concurrency: int = 50
    provider_retry_attempts: int = 3
    provider_retry_base_seconds: float = 0.5
    provider_retry_cap_seconds: float = 8.0
    provider_cooldown_seconds: float = 1.0
    provider_success_window: int = 10
    max_http_attempts: int | None = None
    max_terra_attempts: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_elapsed_seconds: float | None = None

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
            "provider_concurrency",
            "provider_retry_attempts",
            "provider_success_window",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 <= self.crop_padding <= 0.5:
            raise ValueError("crop_padding must be between 0 and 0.5")
        if self.max_page_concurrency > self.page_batch_size:
            raise ValueError("max_page_concurrency cannot exceed page_batch_size")
        for name in (
            "provider_retry_base_seconds",
            "provider_retry_cap_seconds",
            "provider_cooldown_seconds",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.provider_retry_cap_seconds < self.provider_retry_base_seconds:
            raise ValueError(
                "provider_retry_cap_seconds cannot be below provider_retry_base_seconds"
            )
        for name in (
            "max_http_attempts",
            "max_terra_attempts",
            "max_input_tokens",
            "max_output_tokens",
            "max_elapsed_seconds",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive when set")

    @classmethod
    def from_env(cls) -> ParserConfig:
        def optional_int(name: str) -> int | None:
            value = os.getenv(name)
            return int(value) if value else None

        def optional_float(name: str) -> float | None:
            value = os.getenv(name)
            return float(value) if value else None

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
            provider_concurrency=int(
                os.getenv(
                    "DOCPARSE_PROVIDER_CONCURRENCY",
                    str(defaults.provider_concurrency),
                )
            ),
            provider_retry_attempts=int(
                os.getenv(
                    "DOCPARSE_PROVIDER_RETRY_ATTEMPTS",
                    str(defaults.provider_retry_attempts),
                )
            ),
            provider_retry_base_seconds=float(
                os.getenv(
                    "DOCPARSE_PROVIDER_RETRY_BASE_SECONDS",
                    str(defaults.provider_retry_base_seconds),
                )
            ),
            provider_retry_cap_seconds=float(
                os.getenv(
                    "DOCPARSE_PROVIDER_RETRY_CAP_SECONDS",
                    str(defaults.provider_retry_cap_seconds),
                )
            ),
            provider_cooldown_seconds=float(
                os.getenv(
                    "DOCPARSE_PROVIDER_COOLDOWN_SECONDS",
                    str(defaults.provider_cooldown_seconds),
                )
            ),
            provider_success_window=int(
                os.getenv(
                    "DOCPARSE_PROVIDER_SUCCESS_WINDOW",
                    str(defaults.provider_success_window),
                )
            ),
            max_http_attempts=optional_int("DOCPARSE_MAX_HTTP_ATTEMPTS"),
            max_terra_attempts=optional_int("DOCPARSE_MAX_TERRA_ATTEMPTS"),
            max_input_tokens=optional_int("DOCPARSE_MAX_INPUT_TOKENS"),
            max_output_tokens=optional_int("DOCPARSE_MAX_OUTPUT_TOKENS"),
            max_elapsed_seconds=optional_float("DOCPARSE_MAX_ELAPSED_SECONDS"),
        )
