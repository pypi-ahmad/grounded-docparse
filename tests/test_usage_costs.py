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
                model="gpt-6-sol",
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
        "gpt-6-sol",
    ]
    assert summary.input_tokens == 3_000_500
    assert summary.cached_input_tokens == 250_000
    assert summary.output_tokens == 300_100
    assert summary.estimated_cost == pytest.approx(5.7)
    assert summary.unavailable_calls == 0


def test_usage_costs_exclude_unavailable_telemetry() -> None:
    summary = summarize_calls(
        [
            AgentUsage(
                agent="draft",
                model="gpt-6-sol",
                telemetry_available=False,
            )
        ]
    )

    assert summary.models == ()
    assert summary.unavailable_calls == 1


def test_model_rate_card_uses_configured_fixed_rates() -> None:
    pricing = pricing_for("gpt-6-sol")
    assert (pricing.input_per_million, pricing.output_per_million) == (2.00, 10.00)
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
        model="gpt-6-sol",
        input_tokens=100,
        output_tokens=10,
    )

    ledger.extend([call])
    first = ledger.snapshot()
    first.append(call)

    assert len(ledger.snapshot()) == 1


@pytest.mark.parametrize("input_tokens, expected", [(272_000, 0.628), (272_001, 1.206004)])
def test_sol_cache_writes_and_long_context_boundary(input_tokens, expected) -> None:
    summary = summarize_calls([AgentUsage(
        agent="test", model="gpt-6-sol", input_tokens=input_tokens,
        cached_input_tokens=20_000, cache_write_tokens=40_000, output_tokens=10_000,
    )])
    assert summary.estimated_cost == pytest.approx(expected)
    assert summary.cache_write_tokens == 40_000


def test_sol_threshold_applies_to_each_call_not_session_total() -> None:
    calls = [AgentUsage(agent="test", model="gpt-6-sol", input_tokens=200_000)] * 3
    assert summarize_calls(calls).estimated_cost == pytest.approx(1.2)


def test_cache_counts_are_bounded_per_call() -> None:
    calls = [
        AgentUsage(agent="test", model="gpt-6-sol", input_tokens=100,
                   cached_input_tokens=80, cache_write_tokens=90),
        AgentUsage(agent="test", model="gpt-6-sol", input_tokens=100),
    ]
    summary = summarize_calls(calls)
    assert summary.cached_input_tokens == 80
    assert summary.cache_write_tokens == 20
    assert summary.estimated_cost == pytest.approx(0.000266)


def test_legacy_saved_usage_defaults_cache_writes_to_zero() -> None:
    from grounded_docparse.models import RunUsage

    usage = RunUsage.model_validate({"calls": [{"agent": "test", "model": "gpt-6-sol"}]})
    assert usage.calls[0].cache_write_tokens == usage.cache_write_tokens == 0
