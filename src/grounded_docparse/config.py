from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(APP_ROOT / ".env", override=False)

LUNA_MODEL = "gpt-5.6-luna"
LUNA_REASONING_EFFORT = "medium"


class CloudModel(StrEnum):
    GPT_5_6_LUNA = "gpt-5.6-luna"
    GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite"
    GEMINI_3_7_FLASH = "gemini-3.7-flash"
    AGNES_2_5_FLASH = "agnes-2.5-flash"

    @property
    def label(self) -> str:
        return {
            self.GPT_5_6_LUNA: "GPT 5.6 Luna",
            self.GEMINI_3_5_FLASH_LITE: "Gemini 3.5 Flash Lite",
            self.GEMINI_3_7_FLASH: "Gemini Flash 3.7",
            self.AGNES_2_5_FLASH: "Agnes 2.5 Flash",
        }[self]

    @property
    def reasoning_effort(self) -> str:
        return "minimal" if self is self.GEMINI_3_5_FLASH_LITE else "medium"

    @property
    def api_key_name(self) -> str:
        if self is self.GPT_5_6_LUNA:
            return "OPENAI_API_KEY"
        if self is self.AGNES_2_5_FLASH:
            return "AGNES_API_KEY"
        return "GOOGLE_API_KEY"


class ExtractionEngine(StrEnum):
    PURE_AI = "pure-ai"
    PADDLE_VLLM = "paddle-vllm"
    GLM_VLLM = "glm-vllm"
    DOCLING_RAPIDOCR = "docling-rapidocr"
    PDF_INSPECTOR = "pdf-inspector"
    OLLAMA = "ollama"

    @property
    def label(self) -> str:
        return {
            self.PURE_AI: "AI ADE",
            self.PADDLE_VLLM: "PaddleOCR-VL-1.6",
            self.GLM_VLLM: "GLM-OCR",
            self.DOCLING_RAPIDOCR: "Docling + RapidOCR",
            self.PDF_INSPECTOR: "PDF Inspector (no OCR)",
            self.OLLAMA: "Local Ollama",
        }[self]

    @property
    def vllm_ocr_engine(self) -> OcrEngine | None:
        if self is self.PADDLE_VLLM:
            return OcrEngine.PADDLEOCR_VL_1_6
        if self is self.GLM_VLLM:
            return OcrEngine.GLM_OCR
        return None

    @property
    def parser_ocr_engine(self) -> OcrEngine | None:
        if self is self.OLLAMA:
            return OcrEngine.OLLAMA
        if self is self.DOCLING_RAPIDOCR:
            return OcrEngine.RAPIDOCR
        return self.vllm_ocr_engine


class OcrEngine(StrEnum):
    GLM_OCR = "glm-ocr"
    PADDLEOCR_VL_1_6 = "paddleocr-vl-1.6"
    OLLAMA = "ollama"
    RAPIDOCR = "rapidocr"

    @property
    def label(self) -> str:
        return {
            self.GLM_OCR: "GLM-OCR",
            self.PADDLEOCR_VL_1_6: "PaddleOCR-VL-1.6",
            self.OLLAMA: "Local Ollama",
            self.RAPIDOCR: "Docling + RapidOCR",
        }[self]


class AlternateOcrEngine(StrEnum):
    OLLAMA_GLM_OCR = "ollama-glm-ocr"
    OLLAMA_PADDLEOCR_VL_1_6 = "ollama-paddleocr-vl-1.6"
    RAPIDOCR = "rapidocr"
    VLLM_PADDLEOCR_VL_1_6 = "vllm-paddleocr-vl-1.6"
    VLLM_GLM_OCR = "vllm-glm-ocr"

    @property
    def label(self) -> str:
        return {
            self.OLLAMA_GLM_OCR: "PP-DocLayoutV3 + Ollama GLM-OCR",
            self.OLLAMA_PADDLEOCR_VL_1_6: (
                "PP-DocLayoutV3 + Ollama PaddleOCR-VL-1.6"
            ),
            self.RAPIDOCR: "RapidOCR (CPU)",
            self.VLLM_PADDLEOCR_VL_1_6: "WSL vLLM PaddleOCR-VL-1.6",
            self.VLLM_GLM_OCR: "WSL vLLM GLM-OCR",
        }[self]

    @property
    def vllm_engine(self) -> OcrEngine | None:
        if self is self.VLLM_PADDLEOCR_VL_1_6:
            return OcrEngine.PADDLEOCR_VL_1_6
        if self is self.VLLM_GLM_OCR:
            return OcrEngine.GLM_OCR
        return None

    @property
    def ollama_model(self) -> str | None:
        if self is self.OLLAMA_GLM_OCR:
            return "glm-ocr:latest"
        if self is self.OLLAMA_PADDLEOCR_VL_1_6:
            return "AuditAid/PaddleOCR-VL-1.6-0.9B:latest"
        return None

    def matches_primary(self, engine: OcrEngine, ollama_model: str) -> bool:
        if self is self.RAPIDOCR:
            return engine is OcrEngine.RAPIDOCR
        if self.vllm_engine is not None:
            return engine is self.vllm_engine
        return engine is OcrEngine.OLLAMA and self.ollama_model == ollama_model


