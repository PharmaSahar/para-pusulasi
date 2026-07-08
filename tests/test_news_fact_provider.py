from __future__ import annotations

import json
from datetime import timezone

import pytest

import src.news_fact_provider as news_provider
from src.news_fact_provider import LiveNewsFactProvider, NewsFactProviderError


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_news_provider_fetches_supported_key(monkeypatch):
    provider = LiveNewsFactProvider(source_label="trusted_news")

    def _fake_urlopen(request, timeout):
        assert "MARKET_SENTIMENT_SCORE" in request.full_url
        return _FakeResponse({"value": 67.5, "as_of": "2026-07-08T11:00:00Z"})

    monkeypatch.setattr(news_provider, "urlopen", _fake_urlopen)

    response = provider.fetch("market_sentiment_score")

    assert response.key == "market_sentiment_score"
    assert response.value == pytest.approx(67.5)
    assert response.unit == "news_points"
    assert response.source == "trusted_news"
    assert response.collected_at.tzinfo is not None
    assert response.collected_at.tzinfo.utcoffset(response.collected_at) == timezone.utc.utcoffset(response.collected_at)


def test_news_provider_rejects_unsupported_key():
    provider = LiveNewsFactProvider()

    with pytest.raises(NewsFactProviderError) as err:
        provider.fetch("central_bank_speech_count")

    assert "unsupported_news_key" in str(err.value)


def test_news_provider_wraps_transport_errors(monkeypatch):
    provider = LiveNewsFactProvider()

    def _raise_transport(request, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(news_provider, "urlopen", _raise_transport)

    with pytest.raises(NewsFactProviderError) as err:
        provider.fetch("risk_headline_count_24h")

    assert "news_fetch_failed" in str(err.value)


def test_news_provider_rejects_malformed_payload(monkeypatch):
    provider = LiveNewsFactProvider()

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(news_provider, "urlopen", _fake_urlopen)

    with pytest.raises(NewsFactProviderError) as err:
        provider.fetch("policy_headline_count_24h")

    assert "news_fetch_failed" in str(err.value)
