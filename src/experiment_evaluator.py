"""Experiment evaluator core logic (T3.1).

This module is intentionally pure and analytics-agnostic:
- No pipeline integration
- No collector dependencies
- No registry writes
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


DEFAULT_MIN_IMPRESSIONS = 100
DEFAULT_MIN_CTR_DELTA = 0.01

_REQUIRED_FIELDS = (
    "experiment_id",
    "variant_id",
    "impressions",
    "clicks",
    "ctr",
    "watch_time_hours",
    "average_view_duration_seconds",
)


@dataclass(frozen=True)
class VariantPerformance:
    experiment_id: str
    variant_id: str
    impressions: int
    clicks: int
    ctr: float
    watch_time_hours: float
    average_view_duration_seconds: float


@dataclass(frozen=True)
class EvaluationResult:
    winner_variant_id: str | None
    decision_reason: str
    confidence_band: str
    insufficient_data: bool
    evaluated_at: str


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(field_name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_required_field:{field_name}")
    return value.strip()


def _to_int(field_name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid_metric:{field_name}")
    return value


def _to_float(field_name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid_metric:{field_name}")
    return float(value)


def _validate_non_negative(field_name: str, value: float | int) -> None:
    if value < 0:
        raise ValueError(f"invalid_metric:{field_name}")


def _validate_row(payload: dict[str, Any]) -> VariantPerformance:
    for field in _REQUIRED_FIELDS:
        if field not in payload:
            raise ValueError(f"missing_required_field:{field}")

    experiment_id = _require_text("experiment_id", payload.get("experiment_id"))
    variant_id = _require_text("variant_id", payload.get("variant_id"))

    impressions = _to_int("impressions", payload.get("impressions"))
    clicks = _to_int("clicks", payload.get("clicks"))
    ctr_provided = _to_float("ctr", payload.get("ctr"))
    watch_time_hours = _to_float("watch_time_hours", payload.get("watch_time_hours"))
    average_view_duration_seconds = _to_float(
        "average_view_duration_seconds", payload.get("average_view_duration_seconds")
    )

    _validate_non_negative("impressions", impressions)
    _validate_non_negative("clicks", clicks)
    _validate_non_negative("ctr", ctr_provided)
    _validate_non_negative("watch_time_hours", watch_time_hours)
    _validate_non_negative("average_view_duration_seconds", average_view_duration_seconds)

    if clicks > impressions:
        raise ValueError("invalid_metric:clicks")
    if ctr_provided > 1.0:
        raise ValueError("invalid_metric:ctr")

    # Canonical CTR for evaluation is derived from clicks/impressions.
    ctr = 0.0 if impressions == 0 else (clicks / impressions)

    return VariantPerformance(
        experiment_id=experiment_id,
        variant_id=variant_id,
        impressions=impressions,
        clicks=clicks,
        ctr=ctr,
        watch_time_hours=watch_time_hours,
        average_view_duration_seconds=average_view_duration_seconds,
    )


def _resolve_confidence_band(ctr_gap: float) -> str:
    if ctr_gap >= 0.05:
        return "high"
    if ctr_gap >= 0.02:
        return "medium"
    return "low"


def _validate_thresholds(min_impressions: int, min_ctr_delta: float) -> None:
    if isinstance(min_impressions, bool) or not isinstance(min_impressions, int) or min_impressions <= 0:
        raise ValueError("invalid_threshold:min_impressions")
    if isinstance(min_ctr_delta, bool) or not isinstance(min_ctr_delta, (int, float)) or float(min_ctr_delta) < 0:
        raise ValueError("invalid_threshold:min_ctr_delta")


def evaluate_experiment(
    *,
    metrics: Iterable[dict[str, Any]],
    min_impressions: int = DEFAULT_MIN_IMPRESSIONS,
    min_ctr_delta: float = DEFAULT_MIN_CTR_DELTA,
    evaluated_at_override: str | None = None,
) -> EvaluationResult:
    """Evaluate experiment metrics and return deterministic winner decision.

    Rules:
    - No winner unless at least two variants satisfy minimum impressions.
    - Select winner only when top CTR exceeds second CTR by min_ctr_delta.
    - If top CTR ties with second CTR, return no-decision.
    - Input metric rows must be complete and valid.
    """
    _validate_thresholds(min_impressions=min_impressions, min_ctr_delta=float(min_ctr_delta))

    rows = list(metrics)
    if not rows:
        raise ValueError("empty_metrics")

    validated = [_validate_row(item) for item in rows]

    experiment_ids = {row.experiment_id for row in validated}
    if len(experiment_ids) != 1:
        raise ValueError("mixed_experiment_id")

    eligible = [item for item in validated if item.impressions >= min_impressions]
    if evaluated_at_override is None:
        evaluated_at = _utcnow_iso()
    else:
        evaluated_at = _require_text("evaluated_at_override", evaluated_at_override)

    if len(eligible) < 2:
        return EvaluationResult(
            winner_variant_id=None,
            decision_reason="insufficient_impressions",
            confidence_band="none",
            insufficient_data=True,
            evaluated_at=evaluated_at,
        )

    ranked = sorted(eligible, key=lambda item: (-item.ctr, item.variant_id))
    top = ranked[0]
    second = ranked[1]
    ctr_gap = top.ctr - second.ctr

    if ctr_gap == 0.0:
        return EvaluationResult(
            winner_variant_id=None,
            decision_reason="ctr_tie",
            confidence_band="none",
            insufficient_data=False,
            evaluated_at=evaluated_at,
        )

    if ctr_gap < float(min_ctr_delta):
        return EvaluationResult(
            winner_variant_id=None,
            decision_reason="ctr_gap_below_threshold",
            confidence_band="none",
            insufficient_data=False,
            evaluated_at=evaluated_at,
        )

    return EvaluationResult(
        winner_variant_id=top.variant_id,
        decision_reason="clear_ctr_winner",
        confidence_band=_resolve_confidence_band(ctr_gap),
        insufficient_data=False,
        evaluated_at=evaluated_at,
    )
