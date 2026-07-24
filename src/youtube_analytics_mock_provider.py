from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

from .analytics_provider_contract import (
    AnalyticsProviderError,
    AnalyticsProviderPage,
    AnalyticsProviderRequest,
    AnalyticsProviderRow,
)

SUPPORTED_PROVIDER_SCHEMA_VERSION = "analytics-provider.v1"
SUPPORTED_QUERY_FAMILIES = {"CHANNEL_DAILY", "VIDEO_DAILY"}
SUPPORTED_METRICS = {
    "impressions",
    "impressions_ctr",
    "views",
    "watch_time_minutes",
    "average_view_duration_seconds",
    "average_percentage_viewed",
    "subscribers_gained",
    "subscribers_lost",
    "likes",
    "comments",
    "shares",
}
SUPPORTED_DIMENSIONS = {"content_type", "topic", "topic_domain", "language"}
SUPPORTED_CONTENT_TYPES = {"LONG_FORM", "SHORT"}


@dataclass(frozen=True, slots=True)
class _FixtureRow:
    day: date
    video_id: str
    channel_id: str
    youtube_channel_id: str
    views: int
    watch_time_minutes: int
    average_view_duration_seconds: float
    average_percentage_viewed: float
    impressions: int
    impressions_ctr: float | None
    likes: int
    comments: int
    shares: int
    subscribers_gained: int
    subscribers_lost: int
    partial: bool = False
    missing_metrics: tuple[str, ...] = ()


