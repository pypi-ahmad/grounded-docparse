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
    PageDraft,
    PageInspection,
    RegionDraft,
)
from grounded_docparse.runtime import ProviderRuntime


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
    runtime = _runtime(ParserConfig(provider_retry_attempts=3))
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


def test_parser_binds_one_runtime_without_changing_factory_signature(
    monkeypatch, tmp_path: Path
) -> None:
    _stub_document(monkeypatch, tmp_path, page_count=2)

    class Responses:
        def __init__(self) -> None:
            self.calls = 0

        def parse(self, **kwargs: object) -> object:
            self.calls += 1
            text_format = kwargs["text_format"]
            if text_format is PageDraft:
                parsed = PageDraft(
                    regions=[
                        RegionDraft(
                            type="paragraph",
                            reading_order=0,
                            text="grounded",
                            confidence=1.0,
                        )
                    ]
                )
            else:
                assert text_format is PageInspection
                parsed = PageInspection()
            return SimpleNamespace(
                output_parsed=parsed,
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
        ParserConfig(),
        gateway_factory=factory,
    ).parse(b"pdf", "budget.pdf")

    payload = json.loads(result.json)
    assert len(factory_calls) == 2
    assert all(config is factory_calls[0] for config in factory_calls)
    assert len({id(gateway.runtime) for gateway in gateways}) == 1
    assert responses.calls >= 2
    assert all(page.blocks for page in result.document.pages)
    assert payload["schema_version"] == "4.4.0"
    assert payload["metadata"]["runtime"]["http_attempts"] == responses.calls
    assert result.runtime_diagnostics is not None
    assert (
        result.runtime_diagnostics.model_dump(mode="json")
        == payload["metadata"]["runtime"]
    )


def test_runtime_config_defaults_environment_and_validation(monkeypatch) -> None:
    defaults = ParserConfig()
    assert defaults.provider_retry_attempts == 3
    assert defaults.max_visual_recovery_crops == 64
    assert defaults.crop_padding == 0.1
    assert defaults.glm_form_recovery_enabled is True

    monkeypatch.setenv("DOCPARSE_PROVIDER_CONCURRENCY", "7")
    monkeypatch.setenv("DOCPARSE_PROVIDER_RETRY_ATTEMPTS", "4")
    monkeypatch.setenv("DOCPARSE_MAX_VISUAL_RECOVERY_CROPS", "6")
    monkeypatch.setenv("DOCPARSE_GLM_FORM_RECOVERY_ENABLED", "false")

    config = ParserConfig.from_env()
    assert config.provider_concurrency == 7
    assert config.provider_retry_attempts == 4
    assert config.max_visual_recovery_crops == 6
    assert config.glm_form_recovery_enabled is False

    with pytest.raises(ValueError, match="provider_retry_attempts"):
        ParserConfig(provider_retry_attempts=0)
    with pytest.raises(ValueError, match="max_visual_recovery_crops"):
        ParserConfig(max_visual_recovery_crops=0)
