from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
