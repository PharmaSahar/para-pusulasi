from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

SUPPORTED_PROVIDER_SCHEMA_VERSIONS = {"analytics-provider.v1"}
SUPPORTED_CONTENT_TYPES = {"SHORT", "LONG_FORM"}
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
SUPPORTED_CONTENT_TYPE_FILTERS = {"SHORT", "LONG_FORM"}


class AnalyticsProviderError(RuntimeError):
    """Structured provider error without live transport details."""

    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        provider_name: str,
        request_identity: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.category = category
        self.retryable = category in {"RATE_LIMITED", "QUOTA_EXCEEDED", "TRANSIENT_PROVIDER_ERROR"}
        self.safe_message = safe_message
        self.provider_name = provider_name
        self.request_identity = request_identity
        self.retry_after_seconds = retry_after_seconds
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be nonnegative")

    def to_payload(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "retryable": self.retryable,
            "safe_message": self.safe_message,
            "request_identity": self.request_identity,
            "provider_name": self.provider_name,
            "retry_after_seconds": self.retry_after_seconds,
        }


@dataclass(frozen=True, slots=True)
class AnalyticsProviderRequest:
    provider_schema_version: str
    channel_id: str
    youtube_channel_id: str
    start_date: date
    end_date: date
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    content_types: tuple[str, ...]
    page_size: int
    cursor: str | None
    query_version: str
    request_identity: str | None = None

    def __post_init__(self) -> None:
        schema_version = str(self.provider_schema_version or "").strip()
        if not schema_version:
            raise ValueError("provider_schema_version is required")
        if schema_version not in SUPPORTED_PROVIDER_SCHEMA_VERSIONS:
            raise ValueError("unsupported provider schema version")

        channel_id = str(self.channel_id or "").strip()
        if not channel_id:
            raise ValueError("channel_id is required")

        youtube_channel_id = str(self.youtube_channel_id or "").strip()
        if not youtube_channel_id:
            raise ValueError("youtube_channel_id is required")

        if not isinstance(self.start_date, date) or isinstance(self.start_date, datetime):
            raise ValueError("start_date must be a calendar date")
        if not isinstance(self.end_date, date) or isinstance(self.end_date, datetime):
            raise ValueError("end_date must be a calendar date")
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")

        page_size = int(self.page_size)
        if page_size <= 0 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")

        metrics = tuple(str(metric).strip() for metric in self.metrics)
        if not metrics:
            raise ValueError("metrics must not be empty")
        if any(metric not in SUPPORTED_METRICS for metric in metrics):
            raise ValueError("unsupported metrics")
        if len(set(metrics)) != len(metrics):
            raise ValueError("metrics must be unique")

        dimensions = tuple(str(dimension).strip() for dimension in self.dimensions)
        if any(dimension not in SUPPORTED_DIMENSIONS for dimension in dimensions):
            raise ValueError("unsupported dimensions")
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("dimensions must be unique")

        content_types = tuple(str(content_type).strip().upper() for content_type in self.content_types)
        if not content_types:
            raise ValueError("content_types must not be empty")
        if any(content_type not in SUPPORTED_CONTENT_TYPE_FILTERS for content_type in content_types):
            raise ValueError("unsupported content_type filter")
        if len(set(content_types)) != len(content_types):
            raise ValueError("content_types must be unique")

        query_version = str(self.query_version or "").strip()
        if not query_version:
            raise ValueError("query_version is required")

        cursor = self.cursor
        if cursor is not None:
            cursor = str(cursor).strip()
            if not cursor:
                raise ValueError("cursor cannot be blank")
        object.__setattr__(self, "metrics", tuple(sorted(metrics)))
        object.__setattr__(self, "dimensions", tuple(sorted(dimensions)))
        object.__setattr__(self, "content_types", tuple(sorted(content_types)))
        object.__setattr__(self, "cursor", cursor)
        object.__setattr__(self, "request_identity", self._build_request_identity())

    def _build_request_identity(self) -> str:
        payload = {
            "provider_schema_version": self.provider_schema_version,
            "channel_id": self.channel_id,
            "youtube_channel_id": self.youtube_channel_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "metrics": list(self.metrics),
            "dimensions": list(self.dimensions),
            "content_types": list(self.content_types),
            "page_size": self.page_size,
            "cursor": self.cursor,
            "query_version": self.query_version,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalyticsProviderRow:
    channel_id: str
    youtube_channel_id: str
    internal_video_id: str
    youtube_video_id: str
    content_job_id: str
    content_type: str
    snapshot_timestamp: datetime
    publication_timestamp: datetime
    title_at_snapshot: str | None
    topic: str | None
    topic_domain: str | None
    language: str | None
    duration_seconds: int | None
    thumbnail_identity: str | None
    prompt_template_version: str | None
    impressions: int | None
    impressions_ctr: float | None
    views: int | None
    watch_time_minutes: int | None
    average_view_duration_seconds: float | None
    average_percentage_viewed: float | None
    subscribers_gained: int | None
    subscribers_lost: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    metric_source: str
    provenance_reference: str
    source_query_version: str
    freshness_status: str | None
    completeness_status: str | None
    missing_fields: tuple[str, ...]
    partial_data_reason: str | None
    validation_status: str | None

    def __post_init__(self) -> None:
        if not str(self.channel_id or "").strip():
            raise ValueError("channel_id is required")
        if not str(self.youtube_channel_id or "").strip():
            raise ValueError("youtube_channel_id is required")
        if not str(self.internal_video_id or "").strip():
            raise ValueError("internal_video_id is required")
        if not str(self.youtube_video_id or "").strip():
            raise ValueError("youtube_video_id is required")
        if not str(self.content_job_id or "").strip():
            raise ValueError("content_job_id is required")
        if not str(self.metric_source or "").strip():
            raise ValueError("metric_source is required")
        if not str(self.provenance_reference or "").strip():
            raise ValueError("provenance_reference is required")
        if not str(self.source_query_version or "").strip():
            raise ValueError("source_query_version is required")

        content_type = str(self.content_type or "").strip().upper()
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError("content_type must be SHORT or LONG_FORM")
        object.__setattr__(self, "content_type", content_type)

        for name in (
            "snapshot_timestamp",
            "publication_timestamp",
        ):
            value = getattr(self, name)
            if not isinstance(value, datetime):
                raise ValueError(f"{name} must be a datetime")
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(timezone.utc))

        for field_name in ("impressions", "views", "watch_time_minutes", "subscribers_gained", "subscribers_lost", "likes", "comments", "shares"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool):
                raise ValueError(f"{field_name} must not be boolean")
            if not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be numeric or null")

        for field_name in ("impressions_ctr", "average_view_duration_seconds", "average_percentage_viewed"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool):
                raise ValueError(f"{field_name} must not be boolean")
            if not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be numeric or null")

        object.__setattr__(self, "missing_fields", tuple(str(field).strip() for field in self.missing_fields))

    def to_payload(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "youtube_channel_id": self.youtube_channel_id,
            "internal_video_id": self.internal_video_id,
            "youtube_video_id": self.youtube_video_id,
            "content_job_id": self.content_job_id,
            "content_type": self.content_type,
            "snapshot_timestamp": self.snapshot_timestamp.isoformat(),
            "publication_timestamp": self.publication_timestamp.isoformat(),
            "title_at_snapshot": self.title_at_snapshot,
            "topic": self.topic,
            "topic_domain": self.topic_domain,
            "language": self.language,
            "duration_seconds": self.duration_seconds,
            "thumbnail_identity": self.thumbnail_identity,
            "prompt_template_version": self.prompt_template_version,
            "impressions": self.impressions,
            "impressions_ctr": self.impressions_ctr,
            "views": self.views,
            "watch_time_minutes": self.watch_time_minutes,
            "average_view_duration_seconds": self.average_view_duration_seconds,
            "average_percentage_viewed": self.average_percentage_viewed,
            "subscribers_gained": self.subscribers_gained,
            "subscribers_lost": self.subscribers_lost,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "metric_source": self.metric_source,
            "provenance_reference": self.provenance_reference,
            "source_query_version": self.source_query_version,
            "freshness_status": self.freshness_status,
            "completeness_status": self.completeness_status,
            "missing_fields": list(self.missing_fields),
            "partial_data_reason": self.partial_data_reason,
            "validation_status": self.validation_status,
        }


