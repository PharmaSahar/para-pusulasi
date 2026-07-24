from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .analytics_provider_contract import (
    AnalyticsProviderError,
    AnalyticsProviderPage,
    AnalyticsProviderRequest,
    AnalyticsProviderRow,
)
from .credential_provider_contract import (
    CredentialDescriptor,
    CredentialProviderError,
    CredentialProviderRequest,
    CredentialProvider,
)

SUPPORTED_PROVIDER_SCHEMA_VERSION = "analytics-provider.v1"
SUPPORTED_ERROR_CATEGORIES = {
    "NOT_FOUND",
    "INVALID_CURSOR",
    "UNSUPPORTED_RESOURCE",
    "PERMISSION_DENIED",
    "RATE_LIMIT",
    "INTERNAL_ERROR",
}


class YouTubeDataMockProviderError(RuntimeError):
    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        request_identity: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.category = category
        self.retryable = retryable
        self.safe_message = safe_message
        self.request_identity = request_identity

    def to_payload(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "retryable": self.retryable,
            "safe_message": self.safe_message,
            "request_identity": self.request_identity,
        }


@dataclass(frozen=True, slots=True)
class MockVideoRecord:
    internal_video_id: str
    youtube_video_id: str
    content_job_id: str
    content_type: str
    publication_timestamp: datetime
    title: str
    topic: str
    topic_domain: str
    language: str
    duration_seconds: int
    thumbnail_identity: str
    views: int
    likes: int
    comments: int
    privacy_status: str