class YouTubeAnalyticsMockProvider:
    provider_name = "youtube-analytics-mock"

    def __init__(self, *, simulated_errors: Mapping[str, str] | None = None, fixed_now: datetime | None = None) -> None:
        self._simulated_errors = dict(simulated_errors or {})
        self._fixed_now = fixed_now
        self._fixture_rows = self._build_fixture_rows()

    def fetch_analytics_page(self, request: AnalyticsProviderRequest) -> AnalyticsProviderPage:
        self._validate_request(request)
        self._raise_simulated_error(request)
        query_family = str(request.query_version or "").strip().upper()
        if query_family not in SUPPORTED_QUERY_FAMILIES:
            raise AnalyticsProviderError(
                "unsupported query family",
                category="UNSUPPORTED_QUERY_FAMILY",
                provider_name=self.provider_name,
                request_identity=request.request_identity,
            )

        rows = self._build_rows(request, query_family)
        ordered_rows = sorted(rows, key=lambda row: (row.publication_timestamp, row.youtube_video_id))
        page_size = int(request.page_size)
        cursor = request.cursor
        start_index = 0 if cursor is None else self._cursor_to_index(cursor, page_size)
        page_rows = ordered_rows[start_index : start_index + page_size]
        has_more = (start_index + page_size) < len(ordered_rows)
        next_cursor = None if not has_more else self._index_to_cursor(start_index + page_size, page_size)
        if has_more and not next_cursor:
            next_cursor = self._index_to_cursor(start_index + page_size, page_size) or "page-1"

        return AnalyticsProviderPage(
            provider_schema_version=SUPPORTED_PROVIDER_SCHEMA_VERSION,
            request_identity=request.request_identity,
            provider_name=self.provider_name,
            provider_query_version=query_family,
            fetched_at=self._now(),
            rows=tuple(page_rows),
            next_cursor=next_cursor,
            has_more=has_more,
            source_freshness="mock-fresh",
            warnings=(),
        )

    def _validate_request(self, request: AnalyticsProviderRequest) -> None:
        if request.channel_id != "channel_alpha":
            raise AnalyticsProviderError(
                "channel mismatch",
                category="CHANNEL_MISMATCH",
                provider_name=self.provider_name,
                request_identity=request.request_identity,
            )
        if request.youtube_channel_id != "UC-alpha":
            raise AnalyticsProviderError(
                "channel mismatch",
                category="CHANNEL_MISMATCH",
                provider_name=self.provider_name,
                request_identity=request.request_identity,
            )
        if request.start_date > request.end_date:
            raise AnalyticsProviderError(
                "invalid date range",
                category="INVALID_DATE_RANGE",
                provider_name=self.provider_name,
                request_identity=request.request_identity,
            )
        for metric in request.metrics:
            if metric not in SUPPORTED_METRICS:
                raise AnalyticsProviderError(
                    "unsupported metric",
                    category="UNSUPPORTED_METRIC",
                    provider_name=self.provider_name,
                    request_identity=request.request_identity,
                )
        for dimension in request.dimensions:
            if dimension not in SUPPORTED_DIMENSIONS:
                raise AnalyticsProviderError(
                    "unsupported dimension",
                    category="UNSUPPORTED_DIMENSION",
                    provider_name=self.provider_name,
                    request_identity=request.request_identity,
                )
        for content_type in request.content_types:
            if content_type not in SUPPORTED_CONTENT_TYPES:
                raise AnalyticsProviderError(
                    "unsupported content type",
                    category="UNSUPPORTED_CONTENT_TYPE",
                    provider_name=self.provider_name,
                    request_identity=request.request_identity,
                )

    def _raise_simulated_error(self, request: AnalyticsProviderRequest) -> None:
        selected = self._simulated_errors.get(request.channel_id)
        if selected is None:
            return
        category = str(selected).strip().upper()
        if category == "PERMISSION_DENIED":
            raise AnalyticsProviderError(
                "permission denied",
                category="PERMISSION_DENIED",
                provider_name=self.provider_name,
                request_identity=request.request_identity,
            )
        if category == "RATE_LIMITED":
            raise AnalyticsProviderError(
                "rate limited",
                category="RATE_LIMITED",
                provider_name=self.provider_name,
                request_identity=request.request_identity,
                retry_after_seconds=60,
            )
        if category == "INTERNAL_ERROR":
            raise AnalyticsProviderError(
                "internal error",
                category="INTERNAL_ERROR",
                provider_name=self.provider_name,
                request_identity=request.request_identity,
            )
        raise AnalyticsProviderError(
            "internal error",
            category="INTERNAL_ERROR",
            provider_name=self.provider_name,
            request_identity=request.request_identity,
        )

    def _build_rows(self, request: AnalyticsProviderRequest, query_family: str) -> list[AnalyticsProviderRow]:
        rows: list[AnalyticsProviderRow] = []
        for fixture in self._fixture_rows:
            if fixture.day < request.start_date or fixture.day > request.end_date:
                continue
            if query_family == "CHANNEL_DAILY":
                rows.append(self._build_channel_row(request, fixture))
            else:
                rows.append(self._build_video_row(request, fixture))
        return rows

    def _build_channel_row(self, request: AnalyticsProviderRequest, fixture: _FixtureRow) -> AnalyticsProviderRow:
        return self._build_row(request, fixture, internal_video_id=f"mock-channel-{fixture.day.day:02d}")

    def _build_video_row(self, request: AnalyticsProviderRequest, fixture: _FixtureRow) -> AnalyticsProviderRow:
        return self._build_row(request, fixture, internal_video_id=fixture.video_id)

    def _build_row(self, request: AnalyticsProviderRequest, fixture: _FixtureRow, *, internal_video_id: str) -> AnalyticsProviderRow:
        metric_source = "youtube_analytics_mock"
        provenance_reference = f"mock://analytics/{request.channel_id}/{internal_video_id}"
        missing_fields: list[str] = []
        impressions = fixture.impressions
        impressions_ctr = fixture.impressions_ctr
        views = fixture.views
        likes = fixture.likes
        comments = fixture.comments
        shares = fixture.shares
        watch_time_minutes = fixture.watch_time_minutes
        average_view_duration_seconds = fixture.average_view_duration_seconds
        average_percentage_viewed = fixture.average_percentage_viewed
        subscribers_gained = fixture.subscribers_gained
        subscribers_lost = fixture.subscribers_lost
        partial_data_reason = None
        completeness_status = "complete"
        if fixture.partial:
            completeness_status = "partial"
            partial_data_reason = "unavailable_metric"
            missing_fields.append("impressions_ctr")
            impressions_ctr = None

        if fixture.impressions == 0:
            missing_fields.append("impressions_ctr")
            impressions_ctr = None

        if fixture.missing_metrics:
            missing_fields.extend(fixture.missing_metrics)
            if "impressions_ctr" in fixture.missing_metrics:
                impressions_ctr = None

        if missing_fields:
            completeness_status = "partial"
            if partial_data_reason is None:
                partial_data_reason = "unavailable_metric"

        return AnalyticsProviderRow(
            channel_id=request.channel_id,
            youtube_channel_id=request.youtube_channel_id,
            internal_video_id=internal_video_id,
            youtube_video_id=fixture.video_id,
            content_job_id=f"job-{fixture.day.strftime('%Y%m%d')}-{fixture.video_id}",
            content_type="LONG_FORM",
            snapshot_timestamp=self._now(),
            publication_timestamp=datetime.combine(fixture.day, datetime.min.time(), tzinfo=timezone.utc),
            title_at_snapshot=f"Mock {fixture.day.strftime('%Y-%m-%d')}",
            topic="mock",
            topic_domain="mock",
            language="en",
            duration_seconds=180,
            thumbnail_identity=f"thumb-{fixture.video_id}",
            prompt_template_version="mock-v1",
            impressions=impressions,
            impressions_ctr=impressions_ctr,
            views=views,
            watch_time_minutes=watch_time_minutes,
            average_view_duration_seconds=average_view_duration_seconds,
            average_percentage_viewed=average_percentage_viewed,
            subscribers_gained=subscribers_gained,
            subscribers_lost=subscribers_lost,
            likes=likes,
            comments=comments,
            shares=shares,
            metric_source=metric_source,
            provenance_reference=provenance_reference,
            source_query_version=request.query_version,
            freshness_status="fresh",
            completeness_status=completeness_status,
            missing_fields=tuple(missing_fields),
            partial_data_reason=partial_data_reason,
            validation_status="accepted",
        )

    def _build_fixture_rows(self) -> list[_FixtureRow]:
        return [
            _FixtureRow(day=date(2026, 7, 1), video_id="mock-video-001", channel_id="channel_alpha", youtube_channel_id="UC-alpha", views=10, watch_time_minutes=5, average_view_duration_seconds=30.0, average_percentage_viewed=45.0, impressions=100, impressions_ctr=0.12, likes=2, comments=1, shares=0, subscribers_gained=1, subscribers_lost=0),
            _FixtureRow(day=date(2026, 7, 2), video_id="mock-video-002", channel_id="channel_alpha", youtube_channel_id="UC-alpha", views=25, watch_time_minutes=14, average_view_duration_seconds=34.0, average_percentage_viewed=50.0, impressions=150, impressions_ctr=0.16, likes=4, comments=2, shares=1, subscribers_gained=1, subscribers_lost=0),
            _FixtureRow(day=date(2026, 7, 3), video_id="mock-video-003", channel_id="channel_alpha", youtube_channel_id="UC-alpha", views=0, watch_time_minutes=0, average_view_duration_seconds=0.0, average_percentage_viewed=0.0, impressions=0, impressions_ctr=None, likes=0, comments=0, shares=0, subscribers_gained=0, subscribers_lost=0),
            _FixtureRow(day=date(2026, 7, 4), video_id="mock-video-004", channel_id="channel_alpha", youtube_channel_id="UC-alpha", views=50, watch_time_minutes=30, average_view_duration_seconds=36.0, average_percentage_viewed=60.0, impressions=250, impressions_ctr=0.20, likes=6, comments=3, shares=2, subscribers_gained=2, subscribers_lost=1, partial=True),
            _FixtureRow(day=date(2026, 7, 5), video_id="mock-video-005", channel_id="channel_alpha", youtube_channel_id="UC-alpha", views=70, watch_time_minutes=41, average_view_duration_seconds=35.0, average_percentage_viewed=58.0, impressions=300, impressions_ctr=0.22, likes=8, comments=4, shares=2, subscribers_gained=3, subscribers_lost=1),
            _FixtureRow(day=date(2026, 7, 6), video_id="mock-video-006", channel_id="channel_alpha", youtube_channel_id="UC-alpha", views=80, watch_time_minutes=48, average_view_duration_seconds=36.0, average_percentage_viewed=62.0, impressions=350, impressions_ctr=0.24, likes=9, comments=5, shares=3, subscribers_gained=2, subscribers_lost=1),
        ]

    def _cursor_to_index(self, cursor: str, page_size: int) -> int:
        normalized = str(cursor or "").strip()
        if normalized == "page-1":
            return page_size
        if normalized == "page-2":
            return page_size * 2
        raise AnalyticsProviderError(
            "invalid cursor",
            category="INVALID_CURSOR",
            provider_name=self.provider_name,
            request_identity=None,
        )

    def _index_to_cursor(self, index: int, page_size: int) -> str:
        if index == page_size:
            return "page-1"
        if index == page_size * 2:
            return "page-2"
        return ""

    def _now(self) -> datetime:
        if self._fixed_now is not None:
            return self._fixed_now
        return datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
