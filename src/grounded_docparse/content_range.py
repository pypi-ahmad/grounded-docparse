from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContentUnit(StrEnum):
    PAGE = "page"
    FRAME = "frame"
    SLIDE = "slide"
    SHEET = "sheet"
    SECTION = "section"
    BLOCK = "block"
    ROW = "row"


class ContentRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> ContentRange:
        if self.end < self.start:
            raise ValueError("content range end must be at or after start")
        return self


class ContentRangeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: ContentUnit
    total: int = Field(ge=1)


class AppliedContentRange(ContentRange):
    unit: ContentUnit
    total: int = Field(ge=1)


def resolve_content_range(
    requested: ContentRange | None,
    info: ContentRangeInfo,
) -> AppliedContentRange | None:
    if requested is None:
        return None
    if requested.end > info.total:
        raise ValueError(
            f"{info.unit.value} range must be within 1-{info.total}; got "
            f"{requested.start}-{requested.end}"
        )
    return AppliedContentRange(
        start=requested.start,
        end=requested.end,
        unit=info.unit,
        total=info.total,
    )
