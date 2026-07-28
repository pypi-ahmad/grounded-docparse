from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from grounded_docparse import pipeline
from grounded_docparse.config import ParserConfig
from grounded_docparse.gateways import OpenAIDocumentGateway
from grounded_docparse.ingest import IngestedDocument, PageEvidence
from grounded_docparse.models import (
    AtomicDraft,
    PageDraft,
    PageInspection,
    PagePlan,
    RegionDraft,
    RunUsage,
)
from grounded_docparse.runtime import BudgetExceeded, ProviderRuntime


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _status_error(status: int, *, retry_after: str | None = None) -> APIStatusError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    request = httpx.Request("POST", "https://api.openai.test/v1/responses")
    response = httpx.Response(status, headers=headers, request=request)
    return APIStatusError("provider error", response=response, body=None)


def _runtime(
    config: ParserConfig, fake_time: FakeTime | None = None
) -> ProviderRuntime:
    fake_time = fake_time or FakeTime()
    return ProviderRuntime(
        config,
        clock=fake_time.clock,
        sleeper=fake_time.sleep,
        random=lambda: 0.5,
        wall_clock=fake_time.clock,
    )


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
def test_runtime_retries_only_retryable_http_statuses(status: int) -> None:
    runtime = _runtime(ParserConfig(provider_retry_attempts=3))
    calls = 0

    def request() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _status_error(status)
        return "ok"

    assert runtime.request(request, model="luna", stage="draft") == "ok"
    assert calls == 3
    assert runtime.diagnostics().http_attempts == 3
    assert runtime.diagnostics().retries == 2


def test_runtime_retries_connection_errors_and_stops_at_attempt_bound() -> None:
    runtime = _runtime(ParserConfig(provider_retry_attempts=3))
    calls = 0

    def request() -> None:
        nonlocal calls
        calls += 1
        raise APIConnectionError(request=httpx.Request("POST", "https://api.test"))

    with pytest.raises(APIConnectionError):
        runtime.request(request, model="luna", stage="draft")

    assert calls == 3
    assert runtime.diagnostics().http_attempts == 3


def test_runtime_releases_permit_after_provider_timeout() -> None:
    runtime = _runtime(ParserConfig(provider_concurrency=1, provider_retry_attempts=1))

    with pytest.raises(APITimeoutError):
        runtime.request(
            lambda: (_ for _ in ()).throw(
                APITimeoutError(request=httpx.Request("POST", "https://api.test"))
            ),
            model="luna",
            stage="draft",
        )

    assert (
        runtime.request(lambda: "released", model="luna", stage="draft") == "released"
    )


def test_runtime_counts_logical_calls_separately_from_retry_attempts() -> None:
    runtime = _runtime(ParserConfig(provider_retry_attempts=3, max_model_calls=1))
    calls = 0

    def request() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _status_error(500)
        return "ok"

    assert runtime.request(request, model="gpt-5.6-luna", stage="inspection") == "ok"
    diagnostics = runtime.diagnostics()
    assert diagnostics.model_calls == 1
    assert diagnostics.http_attempts == 3
    assert diagnostics.retries == 2

    with pytest.raises(BudgetExceeded, match="model_calls"):
        runtime.request(lambda: "denied", model="luna", stage="inspection")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 600])
def test_runtime_does_not_retry_nonretryable_http_statuses(status: int) -> None:
    runtime = _runtime(ParserConfig(provider_retry_attempts=3))
    calls = 0

    def request() -> None:
        nonlocal calls
        calls += 1
        raise _status_error(status)

    with pytest.raises(APIStatusError):
        runtime.request(request, model="luna", stage="draft")

    assert calls == 1
    assert runtime.diagnostics().retries == 0


def test_usage_is_charged_before_a_waiting_call_checks_token_budget() -> None:
    runtime = ProviderRuntime(ParserConfig(provider_concurrency=1, max_input_tokens=1))
    first_entered = threading.Event()
    release_first = threading.Event()
    second_called = threading.Event()
    errors: list[Exception] = []

    def first() -> str:
        first_entered.set()
        release_first.wait(timeout=1)
        return "first"

    def run_first() -> None:
        runtime.request(
            first,
            model="luna",
            stage="draft",
            on_success=lambda _result: runtime.record_usage(
                input_tokens=1,
                output_tokens=0,
            ),
        )

    def run_second() -> None:
        try:
            runtime.request(
                lambda: second_called.set(),
                model="luna",
                stage="inspection",
            )
        except Exception as exc:  # noqa: BLE001 - captured for thread assertion
            errors.append(exc)

    first_thread = threading.Thread(target=run_first)
    second_thread = threading.Thread(target=run_second)
    first_thread.start()
    assert first_entered.wait(timeout=1)
    second_thread.start()
    release_first.set()
    first_thread.join(timeout=1)
    second_thread.join(timeout=1)

    assert not second_called.is_set()
    assert len(errors) == 1
    assert isinstance(errors[0], BudgetExceeded)
    assert errors[0].budget == "input_tokens"


