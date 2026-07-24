from __future__ import annotations

import json
import os
import socket
from datetime import date, datetime, timezone

import pytest

from src.analytics_provider_contract import AnalyticsProviderError, AnalyticsProviderRequest
from src.credential_provider_contract import (
    CredentialDescriptor,
    CredentialProviderRequest,
    InMemoryCredentialProvider,
)
from src.youtube_data_mock_provider import YouTubeDataMockProvider, YouTubeDataMockProviderError


def _build_request(**overrides):
    payload = {
        "provider_schema_version": "analytics-provider.v1",
        "channel_id": "channel_alpha",
        "youtube_channel_id": "UC-mock-alpha",
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 7),
        "metrics": ("views", "likes"),
        "dimensions": ("content_type",),
        "content_types": ("LONG_FORM",),
        "page_size": 2,
        "cursor": None,
        "query_version": "mock-q1",
    }
    payload.update(overrides)
    return AnalyticsProviderRequest(**payload)


def _build_credential_provider():
    descriptors = [
        CredentialDescriptor(
            provider_name="fake",
            credential_identity="mock-credential-alpha",
            channel_id="channel_alpha",
            youtube_channel_id="UC-mock-alpha",
            scope_names=("youtube.readonly",),
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            refresh_supported=False,
            status="ACTIVE",
        )
    ]
    return InMemoryCredentialProvider(provider_name="fake", descriptors=descriptors)


def test_provider_creation_uses_credential_provider():
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    assert provider.provider_name == "youtube-data-mock"


def test_deterministic_output_for_repeat_requests():
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    first = provider.resolve(_build_request())
    second = provider.resolve(_build_request())
    assert first.to_payload() == second.to_payload()


def test_stable_ordering_by_publication_timestamp():
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    page = provider.resolve(_build_request())
    timestamps = [row.publication_timestamp for row in page.rows]
    assert timestamps == sorted(timestamps)


def test_pagination_and_cursor_progression():
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    first = provider.resolve(_build_request(page_size=2))
    assert len(first.rows) == 2
    assert first.next_cursor == "page-1"
    assert first.has_more is True

    second = provider.resolve(_build_request(page_size=2, cursor="page-1"))
    assert len(second.rows) == 2
    assert second.next_cursor == "page-2"
    assert second.has_more is True

    third = provider.resolve(_build_request(page_size=2, cursor="page-2"))
    assert len(third.rows) == 1
    assert third.next_cursor is None
    assert third.has_more is False


def test_cursor_end_raises_invalid_cursor_error():
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    with pytest.raises(YouTubeDataMockProviderError) as exc_info:
        provider.resolve(_build_request(cursor="page-99"))
    assert exc_info.value.category == "INVALID_CURSOR"


def test_metadata_mapping_is_preserved():
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    page = provider.resolve(_build_request(page_size=2))
    row = page.rows[0]
    assert row.title_at_snapshot == "Mock Alpha Video"
    assert row.topic_domain == "mock"
    assert row.duration_seconds == 180
    assert row.thumbnail_identity == "thumb-alpha-1"


def test_error_mapping_for_not_found():
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    with pytest.raises(YouTubeDataMockProviderError) as exc_info:
        provider.resolve(_build_request(channel_id="channel_missing"))
    assert exc_info.value.category == "NOT_FOUND"


def test_error_mapping_for_unsupported_resource():
    provider = YouTubeDataMockProvider(
        credential_provider=_build_credential_provider(),
        simulated_errors={"channel_alpha": "UNSUPPORTED_RESOURCE"},
    )
    with pytest.raises(YouTubeDataMockProviderError) as exc_info:
        provider.resolve(_build_request())
    assert exc_info.value.category == "UNSUPPORTED_RESOURCE"


def test_error_mapping_for_permission_denied():
    provider = YouTubeDataMockProvider(
        credential_provider=_build_credential_provider(),
        simulated_errors={"channel_alpha": "PERMISSION_DENIED"},
    )
    with pytest.raises(YouTubeDataMockProviderError) as exc_info:
        provider.resolve(_build_request())
    assert exc_info.value.category == "PERMISSION_DENIED"


def test_error_mapping_for_rate_limit():
    provider = YouTubeDataMockProvider(
        credential_provider=_build_credential_provider(),
        simulated_errors={"channel_alpha": "RATE_LIMIT"},
    )
    with pytest.raises(YouTubeDataMockProviderError) as exc_info:
        provider.resolve(_build_request())
    assert exc_info.value.category == "RATE_LIMIT"


def test_error_mapping_for_internal_error():
    provider = YouTubeDataMockProvider(
        credential_provider=_build_credential_provider(),
        simulated_errors={"channel_alpha": "INTERNAL_ERROR"},
    )
    with pytest.raises(YouTubeDataMockProviderError) as exc_info:
        provider.resolve(_build_request())
    assert exc_info.value.category == "INTERNAL_ERROR"


def test_no_network_or_oauth(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/should-not-use.json")

    def _fail(*args, **kwargs):
        raise AssertionError("network access should not occur")

    monkeypatch.setattr(socket, "create_connection", _fail)
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    page = provider.resolve(_build_request(page_size=2))
    assert page.rows


def test_fetch_analytics_page_aliases_resolve():
    provider = YouTubeDataMockProvider(credential_provider=_build_credential_provider())
    page = provider.fetch_analytics_page(_build_request())
    assert page.rows
