from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from grounded_docparse import pipeline
from grounded_docparse.config import ParserConfig
from grounded_docparse.gateways import OpenAIDocumentGateway
from grounded_docparse.ingest import IngestedDocument, PageEvidence
from grounded_docparse.models import PageDraft, RegionDraft
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


def _runtime(config: ParserConfig, fake_time: FakeTime | None = None) -> ProviderRuntime:
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
    runtime = ProviderRuntime(
        ParserConfig(provider_concurrency=1, max_input_tokens=1)
    )
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

    runtime.request(lambda: "ok", model="luna", stage="draft")
    runtime.request(lambda: "ok", model="luna", stage="draft")

    assert fake_time.sleeps == [2.0]
    assert runtime.diagnostics().effective_concurrency == 3


@pytest.mark.parametrize(
    ("config", "setup", "model", "budget"),
    [
        (ParserConfig(max_http_attempts=1), lambda runtime: None, "luna", "http_attempts"),
        (
            ParserConfig(max_terra_attempts=1),
            lambda runtime: None,
            "gpt-5.6-terra",
            "terra_attempts",
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

    if budget in {"http_attempts", "terra_attempts"}:
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
    runtime.reserve_base_drafts(2)
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


def test_default_gateway_disables_sdk_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def client(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(responses=object())

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("grounded_docparse.gateways.OpenAI", client)

    OpenAIDocumentGateway(ParserConfig())

    assert captured == {"max_retries": 0}


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
    monkeypatch.setattr(pipeline, "render_annotated_pdf", lambda *_args, **_kwargs: b"%PDF")


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
    assert payload["schema_version"] == "2.1.0"
    assert payload["metadata"]["runtime"]["http_attempts"] == 2
    assert all(
        denial["budget"] == "http_attempts"
        for denial in payload["metadata"]["runtime"]["budget_denials"]
    )
    assert [event.page for event in result.trace] == [1, 1, 2, 2]
    assert "runtime" not in json.loads(result.legacy_json)
    assert result.runtime_diagnostics is not None
    assert result.runtime_diagnostics.model_dump(mode="json") == payload["metadata"]["runtime"]


def test_runtime_config_defaults_environment_and_validation(monkeypatch) -> None:
    defaults = ParserConfig()
    assert defaults.provider_retry_attempts == 3
    assert defaults.max_http_attempts is None
    assert defaults.max_terra_attempts is None
    assert defaults.max_input_tokens is None
    assert defaults.max_output_tokens is None
    assert defaults.max_elapsed_seconds is None

    monkeypatch.setenv("DOCPARSE_PROVIDER_CONCURRENCY", "7")
    monkeypatch.setenv("DOCPARSE_PROVIDER_RETRY_ATTEMPTS", "4")
    monkeypatch.setenv("DOCPARSE_MAX_HTTP_ATTEMPTS", "20")
    monkeypatch.setenv("DOCPARSE_MAX_TERRA_ATTEMPTS", "5")
    monkeypatch.setenv("DOCPARSE_MAX_INPUT_TOKENS", "100")
    monkeypatch.setenv("DOCPARSE_MAX_OUTPUT_TOKENS", "50")
    monkeypatch.setenv("DOCPARSE_MAX_ELAPSED_SECONDS", "12.5")

    config = ParserConfig.from_env()
    assert config.provider_concurrency == 7
    assert config.provider_retry_attempts == 4
    assert config.max_http_attempts == 20
    assert config.max_terra_attempts == 5
    assert config.max_input_tokens == 100
    assert config.max_output_tokens == 50
    assert config.max_elapsed_seconds == 12.5

    with pytest.raises(ValueError, match="provider_retry_attempts"):
        ParserConfig(provider_retry_attempts=0)
    with pytest.raises(ValueError, match="max_http_attempts"):
        ParserConfig(max_http_attempts=0)
