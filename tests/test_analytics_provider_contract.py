from __future__ import annotations

import json
import socket
from datetime import date, datetime, timezone

import pytest

from src.analytics_provider_contract import (
    AnalyticsProviderError,
    AnalyticsProviderPage,
    AnalyticsProviderRequest,
    AnalyticsProviderRow,
    InMemoryAnalyticsProvider,
    provider_row_to_snapshot,
)


def _build_request(**overrides):
    payload = {
        "provider_schema_version": "analytics-provider.v1",
        "channel_id": "channel_alpha",
        "youtube_channel_id": "UC-alpha",
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 7),
        "metrics": ("views", "likes"),
        "dimensions": ("content_type",),
        "content_types": ("LONG_FORM",),
        "page_size": 50,
        "cursor": None,
        "query_version": "q1",
    }
    payload.update(overrides)
    return AnalyticsProviderRequest(**payload)


def _build_row(**overrides):
    payload = {
        "channel_id": "channel_alpha",
        "youtube_channel_id": "UC-alpha",
        "internal_video_id": "video-001",
        "youtube_video_id": "yt-video-001",
        "content_job_id": "job-001",
        "content_type": "LONG_FORM",
        "snapshot_timestamp": datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        "publication_timestamp": datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
        "title_at_snapshot": "Example",
        "topic": "analytics",
        "topic_domain": "growth",
        "language": "en",
        "duration_seconds": 180,
        "thumbnail_identity": "thumb-001",
        "prompt_template_version": "v1",
        "impressions": 100,
        "impressions_ctr": 0.12,
        "views": 90,
        "watch_time_minutes": 15,
        "average_view_duration_seconds": 45.5,
        "average_percentage_viewed": 42.1,
        "subscribers_gained": 2,
        "subscribers_lost": 0,
        "likes": 5,
        "comments": 1,
        "shares": 1,
        "metric_source": "fixture",
        "provenance_reference": "fixture://evidence/001",
        "source_query_version": "q1",
        "freshness_status": "fresh",
        "completeness_status": "complete",
        "missing_fields": (),
        "partial_data_reason": None,
        "validation_status": "accepted",
    }
    payload.update(overrides)
    return AnalyticsProviderRow(**payload)


def test_valid_provider_request_is_accepted():
    request = _build_request()
    assert request.request_identity
    assert request.provider_schema_version == "analytics-provider.v1"


def test_request_identity_is_deterministic_for_metric_order_changes():
    first = _build_request(metrics=("views", "likes"))
    second = _build_request(metrics=("likes", "views"))
    assert first.request_identity == second.request_identity


def test_request_identity_is_deterministic_for_dimension_order_changes():
    first = _build_request(dimensions=("content_type", "topic"))
    second = _build_request(dimensions=("topic", "content_type"))
    assert first.request_identity == second.request_identity


def test_request_identity_is_deterministic_for_content_type_order_changes():
    first = _build_request(content_types=("LONG_FORM", "SHORT"))
    second = _build_request(content_types=("SHORT", "LONG_FORM"))
    assert first.request_identity == second.request_identity


def test_request_identity_changes_for_channel_change():
    first = _build_request(channel_id="channel_alpha")
    second = _build_request(channel_id="channel_beta")
    assert first.request_identity != second.request_identity


def test_request_identity_changes_for_date_range_change():
    first = _build_request(start_date=date(2026, 7, 1), end_date=date(2026, 7, 7))
    second = _build_request(start_date=date(2026, 7, 2), end_date=date(2026, 7, 8))
    assert first.request_identity != second.request_identity


def test_request_identity_changes_for_cursor_change():
    first = _build_request(cursor=None)
    second = _build_request(cursor="next-page")
    assert first.request_identity != second.request_identity


def test_invalid_page_size_is_rejected():
    with pytest.raises(ValueError):
        _build_request(page_size=0)


def test_missing_channel_is_rejected():
    with pytest.raises(ValueError):
        _build_request(channel_id="   ")


def test_unsupported_provider_schema_is_rejected():
    with pytest.raises(ValueError):
        _build_request(provider_schema_version="unsupported")


def test_valid_provider_row_is_accepted():
    row = _build_row()
    assert row.channel_id == "channel_alpha"


def test_null_remains_distinct_from_zero():
    zero_row = _build_row(views=0)
    null_row = _build_row(views=None)
    assert zero_row.views == 0
    assert null_row.views is None


def test_boolean_numeric_metric_is_rejected():
    with pytest.raises(ValueError):
        _build_row(views=True)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError):
        _build_row(snapshot_timestamp=datetime(2026, 7, 4, 12, 0))


def test_invalid_content_type_is_rejected():
    with pytest.raises(ValueError):
        _build_row(content_type="video")


def test_valid_provider_page_has_deterministic_response_identity():
    request = _build_request()
    page = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=request.request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=( _build_row(), ),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=("ok",),
    )
    assert page.response_identity
    assert page.request_identity == request.request_identity


def test_fetched_at_does_not_change_response_identity():
    request = _build_request()
    first = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=request.request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )
    second = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=request.request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )
    assert first.response_identity == second.response_identity


def test_row_change_changes_response_identity():
    request = _build_request()
    first = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=request.request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )
    second = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=request.request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(views=91),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )
    assert first.response_identity != second.response_identity


