"""Collector -> Evaluator bridge.

Transforms collector-normalized rows into evaluator input and returns a
single evaluation result with attached collector context.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .analytics_collector import build_evaluator_rows, collect_analytics_rows
from .experiment_evaluator import (
    DEFAULT_MIN_CTR_DELTA,
    DEFAULT_MIN_IMPRESSIONS,
    EvaluationResult,
    evaluate_experiment,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate_from_collector(
    *,
    experiment_id: str,
    variant_by_video_id: dict[str, str],
    video_ids: list[str],
    channel_cfg=None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_impressions: int = DEFAULT_MIN_IMPRESSIONS,
    min_ctr_delta: float = DEFAULT_MIN_CTR_DELTA,
    evaluated_at_override: str | None = None,
) -> dict[str, Any]:
    """Collect analytics rows and evaluate winner with evaluator core."""
    collector_rows = collect_analytics_rows(
        experiment_id=experiment_id,
        variant_by_video_id=variant_by_video_id,
        video_ids=video_ids,
        channel_cfg=channel_cfg,
        start_date=start_date,
        end_date=end_date,
    )
    evaluator_rows = build_evaluator_rows(collector_rows)

    if not evaluator_rows:
        evaluation = EvaluationResult(
            winner_variant_id=None,
            decision_reason="no_eligible_metrics",
            confidence_band="none",
            insufficient_data=True,
            evaluated_at=evaluated_at_override or _utcnow_iso(),
        )
    else:
        evaluation = evaluate_experiment(
            metrics=evaluator_rows,
            min_impressions=min_impressions,
            min_ctr_delta=min_ctr_delta,
            evaluated_at_override=evaluated_at_override,
        )

    return {
        "collector_rows": collector_rows,
        "evaluator_rows": evaluator_rows,
        "evaluation": evaluation,
    }
