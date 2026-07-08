from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time

import pytest

from src.fact_bundle import (
    FactBundleProvider,
    FactRecord,
    FactSourceStatus,
    FactTemporalScope,
    FactValidationStatus,
    FactVolatility,
    create_fact_bundle,
    generate_fact_bundle_id,
)
from src.fact_bundle_cache import FactBundleCache
from src.fact_bundle_providers import (
    FactDataProvider,
    ProviderChainExhaustedError,
    ProviderError,
    ProviderFactResponse,
    ProviderRegistry,
    ProviderTimeoutError,
    fetch_fact_with_provider_chain,
)


def _fact(**overrides) -> FactRecord:
    base = {
        "key": "usd_try",
        "value": 46.84,
        "unit": "TRY",
        "source": "TCMB",
        "collected_at": datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
        "confidence": 0.95,
        "volatility": FactVolatility.HIGH,
        "historical_current": FactTemporalScope.CURRENT,
        "ttl": 300,
    }
    base.update(overrides)
    return FactRecord(**base)


class DummyProvider(FactBundleProvider):
    @property
    def provider_name(self) -> str:
        return "dummy"

    def fetch_fact(self, key: str) -> FactRecord:
        return _fact(key=key)


class DummyCache(FactBundleCache):
    def __init__(self):
        self.storage: dict[str, object] = {}

    def get(self, bundle_id: str):
        return self.storage.get(bundle_id)

    def set(self, bundle):
        self.storage[bundle.bundle_id] = bundle

    def invalidate(self, bundle_id: str) -> None:
        self.storage.pop(bundle_id, None)

    def clear(self) -> None:
        self.storage.clear()


def test_create_fact_bundle_populates_bundle_identity_and_expiry():
    created_at = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    source_status = FactSourceStatus(
        overall="healthy",
        primary_provider="tcmb",
        fallback_providers=("frankfurter",),
        checked_at=created_at,
    )

    bundle = create_fact_bundle([_fact()], source_status, ttl_seconds=300, created_at=created_at)

    assert bundle.schema_version == 1
    assert bundle.bundle_id
    assert bundle.created_at == created_at
    assert bundle.expires_at == created_at + timedelta(seconds=300)
    assert bundle.source_status == source_status
    assert bundle.validation_status == FactValidationStatus.UNVALIDATED
    assert len(bundle.facts) == 1


def test_generate_fact_bundle_id_is_unique_and_non_empty():
    first = generate_fact_bundle_id()
    second = generate_fact_bundle_id()

    assert first
    assert second
    assert first != second


def test_provider_and_cache_interfaces_are_abstract():
    with pytest.raises(TypeError):
        FactBundleProvider()

    with pytest.raises(TypeError):
        FactBundleCache()


def test_dummy_provider_and_cache_support_bundle_workflow():
    provider = DummyProvider()
    cache = DummyCache()
    source_status = FactSourceStatus(overall="healthy", primary_provider=provider.provider_name)
    bundle = create_fact_bundle(provider.fetch_facts(["usd_try"]), source_status, ttl_seconds=60)

    cache.set(bundle)

    assert cache.get(bundle.bundle_id) == bundle
    cache.invalidate(bundle.bundle_id)
    assert cache.get(bundle.bundle_id) is None


class DummyDataProvider(FactDataProvider):
    def __init__(self, name: str, response: ProviderFactResponse | None = None, err: Exception | None = None, timeout_sec: float = 0.2):
        self._name = name
        self._response = response
        self._err = err
        self._timeout_sec = timeout_sec

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def timeout_sec(self) -> float:
        return self._timeout_sec

    def fetch(self, key: str) -> ProviderFactResponse:
        if self._err:
            raise self._err
        assert self._response is not None
        return self._response