def test_has_more_true_requires_next_cursor():
    request = _build_request()
    with pytest.raises(ValueError):
        AnalyticsProviderPage(
            provider_schema_version="analytics-provider.v1",
            request_identity=request.request_identity,
            provider_name="fake",
            provider_query_version="q1",
            fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
            rows=(_build_row(),),
            next_cursor=None,
            has_more=True,
            source_freshness="fresh",
            warnings=(),
        )


def test_has_more_false_forbids_next_cursor():
    request = _build_request()
    with pytest.raises(ValueError):
        AnalyticsProviderPage(
            provider_schema_version="analytics-provider.v1",
            request_identity=request.request_identity,
            provider_name="fake",
            provider_query_version="q1",
            fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
            rows=(_build_row(),),
            next_cursor="next",
            has_more=False,
            source_freshness="fresh",
            warnings=(),
        )


def test_rows_remain_immutable():
    page = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=_build_request().request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )
    with pytest.raises(AttributeError):
        page.rows[0].views = 999  # type: ignore[attr-defined]


def test_warnings_serialize_deterministically():
    page = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=_build_request().request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=("warning-b", "warning-a"),
    )
    payload = page.to_payload()
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload
    assert payload["warnings"] == ["warning-a", "warning-b"]


def test_provider_error_category_and_retry_semantics_are_stable():
    error = AnalyticsProviderError("temporary", category="RATE_LIMITED", provider_name="fake", request_identity="req")
    assert error.category == "RATE_LIMITED"
    assert error.retryable is True
    assert error.to_payload()["retryable"] is True


def test_retry_after_seconds_rejects_negative_values():
    with pytest.raises(ValueError):
        AnalyticsProviderError("bad", category="RATE_LIMITED", provider_name="fake", request_identity="req", retry_after_seconds=-1)


def test_safe_error_representation_contains_no_traceback():
    error = AnalyticsProviderError("problem", category="INVALID_REQUEST", provider_name="fake", request_identity="req")
    payload = error.to_payload()
    assert "traceback" not in json.dumps(payload)
    assert payload["safe_message"] == "problem"


def test_fake_provider_returns_configured_first_page():
    page = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=_build_request().request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor="cursor-2",
        has_more=True,
        source_freshness="fresh",
        warnings=(),
    )
    provider = InMemoryAnalyticsProvider(provider_name="fake", pages={None: page})
    result = provider.fetch_analytics_page(_build_request())
    assert result.response_identity == page.response_identity


def test_fake_provider_supports_second_page():
    second_page = AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=_build_request(cursor="cursor-2").request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(views=91),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )
    provider = InMemoryAnalyticsProvider(provider_name="fake", pages={"cursor-2": second_page})
    request = _build_request(cursor="cursor-2")
    result = provider.fetch_analytics_page(request)
    assert result.rows[0].views == 91


def test_fake_provider_records_requests():
    provider = InMemoryAnalyticsProvider(provider_name="fake", pages={None: AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=_build_request().request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )})
    provider.fetch_analytics_page(_build_request())
    assert len(provider.requests) == 1


def test_fake_provider_simulates_rate_limit_and_transient_errors():
    provider = InMemoryAnalyticsProvider(
        provider_name="fake",
        pages={None: AnalyticsProviderPage(
            provider_schema_version="analytics-provider.v1",
            request_identity=_build_request().request_identity,
            provider_name="fake",
            provider_query_version="q1",
            fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
            rows=(_build_row(),),
            next_cursor=None,
            has_more=False,
            source_freshness="fresh",
            warnings=(),
        )},
        errors={"RATE_LIMITED": ("RATE_LIMITED", None)},
    )
    with pytest.raises(AnalyticsProviderError):
        provider.fetch_analytics_page(_build_request())


def test_fake_provider_simulates_permanent_error():
    provider = InMemoryAnalyticsProvider(
        provider_name="fake",
        pages={},
        errors={"PERMANENT_PROVIDER_ERROR": ("PERMANENT_PROVIDER_ERROR", None)},
    )
    with pytest.raises(AnalyticsProviderError):
        provider.fetch_analytics_page(_build_request())


def test_fake_provider_makes_no_network_call(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    provider = InMemoryAnalyticsProvider(provider_name="fake", pages={None: AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=_build_request().request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )})
    provider.fetch_analytics_page(_build_request())


def test_fake_provider_accesses_no_credentials(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    provider = InMemoryAnalyticsProvider(provider_name="fake", pages={None: AnalyticsProviderPage(
        provider_schema_version="analytics-provider.v1",
        request_identity=_build_request().request_identity,
        provider_name="fake",
        provider_query_version="q1",
        fetched_at=datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc),
        rows=(_build_row(),),
        next_cursor=None,
        has_more=False,
        source_freshness="fresh",
        warnings=(),
    )})
    result = provider.fetch_analytics_page(_build_request())
    assert result.rows[0].channel_id == "channel_alpha"


def test_provider_row_maps_to_snapshot():
    row = _build_row()
    snapshot = provider_row_to_snapshot(row)
    assert snapshot["channel_id"] == row.channel_id
    assert snapshot["youtube_video_id"] == row.youtube_video_id
    assert snapshot["content_type"] == row.content_type
