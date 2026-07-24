from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .google_oauth_credentials import OAuthCredentialLease
from .youtube_analytics_live_client import AnalyticsLiveClient, YouTubeAnalyticsLiveClientError


@dataclass(frozen=True, slots=True)
class ChannelExecutionPlan:
    channel_id: str
    youtube_channel_id: str
    start_date: str
    end_date: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...] = ()
    filters: tuple[str, ...] = ()
    sort: tuple[str, ...] = ()
    max_results: int | None = None
    start_index: int | None = None
    currency: str | None = None
    timeout_seconds: int = 30
    retry_metadata: Mapping[str, Any] = None
    enabled: bool = True

    def __post_init__(self) -> None:
        normalized_channel_id = str(self.channel_id or "").strip()
        normalized_youtube_channel_id = str(self.youtube_channel_id or "").strip()
        if not normalized_channel_id:
            raise ValueError("channel_id is required")
        if not normalized_youtube_channel_id:
            raise ValueError("youtube_channel_id is required")

        normalized_start_date = str(self.start_date or "").strip()
        normalized_end_date = str(self.end_date or "").strip()
        if not normalized_start_date:
            raise ValueError("start_date is required")
        if not normalized_end_date:
            raise ValueError("end_date is required")

        normalized_metrics = tuple(sorted({str(value).strip() for value in self.metrics}))
        if not normalized_metrics or any(not value for value in normalized_metrics):
            raise ValueError("metrics must contain at least one non-blank value")

        normalized_dimensions = tuple(sorted({str(value).strip() for value in self.dimensions if str(value).strip()}))
        normalized_filters = tuple(sorted({str(value).strip() for value in self.filters if str(value).strip()}))
        normalized_sort = tuple(sorted({str(value).strip() for value in self.sort if str(value).strip()}))

        timeout = int(self.timeout_seconds)
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")

        retry_metadata = dict(self.retry_metadata or {})

        object.__setattr__(self, "channel_id", normalized_channel_id)
        object.__setattr__(self, "youtube_channel_id", normalized_youtube_channel_id)
        object.__setattr__(self, "start_date", normalized_start_date)
        object.__setattr__(self, "end_date", normalized_end_date)
        object.__setattr__(self, "metrics", normalized_metrics)
        object.__setattr__(self, "dimensions", normalized_dimensions)
        object.__setattr__(self, "filters", normalized_filters)
        object.__setattr__(self, "sort", normalized_sort)
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "retry_metadata", retry_metadata)


@dataclass(frozen=True, slots=True)
class ChannelExecutionResult:
    channel_id: str
    youtube_channel_id: str
    status: str
    attempts: int
    timeout_seconds: int
    retryable: bool
    request_identity: str | None = None
    payload: Mapping[str, Any] | None = None
    error_category: str | None = None
    safe_message: str | None = None

    def __post_init__(self) -> None:
        if str(self.status or "").strip() not in {
            "success",
            "skipped",
            "retryable_failure",
            "permanent_failure",
        }:
            raise ValueError("status is invalid")
        if int(self.attempts) < 0:
            raise ValueError("attempts must be nonnegative")
        if int(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.payload is not None:
            object.__setattr__(self, "payload", dict(self.payload))


@dataclass(frozen=True, slots=True)
class MultiChannelExecutionSummary:
    results: tuple[ChannelExecutionResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results))

    @property
    def total_channels(self) -> int:
        return len(self.results)

    @property
    def successful_channels(self) -> int:
        return sum(1 for item in self.results if item.status == "success")

    @property
    def skipped_channels(self) -> int:
        return sum(1 for item in self.results if item.status == "skipped")

    @property
    def retryable_failures(self) -> int:
        return sum(1 for item in self.results if item.status == "retryable_failure")

    @property
    def permanent_failures(self) -> int:
        return sum(1 for item in self.results if item.status == "permanent_failure")

    def to_payload(self) -> dict[str, Any]:
        return {
            "total_channels": self.total_channels,
            "successful_channels": self.successful_channels,
            "skipped_channels": self.skipped_channels,
            "retryable_failures": self.retryable_failures,
            "permanent_failures": self.permanent_failures,
            "results": [
                {
                    "channel_id": item.channel_id,
                    "youtube_channel_id": item.youtube_channel_id,
                    "status": item.status,
                    "attempts": item.attempts,
                    "timeout_seconds": item.timeout_seconds,
                    "retryable": item.retryable,
                    "request_identity": item.request_identity,
                    "payload": dict(item.payload or {}),
                    "error_category": item.error_category,
                    "safe_message": item.safe_message,
                }
                for item in self.results
            ],
        }


@runtime_checkable
class ChannelSelectionPolicy(Protocol):
    def select(self, plans: tuple[ChannelExecutionPlan, ...]) -> tuple[ChannelExecutionPlan, ...]:
        ...


class DeterministicChannelSelectionPolicy:
    def select(self, plans: tuple[ChannelExecutionPlan, ...]) -> tuple[ChannelExecutionPlan, ...]:
        enabled = [plan for plan in plans if plan.enabled]
        ordered = sorted(enabled, key=lambda item: (item.channel_id, item.youtube_channel_id))
        return tuple(ordered)


