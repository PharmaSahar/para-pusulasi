from __future__ import annotations

from copy import deepcopy

import src.analytics_quality_guard as analytics_quality_guard


def _snapshot() -> dict:
    return {
        "performance_schema_version": "v1",
        "day": "2026-07-17",
        "created_at": "2026-07-17T10:00:00+00:00",
        "channel_id": "demo_channel",
        "content_id": "content_1",
        "run_id": "run_1",
        "title": "Title",
        "video_id": "video_123456",
        "impressions": 100,
        "click_through_rate": 2.5,
        "average_view_duration_seconds": 45.0,
        "average_view_percentage": 52.0,
        "watch_time_hours": 1.2,
    }


def test_valid_snapshot_accepted(monkeypatch):
    events = []
    monkeypatch.setattr(analytics_quality_guard, "_record_event", lambda payload: events.append(payload))

    result = analytics_quality_guard.validate_performance_snapshot(_snapshot(), existing_rows=[])

    assert result.accepted is True
    assert result.status == "accepted"
    assert events == []


def test_negative_metric_rejected(monkeypatch):
    events = []
    monkeypatch.setattr(analytics_quality_guard, "_record_event", lambda payload: events.append(payload))
    snapshot = _snapshot()
    snapshot["watch_time_hours"] = -1

    result = analytics_quality_guard.validate_performance_snapshot(snapshot, existing_rows=[])

    assert result.accepted is False
    assert result.reason_code == "analytics_snapshot_negative_metric"
    assert events[-1]["event_type"] == "analytics_validation_rejected"


def test_duplicate_snapshot_suppressed(monkeypatch):
    events = []
    monkeypatch.setattr(analytics_quality_guard, "_record_event", lambda payload: events.append(payload))
    snapshot = _snapshot()

    result = analytics_quality_guard.validate_performance_snapshot(snapshot, existing_rows=[deepcopy(snapshot)])

    assert result.accepted is True
    assert result.duplicate is True
    assert result.reason_code == "analytics_snapshot_duplicate"
    assert events[-1]["status"] == "duplicate"