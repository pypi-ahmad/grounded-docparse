from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ParserConfig:
    terra_model: str = "gpt-5.6-terra"
    luna_model: str = "gpt-5.6-luna"
    glm_model: str = "glm-ocr"
    ollama_host: str = "http://127.0.0.1:11434"
    paddle_image: str = (
        "ccr-2vdh3abv-pub.cnc.bj.baidubce.com/"
        "paddlepaddle/paddleocr-vl:latest-nvidia-gpu@"
        "sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db"
    )
    paddle_cache_volume: str = "grounded-docparse-paddle-cache"
    render_dpi: int = 300
    max_upload_bytes: int = 250 * 1024 * 1024
    max_pages: int = 500
    max_page_pixels: int = 20_000_000
    max_table_rows: int = 100_000
    max_table_columns: int = 200
    max_table_cells: int = 2_000_000
    luna_max_output_tokens: int = 16_384
    terra_max_output_tokens: int = 16_384
    glm_max_output_tokens: int = 16_384
    paddle_max_new_tokens: int = 16_384
    paddle_timeout_seconds: int = 60 * 60
    page_window_size: int = 10
    source_chunk_pages: int = 25
    chunk_retry_count: int = 2
    window_retry_count: int = 2
    enable_paddle: bool = True
    enable_glm: bool = True
    enable_openai: bool = True
    enable_chart_recognition: bool = True
    enable_image_ocr: bool = True

    def __post_init__(self) -> None:
        for name in (
            "render_dpi",
            "max_upload_bytes",
            "max_pages",
            "max_page_pixels",
            "max_table_rows",
            "max_table_columns",
            "max_table_cells",
            "paddle_timeout_seconds",
            "luna_max_output_tokens",
            "terra_max_output_tokens",
            "glm_max_output_tokens",
            "paddle_max_new_tokens",
            "page_window_size",
            "source_chunk_pages",
            "chunk_retry_count",
            "window_retry_count",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.enable_paddle and "@sha256:" not in self.paddle_image:
            raise ValueError("paddle_image must be pinned by sha256 digest")

    @classmethod
    def from_env(cls) -> ParserConfig:
        defaults = cls()
        return cls(
            terra_model=os.getenv("DOCPARSE_TERRA_MODEL", defaults.terra_model),
            luna_model=os.getenv("DOCPARSE_LUNA_MODEL", defaults.luna_model),
            glm_model=os.getenv("DOCPARSE_GLM_MODEL", defaults.glm_model),
            ollama_host=os.getenv("DOCPARSE_OLLAMA_HOST", defaults.ollama_host),
            paddle_image=os.getenv("DOCPARSE_PADDLE_IMAGE", defaults.paddle_image),
            paddle_cache_volume=os.getenv(
                "DOCPARSE_PADDLE_CACHE_VOLUME", defaults.paddle_cache_volume
            ),
            render_dpi=int(os.getenv("DOCPARSE_RENDER_DPI", str(defaults.render_dpi))),
            max_upload_bytes=int(
                os.getenv("DOCPARSE_MAX_UPLOAD_BYTES", str(defaults.max_upload_bytes))
            ),
            max_pages=int(os.getenv("DOCPARSE_MAX_PAGES", str(defaults.max_pages))),
            max_page_pixels=int(
                os.getenv("DOCPARSE_MAX_PAGE_PIXELS", str(defaults.max_page_pixels))
            ),
            max_table_rows=int(
                os.getenv("DOCPARSE_MAX_TABLE_ROWS", str(defaults.max_table_rows))
            ),
            max_table_columns=int(
                os.getenv("DOCPARSE_MAX_TABLE_COLUMNS", str(defaults.max_table_columns))
            ),
            max_table_cells=int(
                os.getenv("DOCPARSE_MAX_TABLE_CELLS", str(defaults.max_table_cells))
            ),
            luna_max_output_tokens=int(
                os.getenv("DOCPARSE_LUNA_MAX_OUTPUT_TOKENS", str(defaults.luna_max_output_tokens))
            ),
            terra_max_output_tokens=int(
                os.getenv("DOCPARSE_TERRA_MAX_OUTPUT_TOKENS", str(defaults.terra_max_output_tokens))
            ),
            glm_max_output_tokens=int(
                os.getenv("DOCPARSE_GLM_MAX_OUTPUT_TOKENS", str(defaults.glm_max_output_tokens))
            ),
            paddle_max_new_tokens=int(
                os.getenv(
                    "DOCPARSE_PADDLE_MAX_NEW_TOKENS",
                    str(defaults.paddle_max_new_tokens),
                )
            ),
            paddle_timeout_seconds=int(
                os.getenv(
                    "DOCPARSE_PADDLE_TIMEOUT_SECONDS",
                    str(defaults.paddle_timeout_seconds),
                )
            ),
            page_window_size=int(
                os.getenv("DOCPARSE_PAGE_WINDOW_SIZE", str(defaults.page_window_size))
            ),
            source_chunk_pages=int(
                os.getenv(
                    "DOCPARSE_SOURCE_CHUNK_PAGES", str(defaults.source_chunk_pages)
                )
            ),
            chunk_retry_count=int(
                os.getenv(
                    "DOCPARSE_CHUNK_RETRY_COUNT", str(defaults.chunk_retry_count)
                )
            ),
            window_retry_count=int(
                os.getenv(
                    "DOCPARSE_WINDOW_RETRY_COUNT",
                    str(defaults.window_retry_count),
                )
            ),
            enable_paddle=_bool_env("DOCPARSE_ENABLE_PADDLE", True),
            enable_glm=_bool_env("DOCPARSE_ENABLE_GLM", True),
            enable_openai=_bool_env("DOCPARSE_ENABLE_OPENAI", True),
            enable_chart_recognition=_bool_env(
                "DOCPARSE_ENABLE_CHART_RECOGNITION", True
            ),
            enable_image_ocr=_bool_env("DOCPARSE_ENABLE_IMAGE_OCR", True),
        )