class MultiChannelAnalyticsService:
    """Deterministic sequential execution service for read-only channel analytics."""

    def __init__(
        self,
        *,
        analytics_client: AnalyticsLiveClient,
        selection_policy: ChannelSelectionPolicy | None = None,
        max_attempts: int = 2,
    ) -> None:
        self._analytics_client = analytics_client
        self._selection_policy = selection_policy or DeterministicChannelSelectionPolicy()
        self._max_attempts = max(1, int(max_attempts))

    def run(
        self,
        *,
        plans: tuple[ChannelExecutionPlan, ...],
        leases: Mapping[str, OAuthCredentialLease],
        retry_metadata: Mapping[str, Any] | None = None,
    ) -> MultiChannelExecutionSummary:
        selected = self._selection_policy.select(tuple(plans))
        results: list[ChannelExecutionResult] = []
        base_retry_metadata = dict(retry_metadata or {})

        for plan in selected:
            lease = self._select_lease(plan=plan, leases=leases)
            if lease is None:
                results.append(
                    ChannelExecutionResult(
                        channel_id=plan.channel_id,
                        youtube_channel_id=plan.youtube_channel_id,
                        status="skipped",
                        attempts=0,
                        timeout_seconds=plan.timeout_seconds,
                        retryable=False,
                        error_category="LEASE_UNAVAILABLE",
                        safe_message="lease unavailable",
                    )
                )
                continue

            result = self._run_single_channel(
                plan=plan,
                lease=lease,
                base_retry_metadata=base_retry_metadata,
            )
            results.append(result)

        return MultiChannelExecutionSummary(results=tuple(results))

    def _run_single_channel(
        self,
        *,
        plan: ChannelExecutionPlan,
        lease: OAuthCredentialLease,
        base_retry_metadata: Mapping[str, Any],
    ) -> ChannelExecutionResult:
        allowed_attempts = self._determine_attempts(plan)
        last_error: YouTubeAnalyticsLiveClientError | None = None

        for attempt in range(1, allowed_attempts + 1):
            merged_retry_metadata = dict(base_retry_metadata)
            merged_retry_metadata.update(dict(plan.retry_metadata))
            merged_retry_metadata["attempt"] = attempt
            merged_retry_metadata["channel_id"] = plan.channel_id
            merged_retry_metadata["youtube_channel_id"] = plan.youtube_channel_id

            try:
                payload = self._analytics_client.run_dry(
                    oauth_lease=lease,
                    channel_id=plan.channel_id,
                    youtube_channel_id=plan.youtube_channel_id,
                    start_date=plan.start_date,
                    end_date=plan.end_date,
                    metrics=plan.metrics,
                    dimensions=plan.dimensions,
                    filters=plan.filters,
                    sort=plan.sort,
                    max_results=plan.max_results,
                    start_index=plan.start_index,
                    currency=plan.currency,
                    timeout_seconds=plan.timeout_seconds,
                    retry_metadata=merged_retry_metadata,
                )
                return ChannelExecutionResult(
                    channel_id=plan.channel_id,
                    youtube_channel_id=plan.youtube_channel_id,
                    status="success",
                    attempts=attempt,
                    timeout_seconds=plan.timeout_seconds,
                    retryable=False,
                    request_identity=str(payload.get("request_identity") or ""),
                    payload=payload,
                )
            except YouTubeAnalyticsLiveClientError as exc:
                last_error = exc
                if exc.retryable and attempt < allowed_attempts:
                    continue

                return ChannelExecutionResult(
                    channel_id=plan.channel_id,
                    youtube_channel_id=plan.youtube_channel_id,
                    status="retryable_failure" if exc.retryable else "permanent_failure",
                    attempts=attempt,
                    timeout_seconds=plan.timeout_seconds,
                    retryable=exc.retryable,
                    request_identity=exc.request_identity,
                    error_category=exc.category,
                    safe_message=exc.safe_message,
                )

        if last_error is None:
            raise RuntimeError("internal execution state")

        return ChannelExecutionResult(
            channel_id=plan.channel_id,
            youtube_channel_id=plan.youtube_channel_id,
            status="retryable_failure" if last_error.retryable else "permanent_failure",
            attempts=allowed_attempts,
            timeout_seconds=plan.timeout_seconds,
            retryable=last_error.retryable,
            request_identity=last_error.request_identity,
            error_category=last_error.category,
            safe_message=last_error.safe_message,
        )

    def _determine_attempts(self, plan: ChannelExecutionPlan) -> int:
        explicit = plan.retry_metadata.get("max_attempts")
        if explicit is None:
            return self._max_attempts
        return max(1, int(explicit))

    def _select_lease(
        self,
        *,
        plan: ChannelExecutionPlan,
        leases: Mapping[str, OAuthCredentialLease],
    ) -> OAuthCredentialLease | None:
        direct = leases.get(plan.channel_id)
        if direct is not None:
            return direct

        secondary = leases.get(plan.youtube_channel_id)
        if secondary is not None:
            return secondary

        for lease in leases.values():
            if lease.channel_id == plan.channel_id and lease.youtube_channel_id == plan.youtube_channel_id:
                return lease
        return None


__all__ = [
    "ChannelExecutionPlan",
    "ChannelExecutionResult",
    "ChannelSelectionPolicy",
    "DeterministicChannelSelectionPolicy",
    "MultiChannelAnalyticsService",
    "MultiChannelExecutionSummary",
]
