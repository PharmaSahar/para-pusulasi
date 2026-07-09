from __future__ import annotations

import json
from datetime import timezone

import pytest

import src.market_fact_provider as market_provider
from src.market_fact_provider import LiveMarketFactProvider, MarketFactProviderError


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_market_provider_fetches_supported_index(monkeypatch):
    provider = LiveMarketFactProvider(source_label="trusted_market")

    def _fake_urlopen(request, timeout):
        assert "XU100" in request.full_url
        return _FakeResponse({"value": 10342.55, "as_of": "2026-07-08T10:30:00Z"})

    monkeypatch.setattr(market_provider, "urlopen", _fake_urlopen)

    response = provider.fetch("bist100")

    assert response.key == "bist100"
    assert response.value == pytest.approx(10342.55)
    assert response.unit == "index_points"
    assert response.source == "trusted_market"
    assert response.collected_at.tzinfo is not None
    assert response.collected_at.tzinfo.utcoffset(response.collected_at) == timezone.utc.utcoffset(response.collected_at)


def test_market_provider_rejects_unsupported_key():
    provider = LiveMarketFactProvider()

    with pytest.raises(MarketFactProviderError) as err:
        provider.fetch("dowjones")

    assert "unsupported_market_key" in str(err.value)


def test_market_provider_wraps_transport_errors(monkeypatch):
    provider = LiveMarketFactProvider()

    def _raise_transport(request, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(market_provider, "urlopen", _raise_transport)

    with pytest.raises(MarketFactProviderError) as err:
        provider.fetch("sp500")

    assert "market_fetch_failed" in str(err.value)


def test_market_provider_rejects_malformed_payload(monkeypatch):
    provider = LiveMarketFactProvider()

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(market_provider, "urlopen", _fake_urlopen)

    with pytest.raises(MarketFactProviderError) as err:
        provider.fetch("nasdaq100")

    assert "market_fetch_failed" in str(err.value)
