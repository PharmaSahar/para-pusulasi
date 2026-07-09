from __future__ import annotations

import json
from datetime import timezone

import pytest

import src.commodity_fact_provider as commodity_provider
from src.commodity_fact_provider import CommodityFactProviderError, LiveCommodityFactProvider


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_commodity_provider_fetches_supported_key(monkeypatch):
    provider = LiveCommodityFactProvider(source_label="trusted_commodity")

    def _fake_urlopen(request, timeout):
        assert "XAUUSD" in request.full_url
        return _FakeResponse({"price": 2441.25, "as_of": "2026-07-08T11:00:00Z"})

    monkeypatch.setattr(commodity_provider, "urlopen", _fake_urlopen)

    response = provider.fetch("gold_oz_usd")

    assert response.key == "gold_oz_usd"
    assert response.value == pytest.approx(2441.25)
    assert response.unit == "USD"
    assert response.source == "trusted_commodity"
    assert response.collected_at.tzinfo is not None
    assert response.collected_at.tzinfo.utcoffset(response.collected_at) == timezone.utc.utcoffset(response.collected_at)


def test_commodity_provider_rejects_unsupported_key():
    provider = LiveCommodityFactProvider()

    with pytest.raises(CommodityFactProviderError) as err:
        provider.fetch("uranium_usd")

    assert "unsupported_commodity_key" in str(err.value)


def test_commodity_provider_wraps_transport_errors(monkeypatch):
    provider = LiveCommodityFactProvider()

    def _raise_transport(request, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(commodity_provider, "urlopen", _raise_transport)

    with pytest.raises(CommodityFactProviderError) as err:
        provider.fetch("silver_oz_usd")

    assert "commodity_fetch_failed" in str(err.value)


def test_commodity_provider_rejects_malformed_payload(monkeypatch):
    provider = LiveCommodityFactProvider()

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(commodity_provider, "urlopen", _fake_urlopen)

    with pytest.raises(CommodityFactProviderError) as err:
        provider.fetch("brent_usd_barrel")

    assert "commodity_fetch_failed" in str(err.value)
