"""Provider layer for Fact Bundle Engine.

This module adds provider abstractions, registry management, and
primary/fallback resolution with timeout and structured errors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
import time

from .fact_bundle import FactRecord, FactTemporalScope, FactVolatility


class ProviderError(RuntimeError):
    """Base error for provider layer failures."""

    def __init__(self, message: str, *, provider_name: str | None = None, key: str | None = None):
        super().__init__(message)
        self.provider_name = provider_name
        self.key = key


class ProviderTimeoutError(ProviderError):
    """Raised when provider fetch exceeds timeout budget."""


class ProviderChainExhaustedError(ProviderError):
    """Raised when all primary/fallback providers fail."""

    def __init__(self, key: str, failures: list[str]):
        self.failures = failures
        message = f"provider_chain_exhausted for key={key}: " + " | ".join(failures)
        super().__init__(message, key=key)


@dataclass(frozen=True, slots=True)
class ProviderFactResponse:
    """Typed provider response before conversion into FactRecord."""

    key: str
    value: Any
    unit: str
    source: str
    collected_at: datetime
    confidence: float
    volatility: FactVolatility | str
    historical_current: FactTemporalScope | str
    ttl: int

    def to_fact_record(self) -> FactRecord:
        return FactRecord(
            key=self.key,
            value=self.value,
            unit=self.unit,
            source=self.source,
            collected_at=self.collected_at,
            confidence=self.confidence,
            volatility=self.volatility,
            historical_current=self.historical_current,
            ttl=self.ttl,
        )


class FactDataProvider(ABC):
    """Abstract provider contract for fetching canonical fact keys."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    def timeout_sec(self) -> float:
        return 5.0

    @abstractmethod
    def fetch(self, key: str) -> ProviderFactResponse:
        raise NotImplementedError


class ProviderRegistry:
    """In-memory registry for provider implementations."""

    def __init__(self):
        self._providers: dict[str, FactDataProvider] = {}

    def register(self, provider: FactDataProvider) -> None:
        name = provider.provider_name.strip()
        if not name:
            raise ProviderError("provider_name must be non-empty")
        if name in self._providers:
            raise ProviderError(f"provider already registered: {name}", provider_name=name)
        self._providers[name] = provider

    def get(self, provider_name: str) -> FactDataProvider:
        try:
            return self._providers[provider_name]
        except KeyError as e:
            raise ProviderError(f"provider not registered: {provider_name}", provider_name=provider_name) from e

    def names(self) -> tuple[str, ...]:
        return tuple(self._providers.keys())


@dataclass(frozen=True, slots=True)
class ProviderChainResult:
    """Result metadata for a resolved provider chain call."""

    fact: FactRecord
    selected_provider: str
    tried_providers: tuple[str, ...]
    failures: tuple[str, ...]
    fetched_at: datetime


def _run_with_timeout(fn: Callable[[], ProviderFactResponse], timeout_sec: float) -> ProviderFactResponse:
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_sec)
    except FuturesTimeoutError as e:
        # Do not wait for hung/slow provider task; continue fallback chain immediately.
        future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise ProviderTimeoutError(f"provider timeout after {timeout_sec:.2f}s") from e
    finally:
        if not future.cancelled():
            executor.shutdown(wait=False, cancel_futures=True)


def fetch_fact_with_provider_chain(
    *,
    registry: ProviderRegistry,
    key: str,
    primary_provider: str,
    fallback_providers: Iterable[str] = (),
    now_fn: Callable[[], datetime] | None = None,
) -> ProviderChainResult:
    """Resolve a fact through primary/fallback providers.

    Returns a normalized FactRecord plus resolution metadata.
    Raises ProviderChainExhaustedError when all providers fail.
    """
    providers_to_try = [primary_provider, *list(fallback_providers)]
    failures: list[str] = []
    tried: list[str] = []
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    for provider_name in providers_to_try:
        provider = registry.get(provider_name)
        tried.append(provider.provider_name)
        start = time.monotonic()
        try:
            response = _run_with_timeout(lambda: provider.fetch(key), provider.timeout_sec)
            fact = response.to_fact_record()
            return ProviderChainResult(
                fact=fact,
                selected_provider=provider.provider_name,
                tried_providers=tuple(tried),
                failures=tuple(failures),
                fetched_at=now_fn(),
            )
        except ProviderTimeoutError:
            elapsed = time.monotonic() - start
            failures.append(f"{provider.provider_name}: timeout ({elapsed:.3f}s)")
        except ProviderError as e:
            failures.append(f"{provider.provider_name}: {e}")

    raise ProviderChainExhaustedError(key, failures)


__all__ = [
    "FactDataProvider",
    "ProviderChainExhaustedError",
    "ProviderChainResult",
    "ProviderError",
    "ProviderFactResponse",
    "ProviderRegistry",
    "ProviderTimeoutError",
    "fetch_fact_with_provider_chain",
]