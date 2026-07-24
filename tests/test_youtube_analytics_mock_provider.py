from __future__ import annotations

import os
import socket
from datetime import date, datetime, timezone

import pytest

from src.analytics_provider_contract import AnalyticsProviderError, AnalyticsProviderRequest
from src.youtube_analytics_mock_provider import YouTubeAnalyticsMockProvider


def _build_request(**overrides):
    payload = {
        "provider_schema_version": "analytics-provider.v1",
        "channel_id": "channel_alpha",
        "youtube_channel_id": "UC-alpha",
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 5),
        "metrics": ("views", "likes", "watch_time_minutes", "average_percentage_viewed", "impressions", "impressions_ctr"),
        "dimensions": ("content_type",),
        "content_types": ("LONG_FORM",),
        "page_size": 3,
        "cursor": None,
        "query_version": "CHANNEL_DAILY",
    }
    payload.update(overrides)
    request = AnalyticsProviderRequest(**payload)
    return request


def test_provider_creation_is_supported():
    provider = YouTubeAnalyticsMockProvider()
    assert provider.provider_name == "youtube-analytics-mock"
    assert hasattr(provider, "fetch_analytics_page")


def test_channel_daily_output_is_deterministic():
    provider = YouTubeAnalyticsMockProvider()
    first = provider.fetch_analytics_page(_build_request())
    second = provider.fetch_analytics_page(_build_request())
    assert first.to_payload() == second.to_payload()


def test_video_daily_output_is_deterministic():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request(query_version="VIDEO_DAILY", page_size=4)
    first = provider.fetch_analytics_page(request)
    second = provider.fetch_analytics_page(request)
    assert first.to_payload() == second.to_payload()


def test_rows_are_stably_ordered_by_day_then_video():
    provider = YouTubeAnalyticsMockProvider()
    page = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=10))
    dates = [row.publication_timestamp for row in page.rows]
    assert dates == sorted(dates)


def test_inclusive_start_and_end_dates_are_preserved():
    provider = YouTubeAnalyticsMockProvider()
    page = provider.fetch_analytics_page(_build_request(start_date=date(2026, 7, 2), end_date=date(2026, 7, 4)))
    days = {row.publication_timestamp.date().isoformat() for row in page.rows}
    assert days == {"2026-07-02", "2026-07-03", "2026-07-04"}


def test_invalid_date_range_raises_error():
    provider = YouTubeAnalyticsMockProvider()
    with pytest.raises(ValueError):
        _build_request(start_date=date(2026, 7, 5), end_date=date(2026, 7, 4))


def test_metric_types_are_preserved():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request(
        query_version="VIDEO_DAILY",
        metrics=("views", "likes", "watch_time_minutes", "average_percentage_viewed", "impressions", "impressions_ctr"),
        page_size=5,
    )
    page = provider.fetch_analytics_page(request)
    row = page.rows[0]
    assert isinstance(row.views, int)
    assert isinstance(row.likes, int)
    assert isinstance(row.watch_time_minutes, int)
    assert isinstance(row.average_percentage_viewed, float)
    assert isinstance(row.impressions_ctr, float)


def test_ctr_representation_is_preserved_for_zero_impressions():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request(query_version="VIDEO_DAILY", page_size=10)
    page = provider.fetch_analytics_page(request)
    zero_row = next(row for row in page.rows if row.views == 0)
    assert zero_row.impressions == 0
    assert zero_row.impressions_ctr is None
    assert "impressions_ctr" in zero_row.missing_fields


def test_partial_data_is_marked_and_not_coerced_to_zero():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request(query_version="VIDEO_DAILY", page_size=10)
    page = provider.fetch_analytics_page(request)
    partial_row = next(row for row in page.rows if row.partial_data_reason == "unavailable_metric")
    assert partial_row.completeness_status == "partial"
    assert partial_row.impressions_ctr is None
    assert partial_row.partial_data_reason == "unavailable_metric"


def test_pagination_first_page_has_next_cursor():
    provider = YouTubeAnalyticsMockProvider()
    page = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=2))
    assert len(page.rows) == 2
    assert page.next_cursor == "page-1"
    assert page.has_more is True


def test_pagination_middle_and_final_pages_are_stable():
    provider = YouTubeAnalyticsMockProvider()
    first = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=2))
    second = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=2, cursor="page-1"))
    third = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=2, cursor="page-2"))
    assert first.next_cursor == "page-1"
    assert second.next_cursor == "page-2"
    assert third.next_cursor is None
    assert third.has_more is False
    assert len(first.rows) + len(second.rows) + len(third.rows) == 5


