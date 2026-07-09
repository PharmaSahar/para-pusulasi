from __future__ import annotations

import pytest

from src.experiment_evaluator import evaluate_experiment


def _row(
    *,
    experiment_id: str = "exp_001",
    variant_id: str,
    impressions: int,
    clicks: int,
    ctr: float,
    watch_time_hours: float = 10.0,
    average_view_duration_seconds: float = 42.0,
) -> dict:
    return {
        "experiment_id": experiment_id,
        "variant_id": variant_id,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "watch_time_hours": watch_time_hours,
        "average_view_duration_seconds": average_view_duration_seconds,
    }


def test_evaluator_selects_clear_winner():
    rows = [
        _row(variant_id="var_0001", impressions=400, clicks=40, ctr=0.10),
        _row(variant_id="var_0002", impressions=420, clicks=74, ctr=0.176),
    ]

    result = evaluate_experiment(metrics=rows, min_impressions=100, min_ctr_delta=0.01)

    assert result.winner_variant_id == "var_0002"
    assert result.decision_reason == "clear_ctr_winner"
    assert result.insufficient_data is False
    assert result.confidence_band in {"low", "medium", "high"}
    assert isinstance(result.evaluated_at, str) and result.evaluated_at


def test_evaluator_returns_no_decision_for_insufficient_data():
    rows = [
        _row(variant_id="var_0001", impressions=90, clicks=9, ctr=0.10),
        _row(variant_id="var_0002", impressions=95, clicks=14, ctr=0.147),
    ]

    result = evaluate_experiment(metrics=rows, min_impressions=100, min_ctr_delta=0.01)

    assert result.winner_variant_id is None
    assert result.decision_reason == "insufficient_impressions"
    assert result.confidence_band == "none"
    assert result.insufficient_data is True


def test_evaluator_returns_no_decision_for_tie():
    rows = [
        _row(variant_id="var_0001", impressions=200, clicks=20, ctr=0.10),
        _row(variant_id="var_0002", impressions=230, clicks=23, ctr=0.10),
    ]

    result = evaluate_experiment(metrics=rows, min_impressions=100, min_ctr_delta=0.01)

    assert result.winner_variant_id is None
    assert result.decision_reason == "ctr_tie"
    assert result.confidence_band == "none"
    assert result.insufficient_data is False


def test_evaluator_rejects_missing_required_field():
    rows = [
        _row(variant_id="var_0001", impressions=200, clicks=20, ctr=0.10),
        {
            "experiment_id": "exp_001",
            "variant_id": "var_0002",
            "impressions": 210,
            "clicks": 26,
            # ctr intentionally missing
            "watch_time_hours": 11.0,
            "average_view_duration_seconds": 43.0,
        },
    ]

    with pytest.raises(ValueError, match="missing_required_field:ctr"):
        evaluate_experiment(metrics=rows)


def test_evaluator_rejects_negative_metric_values():
    rows = [
        _row(variant_id="var_0001", impressions=200, clicks=-1, ctr=0.10),
        _row(variant_id="var_0002", impressions=210, clicks=21, ctr=0.10),
    ]

    with pytest.raises(ValueError, match="invalid_metric:clicks"):
        evaluate_experiment(metrics=rows)


def test_evaluator_result_is_deterministic_for_same_input():
    rows = [
        _row(variant_id="var_0002", impressions=420, clicks=74, ctr=0.176),
        _row(variant_id="var_0001", impressions=400, clicks=40, ctr=0.10),
        _row(variant_id="var_0003", impressions=390, clicks=39, ctr=0.10),
    ]

    fixed_evaluated_at = "2026-07-09T12:00:00+00:00"
    first = evaluate_experiment(
        metrics=rows,
        min_impressions=100,
        min_ctr_delta=0.01,
        evaluated_at_override=fixed_evaluated_at,
    )
    second = evaluate_experiment(
        metrics=list(reversed(rows)),
        min_impressions=100,
        min_ctr_delta=0.01,
        evaluated_at_override=fixed_evaluated_at,
    )

    assert first == second


def test_evaluator_uses_computed_ctr_when_provided_ctr_conflicts():
    rows = [
        # Provided ctr is intentionally high, but computed CTR is 5/200 = 0.025
        _row(variant_id="var_0001", impressions=200, clicks=5, ctr=0.99),
        # Provided ctr is intentionally low, but computed CTR is 30/200 = 0.15
        _row(variant_id="var_0002", impressions=200, clicks=30, ctr=0.01),
    ]

    result = evaluate_experiment(metrics=rows, min_impressions=100, min_ctr_delta=0.01)

    assert result.winner_variant_id == "var_0002"
    assert result.decision_reason == "clear_ctr_winner"
