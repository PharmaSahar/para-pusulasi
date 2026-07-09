from __future__ import annotations

from datetime import datetime, timezone
import sys

import pytest

from src.fact_bundle import FactRecord
from src.fact_bundle_providers import FactDataProvider, ProviderError
from src.fact_provider_registry import REGISTERED_FACT_PROVIDERS
from src.fact_sources import FactSourceError, TrustedFactProvider


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _patch_provider_urlopen(monkeypatch: pytest.MonkeyPatch, provider: object, payload: dict) -> None:
    module = sys.modules[provider.__class__.__module__]

    def _fake_urlopen(request, timeout):
        return _FakeResponse(payload)

    monkeypatch.setattr(module, "urlopen", _fake_urlopen)


@pytest.mark.parametrize(
    "entry_name, expected_method, payload, expected_key, expected_value, expected_unit",
    [
        ("market", "fetch", {"value": 100.25, "as_of": "2026-07-08T11:00:00Z"}, "sp500", 100.25, "index_points"),
        ("crypto", "fetch", {"price": 25000.5, "as_of": "2026-07-08T11:00:00Z"}, "btc_usd", 25000.5, "USD"),
        ("commodity", "fetch", {"price": 2441.25, "as_of": "2026-07-08T11:00:00Z"}, "gold_oz_usd", 2441.25, "USD"),
        ("macro", "fetch", {"value": 3.2, "as_of": "2026-07-08T11:00:00Z"}, "us_cpi_yoy", 3.2, "percent"),
        ("calendar", "fetch", {"value": 4, "as_of": "2026-07-08T11:00:00Z"}, "us_high_impact_events_today", 4.0, "calendar_points"),
        ("news", "fetch", {"value": 67.5, "as_of": "2026-07-08T11:00:00Z"}, "market_sentiment_score", 67.5, "news_points"),
    ],
)
def test_fact_data_providers_return_factbundle_compatible_payloads(
    monkeypatch: pytest.MonkeyPatch,
    entry_name: str,
    expected_method: str,
    payload: dict,
    expected_key: str,
    expected_value: float,
    expected_unit: str,
):
    entry = next(item for item in REGISTERED_FACT_PROVIDERS if item.name == entry_name)
    assert isinstance(entry.provider, FactDataProvider)

    _patch_provider_urlopen(monkeypatch, entry.provider, payload)

    response = getattr(entry.provider, expected_method)(expected_key)
    fact = response.to_fact_record()

    assert isinstance(response, object)
    assert isinstance(fact, FactRecord)
    assert fact.key == expected_key
    assert fact.value == pytest.approx(expected_value)
    assert fact.unit == expected_unit
    assert fact.collected_at.tzinfo is not None
    assert fact.collected_at.tzinfo.utcoffset(fact.collected_at) == timezone.utc.utcoffset(fact.collected_at)


def test_fx_provider_returns_factbundle_compatible_payload(monkeypatch: pytest.MonkeyPatch):
    entry = next(item for item in REGISTERED_FACT_PROVIDERS if item.name == "FX")
    assert isinstance(entry.provider, TrustedFactProvider)

    module = sys.modules[entry.provider.__class__.__module__]

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"rates": {"TRY": 31.75}})

    monkeypatch.setattr(module, "urlopen", _fake_urlopen)

    value = entry.provider.get_usd_try()

    assert value.name == "USD/TRY"
    assert value.value == pytest.approx(31.75)
    assert value.source


@pytest.mark.parametrize("entry_name", [entry.name for entry in REGISTERED_FACT_PROVIDERS if entry.name != "FX"])
def test_fact_data_provider_failures_raise_provider_errors(monkeypatch: pytest.MonkeyPatch, entry_name: str):
    entry = next(item for item in REGISTERED_FACT_PROVIDERS if item.name == entry_name)
    assert isinstance(entry.provider, FactDataProvider)

    module = sys.modules[entry.provider.__class__.__module__]

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(module, "urlopen", _fake_urlopen)

    with pytest.raises(ProviderError):
        if entry_name == "market":
            entry.provider.fetch("sp500")
        elif entry_name == "crypto":
            entry.provider.fetch("btc_usd")
        elif entry_name == "commodity":
            entry.provider.fetch("gold_oz_usd")
        elif entry_name == "macro":
            entry.provider.fetch("us_cpi_yoy")
        elif entry_name == "calendar":
            entry.provider.fetch("us_high_impact_events_today")
        else:
            entry.provider.fetch("market_sentiment_score")


def test_fx_provider_failures_raise_fact_source_error(monkeypatch: pytest.MonkeyPatch):
    entry = next(item for item in REGISTERED_FACT_PROVIDERS if item.name == "FX")

    module = sys.modules[entry.provider.__class__.__module__]

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"rates": {"EUR": 1.0}})

    monkeypatch.setattr(module, "urlopen", _fake_urlopen)

    with pytest.raises(FactSourceError):
        entry.provider.get_usd_try()
