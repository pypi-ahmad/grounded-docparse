from datetime import date

import pytest

from grounded_docparse.models import AgentUsage
from grounded_docparse.usage_costs import (
    SessionUsageLedger,
    pricing_for,
    summarize_calls,
)


def test_usage_costs_split_models_and_calculate_total() -> None:
    summary = summarize_calls(
        [
            AgentUsage(
                agent="draft",
                model="gpt-5.6-luna",
                input_tokens=1_000_000,
                cached_input_tokens=250_000,
                output_tokens=100_000,
            ),
            AgentUsage(
                agent="review",
                model="gemini-3.5-flash-lite",
                input_tokens=2_000_000,
                output_tokens=200_000,
            ),
            AgentUsage(
                agent="classify",
                model="agnes-2.5-flash",
                input_tokens=500,
                output_tokens=100,
            ),
        ],
        pricing_date=date(2026, 8, 15),
    )

    assert [row.model for row in summary.models] == [
        "agnes-2.5-flash",
        "gemini-3.5-flash-lite",
        "gpt-5.6-luna",
    ]
    assert summary.input_tokens == 3_000_500
    assert summary.cached_input_tokens == 250_000
    assert summary.output_tokens == 300_100
    assert summary.estimated_cost == pytest.approx(1.375)
    assert summary.unavailable_calls == 0


def test_usage_costs_exclude_unavailable_telemetry() -> None:
    summary = summarize_calls(
        [
            AgentUsage(
                agent="draft",
                model="gpt-5.6-luna",
                telemetry_available=False,
            )
        ]
    )

    assert summary.models == ()
    assert summary.unavailable_calls == 1


def test_model_rate_card_uses_configured_fixed_rates() -> None:
    pricing = pricing_for("gpt-5.6-luna")
    assert (pricing.input_per_million, pricing.output_per_million) == (0.20, 1.20)
    gemini_lite = pricing_for("gemini-3.5-flash-lite")
    assert (gemini_lite.input_per_million, gemini_lite.output_per_million) == (
        0.30,
        2.50,
    )
    gemini_flash = pricing_for("gemini-3.7-flash", pricing_date=date(2027, 1, 1))
    assert (gemini_flash.input_per_million, gemini_flash.output_per_million) == (
        0.75,
        3.75,
    )
    agnes = pricing_for("agnes-2.5-flash")
    assert (agnes.input_per_million, agnes.output_per_million) == (0.0, 0.0)


def test_launch_session_ledger_returns_isolated_snapshots() -> None:
    ledger = SessionUsageLedger()
    call = AgentUsage(
        agent="draft",
        model="gpt-5.6-luna",
        input_tokens=100,
        output_tokens=10,
    )

    ledger.extend([call])
    first = ledger.snapshot()
    first.append(call)

    assert len(ledger.snapshot()) == 1