def test_attempt_budget_denies_retry_without_sleeping_or_counting_it() -> None:
    fake_time = FakeTime()
    runtime = _runtime(
        ParserConfig(max_http_attempts=1, provider_retry_attempts=3),
        fake_time,
    )

    with pytest.raises(BudgetExceeded, match="http_attempts"):
        runtime.request(
            lambda: (_ for _ in ()).throw(_status_error(500)),
            model="luna",
            stage="draft",
        )

    assert fake_time.sleeps == []
    assert runtime.diagnostics().http_attempts == 1
    assert runtime.diagnostics().retries == 0


def test_runtime_honors_retry_after_and_capped_full_jitter() -> None:
    fake_time = FakeTime()
    runtime = _runtime(
        ParserConfig(
            provider_retry_attempts=3,
            provider_retry_base_seconds=2,
            provider_retry_cap_seconds=3,
        ),
        fake_time,
    )
    errors = [_status_error(429, retry_after="5"), _status_error(500)]

    def request() -> str:
        if errors:
            raise errors.pop(0)
        return "ok"

    assert runtime.request(request, model="luna", stage="draft") == "ok"
    assert fake_time.sleeps == [5.0, 1.5]
    diagnostics = runtime.diagnostics()
    assert diagnostics.retry_sleep_seconds == 6.5
    assert diagnostics.rate_limit_events == 1


def test_runtime_honors_http_date_retry_after() -> None:
    fake_time = FakeTime()
    runtime = _runtime(
        ParserConfig(provider_retry_attempts=2),
        fake_time,
    )
    calls = 0

    def request() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _status_error(
                429,
                retry_after="Thu, 01 Jan 1970 00:00:04 GMT",
            )
        return "ok"

    assert runtime.request(request, model="luna", stage="draft") == "ok"
    assert fake_time.sleeps == [4.0]