@dataclass(frozen=True, slots=True)
class AnalyticsProviderPage:
    provider_schema_version: str
    request_identity: str
    provider_name: str
    provider_query_version: str
    fetched_at: datetime
    rows: tuple[AnalyticsProviderRow, ...]
    next_cursor: str | None
    has_more: bool
    source_freshness: str
    warnings: tuple[str, ...]
    response_identity: str | None = None

    def __post_init__(self) -> None:
        if str(self.provider_schema_version or "").strip() not in SUPPORTED_PROVIDER_SCHEMA_VERSIONS:
            raise ValueError("unsupported provider_schema_version")
        if not str(self.request_identity or "").strip():
            raise ValueError("request_identity is required")
        if not str(self.provider_name or "").strip():
            raise ValueError("provider_name is required")
        if not str(self.provider_query_version or "").strip():
            raise ValueError("provider_query_version is required")
        if not isinstance(self.fetched_at, datetime) or self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        if self.has_more and not self.next_cursor:
            raise ValueError("has_more true requires next_cursor")
        if not self.has_more and self.next_cursor:
            raise ValueError("has_more false forbids next_cursor")
        object.__setattr__(self, "fetched_at", self.fetched_at.astimezone(timezone.utc))
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "warnings", tuple(sorted(self.warnings)))
        object.__setattr__(self, "response_identity", self._build_response_identity())

    def _build_response_identity(self) -> str:
        payload = {
            "provider_schema_version": self.provider_schema_version,
            "request_identity": self.request_identity,
            "provider_name": self.provider_name,
            "provider_query_version": self.provider_query_version,
            "rows": [row.to_payload() for row in self.rows],
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
            "source_freshness": self.source_freshness,
            "warnings": list(self.warnings),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider_schema_version": self.provider_schema_version,
            "request_identity": self.request_identity,
            "provider_name": self.provider_name,
            "provider_query_version": self.provider_query_version,
            "fetched_at": self.fetched_at.isoformat(),
            "rows": [row.to_payload() for row in self.rows],
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
            "source_freshness": self.source_freshness,
            "warnings": list(self.warnings),
            "response_identity": self.response_identity,
        }


