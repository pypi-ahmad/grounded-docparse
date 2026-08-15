from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from .config import CloudModel
from .models import AgentUsage


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None


@dataclass(frozen=True)
class ModelUsageCost:
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    estimated_cost: float
    pricing: ModelPricing


@dataclass(frozen=True)
class UsageCostSummary:
    models: tuple[ModelUsageCost, ...]
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    estimated_cost: float
    unavailable_calls: int


class SessionUsageLedger:
    def __init__(self) -> None:
        self._calls: list[AgentUsage] = []
        self._lock = threading.Lock()

    def extend(self, calls: Iterable[AgentUsage]) -> None:
        copied = [call.model_copy(deep=True) for call in calls]
        with self._lock:
            self._calls.extend(copied)

    def snapshot(self) -> list[AgentUsage]:
        with self._lock:
            return [call.model_copy(deep=True) for call in self._calls]


def pricing_for(model: str, *, pricing_date: date | None = None) -> ModelPricing:
    pricing_date = pricing_date or datetime.now().astimezone().date()
    pricing = {
        CloudModel.GPT_5_6_LUNA.value: ModelPricing(0.20, 1.20, 0.02),
        CloudModel.GEMINI_3_5_FLASH_LITE.value: ModelPricing(0.30, 2.50),
        CloudModel.GEMINI_3_7_FLASH.value: ModelPricing(
            0.75 if pricing_date <= date(2026, 12, 31) else 1.50,
            3.75 if pricing_date <= date(2026, 12, 31) else 7.50,
        ),
        CloudModel.AGNES_2_5_FLASH.value: ModelPricing(0.0, 0.0),
    }
    return pricing.get(model, ModelPricing(0.0, 0.0))


def summarize_calls(
    calls: Iterable[AgentUsage], *, pricing_date: date | None = None
) -> UsageCostSummary:
    calls = list(calls)
    available = [call for call in calls if call.telemetry_available]
    unavailable_calls = sum(1 for call in calls if not call.telemetry_available)
    rows: list[ModelUsageCost] = []
    for model in sorted({call.model for call in available}):
        model_calls = [call for call in available if call.model == model]
        input_tokens = sum(call.input_tokens for call in model_calls)
        cached_tokens = min(
            sum(call.cached_input_tokens for call in model_calls), input_tokens
        )
        output_tokens = sum(call.output_tokens for call in model_calls)
        pricing = pricing_for(model, pricing_date=pricing_date)
        cached_rate = (
            pricing.cached_input_per_million
            if pricing.cached_input_per_million is not None
            else pricing.input_per_million
        )
        cost = (
            (input_tokens - cached_tokens) * pricing.input_per_million
            + cached_tokens * cached_rate
            + output_tokens * pricing.output_per_million
        ) / 1_000_000
        rows.append(
            ModelUsageCost(
                model=model,
                input_tokens=input_tokens,
                cached_input_tokens=cached_tokens,
                output_tokens=output_tokens,
                estimated_cost=cost,
                pricing=pricing,
            )
        )
    return UsageCostSummary(
        models=tuple(rows),
        input_tokens=sum(row.input_tokens for row in rows),
        cached_input_tokens=sum(row.cached_input_tokens for row in rows),
        output_tokens=sum(row.output_tokens for row in rows),
        estimated_cost=sum(row.estimated_cost for row in rows),
        unavailable_calls=unavailable_calls,
    )