def test_runtime_shares_provider_admission_across_callers() -> None:
    runtime = ProviderRuntime(ParserConfig(provider_concurrency=2))
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = 0
    maximum = 0

    def request() -> None:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        barrier.wait(timeout=1)
        time.sleep(0.01)
        with lock:
            active -= 1

    threads = [
        threading.Thread(
            target=lambda: runtime.request(request, model="luna", stage="draft")
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert maximum == 2


def test_429_halves_concurrency_then_success_window_recovers_one_slot() -> None:
    fake_time = FakeTime()
    runtime = _runtime(
        ParserConfig(
            provider_concurrency=4,
            provider_retry_attempts=1,
            provider_cooldown_seconds=2,
            provider_success_window=2,
        ),
        fake_time,
    )

    with pytest.raises(APIStatusError):
        runtime.request(
            lambda: (_ for _ in ()).throw(_status_error(429)),
            model="luna",
            stage="draft",
        )

    assert runtime.diagnostics().effective_concurrency == 2
    assert runtime.diagnostics().cooldown_until == 2.0

    with pytest.raises(APIStatusError):
        runtime.request(
            lambda: (_ for _ in ()).throw(_status_error(429)),
            model="luna",
            stage="draft",
        )

    assert runtime.diagnostics().effective_concurrency == 1

    runtime.request(lambda: "ok", model="luna", stage="draft")
    runtime.request(lambda: "ok", model="luna", stage="draft")

    assert fake_time.sleeps == [2.0, 2.0]
    assert runtime.diagnostics().effective_concurrency == 2


@pytest.mark.parametrize(
    ("config", "setup", "model", "budget"),
    [
        (
            ParserConfig(max_http_attempts=1),
            lambda runtime: None,
            "luna",
            "http_attempts",
        ),
        (
            ParserConfig(max_input_tokens=3),
            lambda runtime: runtime.record_usage(input_tokens=3, output_tokens=0),
            "luna",
            "input_tokens",
        ),
        (
            ParserConfig(max_output_tokens=2),
            lambda runtime: runtime.record_usage(input_tokens=0, output_tokens=2),
            "luna",
            "output_tokens",
        ),
    ],
)
def test_runtime_denies_each_configured_count_budget_before_call(
    config: ParserConfig,
    setup,
    model: str,
    budget: str,
) -> None:
    runtime = _runtime(config)
    setup(runtime)
    called = 0

    if budget == "http_attempts":
        runtime.request(lambda: "first", model=model, stage="draft")

    def denied_call() -> None:
        nonlocal called
        called += 1

    with pytest.raises(BudgetExceeded, match=budget):
        runtime.request(denied_call, model=model, stage="inspection")

    assert called == 0
    assert runtime.diagnostics().budget_denials[-1].budget == budget


def test_runtime_denies_elapsed_budget_before_call() -> None:
    fake_time = FakeTime()
    runtime = _runtime(ParserConfig(max_elapsed_seconds=3), fake_time)
    fake_time.now = 3
    called = False

    def request() -> None:
        nonlocal called
        called = True

    with pytest.raises(BudgetExceeded, match="elapsed_seconds"):
        runtime.request(request, model="luna", stage="inspection")

    assert called is False


def test_base_draft_attempts_are_reserved_before_escalation() -> None:
    runtime = _runtime(ParserConfig(max_http_attempts=2))
    runtime.reserve_full_page_fallbacks(20)
    escalation_called = False

    with pytest.raises(BudgetExceeded, match="reserved"):
        runtime.request(
            lambda: globals().update(),
            model="luna",
            stage="inspection",
        )

    def escalation() -> None:
        nonlocal escalation_called
        escalation_called = True

    runtime.request(lambda: "page 1", model="luna", stage="page_draft", base_draft=True)
    runtime.request(lambda: "page 2", model="luna", stage="page_draft", base_draft=True)
    with pytest.raises(BudgetExceeded):
        runtime.request(escalation, model="luna", stage="inspection")

    assert escalation_called is False


def test_base_draft_preflight_rejects_insufficient_logical_call_budget() -> None:
    runtime = _runtime(ParserConfig(max_model_calls=1))

    with pytest.raises(BudgetExceeded, match="cannot cover 2 fallbacks"):
        runtime.reserve_full_page_fallbacks(20)

    diagnostics = runtime.diagnostics()
    assert diagnostics.model_calls == 0
    assert diagnostics.budget_denials[-1].stage == "run_preflight"


def test_runtime_enforces_run_wide_repair_round_budget() -> None:
    runtime = _runtime(ParserConfig(max_repair_rounds=1))
    runtime.claim_repair_round(stage="manager_repair", model="luna", page_number=1)

    with pytest.raises(BudgetExceeded, match="repair_rounds"):
        runtime.claim_repair_round(
            stage="quality_repair",
            model="gpt-5.6-luna",
            page_number=2,
        )

    assert runtime.diagnostics().repair_rounds == 1


def test_runtime_releases_permit_after_base_exception_and_callback_failure() -> None:
    runtime = ProviderRuntime(
        ParserConfig(provider_concurrency=1, provider_retry_attempts=1)
    )

    class Cancelled(BaseException):
        pass

    with pytest.raises(Cancelled):
        runtime.request(
            lambda: (_ for _ in ()).throw(Cancelled()),
            model="luna",
            stage="draft",
        )

    with pytest.raises(RuntimeError, match="usage failed"):
        runtime.request(
            lambda: "ok",
            model="luna",
            stage="draft",
            on_success=lambda _result: (_ for _ in ()).throw(
                RuntimeError("usage failed")
            ),
        )

    assert (
        runtime.request(lambda: "released", model="luna", stage="draft") == "released"
    )


def test_default_gateway_disables_sdk_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def client(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(responses=object())

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("grounded_docparse.gateways.OpenAI", client)

    OpenAIDocumentGateway(ParserConfig())

    assert captured == {"max_retries": 0}


def test_gateway_bounds_provider_timeout_by_remaining_run_latency() -> None:
    fake_time = FakeTime()
    runtime = _runtime(ParserConfig(max_elapsed_seconds=5), fake_time)
    responses = object()
    timeouts: list[float] = []

    class Client:
        responses = object()

        def with_options(self, *, timeout: float):
            timeouts.append(timeout)
            return SimpleNamespace(responses=responses)

    gateway = OpenAIDocumentGateway(
        ParserConfig(max_elapsed_seconds=5),
        client=Client(),
        runtime=runtime,
    )
    fake_time.now = 2

    assert gateway._provider_responses() is responses
    assert timeouts == [3]


def _stub_document(monkeypatch, tmp_path: Path, *, page_count: int = 1) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF")
    pages = []
    for number in range(1, page_count + 1):
        image_path = tmp_path / f"page-{number}.png"
        image_path.write_bytes(b"image")
        pages.append(
            PageEvidence(
                number=number,
                width=100,
                height=100,
                dpi=72,
                image_path=image_path,
                scanned=True,
            )
        )
    source = IngestedDocument(
        name="budget.pdf",
        sha256="a" * 64,
        source_path=source_path,
        pages=pages,
    )
    monkeypatch.setattr(pipeline, "ingest_document", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(
        pipeline, "render_annotated_pdf", lambda *_args, **_kwargs: b"%PDF"
    )


def test_parser_binds_one_runtime_without_changing_factory_signature_and_fails_closed(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_document(monkeypatch, tmp_path, page_count=2)

    class Responses:
        def __init__(self) -> None:
            self.calls = 0

        def parse(self, **kwargs: object) -> object:
            self.calls += 1
            assert kwargs["text_format"] is PageDraft
            return SimpleNamespace(
                output_parsed=PageDraft(
                    regions=[
                        RegionDraft(
                            type="paragraph",
                            reading_order=0,
                            text="uncertain",
                            confidence=0.1,
                        )
                    ]
                ),
                output=[],
                usage=SimpleNamespace(input_tokens=4, output_tokens=2),
            )

    responses = Responses()
    factory_calls: list[ParserConfig] = []
    gateways: list[OpenAIDocumentGateway] = []

    def factory(config: ParserConfig) -> OpenAIDocumentGateway:
        factory_calls.append(config)
        gateway = OpenAIDocumentGateway(
            config,
            client=SimpleNamespace(responses=responses),
        )
        gateways.append(gateway)
        return gateway

    result = pipeline.DocumentParser(
        ParserConfig(max_http_attempts=2),
        gateway_factory=factory,
    ).parse(b"pdf", "budget.pdf")

    payload = json.loads(result.json)
    assert len(factory_calls) == 2
    assert all(config is factory_calls[0] for config in factory_calls)
    assert len({id(gateway.runtime) for gateway in gateways}) == 1
    assert responses.calls == 2
    assert all(
        page.blocks[0].verification.value == "needs_review"
        for page in result.document.pages
    )
    assert payload["schema_version"] == "4.0.0"
    assert payload["metadata"]["runtime"]["http_attempts"] == 2
    assert all(
        denial["budget"] == "http_attempts"
        for denial in payload["metadata"]["runtime"]["budget_denials"]
    )
    assert [event.page for event in result.trace] == [1, 1, 2, 2]
    assert "runtime" not in json.loads(result.legacy_json)
    assert result.runtime_diagnostics is not None
    assert (
        result.runtime_diagnostics.model_dump(mode="json")
        == payload["metadata"]["runtime"]
    )


def test_parser_routes_repair_budget_exhaustion_to_review(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_document(monkeypatch, tmp_path, page_count=2)
    plan_calls: list[int] = []

    class Gateway:
        def __init__(self) -> None:
            self.input_tokens = 0
            self.output_tokens = 0
            self.usage = RunUsage()
            self.trace = []

        def bind_runtime(self, runtime: ProviderRuntime) -> None:
            self.runtime = runtime

        def draft_page(self, _page: PageEvidence) -> PageDraft:
            return PageDraft(
                regions=[
                    RegionDraft(
                        type="paragraph",
                        reading_order=0,
                        text="uncertain",
                        confidence=0.1,
                    )
                ]
            )

        def plan_page(self, page: PageEvidence, *_args, **_kwargs) -> PagePlan:
            plan_calls.append(page.number)
            return PagePlan(finish=True)

    result = pipeline.DocumentParser(
        ParserConfig(
            max_repair_rounds=1,
            max_page_concurrency=1,
        ),
        gateway_factory=lambda _config: Gateway(),
    ).parse(b"pdf", "budget.pdf")

    assert plan_calls == [1]
    denied_block = result.document.pages[1].blocks[0]
    assert denied_block.verification.value == "needs_review"
    assert "Manager repair budget exhausted" in (denied_block.verification_reason or "")
    assert result.runtime_diagnostics is not None
    assert result.runtime_diagnostics.budget_denials[-1].budget == "repair_rounds"


def test_targeted_span_budget_denial_preserves_literal_and_routes_to_review(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_document(monkeypatch, tmp_path)

    def render_crop(*_args, **_kwargs):
        output = _args[3]
        output.write_bytes(b"crop")
        return output

    monkeypatch.setattr(pipeline, "render_region_crop", render_crop)
    repair_calls = 0

    class Gateway:
        def __init__(self) -> None:
            self.input_tokens = 0
            self.output_tokens = 0
            self.usage = RunUsage()
            self.trace = []

        def bind_runtime(self, runtime: ProviderRuntime) -> None:
            self.runtime = runtime

        def draft_page(self, _page: PageEvidence) -> PageDraft:
            return PageDraft(
                regions=[
                    RegionDraft(
                        type="paragraph",
                        reading_order=0,
                        text="Code l23",
                        confidence=0.99,
                        bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                        atoms=[
                            AtomicDraft(
                                kind="line",
                                text="Code l23",
                                confidence=0.2,
                                bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                                low_confidence_spans=[{"start": 5, "end": 6}],
                            )
                        ],
                    )
                ]
            )

        def plan_page(self, *_args, **_kwargs) -> PagePlan:
            return PagePlan(finish=True)

        def inspect_quality_crops(self, *_args, **_kwargs) -> PageInspection:
            return PageInspection()

        def repair_spans(self, *_args, **_kwargs):
            nonlocal repair_calls
            repair_calls += 1
            raise AssertionError("repair call must be denied before provider admission")

    result = pipeline.DocumentParser(
        ParserConfig(max_repair_rounds=1),
        gateway_factory=lambda _config: Gateway(),
    ).parse(b"pdf", "budget.pdf")

    block = result.document.pages[0].blocks[0]
    assert repair_calls == 0
    assert block.text == "Code l23"
    assert block.atoms[0].low_confidence_spans
    assert block.verification.value == "needs_review"
    assert "Quality repair budget exhausted" in (block.verification_reason or "")


def test_runtime_config_defaults_environment_and_validation(monkeypatch) -> None:
    defaults = ParserConfig()
    assert defaults.provider_retry_attempts == 3
    assert defaults.max_model_calls is None
    assert defaults.max_http_attempts is None
    assert defaults.max_input_tokens is None
    assert defaults.max_output_tokens is None
    assert defaults.max_elapsed_seconds is None
    assert defaults.max_repair_rounds is None
    assert defaults.targeted_repair_context_padding is None

    monkeypatch.setenv("DOCPARSE_PROVIDER_CONCURRENCY", "7")
    monkeypatch.setenv("DOCPARSE_PROVIDER_RETRY_ATTEMPTS", "4")
    monkeypatch.setenv("DOCPARSE_MAX_MODEL_CALLS", "12")
    monkeypatch.setenv("DOCPARSE_MAX_HTTP_ATTEMPTS", "20")
    monkeypatch.setenv("DOCPARSE_MAX_INPUT_TOKENS", "100")
    monkeypatch.setenv("DOCPARSE_MAX_OUTPUT_TOKENS", "50")
    monkeypatch.setenv("DOCPARSE_MAX_ELAPSED_SECONDS", "12.5")
    monkeypatch.setenv("DOCPARSE_MAX_REPAIR_ROUNDS", "6")
    monkeypatch.setenv("DOCPARSE_TARGETED_REPAIR_CONTEXT_PADDING", "0.15")

    config = ParserConfig.from_env()
    assert config.provider_concurrency == 7
    assert config.provider_retry_attempts == 4
    assert config.max_model_calls == 12
    assert config.max_http_attempts == 20
    assert config.max_input_tokens == 100
    assert config.max_output_tokens == 50
    assert config.max_elapsed_seconds == 12.5
    assert config.max_repair_rounds == 6
    assert config.targeted_repair_context_padding == 0.15

    with pytest.raises(ValueError, match="provider_retry_attempts"):
        ParserConfig(provider_retry_attempts=0)
    with pytest.raises(ValueError, match="max_http_attempts"):
        ParserConfig(max_http_attempts=0)
    with pytest.raises(ValueError, match="targeted_repair_context_padding"):
        ParserConfig(targeted_repair_context_padding=0.6)
