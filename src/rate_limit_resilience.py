from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping


class ResiliencePolicyError(RuntimeError):
    """Structured resilience error for retry, quota, and circuit outcomes."""

    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        retryable: bool,
        attempts: int,
        quota_budget: "QuotaBudget",
        circuit_breaker: "CircuitBreaker",
        retry_delays_ms: tuple[int, ...],
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.category = category
        self.retryable = retryable
        self.attempts = int(attempts)
        self.quota_budget = quota_budget
        self.circuit_breaker = circuit_breaker
        self.retry_delays_ms = tuple(retry_delays_ms)

    def to_payload(self) -> dict[str, Any]:
        return {
            "safe_message": self.safe_message,
            "category": self.category,
            "retryable": self.retryable,
            "attempts": self.attempts,
            "retry_delays_ms": list(self.retry_delays_ms),
            "quota_budget": self.quota_budget.to_payload(),
            "circuit_breaker": self.circuit_breaker.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class FailureDecision:
    category: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class QuotaBudget:
    total_tokens: int
    consumed_tokens: int = 0

    def __post_init__(self) -> None:
        total = int(self.total_tokens)
        consumed = int(self.consumed_tokens)
        if total <= 0:
            raise ValueError("total_tokens must be positive")
        if consumed < 0:
            raise ValueError("consumed_tokens must be nonnegative")
        if consumed > total:
            raise ValueError("consumed_tokens cannot exceed total_tokens")
        object.__setattr__(self, "total_tokens", total)
        object.__setattr__(self, "consumed_tokens", consumed)

    @property
    def remaining_tokens(self) -> int:
        return self.total_tokens - self.consumed_tokens

    def can_consume(self, tokens: int = 1) -> bool:
        required = max(0, int(tokens))
        return self.remaining_tokens >= required

    def consume(self, tokens: int = 1) -> "QuotaBudget":
        required = max(0, int(tokens))
        if not self.can_consume(required):
            raise ValueError("quota exhausted")
        return QuotaBudget(total_tokens=self.total_tokens, consumed_tokens=self.consumed_tokens + required)

    def to_payload(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "consumed_tokens": self.consumed_tokens,
            "remaining_tokens": self.remaining_tokens,
        }


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    initial_delay_ms: int
    multiplier: float
    max_delay_ms: int

    def __post_init__(self) -> None:
        if int(self.initial_delay_ms) <= 0:
            raise ValueError("initial_delay_ms must be positive")
        if float(self.multiplier) < 1.0:
            raise ValueError("multiplier must be >= 1")
        if int(self.max_delay_ms) < int(self.initial_delay_ms):
            raise ValueError("max_delay_ms must be >= initial_delay_ms")
        object.__setattr__(self, "initial_delay_ms", int(self.initial_delay_ms))
        object.__setattr__(self, "multiplier", float(self.multiplier))
        object.__setattr__(self, "max_delay_ms", int(self.max_delay_ms))

    def delay_ms_for_retry(self, retry_number: int) -> int:
        if int(retry_number) <= 0:
            raise ValueError("retry_number must be positive")
        candidate = int(round(self.initial_delay_ms * (self.multiplier ** (int(retry_number) - 1))))
        return min(self.max_delay_ms, candidate)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    retryable_categories: tuple[str, ...]

    def __post_init__(self) -> None:
        attempts = int(self.max_attempts)
        if attempts <= 0:
            raise ValueError("max_attempts must be positive")
        categories = tuple(sorted({str(value).strip() for value in self.retryable_categories}))
        if not categories or any(not value for value in categories):
            raise ValueError("retryable_categories must contain non-blank values")
        object.__setattr__(self, "max_attempts", attempts)
        object.__setattr__(self, "retryable_categories", categories)


@dataclass(frozen=True, slots=True)
class CircuitBreaker:
    failure_threshold: int
    recovery_timeout_seconds: int
    state: str = "CLOSED"
    consecutive_failures: int = 0
    opened_at: str | None = None

    def __post_init__(self) -> None:
        threshold = int(self.failure_threshold)
        timeout = int(self.recovery_timeout_seconds)
        if threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if timeout <= 0:
            raise ValueError("recovery_timeout_seconds must be positive")

        state = str(self.state or "").strip().upper()
        if state not in {"CLOSED", "OPEN", "HALF_OPEN"}:
            raise ValueError("state is invalid")

        failures = int(self.consecutive_failures)
        if failures < 0:
            raise ValueError("consecutive_failures must be nonnegative")

        opened_at = self.opened_at
        if opened_at is not None:
            opened_at = _parse_timestamp(opened_at).isoformat()

        object.__setattr__(self, "failure_threshold", threshold)
        object.__setattr__(self, "recovery_timeout_seconds", timeout)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "consecutive_failures", failures)
        object.__setattr__(self, "opened_at", opened_at)

    def transition(self, *, now: datetime) -> "CircuitBreaker":
        now_utc = _to_utc(now)
        if self.state != "OPEN" or self.opened_at is None:
            return self
        opened = _parse_timestamp(self.opened_at)
        if now_utc >= opened + timedelta(seconds=self.recovery_timeout_seconds):
            return CircuitBreaker(
                failure_threshold=self.failure_threshold,
                recovery_timeout_seconds=self.recovery_timeout_seconds,
                state="HALF_OPEN",
                consecutive_failures=0,
                opened_at=self.opened_at,
            )
        return self

    def allows_request(self, *, now: datetime) -> bool:
        transitioned = self.transition(now=now)
        return transitioned.state in {"CLOSED", "HALF_OPEN"}

    def on_success(self) -> "CircuitBreaker":
        return CircuitBreaker(
            failure_threshold=self.failure_threshold,
            recovery_timeout_seconds=self.recovery_timeout_seconds,
            state="CLOSED",
            consecutive_failures=0,
            opened_at=None,
        )

    def on_failure(self, *, now: datetime) -> "CircuitBreaker":
        now_utc = _to_utc(now)
        transitioned = self.transition(now=now_utc)

        if transitioned.state == "HALF_OPEN":
            return CircuitBreaker(
                failure_threshold=self.failure_threshold,
                recovery_timeout_seconds=self.recovery_timeout_seconds,
                state="OPEN",
                consecutive_failures=self.failure_threshold,
                opened_at=now_utc.isoformat(),
            )

        if transitioned.state == "OPEN":
            return transitioned

        failures = transitioned.consecutive_failures + 1
        if failures >= transitioned.failure_threshold:
            return CircuitBreaker(
                failure_threshold=transitioned.failure_threshold,
                recovery_timeout_seconds=transitioned.recovery_timeout_seconds,
                state="OPEN",
                consecutive_failures=failures,
                opened_at=now_utc.isoformat(),
            )

        return CircuitBreaker(
            failure_threshold=transitioned.failure_threshold,
            recovery_timeout_seconds=transitioned.recovery_timeout_seconds,
            state="CLOSED",
            consecutive_failures=failures,
            opened_at=None,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_seconds": self.recovery_timeout_seconds,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "opened_at": self.opened_at,
        }