class YouTubeDataMockProvider:
    provider_name = "youtube-data-mock"

    def __init__(
        self,
        *,
        credential_provider: CredentialProvider,
        simulated_errors: Mapping[str, str] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._simulated_errors = dict(simulated_errors or {})
        self._records = self._build_records()

    def fetch_analytics_page(self, request: AnalyticsProviderRequest) -> AnalyticsProviderPage:
        return self.resolve(request)

    def resolve(self, request: AnalyticsProviderRequest) -> AnalyticsProviderPage:
        self._require_credential(request)
        self._raise_simulated_error(request)

        if request.cursor in {"page-99"}:
            raise YouTubeDataMockProviderError(
                "invalid cursor",
                category="INVALID_CURSOR",
                request_identity=request.request_identity,
            )

        page_size = int(request.page_size)
        ordered_records = sorted(self._records, key=lambda item: item.publication_timestamp)
        start_index = 0 if request.cursor is None else self._cursor_to_index(request.cursor)
        page_records = ordered_records[start_index : start_index + page_size]
        has_more = (start_index + page_size) < len(ordered_records)
        next_cursor = None if not has_more else self._index_to_cursor(start_index + page_size)

        rows = tuple(
            self._build_row(request, record, index=start_index + idx)
            for idx, record in enumerate(page_records)
        )
        return AnalyticsProviderPage(
            provider_schema_version=SUPPORTED_PROVIDER_SCHEMA_VERSION,
            request_identity=request.request_identity,
            provider_name=self.provider_name,
            provider_query_version=request.query_version,
            fetched_at=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            rows=rows,
            next_cursor=next_cursor,
            has_more=has_more,
            source_freshness="mock-fresh",
            warnings=(),
        )

    def _require_credential(self, request: AnalyticsProviderRequest) -> None:
        credential_request = CredentialProviderRequest(
            provider_schema_version="credential-provider.v1",
            provider_name="fake",
            channel_id=request.channel_id,
            youtube_channel_id=request.youtube_channel_id,
            credential_kind="YOUTUBE_DATA",
            credential_identity="mock-credential-alpha",
        )
        try:
            self._credential_provider.resolve(credential_request)
        except CredentialProviderError as exc:
            if exc.category == "UNSUPPORTED_PROVIDER":
                raise YouTubeDataMockProviderError(
                    exc.safe_message,
                    category="NOT_FOUND",
                    request_identity=request.request_identity,
                ) from exc
            if exc.category == "NOT_FOUND":
                raise YouTubeDataMockProviderError(
                    exc.safe_message,
                    category="NOT_FOUND",
                    request_identity=request.request_identity,
                ) from exc
            if exc.category == "CHANNEL_MISMATCH":
                raise YouTubeDataMockProviderError(
                    exc.safe_message,
                    category="NOT_FOUND",
                    request_identity=request.request_identity,
                ) from exc
            raise YouTubeDataMockProviderError(
                exc.safe_message,
                category="INTERNAL_ERROR",
                request_identity=request.request_identity,
            ) from exc

    def _raise_simulated_error(self, request: AnalyticsProviderRequest) -> None:
        selected = self._simulated_errors.get(request.channel_id)
        if selected is None:
            return
        category = str(selected).strip().upper()
        if category not in SUPPORTED_ERROR_CATEGORIES:
            raise YouTubeDataMockProviderError(
                "unsupported simulated error",
                category="INTERNAL_ERROR",
                request_identity=request.request_identity,
            )
        raise YouTubeDataMockProviderError(
            f"simulated {category.lower()}",
            category=category,
            request_identity=request.request_identity,
            retryable=category in {"RATE_LIMIT"},
        )

    def _build_row(self, request: AnalyticsProviderRequest, record: MockVideoRecord, *, index: int) -> AnalyticsProviderRow:
        snapshot_timestamp = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
        publication_timestamp = record.publication_timestamp
        return AnalyticsProviderRow(
            channel_id=request.channel_id,
            youtube_channel_id=request.youtube_channel_id,
            internal_video_id=record.internal_video_id,
            youtube_video_id=record.youtube_video_id,
            content_job_id=record.content_job_id,
            content_type=record.content_type,
            snapshot_timestamp=snapshot_timestamp,
            publication_timestamp=publication_timestamp,
            title_at_snapshot=record.title,
            topic=record.topic,
            topic_domain=record.topic_domain,
            language=record.language,
            duration_seconds=record.duration_seconds,
            thumbnail_identity=record.thumbnail_identity,
            prompt_template_version="mock-v1",
            impressions=record.views + 5,
            impressions_ctr=0.12 + (index * 0.01),
            views=record.views,
            watch_time_minutes=record.views // 10,
            average_view_duration_seconds=180.0,
            average_percentage_viewed=72.5,
            subscribers_gained=1,
            subscribers_lost=0,
            likes=record.likes,
            comments=record.comments,
            shares=1,
            metric_source="youtube_data_mock",
            provenance_reference=f"mock://channel/{request.channel_id}/video/{record.youtube_video_id}",
            source_query_version=request.query_version,
            freshness_status="fresh",
            completeness_status="complete",
            missing_fields=(),
            partial_data_reason=None,
            validation_status="accepted",
        )

    def _build_records(self) -> list[MockVideoRecord]:
        return [
            MockVideoRecord(
                internal_video_id="video-001",
                youtube_video_id="yt-001",
                content_job_id="job-001",
                content_type="LONG_FORM",
                publication_timestamp=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
                title="Mock Alpha Video",
                topic="mock",
                topic_domain="mock",
                language="en",
                duration_seconds=180,
                thumbnail_identity="thumb-alpha-1",
                views=120,
                likes=15,
                comments=3,
                privacy_status="public",
            ),
            MockVideoRecord(
                internal_video_id="video-002",
                youtube_video_id="yt-002",
                content_job_id="job-002",
                content_type="LONG_FORM",
                publication_timestamp=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
                title="Mock Beta Video",
                topic="mock",
                topic_domain="mock",
                language="en",
                duration_seconds=240,
                thumbnail_identity="thumb-beta-2",
                views=250,
                likes=24,
                comments=8,
                privacy_status="public",
            ),
            MockVideoRecord(
                internal_video_id="video-003",
                youtube_video_id="yt-003",
                content_job_id="job-003",
                content_type="LONG_FORM",
                publication_timestamp=datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc),
                title="Mock Gamma Video",
                topic="mock",
                topic_domain="mock",
                language="en",
                duration_seconds=300,
                thumbnail_identity="thumb-gamma-3",
                views=380,
                likes=38,
                comments=12,
                privacy_status="public",
            ),
            MockVideoRecord(
                internal_video_id="video-004",
                youtube_video_id="yt-004",
                content_job_id="job-004",
                content_type="LONG_FORM",
                publication_timestamp=datetime(2026, 7, 4, 10, 0, tzinfo=timezone.utc),
                title="Mock Delta Video",
                topic="mock",
                topic_domain="mock",
                language="en",
                duration_seconds=210,
                thumbnail_identity="thumb-delta-4",
                views=430,
                likes=47,
                comments=14,
                privacy_status="public",
            ),
            MockVideoRecord(
                internal_video_id="video-005",
                youtube_video_id="yt-005",
                content_job_id="job-005",
                content_type="LONG_FORM",
                publication_timestamp=datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc),
                title="Mock Epsilon Video",
                topic="mock",
                topic_domain="mock",
                language="en",
                duration_seconds=260,
                thumbnail_identity="thumb-epsilon-5",
                views=510,
                likes=53,
                comments=17,
                privacy_status="public",
            ),
        ]

    def _cursor_to_index(self, cursor: str) -> int:
        normalized = str(cursor or "").strip()
        if normalized == "page-1":
            return 2
        if normalized == "page-2":
            return 4
        if normalized == "page-3":
            return 6
        raise YouTubeDataMockProviderError(
            "invalid cursor",
            category="INVALID_CURSOR",
            request_identity=None,
        )

    def _index_to_cursor(self, index: int) -> str:
        if index == 2:
            return "page-1"
        if index == 4:
            return "page-2"
        if index == 6:
            return "page-3"
        return ""
