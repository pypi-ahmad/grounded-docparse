from __future__ import annotations

import logging
import math
import random as random_module
import threading
import time
from collections.abc import Callable
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import TypeVar

from openai import APIConnectionError, APIStatusError

from .config import ParserConfig
from .models import RuntimeDiagnostics

T = TypeVar("T")
logger = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    def __init__(self, budget: str, detail: str) -> None:
        self.budget = budget
        self.detail = detail
        super().__init__(f"{budget} budget denied provider call: {detail}")


class RetryableProviderError(RuntimeError):
    """A provider response failed in a way that may succeed on retry."""


class ProviderRuntime:
    """Document-scoped provider retry, concurrency, and usage state."""

    def __init__(
        self,
        config: ParserConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        random: Callable[[], float] = random_module.random,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self._clock = clock
        self._sleeper = sleeper
        self._random = random
        self._wall_clock = wall_clock
        self._started = clock()
        self._condition = threading.Condition()
        self._active = 0
        self._effective_concurrency = config.provider_concurrency
        self._cooldown_until = self._started
        self._successes = 0
        self._full_page_fallbacks = 0
        self._max_full_page_fallbacks = 1
        self._model_calls = 0
        self._http_attempts = 0
        self._retries = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._rate_limit_events = 0
        self._limiter_wait_seconds = 0.0
        self._retry_sleep_seconds = 0.0

    def reserve_full_page_fallbacks(self, count: int) -> None:
        self._max_full_page_fallbacks = max(
            1, math.ceil(count * self.config.full_page_fallback_fraction)
        )

    def claim_full_page_fallback(self, *, page_number: int) -> None:
        with self._condition:
            if self._full_page_fallbacks >= self._max_full_page_fallbacks:
                raise BudgetExceeded(
                    "full_page_fallbacks",
                    f"limit {self._max_full_page_fallbacks} reached on page {page_number}",
                )
            self._full_page_fallbacks += 1

    def record_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        with self._condition:
            self._input_tokens += max(0, input_tokens)
            self._output_tokens += max(0, output_tokens)

    def request(
        self,
        call: Callable[[], T],
        *,
        model: str,
        stage: str,
        page_number: int | None = None,
        on_success: Callable[[T], None] | None = None,
    ) -> T:
        for attempt in range(1, self.config.provider_retry_attempts + 1):
            self._acquire()
            success = False
            rate_limited = False
            retry_after: float | None = None
            caught: Exception | None = None
            try:
                self._record_attempt(is_retry=attempt > 1)
                result = call()
                if on_success is not None:
                    on_success(result)
                success = True
            except Exception as exc:  # noqa: BLE001 - provider failures share retry policy
                caught = exc
                retry_after = self._retry_after(exc)
                rate_limited = self._status(exc) == 429
            finally:
                self._release(
                    success=success,
                    rate_limited=rate_limited,
                    retry_after=retry_after,
                )
            if caught is None:
                return result
            if not self._is_retryable(caught) or attempt == self.config.provider_retry_attempts:
                raise caught
            delay = (
                min(
                    self.config.provider_retry_cap_seconds,
                    self.config.provider_retry_base_seconds * (2 ** (attempt - 1)),
                )
                * self._random()
            )
            if retry_after is not None:
                delay = max(delay, retry_after)
            logger.warning(
                "Provider request retry scheduled: model=%s stage=%s page=%s attempt=%d/%d delay_seconds=%.2f error_type=%s",
                model,
                stage,
                page_number,
                attempt + 1,
                self.config.provider_retry_attempts,
                delay,
                type(caught).__name__,
            )
            if delay > 0:
                with self._condition:
                    self._retry_sleep_seconds += delay
                self._sleeper(delay)
        raise AssertionError("unreachable")

    def diagnostics(self) -> RuntimeDiagnostics:
        with self._condition:
            return RuntimeDiagnostics(
                model_calls=self._model_calls,
                full_page_fallbacks=self._full_page_fallbacks,
                http_attempts=self._http_attempts,
                retries=self._retries,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                rate_limit_events=self._rate_limit_events,
                configured_concurrency=self.config.provider_concurrency,
                effective_concurrency=self._effective_concurrency,
                cooldown_until=self._cooldown_until,
                elapsed_seconds=max(0.0, self._clock() - self._started),
                limiter_wait_seconds=self._limiter_wait_seconds,
                retry_sleep_seconds=self._retry_sleep_seconds,
            )

    def _acquire(self) -> None:
        started = self._clock()
        while True:
            cooldown = 0.0
            with self._condition:
                now = self._clock()
                if now < self._cooldown_until:
                    cooldown = self._cooldown_until - now
                elif self._active < self._effective_concurrency:
                    self._active += 1
                    self._limiter_wait_seconds += max(0.0, self._clock() - started)
                    return
                else:
                    self._condition.wait(timeout=0.05)
            if cooldown > 0:
                self._sleeper(cooldown)

    def _record_attempt(self, *, is_retry: bool) -> None:
        with self._condition:
            if not is_retry:
                self._model_calls += 1
            self._http_attempts += 1
            if is_retry:
                self._retries += 1

    def _release(
        self,
        *,
        success: bool,
        rate_limited: bool = False,
        retry_after: float | None = None,
    ) -> None:
        with self._condition:
            self._active -= 1
            if rate_limited:
                self._rate_limit_events += 1
                self._effective_concurrency = max(1, self._effective_concurrency // 2)
                cooldown = max(
                    self.config.provider_cooldown_seconds,
                    retry_after or 0.0,
                )
                self._cooldown_until = max(
                    self._cooldown_until, self._clock() + cooldown
                )
                self._successes = 0
            elif success:
                if self._clock() >= self._cooldown_until:
                    self._successes += 1
                    if (
                        self._successes >= self.config.provider_success_window
                        and self._effective_concurrency < self.config.provider_concurrency
                    ):
                        self._effective_concurrency += 1
                        self._successes = 0
            else:
                self._successes = 0
            self._condition.notify_all()

    @staticmethod
    def _status(exc: Exception) -> int | None:
        if isinstance(exc, APIStatusError):
            return exc.status_code
        code = getattr(exc, "code", None)
        return code if isinstance(code, int) and 100 <= code < 600 else None

    @classmethod
    def _is_retryable(cls, exc: Exception) -> bool:
        if isinstance(exc, (APIConnectionError, RetryableProviderError)):
            return True
        status = cls._status(exc)
        return status in {408, 409, 429} or (status is not None and 500 <= status < 600)

    def _retry_after(self, exc: Exception) -> float | None:
        if not isinstance(exc, APIStatusError):
            return None
        value = exc.response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return max(0.0, parsed.timestamp() - self._wall_clock())
            except (TypeError, ValueError, OverflowError):
                return None