def test_no_duplicate_or_skipped_rows_across_pages():
    provider = YouTubeAnalyticsMockProvider()
    first = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=3))
    second = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=3, cursor="page-1"))
    third = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=3, cursor="page-2"))
    all_ids = [row.provenance_reference for row in (*first.rows, *second.rows, *third.rows)]
    assert len(all_ids) == len(set(all_ids))


def test_invalid_cursor_maps_to_error():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request(query_version="VIDEO_DAILY", cursor="page-99")
    with pytest.raises(AnalyticsProviderError) as exc_info:
        provider.fetch_analytics_page(request)
    assert exc_info.value.category == "INVALID_CURSOR"


def test_unsupported_query_family_is_rejected():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request(query_version="UNSUPPORTED")
    with pytest.raises(AnalyticsProviderError) as exc_info:
        provider.fetch_analytics_page(request)
    assert exc_info.value.category == "UNSUPPORTED_QUERY_FAMILY"


def test_unsupported_metric_is_rejected():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request()
    object.__setattr__(request, "metrics", ("unsupported_metric",))
    with pytest.raises(AnalyticsProviderError) as exc_info:
        provider.fetch_analytics_page(request)
    assert exc_info.value.category == "UNSUPPORTED_METRIC"


def test_unsupported_dimension_is_rejected():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request()
    object.__setattr__(request, "dimensions", ("unsupported_dimension",))
    with pytest.raises(AnalyticsProviderError) as exc_info:
        provider.fetch_analytics_page(request)
    assert exc_info.value.category == "UNSUPPORTED_DIMENSION"


def test_channel_mismatch_is_rejected():
    provider = YouTubeAnalyticsMockProvider()
    request = _build_request(channel_id="channel_other")
    with pytest.raises(AnalyticsProviderError) as exc_info:
        provider.fetch_analytics_page(request)
    assert exc_info.value.category == "CHANNEL_MISMATCH"


def test_permission_denied_mapping_is_used():
    provider = YouTubeAnalyticsMockProvider(simulated_errors={"channel_alpha": "PERMISSION_DENIED"})
    with pytest.raises(AnalyticsProviderError) as exc_info:
        provider.fetch_analytics_page(_build_request())
    assert exc_info.value.category == "PERMISSION_DENIED"


def test_rate_limit_mapping_is_used():
    provider = YouTubeAnalyticsMockProvider(simulated_errors={"channel_alpha": "RATE_LIMITED"})
    with pytest.raises(AnalyticsProviderError) as exc_info:
        provider.fetch_analytics_page(_build_request())
    assert exc_info.value.category == "RATE_LIMITED"


def test_internal_error_mapping_is_used():
    provider = YouTubeAnalyticsMockProvider(simulated_errors={"channel_alpha": "INTERNAL_ERROR"})
    with pytest.raises(AnalyticsProviderError) as exc_info:
        provider.fetch_analytics_page(_build_request())
    assert exc_info.value.category == "INTERNAL_ERROR"


def test_response_serialization_is_stable_and_safe():
    provider = YouTubeAnalyticsMockProvider()
    page = provider.fetch_analytics_page(_build_request())
    payload = page.to_payload()
    assert payload["request_identity"]
    assert payload["response_identity"]
    assert all("token" not in str(item).lower() for item in payload["rows"])


def test_repeated_execution_returns_identical_payload():
    provider = YouTubeAnalyticsMockProvider()
    first = provider.fetch_analytics_page(_build_request())
    second = provider.fetch_analytics_page(_build_request())
    assert first.to_payload() == second.to_payload()


def test_no_system_clock_dependency():
    provider = YouTubeAnalyticsMockProvider(fixed_now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc))
    page = provider.fetch_analytics_page(_build_request())
    assert page.fetched_at == datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


def test_no_network_or_oauth(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/should-not-use.json")
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network access should not occur")))
    provider = YouTubeAnalyticsMockProvider()
    page = provider.fetch_analytics_page(_build_request())
    assert page.rows


def test_no_live_identifiers_are_emitted():
    provider = YouTubeAnalyticsMockProvider()
    page = provider.fetch_analytics_page(_build_request(query_version="VIDEO_DAILY", page_size=10))
    for row in page.rows:
        assert row.youtube_video_id.startswith("mock-video")
        assert row.internal_video_id.startswith("mock-video")
        assert "youtube.com" not in row.provenance_reference