class FailureClassifier:
    """Classifies execution failures into retryability categories."""

    def classify(self, error: Exception) -> FailureDecision:
        category = str(getattr(error, "category", "")).strip().upper()
        retryable = bool(getattr(error, "retryable", False))

        if category:
            return FailureDecision(category=category, retryable=retryable)

        message = str(error).lower()
        if "timeout" in message:
            return FailureDecision(category="TIMEOUT", retryable=True)
        if "rate" in message or "quota" in message:
            return FailureDecision(category="RATE_LIMIT", retryable=True)
        return FailureDecision(category="INTERNAL_ERROR", retryable=False)


@dataclass(frozen=True, slots=True)
class ResilienceResult:
    value: Any
    attempts: int
    retry_delays_ms: tuple[int, ...]
    quota_budget: QuotaBudget
    circuit_breaker: CircuitBreaker
    retry_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if int(self.attempts) <= 0:
            raise ValueError("attempts must be positive")
        object.__setattr__(self, "retry_delays_ms", tuple(int(value) for value in self.retry_delays_ms))
        object.__setattr__(self, "retry_metadata", dict(self.retry_metadata))


class RateLimitManager:
    """Centralized deterministic resilience manager for retry, quota, and circuit decisions."""

    def __init__(
        self,
        *,
        retry_policy: RetryPolicy,
        backoff_policy: BackoffPolicy,
        classifier: FailureClassifier | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._retry_policy = retry_policy
        self._backoff_policy = backoff_policy
        self._classifier = classifier or FailureClassifier()
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def execute(
        self,
        *,
        operation: Callable[[], Any],
        quota_budget: QuotaBudget,
        circuit_breaker: CircuitBreaker,
        retry_metadata: Mapping[str, Any] | None = None,
    ) -> ResilienceResult:
        quota = quota_budget
        circuit = circuit_breaker
        delays: list[int] = []
        bounded_retry_metadata = self._bounded_retry_metadata(retry_metadata or {})

        for attempt in range(1, self._retry_policy.max_attempts + 1):
            now = _to_utc(self._now_provider())
            circuit = circuit.transition(now=now)
            if not circuit.allows_request(now=now):
                raise ResiliencePolicyError(
                    "circuit open",
                    category="CIRCUIT_OPEN",
                    retryable=True,
                    attempts=attempt - 1,
                    quota_budget=quota,
                    circuit_breaker=circuit,
                    retry_delays_ms=tuple(delays),
                )

            if not quota.can_consume(1):
                raise ResiliencePolicyError(
                    "quota exhausted",
                    category="QUOTA_EXHAUSTED",
                    retryable=False,
                    attempts=attempt - 1,
                    quota_budget=quota,
                    circuit_breaker=circuit,
                    retry_delays_ms=tuple(delays),
                )

            quota = quota.consume(1)

            try:
                value = operation()
            except Exception as exc:
                decision = self._classifier.classify(exc)
                circuit = circuit.on_failure(now=now)

                if not decision.retryable or decision.category not in self._retry_policy.retryable_categories:
                    raise ResiliencePolicyError(
                        "permanent failure",
                        category=decision.category,
                        retryable=False,
                        attempts=attempt,
                        quota_budget=quota,
                        circuit_breaker=circuit,
                        retry_delays_ms=tuple(delays),
                    ) from exc

                if attempt >= self._retry_policy.max_attempts:
                    raise ResiliencePolicyError(
                        "retry exhausted",
                        category="RETRY_EXHAUSTED",
                        retryable=False,
                        attempts=attempt,
                        quota_budget=quota,
                        circuit_breaker=circuit,
                        retry_delays_ms=tuple(delays),
                    ) from exc

                delays.append(self._backoff_policy.delay_ms_for_retry(len(delays) + 1))
                continue

            circuit = circuit.on_success()
            return ResilienceResult(
                value=value,
                attempts=attempt,
                retry_delays_ms=tuple(delays),
                quota_budget=quota,
                circuit_breaker=circuit,
                retry_metadata=bounded_retry_metadata,
            )

        raise RuntimeError("unreachable")

    def _bounded_retry_metadata(self, retry_metadata: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(retry_metadata)
        requested = int(payload.get("max_attempts", self._retry_policy.max_attempts))
        payload["max_attempts"] = max(1, min(requested, self._retry_policy.max_attempts))
        return payload


def _to_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_timestamp(raw: str) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "BackoffPolicy",
    "CircuitBreaker",
    "FailureClassifier",
    "FailureDecision",
    "QuotaBudget",
    "RateLimitManager",
    "ResiliencePolicyError",
    "ResilienceResult",
    "RetryPolicy",
]
