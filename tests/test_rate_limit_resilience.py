from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.rate_limit_resilience import (
    BackoffPolicy,
    CircuitBreaker,
    QuotaBudget,
    RateLimitManager,
    ResiliencePolicyError,
    RetryPolicy,
)


class _Failure(Exception):
    def __init__(self, category: str, retryable: bool) -> None:
        super().__init__(category.lower())
        self.category = category
        self.retryable = retryable


class _Operation:
    def __init__(self, outcomes: list[str]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        mode = self._outcomes.pop(0)
        if mode == "success":
            return {"status": "ok", "calls": self.calls}
        if mode == "retryable":
            raise _Failure("TIMEOUT", True)
        if mode == "permanent":
            raise _Failure("PERMANENT", False)
        raise RuntimeError("unknown mode")


def _manager(now_provider=None, max_attempts: int = 4) -> RateLimitManager:
    return RateLimitManager(
        retry_policy=RetryPolicy(max_attempts=max_attempts, retryable_categories=("TIMEOUT", "RATE_LIMIT", "RETRYABLE")),
        backoff_policy=BackoffPolicy(initial_delay_ms=100, multiplier=2.0, max_delay_ms=1000),
        now_provider=now_provider,
    )


def test_retry_success() -> None:
    op = _Operation(["retryable", "success"])
    result = _manager().execute(
        operation=op,
        quota_budget=QuotaBudget(total_tokens=5),
        circuit_breaker=CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=60),
        retry_metadata={"trace": "alpha", "max_attempts": 9},
    )

    assert result.attempts == 2
    assert result.retry_delays_ms == (100,)
    assert result.quota_budget.remaining_tokens == 3
    assert result.retry_metadata["trace"] == "alpha"
    assert result.retry_metadata["max_attempts"] == 4


def test_retry_exhaustion() -> None:
    op = _Operation(["retryable", "retryable", "retryable"])
    with pytest.raises(ResiliencePolicyError) as exc_info:
        _manager(max_attempts=3).execute(
            operation=op,
            quota_budget=QuotaBudget(total_tokens=5),
            circuit_breaker=CircuitBreaker(failure_threshold=9, recovery_timeout_seconds=60),
        )

    assert exc_info.value.category == "RETRY_EXHAUSTED"
    assert exc_info.value.attempts == 3
    assert exc_info.value.retry_delays_ms == (100, 200)


def test_permanent_failure() -> None:
    op = _Operation(["permanent"])
    with pytest.raises(ResiliencePolicyError) as exc_info:
        _manager().execute(
            operation=op,
            quota_budget=QuotaBudget(total_tokens=5),
            circuit_breaker=CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=60),
        )

    assert exc_info.value.category == "PERMANENT"
    assert exc_info.value.retryable is False
    assert exc_info.value.attempts == 1


def test_quota_depletion() -> None:
    op = _Operation(["retryable", "success"])
    with pytest.raises(ResiliencePolicyError) as exc_info:
        _manager(max_attempts=3).execute(
            operation=op,
            quota_budget=QuotaBudget(total_tokens=1),
            circuit_breaker=CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=60),
        )

    assert exc_info.value.category == "QUOTA_EXHAUSTED"


def test_circuit_breaker_transitions() -> None:
    now_box = {"value": datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)}

    def _now() -> datetime:
        return now_box["value"]

    manager = _manager(now_provider=_now, max_attempts=1)
    circuit = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=60)
    quota = QuotaBudget(total_tokens=10)

    with pytest.raises(ResiliencePolicyError) as first:
        manager.execute(operation=_Operation(["permanent"]), quota_budget=quota, circuit_breaker=circuit)
    circuit = first.value.circuit_breaker

    with pytest.raises(ResiliencePolicyError) as second:
        manager.execute(operation=_Operation(["permanent"]), quota_budget=first.value.quota_budget, circuit_breaker=circuit)
    circuit = second.value.circuit_breaker

    assert circuit.state == "OPEN"

    with pytest.raises(ResiliencePolicyError) as blocked:
        manager.execute(operation=_Operation(["success"]), quota_budget=second.value.quota_budget, circuit_breaker=circuit)
    assert blocked.value.category == "CIRCUIT_OPEN"

    now_box["value"] = now_box["value"] + timedelta(seconds=61)
    recovered = manager.execute(
        operation=_Operation(["success"]),
        quota_budget=blocked.value.quota_budget,
        circuit_breaker=circuit,
    )
    assert recovered.circuit_breaker.state == "CLOSED"


def test_deterministic_backoff() -> None:
    op = _Operation(["retryable", "retryable", "retryable", "success"])
    result = _manager(max_attempts=5).execute(
        operation=op,
        quota_budget=QuotaBudget(total_tokens=10),
        circuit_breaker=CircuitBreaker(failure_threshold=10, recovery_timeout_seconds=60),
    )
    assert result.retry_delays_ms == (100, 200, 400)


def test_invalid_policy_configuration_rejected() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0, retryable_categories=("TIMEOUT",))
    with pytest.raises(ValueError):
        BackoffPolicy(initial_delay_ms=0, multiplier=2.0, max_delay_ms=100)
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0, recovery_timeout_seconds=10)


def test_immutable_models() -> None:
    quota = QuotaBudget(total_tokens=5)
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=60)

    with pytest.raises(AttributeError):
        quota.total_tokens = 7
    with pytest.raises(AttributeError):
        breaker.state = "OPEN"


def test_no_forbidden_runtime_behaviors_in_source() -> None:
    source = Path("src/rate_limit_resilience.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "scheduler",
        "cron",
        "polling",
        "upload",
        "deploy",
        "production",
        "write_text(",
        ".write(",
        "asyncio.gather",
        "thread",
    ]
    for token in forbidden:
        assert token not in source
