from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.google_oauth_credentials import OAuthCredentialLease
from src.multi_channel_analytics_service import (
    ChannelExecutionPlan,
    ChannelSelectionPolicy,
    DeterministicChannelSelectionPolicy,
    MultiChannelAnalyticsService,
    MultiChannelExecutionSummary,
)
from src.youtube_analytics_live_client import YouTubeAnalyticsLiveClientError


class _FakeAnalyticsClient:
    def __init__(self, behaviors: dict[str, list[str]] | None = None) -> None:
        self._behaviors = {k: list(v) for k, v in dict(behaviors or {}).items()}
        self.calls: list[dict[str, Any]] = []

    def run_dry(
        self,
        *,
        oauth_lease: OAuthCredentialLease,
        channel_id: str,
        youtube_channel_id: str,
        start_date: str,
        end_date: str,
        metrics: tuple[str, ...],
        dimensions: tuple[str, ...] = (),
        filters: tuple[str, ...] = (),
        sort: tuple[str, ...] = (),
        max_results: int | None = None,
        start_index: int | None = None,
        currency: str | None = None,
        timeout_seconds: int,
        retry_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "channel_id": channel_id,
                "youtube_channel_id": youtube_channel_id,
                "timeout_seconds": timeout_seconds,
                "retry_metadata": dict(retry_metadata or {}),
                "lease_identity": oauth_lease.lease_identity,
            }
        )

        sequence = self._behaviors.get(channel_id)
        mode = sequence.pop(0) if sequence else "success"

        if mode == "retryable":
            raise YouTubeAnalyticsLiveClientError(
                "retryable error",
                category="RETRYABLE_ERROR",
                request_identity=f"req-{channel_id}",
                retryable=True,
            )
        if mode == "permanent":
            raise YouTubeAnalyticsLiveClientError(
                "permanent error",
                category="PERMANENT_ERROR",
                request_identity=f"req-{channel_id}",
                retryable=False,
            )

        return {
            "request_identity": f"req-{channel_id}",
            "status": "success",
            "row_count": 1,
            "rows": ({"day": "2026-07-01", "views": 10},),
            "timeout_seconds": timeout_seconds,
            "retry_metadata": dict(retry_metadata or {}),
        }


class _ReverseSelectionPolicy:
    def select(self, plans: tuple[ChannelExecutionPlan, ...]) -> tuple[ChannelExecutionPlan, ...]:
        return tuple(reversed(plans))


def _lease(*, channel_id: str, youtube_channel_id: str, lease_identity: str) -> OAuthCredentialLease:
    return OAuthCredentialLease(
        provider_name="oauth-provider-alpha",
        credential_identity=f"cred-{channel_id}",
        channel_id=channel_id,
        youtube_channel_id=youtube_channel_id,
        scope_names=("scope-a",),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity=lease_identity,
        access_token_value="fake_access_value",
        refresh_token_value="fake_refresh_value",
    )


def _plan(
    *,
    channel_id: str,
    youtube_channel_id: str,
    timeout_seconds: int = 10,
    enabled: bool = True,
    retry_metadata: dict[str, Any] | None = None,
) -> ChannelExecutionPlan:
    return ChannelExecutionPlan(
        channel_id=channel_id,
        youtube_channel_id=youtube_channel_id,
        start_date="2026-07-01",
        end_date="2026-07-07",
        metrics=("views", "likes"),
        dimensions=("day",),
        filters=("country==US",),
        sort=("-views",),
        timeout_seconds=timeout_seconds,
        retry_metadata=retry_metadata or {"attempt": 1},
        enabled=enabled,
    )


def test_selection_policy_protocol_compatibility() -> None:
    assert isinstance(DeterministicChannelSelectionPolicy(), ChannelSelectionPolicy)


