from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AnalysisThresholds:
    """Deterministic image-analysis thresholds; ratios use rendered page pixels."""

    blank_foreground_ratio: float = 0.001
    skew_degrees: float = 1.0
    min_edge_variance: float = 80.0
    min_contrast_range: float = 40.0
    clipping_border_ratio: float = 0.05
    min_effective_dpi: float = 150.0
    min_short_edge_pixels: int = 900
    table_form_area_ratio: float = 0.25
    visual_area_ratio: float = 0.35
    unknown_area_ratio: float = 0.30
    complex_region_count: int = 10

    def __post_init__(self) -> None:
        for name in (
            "blank_foreground_ratio",
            "clipping_border_ratio",
            "table_form_area_ratio",
            "visual_area_ratio",
            "unknown_area_ratio",
        ):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        for name in (
            "skew_degrees",
            "min_edge_variance",
            "min_contrast_range",
            "min_effective_dpi",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.min_short_edge_pixels <= 0 or self.complex_region_count <= 0:
            raise ValueError("analysis pixel and region thresholds must be positive")


@dataclass(frozen=True, slots=True)
class ParserConfig:
    luna_model: str = "gpt-5.6-luna"
    render_dpi: int = 200
    crop_dpi: int = 450
    crop_padding: float = 0.05
    targeted_repair_context_padding: float | None = None
    max_upload_bytes: int = 250 * 1024 * 1024
    max_pages: int = 500
    max_page_pixels: int = 20_000_000
    luna_max_output_tokens: int = 128_000
    page_batch_size: int = 16
    max_page_concurrency: int = 8
    provider_concurrency: int = 8
    provider_retry_attempts: int = 3
    provider_retry_base_seconds: float = 0.5
    provider_retry_cap_seconds: float = 8.0
    provider_cooldown_seconds: float = 1.0
    provider_success_window: int = 10
    max_model_calls: int | None = None
    max_http_attempts: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_elapsed_seconds: float | None = None
    max_repair_rounds: int | None = None
    full_page_fallback_fraction: float = 0.1
    local_ocr_enabled: bool = True
    glmocr_config_path: str = "config/glmocr.yaml"
    glmocr_layout_device: str = "cuda:0"
    analysis_thresholds: AnalysisThresholds = field(default_factory=AnalysisThresholds)

    def __post_init__(self) -> None:
        for name in (
            "render_dpi",
            "crop_dpi",
            "max_upload_bytes",
            "max_pages",
            "max_page_pixels",
            "luna_max_output_tokens",
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
        if (
            self.targeted_repair_context_padding is not None
            and not 0 <= self.targeted_repair_context_padding <= 0.5
        ):
            raise ValueError(
                "targeted_repair_context_padding must be between 0 and 0.5"
            )
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
        if not 0 < self.full_page_fallback_fraction <= 1:
            raise ValueError("full_page_fallback_fraction must be in (0,1]")
        for name in (
            "max_model_calls",
            "max_http_attempts",
            "max_input_tokens",
            "max_output_tokens",
            "max_elapsed_seconds",
            "max_repair_rounds",
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
        threshold_defaults = defaults.analysis_thresholds
        thresholds = AnalysisThresholds(
            **{
                name: type(getattr(threshold_defaults, name))(
                    os.getenv(
                        f"DOCPARSE_ANALYSIS_{name.upper()}",
                        str(getattr(threshold_defaults, name)),
                    )
                )
                for name in AnalysisThresholds.__dataclass_fields__
            }
        )
        return cls(
            luna_model=os.getenv("DOCPARSE_LUNA_MODEL", defaults.luna_model),
            render_dpi=int(os.getenv("DOCPARSE_RENDER_DPI", str(defaults.render_dpi))),
            crop_dpi=int(os.getenv("DOCPARSE_CROP_DPI", str(defaults.crop_dpi))),
            crop_padding=float(
                os.getenv("DOCPARSE_CROP_PADDING", str(defaults.crop_padding))
            ),
            targeted_repair_context_padding=optional_float(
                "DOCPARSE_TARGETED_REPAIR_CONTEXT_PADDING"
            ),
            max_upload_bytes=int(
                os.getenv("DOCPARSE_MAX_UPLOAD_BYTES", str(defaults.max_upload_bytes))
            ),
            max_pages=int(os.getenv("DOCPARSE_MAX_PAGES", str(defaults.max_pages))),
            max_page_pixels=int(
                os.getenv("DOCPARSE_MAX_PAGE_PIXELS", str(defaults.max_page_pixels))
            ),
            luna_max_output_tokens=int(
                os.getenv(
                    "DOCPARSE_LUNA_MAX_OUTPUT_TOKENS",
                    str(defaults.luna_max_output_tokens),
                )
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
            max_model_calls=optional_int("DOCPARSE_MAX_MODEL_CALLS"),
            max_http_attempts=optional_int("DOCPARSE_MAX_HTTP_ATTEMPTS"),
            max_input_tokens=optional_int("DOCPARSE_MAX_INPUT_TOKENS"),
            max_output_tokens=optional_int("DOCPARSE_MAX_OUTPUT_TOKENS"),
            max_elapsed_seconds=optional_float("DOCPARSE_MAX_ELAPSED_SECONDS"),
            max_repair_rounds=optional_int("DOCPARSE_MAX_REPAIR_ROUNDS"),
            full_page_fallback_fraction=float(
                os.getenv(
                    "DOCPARSE_FULL_PAGE_FALLBACK_FRACTION",
                    str(defaults.full_page_fallback_fraction),
                )
            ),
            local_ocr_enabled=os.getenv("DOCPARSE_LOCAL_OCR_ENABLED", "true").casefold()
            not in {"0", "false", "no"},
            glmocr_config_path=os.getenv(
                "DOCPARSE_GLMOCR_CONFIG_PATH", defaults.glmocr_config_path
            ),
            glmocr_layout_device=os.getenv(
                "DOCPARSE_GLMOCR_LAYOUT_DEVICE", defaults.glmocr_layout_device
            ),
            analysis_thresholds=thresholds,
        )
