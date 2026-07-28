from __future__ import annotations

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
from .models import RuntimeBudgetDenial, RuntimeDiagnostics

T = TypeVar("T")


class BudgetExceeded(RuntimeError):
    def __init__(self, budget: str, detail: str) -> None:
        self.budget = budget
        self.detail = detail
        super().__init__(f"{budget} budget denied provider call: {detail}")


class ProviderRuntime:
    """Document-scoped provider admission, retry, and budget state."""

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
        self._reserved_base_drafts = 0
        self._full_page_fallbacks = 0
        self._max_full_page_fallbacks = 1
        self._model_calls = 0
        self._http_attempts = 0
        self._retries = 0
        self._repair_rounds = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._rate_limit_events = 0
        self._limiter_wait_seconds = 0.0
        self._retry_sleep_seconds = 0.0
        self._budget_denials: list[RuntimeBudgetDenial] = []

    def reserve_full_page_fallbacks(self, count: int) -> None:
        with self._condition:
            self._max_full_page_fallbacks = max(
                1, math.ceil(count * self.config.full_page_fallback_fraction)
            )
            reserved = self._max_full_page_fallbacks
            if (
                self.config.max_model_calls is not None
                and reserved > self.config.max_model_calls
            ):
                self._deny(
                    "model_calls",
                    f"limit {self.config.max_model_calls} cannot cover {reserved} fallbacks",
                    stage="run_preflight",
                    model=self.config.luna_model,
                    page_number=None,
                )
            if (
                self.config.max_http_attempts is not None
                and reserved > self.config.max_http_attempts
            ):
                self._deny(
                    "http_attempts",
                    f"limit {self.config.max_http_attempts} cannot cover {reserved} fallbacks",
                    stage="run_preflight",
                    model=self.config.luna_model,
                    page_number=None,
                )
            if (
                self.config.max_model_calls is None
                and self.config.max_http_attempts is None
            ):
                return
            self._reserved_base_drafts = max(self._reserved_base_drafts, reserved)

    def release_full_page_fallback_reservations(self) -> None:
        with self._condition:
            self._reserved_base_drafts = 0

    def claim_full_page_fallback(self, *, page_number: int) -> None:
        with self._condition:
            if self._full_page_fallbacks >= self._max_full_page_fallbacks:
                self._deny(
                    "full_page_fallbacks",
                    f"limit {self._max_full_page_fallbacks} reached",
                    stage="page_draft_fallback",
                    model=self.config.luna_model,
                    page_number=page_number,
                )
            self._full_page_fallbacks += 1

    def claim_repair_round(
        self,
        *,
        stage: str,
        model: str,
        page_number: int | None = None,
    ) -> None:
        with self._condition:
            if (
                self.config.max_repair_rounds is not None
                and self._repair_rounds >= self.config.max_repair_rounds
            ):
                self._deny(
                    "repair_rounds",
                    f"limit {self.config.max_repair_rounds} reached",
                    stage=stage,
                    model=model,
                    page_number=page_number,
                )
            self._repair_rounds += 1

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
        base_draft: bool = False,
        on_success: Callable[[T], None] | None = None,
    ) -> T:
        reservation_claimed = False
        for attempt in range(1, self.config.provider_retry_attempts + 1):
            self._acquire()
            success: bool | None = None
            rate_limited = False
            retry_after: float | None = None
            caught: Exception | None = None
            provider_completed = False
            try:
                reservation_claimed = self._start_attempt(
                    model=model,
                    stage=stage,
                    page_number=page_number,
                    base_draft=base_draft,
                    reservation_claimed=reservation_claimed,
                    is_retry=attempt > 1,
                )
                result = call()
                provider_completed = True
                if on_success is not None:
                    on_success(result)
                self._check_elapsed_budget(
                    stage=stage,
                    model=model,
                    page_number=page_number,
                )
                success = True
            except Exception as exc:  # noqa: BLE001 - provider failures share retry policy
                caught = exc
                success = (
                    False
                    if provider_completed or not isinstance(exc, BudgetExceeded)
                    else None
                )
                if not provider_completed:
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

            retryable = not provider_completed and self._is_retryable(caught)
            if not retryable or attempt == self.config.provider_retry_attempts:
                raise caught
            self._ensure_retry_allowed(
                model=model,
                stage=stage,
                page_number=page_number,
                base_draft=base_draft,
                reservation_claimed=reservation_claimed,
            )
            delay = (
                min(
                    self.config.provider_retry_cap_seconds,
                    self.config.provider_retry_base_seconds * (2 ** (attempt - 1)),
                )
                * self._random()
            )
            if retry_after is not None:
                delay = max(delay, retry_after)
            if delay > 0:
                with self._condition:
                    self._retry_sleep_seconds += delay
                self._sleeper(delay)
        raise AssertionError("unreachable")

    def remaining_seconds(self) -> float | None:
        if self.config.max_elapsed_seconds is None:
            return None
        elapsed = self._clock() - self._started
        return max(0.001, self.config.max_elapsed_seconds - elapsed)

    def diagnostics(self) -> RuntimeDiagnostics:
        with self._condition:
            return RuntimeDiagnostics(
                model_calls=self._model_calls,
                full_page_fallbacks=self._full_page_fallbacks,
                http_attempts=self._http_attempts,
                retries=self._retries,
                repair_rounds=self._repair_rounds,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                rate_limit_events=self._rate_limit_events,
                configured_concurrency=self.config.provider_concurrency,
                effective_concurrency=self._effective_concurrency,
                cooldown_until=self._cooldown_until,
                elapsed_seconds=max(0.0, self._clock() - self._started),
                limiter_wait_seconds=self._limiter_wait_seconds,
                retry_sleep_seconds=self._retry_sleep_seconds,
                budget_denials=list(self._budget_denials),
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

    def _start_attempt(
        self,
        *,
        model: str,
        stage: str,
        page_number: int | None,
        base_draft: bool,
        reservation_claimed: bool,
        is_retry: bool,
    ) -> bool:
        with self._condition:
            self._check_nonattempt_budgets(
                stage=stage, model=model, page_number=page_number
            )
            logical_call = not is_retry

            claim = (
                base_draft
                and not reservation_claimed
                and self._reserved_base_drafts > 0
            )
            reserved_after = self._reserved_base_drafts - (1 if claim else 0)
            if logical_call and self.config.max_model_calls is not None:
                remaining_after_call = (
                    self.config.max_model_calls - self._model_calls - 1
                )
                if remaining_after_call < reserved_after:
                    detail = f"limit {self.config.max_model_calls} reached"
                    if reserved_after:
                        detail += f"; {reserved_after} base draft calls reserved"
                    self._deny(
                        "model_calls",
                        detail,
                        stage=stage,
                        model=model,
                        page_number=page_number,
                    )
            if self.config.max_http_attempts is not None:
                remaining_after_attempt = (
                    self.config.max_http_attempts - self._http_attempts - 1
                )
                if remaining_after_attempt < reserved_after:
                    detail = f"limit {self.config.max_http_attempts} reached"
                    if reserved_after:
                        detail += f"; {reserved_after} base draft attempts reserved"
                    self._deny(
                        "http_attempts",
                        detail,
                        stage=stage,
                        model=model,
                        page_number=page_number,
                    )

            if claim:
                self._reserved_base_drafts -= 1
            if logical_call:
                self._model_calls += 1
            self._http_attempts += 1
            if is_retry:
                self._retries += 1
            return reservation_claimed or claim

    def _ensure_retry_allowed(
        self,
        *,
        model: str,
        stage: str,
        page_number: int | None,
        base_draft: bool,
        reservation_claimed: bool,
    ) -> None:
        with self._condition:
            self._check_nonattempt_budgets(
                stage=stage,
                model=model,
                page_number=page_number,
            )
            claim = (
                base_draft
                and not reservation_claimed
                and self._reserved_base_drafts > 0
            )
            reserved_after = self._reserved_base_drafts - (1 if claim else 0)
            if (
                self.config.max_http_attempts is not None
                and self.config.max_http_attempts - self._http_attempts - 1
                < reserved_after
            ):
                detail = f"limit {self.config.max_http_attempts} reached"
                if reserved_after:
                    detail += f"; {reserved_after} base draft attempts reserved"
                self._deny(
                    "http_attempts",
                    detail,
                    stage=stage,
                    model=model,
                    page_number=page_number,
                )

    def _check_nonattempt_budgets(
        self, *, stage: str, model: str, page_number: int | None
    ) -> None:
        checks = (
            ("input_tokens", self._input_tokens, self.config.max_input_tokens),
            ("output_tokens", self._output_tokens, self.config.max_output_tokens),
        )
        for budget, used, limit in checks:
            if limit is not None and used >= limit:
                self._deny(
                    budget,
                    f"limit {limit} reached",
                    stage=stage,
                    model=model,
                    page_number=page_number,
                )
        self._check_elapsed_budget(stage=stage, model=model, page_number=page_number)

    def _check_elapsed_budget(
        self, *, stage: str, model: str, page_number: int | None
    ) -> None:
        with self._condition:
            elapsed = self._clock() - self._started
            if (
                self.config.max_elapsed_seconds is not None
                and elapsed >= self.config.max_elapsed_seconds
            ):
                self._deny(
                    "elapsed_seconds",
                    f"limit {self.config.max_elapsed_seconds} reached",
                    stage=stage,
                    model=model,
                    page_number=page_number,
                )

    def _deny(
        self,
        budget: str,
        detail: str,
        *,
        stage: str,
        model: str,
        page_number: int | None,
    ) -> None:
        self._budget_denials.append(
            RuntimeBudgetDenial(
                budget=budget,
                stage=stage,
                model=model,
                page=page_number,
                reason=detail,
            )
        )
        raise BudgetExceeded(budget, detail)

    def _release(
        self,
        *,
        success: bool | None,
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
                        and self._effective_concurrency
                        < self.config.provider_concurrency
                    ):
                        self._effective_concurrency += 1
                        self._successes = 0
            elif success is False:
                self._successes = 0
            self._condition.notify_all()

    @staticmethod
    def _status(exc: Exception) -> int | None:
        return exc.status_code if isinstance(exc, APIStatusError) else None

    @classmethod
    def _is_retryable(cls, exc: Exception) -> bool:
        if isinstance(exc, APIConnectionError):
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
