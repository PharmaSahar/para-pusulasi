from __future__ import annotations

import pytest

from src import analytics_collector
from src.analytics_collector import (
    CollectorAPIError,
    CollectorValidationError,
    build_evaluator_rows,
    collect_analytics_rows,
    normalize_analytics_report,
)


def test_successful_fetch_and_normalize(monkeypatch):
    def _fake_fetch(**kwargs):
        return {
            "video_id": kwargs["video_id"],
            "start_date": "2026-07-01",
            "end_date": "2026-07-09",
            "impressions": 1000,
            "click_through_rate": 5.0,
            "average_view_duration_seconds": 44.0,
            "watch_time_hours": 12.5,
        }

    monkeypatch.setattr(analytics_collector, "fetch_video_analytics", _fake_fetch)

    rows = collect_analytics_rows(
        experiment_id="exp_001",
        variant_by_video_id={"v1": "var_0001"},
        video_ids=["v1"],
    )

    assert len(rows) == 1
    assert rows[0]["ctr"] == 0.05
    assert rows[0]["clicks"] == 50


def test_empty_rows_normalized():
    row = normalize_analytics_report(
        experiment_id="exp_001",
        variant_id="var_0001",
        report={
            "video_id": "v1",
            "impressions": None,
            "click_through_rate": None,
            "watch_time_hours": None,
            "average_view_duration_seconds": None,
        },
    )

    assert row["impressions"] is None
    assert row["ctr"] is None
    assert row["clicks"] is None


def test_api_error_propagates_typed(monkeypatch):
    def _fake_fetch(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(analytics_collector, "fetch_video_analytics", _fake_fetch)

    with pytest.raises(CollectorAPIError, match="analytics_fetch_failed:v1"):
        collect_analytics_rows(
            experiment_id="exp_001",
            variant_by_video_id={"v1": "var_0001"},
            video_ids=["v1"],
        )


def test_invalid_metric_shape_rejected():
    with pytest.raises(CollectorValidationError, match="invalid_metric:impressions"):
        normalize_analytics_report(
            experiment_id="exp_001",
            variant_id="var_0001",
            report={
                "video_id": "v1",
                "impressions": -1,
                "click_through_rate": 0.1,
                "watch_time_hours": 1.0,
                "average_view_duration_seconds": 30.0,
            },
        )


def test_deterministic_normalization_for_same_payload():
    payload = {
        "video_id": "v1",
        "start_date": "2026-07-01",
        "end_date": "2026-07-09",
        "impressions": 200,
        "click_through_rate": 0.2,
        "watch_time_hours": 5.0,
        "average_view_duration_seconds": 20.0,
    }
    first = normalize_analytics_report(experiment_id="exp_001", variant_id="var_0001", report=payload)
    second = normalize_analytics_report(experiment_id="exp_001", variant_id="var_0001", report=payload)

    assert first == second


def test_build_evaluator_rows_skips_incomplete_rows():
    rows = [
        {
            "experiment_id": "exp_001",
            "variant_id": "var_0001",
            "impressions": 100,
            "clicks": 10,
            "ctr": 0.1,
            "watch_time_hours": 2.0,
            "average_view_duration_seconds": 30.0,
        },
        {
            "experiment_id": "exp_001",
            "variant_id": "var_0002",
            "impressions": None,
            "clicks": None,
            "ctr": None,
            "watch_time_hours": None,
            "average_view_duration_seconds": None,
        },
    ]

    evaluator_rows = build_evaluator_rows(rows)

    assert len(evaluator_rows) == 1
    assert evaluator_rows[0]["variant_id"] == "var_0001"