class SlowDataProvider(FactDataProvider):
    @property
    def provider_name(self) -> str:
        return "slow"

    @property
    def timeout_sec(self) -> float:
        return 0.01

    def fetch(self, key: str) -> ProviderFactResponse:
        time.sleep(0.2)
        return ProviderFactResponse(
            key=key,
            value=46.2,
            unit="TRY",
            source="slow",
            collected_at=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            confidence=0.8,
            volatility=FactVolatility.HIGH,
            historical_current=FactTemporalScope.CURRENT,
            ttl=60,
        )


def _provider_response(key: str = "usd_try", source: str = "provider_a", value: float = 46.84) -> ProviderFactResponse:
    return ProviderFactResponse(
        key=key,
        value=value,
        unit="TRY",
        source=source,
        collected_at=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
        confidence=0.95,
        volatility=FactVolatility.HIGH,
        historical_current=FactTemporalScope.CURRENT,
        ttl=120,
    )


def test_provider_registry_register_and_get():
    registry = ProviderRegistry()
    provider = DummyDataProvider(name="primary", response=_provider_response(source="primary"))

    registry.register(provider)

    assert registry.get("primary") is provider
    assert registry.names() == ("primary",)


def test_provider_registry_rejects_duplicate_names():
    registry = ProviderRegistry()
    registry.register(DummyDataProvider(name="dup", response=_provider_response(source="a")))

    with pytest.raises(ProviderError):
        registry.register(DummyDataProvider(name="dup", response=_provider_response(source="b")))


def test_provider_chain_uses_primary_when_successful():
    registry = ProviderRegistry()
    registry.register(DummyDataProvider(name="primary", response=_provider_response(source="primary", value=46.9)))
    registry.register(DummyDataProvider(name="fallback", response=_provider_response(source="fallback", value=47.0)))

    result = fetch_fact_with_provider_chain(
        registry=registry,
        key="usd_try",
        primary_provider="primary",
        fallback_providers=("fallback",),
    )

    assert result.selected_provider == "primary"
    assert result.fact.source == "primary"
    assert result.fact.value == 46.9
    assert result.tried_providers == ("primary",)


def test_provider_chain_falls_back_when_primary_fails():
    registry = ProviderRegistry()
    registry.register(DummyDataProvider(name="primary", err=RuntimeError("primary down")))
    registry.register(DummyDataProvider(name="fallback", response=_provider_response(source="fallback", value=47.1)))

    result = fetch_fact_with_provider_chain(
        registry=registry,
        key="usd_try",
        primary_provider="primary",
        fallback_providers=("fallback",),
    )

    assert result.selected_provider == "fallback"
    assert result.fact.source == "fallback"
    assert result.tried_providers == ("primary", "fallback")
    assert result.failures


def test_provider_chain_raises_when_all_providers_fail():
    registry = ProviderRegistry()
    registry.register(DummyDataProvider(name="primary", err=RuntimeError("primary down")))
    registry.register(DummyDataProvider(name="fallback", err=RuntimeError("fallback down")))

    with pytest.raises(ProviderChainExhaustedError) as err:
        fetch_fact_with_provider_chain(
            registry=registry,
            key="usd_try",
            primary_provider="primary",
            fallback_providers=("fallback",),
        )

    assert "provider_chain_exhausted" in str(err.value)
    assert len(err.value.failures) == 2


def test_provider_timeout_is_handled_and_fallback_is_used():
    registry = ProviderRegistry()
    registry.register(SlowDataProvider())
    registry.register(DummyDataProvider(name="fallback", response=_provider_response(source="fallback", value=47.3)))

    result = fetch_fact_with_provider_chain(
        registry=registry,
        key="usd_try",
        primary_provider="slow",
        fallback_providers=("fallback",),
    )

    assert result.selected_provider == "fallback"
    assert any("timeout" in failure for failure in result.failures)


def test_provider_timeout_raises_when_no_fallback():
    registry = ProviderRegistry()
    registry.register(SlowDataProvider())

    with pytest.raises(ProviderChainExhaustedError) as err:
        fetch_fact_with_provider_chain(
            registry=registry,
            key="usd_try",
            primary_provider="slow",
        )

    assert any("timeout" in failure for failure in err.value.failures)
