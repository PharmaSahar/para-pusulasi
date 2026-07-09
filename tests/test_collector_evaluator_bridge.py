from __future__ import annotations

from src import collector_evaluator_bridge
from src.collector_evaluator_bridge import evaluate_from_collector


def test_bridge_evaluates_winner_from_collector_rows(monkeypatch):
    def _fake_collect(**kwargs):
        return [
            {
                "experiment_id": "exp_001",
                "variant_id": "var_0001",
                "impressions": 300,
                "clicks": 30,
                "ctr": 0.10,
                "watch_time_hours": 4.0,
                "average_view_duration_seconds": 30.0,
            },
            {
                "experiment_id": "exp_001",
                "variant_id": "var_0002",
                "impressions": 320,
                "clicks": 70,
                "ctr": 0.21875,
                "watch_time_hours": 5.0,
                "average_view_duration_seconds": 35.0,
            },
        ]

    monkeypatch.setattr(collector_evaluator_bridge, "collect_analytics_rows", _fake_collect)

    result = evaluate_from_collector(
        experiment_id="exp_001",
        variant_by_video_id={"v1": "var_0001", "v2": "var_0002"},
        video_ids=["v1", "v2"],
        evaluated_at_override="2026-07-09T12:00:00+00:00",
    )

    assert result["evaluation"].winner_variant_id == "var_0002"
    assert result["evaluation"].decision_reason == "clear_ctr_winner"


def test_bridge_returns_no_eligible_metrics_when_rows_incomplete(monkeypatch):
    def _fake_collect(**kwargs):
        return [
            {
                "experiment_id": "exp_001",
                "variant_id": "var_0001",
                "impressions": None,
                "clicks": None,
                "ctr": None,
                "watch_time_hours": None,
                "average_view_duration_seconds": None,
            }
        ]

    monkeypatch.setattr(collector_evaluator_bridge, "collect_analytics_rows", _fake_collect)

    result = evaluate_from_collector(
        experiment_id="exp_001",
        variant_by_video_id={"v1": "var_0001"},
        video_ids=["v1"],
        evaluated_at_override="2026-07-09T12:00:00+00:00",
    )

    assert result["evaluation"].winner_variant_id is None
    assert result["evaluation"].decision_reason == "no_eligible_metrics"
    assert result["evaluation"].insufficient_data is True


def test_bridge_result_is_deterministic_with_override(monkeypatch):
    def _fake_collect(**kwargs):
        return [
            {
                "experiment_id": "exp_001",
                "variant_id": "var_0001",
                "impressions": 300,
                "clicks": 30,
                "ctr": 0.10,
                "watch_time_hours": 4.0,
                "average_view_duration_seconds": 30.0,
            },
            {
                "experiment_id": "exp_001",
                "variant_id": "var_0002",
                "impressions": 320,
                "clicks": 70,
                "ctr": 0.21875,
                "watch_time_hours": 5.0,
                "average_view_duration_seconds": 35.0,
            },
        ]

    monkeypatch.setattr(collector_evaluator_bridge, "collect_analytics_rows", _fake_collect)

    fixed_time = "2026-07-09T12:00:00+00:00"
    first = evaluate_from_collector(
        experiment_id="exp_001",
        variant_by_video_id={"v1": "var_0001", "v2": "var_0002"},
        video_ids=["v1", "v2"],
        evaluated_at_override=fixed_time,
    )
    second = evaluate_from_collector(
        experiment_id="exp_001",
        variant_by_video_id={"v1": "var_0001", "v2": "var_0002"},
        video_ids=["v1", "v2"],
        evaluated_at_override=fixed_time,
    )

    assert first["evaluation"] == second["evaluation"]