def test_deterministic_execution_order() -> None:
    client = _FakeAnalyticsClient()
    service = MultiChannelAnalyticsService(analytics_client=client)

    plans = (
        _plan(channel_id="channel_c", youtube_channel_id="UC-C"),
        _plan(channel_id="channel_a", youtube_channel_id="UC-A"),
        _plan(channel_id="channel_b", youtube_channel_id="UC-B"),
    )
    leases = {
        "channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a"),
        "channel_b": _lease(channel_id="channel_b", youtube_channel_id="UC-B", lease_identity="lease-b"),
        "channel_c": _lease(channel_id="channel_c", youtube_channel_id="UC-C", lease_identity="lease-c"),
    }

    service.run(plans=plans, leases=leases)

    assert [item["channel_id"] for item in client.calls] == ["channel_a", "channel_b", "channel_c"]


def test_per_channel_isolation_continues_after_failure() -> None:
    client = _FakeAnalyticsClient(behaviors={"channel_a": ["permanent"]})
    service = MultiChannelAnalyticsService(analytics_client=client)

    plans = (
        _plan(channel_id="channel_a", youtube_channel_id="UC-A"),
        _plan(channel_id="channel_b", youtube_channel_id="UC-B"),
    )
    leases = {
        "channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a"),
        "channel_b": _lease(channel_id="channel_b", youtube_channel_id="UC-B", lease_identity="lease-b"),
    }

    result = service.run(plans=plans, leases=leases)

    assert result.total_channels == 2
    assert result.results[0].status == "permanent_failure"
    assert result.results[1].status == "success"


def test_retry_metadata_and_retry_attempts_propagation() -> None:
    client = _FakeAnalyticsClient(behaviors={"channel_a": ["retryable", "success"]})
    service = MultiChannelAnalyticsService(analytics_client=client, max_attempts=2)

    plans = (
        _plan(
            channel_id="channel_a",
            youtube_channel_id="UC-A",
            retry_metadata={"attempt": 1, "max_attempts": 2, "trace": "alpha"},
        ),
    )
    leases = {"channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a")}

    result = service.run(plans=plans, leases=leases, retry_metadata={"source": "batch"})

    assert result.results[0].status == "success"
    assert len(client.calls) == 2
    assert client.calls[0]["retry_metadata"]["attempt"] == 1
    assert client.calls[1]["retry_metadata"]["attempt"] == 2
    assert client.calls[1]["retry_metadata"]["trace"] == "alpha"
    assert client.calls[1]["retry_metadata"]["source"] == "batch"


def test_timeout_propagation() -> None:
    client = _FakeAnalyticsClient()
    service = MultiChannelAnalyticsService(analytics_client=client)

    plans = (_plan(channel_id="channel_a", youtube_channel_id="UC-A", timeout_seconds=27),)
    leases = {"channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a")}

    service.run(plans=plans, leases=leases)

    assert client.calls[0]["timeout_seconds"] == 27


def test_lease_selection_by_channel_then_youtube_key() -> None:
    client = _FakeAnalyticsClient()
    service = MultiChannelAnalyticsService(analytics_client=client)

    plans = (_plan(channel_id="channel_x", youtube_channel_id="UC-X"),)
    leases = {
        "UC-X": _lease(channel_id="channel_x", youtube_channel_id="UC-X", lease_identity="lease-youtube-key")
    }

    result = service.run(plans=plans, leases=leases)

    assert result.results[0].status == "success"
    assert client.calls[0]["lease_identity"] == "lease-youtube-key"


def test_skipped_channel_when_lease_missing() -> None:
    client = _FakeAnalyticsClient()
    service = MultiChannelAnalyticsService(analytics_client=client)

    plans = (_plan(channel_id="channel_a", youtube_channel_id="UC-A"),)

    result = service.run(plans=plans, leases={})

    assert result.results[0].status == "skipped"
    assert result.results[0].error_category == "LEASE_UNAVAILABLE"
    assert len(client.calls) == 0


