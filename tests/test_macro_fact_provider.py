from __future__ import annotations

import json
from datetime import timezone

import pytest

import src.macro_fact_provider as macro_provider
from src.macro_fact_provider import LiveMacroFactProvider, MacroFactProviderError


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_macro_provider_fetches_supported_key(monkeypatch):
    provider = LiveMacroFactProvider(source_label="trusted_macro")

    def _fake_urlopen(request, timeout):
        assert "US_CPI_YOY" in request.full_url
        return _FakeResponse({"value": 3.2, "as_of": "2026-07-08T11:00:00Z"})

    monkeypatch.setattr(macro_provider, "urlopen", _fake_urlopen)

    response = provider.fetch("us_cpi_yoy")

    assert response.key == "us_cpi_yoy"
    assert response.value == pytest.approx(3.2)
    assert response.unit == "percent"
    assert response.source == "trusted_macro"
    assert response.collected_at.tzinfo is not None
    assert response.collected_at.tzinfo.utcoffset(response.collected_at) == timezone.utc.utcoffset(response.collected_at)


def test_macro_provider_rejects_unsupported_key():
    provider = LiveMacroFactProvider()

    with pytest.raises(MacroFactProviderError) as err:
        provider.fetch("eu_cpi_yoy")

    assert "unsupported_macro_key" in str(err.value)


def test_macro_provider_wraps_transport_errors(monkeypatch):
    provider = LiveMacroFactProvider()

    def _raise_transport(request, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(macro_provider, "urlopen", _raise_transport)

    with pytest.raises(MacroFactProviderError) as err:
        provider.fetch("us_policy_rate")

    assert "macro_fetch_failed" in str(err.value)


def test_macro_provider_rejects_malformed_payload(monkeypatch):
    provider = LiveMacroFactProvider()

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(macro_provider, "urlopen", _fake_urlopen)

    with pytest.raises(MacroFactProviderError) as err:
        provider.fetch("us_unemployment_rate")

    assert "macro_fetch_failed" in str(err.value)
