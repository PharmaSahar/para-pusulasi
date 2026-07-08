from __future__ import annotations

import json
from datetime import timezone

import pytest

import src.calendar_fact_provider as calendar_provider
from src.calendar_fact_provider import CalendarFactProviderError, LiveCalendarFactProvider


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_calendar_provider_fetches_supported_key(monkeypatch):
    provider = LiveCalendarFactProvider(source_label="trusted_calendar")

    def _fake_urlopen(request, timeout):
        assert "US_HIGH_IMPACT_EVENTS_TODAY" in request.full_url
        return _FakeResponse({"value": 4, "as_of": "2026-07-08T11:00:00Z"})

    monkeypatch.setattr(calendar_provider, "urlopen", _fake_urlopen)

    response = provider.fetch("us_high_impact_events_today")

    assert response.key == "us_high_impact_events_today"
    assert response.value == pytest.approx(4.0)
    assert response.unit == "calendar_points"
    assert response.source == "trusted_calendar"
    assert response.collected_at.tzinfo is not None
    assert response.collected_at.tzinfo.utcoffset(response.collected_at) == timezone.utc.utcoffset(response.collected_at)


def test_calendar_provider_rejects_unsupported_key():
    provider = LiveCalendarFactProvider()

    with pytest.raises(CalendarFactProviderError) as err:
        provider.fetch("jp_high_impact_events_today")

    assert "unsupported_calendar_key" in str(err.value)


def test_calendar_provider_wraps_transport_errors(monkeypatch):
    provider = LiveCalendarFactProvider()

    def _raise_transport(request, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(calendar_provider, "urlopen", _raise_transport)

    with pytest.raises(CalendarFactProviderError) as err:
        provider.fetch("eu_high_impact_events_today")

    assert "calendar_fetch_failed" in str(err.value)


def test_calendar_provider_rejects_malformed_payload(monkeypatch):
    provider = LiveCalendarFactProvider()

    def _fake_urlopen(request, timeout):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr(calendar_provider, "urlopen", _fake_urlopen)

    with pytest.raises(CalendarFactProviderError) as err:
        provider.fetch("next_us_nfp_surprise_score")

    assert "calendar_fetch_failed" in str(err.value)