def test_retryable_failure_when_attempts_exhausted() -> None:
    client = _FakeAnalyticsClient(behaviors={"channel_a": ["retryable", "retryable"]})
    service = MultiChannelAnalyticsService(analytics_client=client, max_attempts=2)

    plans = (_plan(channel_id="channel_a", youtube_channel_id="UC-A"),)
    leases = {"channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a")}

    result = service.run(plans=plans, leases=leases)

    assert result.results[0].status == "retryable_failure"
    assert result.results[0].attempts == 2


def test_permanent_failure_no_extra_attempts() -> None:
    client = _FakeAnalyticsClient(behaviors={"channel_a": ["permanent", "success"]})
    service = MultiChannelAnalyticsService(analytics_client=client, max_attempts=3)

    plans = (_plan(channel_id="channel_a", youtube_channel_id="UC-A"),)
    leases = {"channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a")}

    result = service.run(plans=plans, leases=leases)

    assert result.results[0].status == "permanent_failure"
    assert len(client.calls) == 1


def test_aggregated_summary_counts() -> None:
    client = _FakeAnalyticsClient(
        behaviors={
            "channel_a": ["success"],
            "channel_b": ["retryable", "retryable"],
            "channel_c": ["permanent"],
        }
    )
    service = MultiChannelAnalyticsService(analytics_client=client, max_attempts=2)

    plans = (
        _plan(channel_id="channel_a", youtube_channel_id="UC-A"),
        _plan(channel_id="channel_b", youtube_channel_id="UC-B"),
        _plan(channel_id="channel_c", youtube_channel_id="UC-C"),
        _plan(channel_id="channel_d", youtube_channel_id="UC-D"),
    )
    leases = {
        "channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a"),
        "channel_b": _lease(channel_id="channel_b", youtube_channel_id="UC-B", lease_identity="lease-b"),
        "channel_c": _lease(channel_id="channel_c", youtube_channel_id="UC-C", lease_identity="lease-c"),
    }

    result = service.run(plans=plans, leases=leases)

    assert isinstance(result, MultiChannelExecutionSummary)
    assert result.total_channels == 4
    assert result.successful_channels == 1
    assert result.retryable_failures == 1
    assert result.permanent_failures == 1
    assert result.skipped_channels == 1


def test_immutable_models() -> None:
    plan = _plan(channel_id="channel_a", youtube_channel_id="UC-A")
    service = MultiChannelAnalyticsService(
        analytics_client=_FakeAnalyticsClient(),
        selection_policy=_ReverseSelectionPolicy(),
    )
    result = service.run(
        plans=(plan,),
        leases={"channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a")},
    )

    with pytest.raises(AttributeError):
        plan.timeout_seconds = 99
    with pytest.raises(AttributeError):
        result.results[0].status = "changed"


def test_disabled_plan_not_executed() -> None:
    client = _FakeAnalyticsClient()
    service = MultiChannelAnalyticsService(analytics_client=client)

    plans = (
        _plan(channel_id="channel_a", youtube_channel_id="UC-A", enabled=False),
        _plan(channel_id="channel_b", youtube_channel_id="UC-B", enabled=True),
    )
    leases = {
        "channel_a": _lease(channel_id="channel_a", youtube_channel_id="UC-A", lease_identity="lease-a"),
        "channel_b": _lease(channel_id="channel_b", youtube_channel_id="UC-B", lease_identity="lease-b"),
    }

    result = service.run(plans=plans, leases=leases)

    assert result.total_channels == 1
    assert result.results[0].channel_id == "channel_b"


def test_no_forbidden_runtime_behaviors_in_source() -> None:
    source = Path("src/multi_channel_analytics_service.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "scheduler",
        "cron",
        "polling",
        "dashboard",
        "snapshot",
        "database",
        "upload",
        "deploy",
        "thread",
        "asyncio.gather",
    ]
    for token in forbidden:
        assert token not in source