class AnalyticsProvider(Protocol):
    provider_name: str

    def fetch_analytics_page(self, request: AnalyticsProviderRequest) -> AnalyticsProviderPage:
        ...


class InMemoryAnalyticsProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        pages: Mapping[str | None, AnalyticsProviderPage] | None = None,
        errors: Mapping[str, tuple[str, int | None]] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self._pages = dict(pages or {})
        self._errors = dict(errors or {})
        self.requests: list[AnalyticsProviderRequest] = []

    def fetch_analytics_page(self, request: AnalyticsProviderRequest) -> AnalyticsProviderPage:
        self.requests.append(request)
        if self._errors:
            for category, detail in self._errors.items():
                message, retry_after = detail
                if category == "RATE_LIMITED":
                    raise AnalyticsProviderError(message, category=category, provider_name=self.provider_name, request_identity=request.request_identity, retry_after_seconds=retry_after)
                if category == "PERMANENT_PROVIDER_ERROR":
                    raise AnalyticsProviderError(message, category=category, provider_name=self.provider_name, request_identity=request.request_identity)
        cursor_key = request.cursor
        page = self._pages.get(cursor_key)
        if page is None:
            page = self._pages.get(None)
        if page is None:
            raise AnalyticsProviderError("no configured page", category="INVALID_PROVIDER_RESPONSE", provider_name=self.provider_name, request_identity=request.request_identity)
        return page


def provider_row_to_snapshot(row: AnalyticsProviderRow) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "snapshot_timestamp": row.snapshot_timestamp.isoformat(),
        "snapshot_date": row.snapshot_timestamp.strftime("%Y-%m-%d"),
        "channel_id": row.channel_id,
        "youtube_channel_id": row.youtube_channel_id,
        "internal_video_id": row.internal_video_id,
        "youtube_video_id": row.youtube_video_id,
        "content_job_id": row.content_job_id,
        "content_type": row.content_type,
        "metric_source": row.metric_source,
        "provenance_reference": row.provenance_reference,
        "title_at_snapshot": row.title_at_snapshot,
        "topic": row.topic,
        "topic_domain": row.topic_domain,
        "language": row.language,
        "duration_seconds": row.duration_seconds,
        "publication_timestamp": row.publication_timestamp.isoformat(),
        "thumbnail_identity": row.thumbnail_identity,
        "prompt_template_version": row.prompt_template_version,
        "impressions": row.impressions,
        "impressions_ctr": row.impressions_ctr,
        "views": row.views,
        "watch_time_minutes": row.watch_time_minutes,
        "average_view_duration_seconds": row.average_view_duration_seconds,
        "average_percentage_viewed": row.average_percentage_viewed,
        "subscribers_gained": row.subscribers_gained,
        "subscribers_lost": row.subscribers_lost,
        "likes": row.likes,
        "comments": row.comments,
        "shares": row.shares,
        "fetched_at": None,
        "freshness_status": row.freshness_status,
        "completeness_status": row.completeness_status,
        "missing_fields": list(row.missing_fields),
        "partial_data_reason": row.partial_data_reason,
        "validation_status": row.validation_status,
        "source_query_version": row.source_query_version,
    }


__all__ = [
    "AnalyticsProvider",
    "AnalyticsProviderError",
    "AnalyticsProviderPage",
    "AnalyticsProviderRequest",
    "AnalyticsProviderRow",
    "InMemoryAnalyticsProvider",
    "provider_row_to_snapshot",
]