def default_alternate_ocr_engine(
    engine: OcrEngine, ollama_model: str
) -> AlternateOcrEngine:
    if engine is OcrEngine.RAPIDOCR:
        return AlternateOcrEngine.OLLAMA_PADDLEOCR_VL_1_6
    if engine is OcrEngine.GLM_OCR:
        return AlternateOcrEngine.VLLM_PADDLEOCR_VL_1_6
    if engine is OcrEngine.PADDLEOCR_VL_1_6:
        return AlternateOcrEngine.VLLM_GLM_OCR
    if ollama_model == AlternateOcrEngine.OLLAMA_GLM_OCR.ollama_model:
        return AlternateOcrEngine.OLLAMA_PADDLEOCR_VL_1_6
    if ollama_model == AlternateOcrEngine.OLLAMA_PADDLEOCR_VL_1_6.ollama_model:
        return AlternateOcrEngine.OLLAMA_GLM_OCR
    return AlternateOcrEngine.RAPIDOCR


def validate_paddleocr_service_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "paddleocr_service_url must be an HTTP loopback origin with a valid port"
        ) from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "paddleocr_service_url must be an HTTP loopback origin with an explicit port"
        )
    return value.rstrip("/")


def validate_loopback_origin(value: str, *, name: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} must use a valid loopback port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be an HTTP loopback URL with an explicit port")
    return value.rstrip("/")


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
    ocr_engine: OcrEngine = OcrEngine.GLM_OCR
    cloud_model: CloudModel = CloudModel.GPT_5_6_LUNA
    render_dpi: int = 200
    crop_dpi: int = 450
    crop_padding: float = 0.1
    max_upload_bytes: int = 250 * 1024 * 1024
    max_pages: int = 500
    max_page_pixels: int = 20_000_000
    luna_max_output_tokens: int = 128_000
    max_visual_recovery_crops: int = 64
    ocr_disagreement_enabled: bool = False
    ocr_disagreement_engine: AlternateOcrEngine | None = None
    ocr_disagreement_similarity_threshold: float = 0.90
    max_ocr_disagreement_crops: int = 16
    max_ocr_disagreement_crops_per_page: int = 2
    page_batch_size: int = 16
    max_page_concurrency: int = 8
    provider_concurrency: int = 8
    provider_retry_attempts: int = 3
    provider_retry_base_seconds: float = 0.5
    provider_retry_cap_seconds: float = 8.0
    provider_cooldown_seconds: float = 1.0
    provider_success_window: int = 10
    full_page_fallback_fraction: float = 0.1
    local_ocr_enabled: bool = True
    glm_form_recovery_enabled: bool = True
    glmocr_config_path: str = "config/glmocr.yaml"
    glmocr_layout_device: str = "cuda:0"
    paddleocr_service_url: str = "http://127.0.0.1:8119"
    paddleocr_timeout_seconds: float = 900.0
    glm_vllm_base_url: str = "http://127.0.0.1:8080/v1"
    ollama_model: str = "glm-ocr:latest"
    grounded_ocr_timeout_seconds: float = 900.0
    layout_detection_threshold: float = 0.3
    analysis_thresholds: AnalysisThresholds = field(default_factory=AnalysisThresholds)

    def __post_init__(self) -> None:
        for name in (
            "render_dpi",
            "crop_dpi",
            "max_upload_bytes",
            "max_pages",
            "max_page_pixels",
            "luna_max_output_tokens",
            "max_visual_recovery_crops",
            "max_ocr_disagreement_crops",
            "max_ocr_disagreement_crops_per_page",
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
        if not 0 <= self.ocr_disagreement_similarity_threshold <= 1:
            raise ValueError("ocr_disagreement_similarity_threshold must be between 0 and 1")
        if (
            self.ocr_disagreement_enabled
            and self.ocr_disagreement_engine is not None
            and self.ocr_disagreement_engine.matches_primary(
                self.ocr_engine, self.ollama_model
            )
        ):
            raise ValueError("alternate OCR engine must differ from the primary engine")
        if self.max_ocr_disagreement_crops_per_page > self.max_ocr_disagreement_crops:
            raise ValueError(
                "max_ocr_disagreement_crops_per_page cannot exceed "
                "max_ocr_disagreement_crops"
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
        if self.paddleocr_timeout_seconds <= 0:
            raise ValueError("paddleocr_timeout_seconds must be positive")
        if self.grounded_ocr_timeout_seconds <= 0:
            raise ValueError("grounded_ocr_timeout_seconds must be positive")
        if not 0 < self.layout_detection_threshold <= 1:
            raise ValueError("layout_detection_threshold must be in (0,1]")
        validate_paddleocr_service_url(self.paddleocr_service_url)
        validate_loopback_origin(self.glm_vllm_base_url, name="glm_vllm_base_url")

    @classmethod
    def from_env(cls) -> ParserConfig:
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
            ocr_engine=OcrEngine(
                os.getenv("DOCPARSE_OCR_ENGINE", defaults.ocr_engine.value)
            ),
            cloud_model=CloudModel(
                os.getenv("DOCPARSE_CLOUD_MODEL", defaults.cloud_model.value)
            ),
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
                os.getenv(
                    "DOCPARSE_LUNA_MAX_OUTPUT_TOKENS",
                    str(defaults.luna_max_output_tokens),
                )
            ),
            max_visual_recovery_crops=int(
                os.getenv(
                    "DOCPARSE_MAX_VISUAL_RECOVERY_CROPS",
                    str(defaults.max_visual_recovery_crops),
                )
            ),
            ocr_disagreement_enabled=os.getenv(
                "DOCPARSE_OCR_DISAGREEMENT_ENABLED", "false"
            ).casefold()
            not in {"0", "false", "no"},
            ocr_disagreement_engine=(
                AlternateOcrEngine(value)
                if (
                    value := os.getenv("DOCPARSE_OCR_DISAGREEMENT_ENGINE", "").strip()
                )
                else None
            ),
            ocr_disagreement_similarity_threshold=float(
                os.getenv(
                    "DOCPARSE_OCR_DISAGREEMENT_SIMILARITY_THRESHOLD",
                    str(defaults.ocr_disagreement_similarity_threshold),
                )
            ),
            max_ocr_disagreement_crops=int(
                os.getenv(
                    "DOCPARSE_MAX_OCR_DISAGREEMENT_CROPS",
                    str(defaults.max_ocr_disagreement_crops),
                )
            ),
            max_ocr_disagreement_crops_per_page=int(
                os.getenv(
                    "DOCPARSE_MAX_OCR_DISAGREEMENT_CROPS_PER_PAGE",
                    str(defaults.max_ocr_disagreement_crops_per_page),
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
            full_page_fallback_fraction=float(
                os.getenv(
                    "DOCPARSE_FULL_PAGE_FALLBACK_FRACTION",
                    str(defaults.full_page_fallback_fraction),
                )
            ),
            local_ocr_enabled=os.getenv("DOCPARSE_LOCAL_OCR_ENABLED", "true").casefold()
            not in {"0", "false", "no"},
            glm_form_recovery_enabled=os.getenv(
                "DOCPARSE_GLM_FORM_RECOVERY_ENABLED", "true"
            ).casefold()
            not in {"0", "false", "no"},
            glmocr_config_path=os.getenv(
                "DOCPARSE_GLMOCR_CONFIG_PATH", defaults.glmocr_config_path
            ),
            glmocr_layout_device=os.getenv(
                "DOCPARSE_GLMOCR_LAYOUT_DEVICE", defaults.glmocr_layout_device
            ),
            paddleocr_service_url=os.getenv(
                "DOCPARSE_PADDLEOCR_SERVICE_URL", defaults.paddleocr_service_url
            ).rstrip("/"),
            paddleocr_timeout_seconds=float(
                os.getenv(
                    "DOCPARSE_PADDLEOCR_TIMEOUT_SECONDS",
                    str(defaults.paddleocr_timeout_seconds),
                )
            ),
            glm_vllm_base_url=os.getenv(
                "DOCPARSE_GLM_VLLM_BASE_URL", defaults.glm_vllm_base_url
            ).rstrip("/"),
            ollama_model=os.getenv("DOCPARSE_OLLAMA_MODEL", defaults.ollama_model),
            grounded_ocr_timeout_seconds=float(
                os.getenv(
                    "DOCPARSE_GROUNDED_OCR_TIMEOUT_SECONDS",
                    str(defaults.grounded_ocr_timeout_seconds),
                )
            ),
            layout_detection_threshold=float(
                os.getenv(
                    "DOCPARSE_LAYOUT_DETECTION_THRESHOLD",
                    str(defaults.layout_detection_threshold),
                )
            ),
            analysis_thresholds=thresholds,
        )
