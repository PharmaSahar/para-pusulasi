from __future__ import annotations

import json
from datetime import timezone

import pytest

import src.crypto_fact_provider as crypto_provider
from src.crypto_fact_provider import CryptoFactProviderError, LiveCryptoFactProvider


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_crypto_provider_fetches_supported_key(monkeypatch):
    provider = LiveCryptoFactProvider(source_label="trusted_crypto")

    def _fake_urlopen(request, timeout):
        assert "BTC-USD" in request.full_url
        return _FakeResponse({"price": 117250.12, "as_of": "2026-07-08T11:00:00Z"})

    monkeypatch.setattr(crypto_provider, "urlopen", _fake_urlopen)

    response = provider.fetch("btc_usd")

    assert response.key == "btc_usd"
    assert response.value == pytest.approx(117250.12)
    assert response.unit == "USD"
    assert response.source == "trusted_crypto"
    assert response.collected_at.tzinfo is not None
    assert response.collected_at.tzinfo.utcoffset(response.collected_at) == timezone.utc.utcoffset(response.collected_at)


def test_crypto_provider_rejects_unsupported_key():
    provider = LiveCryptoFactProvider()

    with pytest.raises(CryptoFactProviderError) as err:
        provider.fetch("sol_usd")

    assert "unsupported_crypto_key" in str(err.value)


def test_crypto_provider_wraps_transport_errors(monkeypatch):
    provider = LiveCryptoFactProvider()

    def _raise_transport(request, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(crypto_provider, "urlopen", _raise_transport)

    with pytest.raises(CryptoFactProviderError) as err:
        provider.fetch("eth_usd")

    assert "crypto_fetch_failed" in str(err.value)


def test_crypto_provider_rejects_malformed_payload(monkeypatch):
    provider = LiveCryptoFactProvider()

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(crypto_provider, "urlopen", _fake_urlopen)

    with pytest.raises(CryptoFactProviderError) as err:
        provider.fetch("btc_usd")

    assert "crypto_fetch_failed" in str(err.value)
