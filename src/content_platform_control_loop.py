"""Self-improving content production control loop.

This module computes unified quality and channel health signals, tracks baselines,
detects regressions, and emits safe recommendations with strict governance.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean
from typing import Any

from .experiment_registry import list_experiments


QUALITY_COMPONENTS = (
    "channel_topic_fit",
    "script_quality",
    "metadata_completeness",
    "visual_relevance",
    "visual_diversity",
    "thumbnail_quality",
    "render_quality",
    "upload_reliability",
    "youtube_performance",
)

QUALITY_WEIGHTS = {
    "channel_topic_fit": 0.14,
    "script_quality": 0.14,
    "metadata_completeness": 0.1,
    "visual_relevance": 0.09,
    "visual_diversity": 0.08,
    "thumbnail_quality": 0.12,
    "render_quality": 0.1,
    "upload_reliability": 0.11,
    "youtube_performance": 0.12,
}

MIN_SAMPLE_DEFAULTS = {
    "channel": 5,
    "system": 25,
    "regression": 12,
}

DEFAULT_CONFIDENCE_THRESHOLD = 0.65
MAX_RELATIVE_CHANGE = 0.15
TOPIC_ACCURACY_FLOOR = 60.0
SAFETY_FLOOR = 70.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _clamp(score: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, score))


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(mean(values))


def _normalize_ratio(value: Any) -> float | None:
    v = _safe_float(value)
    if v is None:
        return None
    if v <= 1.0:
        return _clamp(v * 100.0)
    return _clamp(v)


def _normalize_ctr(value: Any) -> float | None:
    ratio = _normalize_ratio(value)
    if ratio is None:
        return None
    return ratio


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _token_set(value: Any) -> set[str]:
    text = str(value or "").lower()
    tokens = [token for token in text.replace("_", " ").replace("-", " ").split() if token]
    return set(tokens)


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    created = _parse_dt(row.get("created_at")) or _utcnow()
    upload_success = row.get("upload_success")
    if upload_success is None:
        upload_success = bool(row.get("youtube_url"))

    topic_fit = _safe_float(row.get("channel_topic_fit_score"))
    if topic_fit is None:
        if _as_bool(row.get("topic_leakage")):
            topic_fit = 35.0
        elif _non_empty_text(row.get("niche")):
            topic_fit = 75.0
        else:
            topic_fit = 60.0

    script_quality = _safe_float(row.get("overall_quality_score"))
    if script_quality is None:
        script_parts = [
            _safe_float(row.get("hook_score")),
            _safe_float(row.get("structure_score")),
            _safe_float(row.get("retention_signal_score")),
        ]
        script_quality = _mean([v for v in script_parts if v is not None]) or 55.0

    meta_fields = [
        _non_empty_text(row.get("title")),
        _non_empty_text(row.get("description")),
        _non_empty_text(row.get("thumbnail_path")) or _non_empty_text(row.get("thumbnail_url")),
        bool(row.get("tags")),
        _non_empty_text(row.get("video_id")) or _non_empty_text(row.get("youtube_url")),
    ]
    metadata_completeness = 100.0 * (sum(1 for ok in meta_fields if ok) / len(meta_fields))

    thumbnail_quality = _safe_float(row.get("thumbnail_quality_score"))
    if thumbnail_quality is None:
        thumbnail_quality = _safe_float(row.get("thumbnail_attention_score")) or 55.0

    visual_relevance = _safe_float(row.get("visual_relevance_score"))
    if visual_relevance is None:
        visual_relevance = (thumbnail_quality * 0.6) + (topic_fit * 0.4)

    visual_reuse = _normalize_ratio(row.get("visual_reuse_ratio"))
    if visual_reuse is None:
        visual_reuse = 0.0

    visual_diversity = _safe_float(row.get("visual_diversity_score"))
    if visual_diversity is None:
        visual_diversity = _clamp(100.0 - visual_reuse)

    render_status = str(row.get("render_status") or "").strip().lower()
    render_quality = _safe_float(row.get("render_quality_score"))
    if render_quality is None:
        render_quality = 92.0 if render_status in {"ok", "success", "rendered", "completed", ""} else 45.0

    upload_reliability = _safe_float(row.get("upload_reliability_score"))
    if upload_reliability is None:
        upload_reliability = 100.0 if _as_bool(upload_success) else 35.0

    ctr = _normalize_ctr(row.get("click_through_rate"))
    watch_time = _safe_float(row.get("watch_time_hours"))
    perf_score = _safe_float(row.get("youtube_performance_score"))
    if perf_score is None:
        ctr_component = _clamp((ctr or 0.0) * 10.0)
        wt_component = _clamp((watch_time or 0.0) * 7.0)
        perf_score = _clamp((ctr_component * 0.55) + (wt_component * 0.45))

    title_tokens = _token_set(row.get("title"))
    script_tokens = _token_set(row.get("script"))

    components = {
        "channel_topic_fit": _clamp(topic_fit),
        "script_quality": _clamp(script_quality),
        "metadata_completeness": _clamp(metadata_completeness),
        "visual_relevance": _clamp(visual_relevance),
        "visual_diversity": _clamp(visual_diversity),
        "thumbnail_quality": _clamp(thumbnail_quality),
        "render_quality": _clamp(render_quality),
        "upload_reliability": _clamp(upload_reliability),
        "youtube_performance": _clamp(perf_score),
    }

    weighted = sum(components[name] * QUALITY_WEIGHTS[name] for name in QUALITY_COMPONENTS)

    return {
        **row,
        "created_at": created.isoformat(),
        "upload_success": bool(_as_bool(upload_success)),
        "guard_blocked": bool(_as_bool(row.get("guard_blocked"))),
        "topic_leakage": bool(_as_bool(row.get("topic_leakage"))),
        "visual_reuse_ratio": visual_reuse,
        "component_scores": components,
        "quality_score": round(_clamp(weighted), 3),
        "title_tokens": sorted(title_tokens),
        "script_tokens": sorted(script_tokens),
        "channel_id": str(row.get("channel_id") or "unknown").strip() or "unknown",
        "content_id": str(row.get("content_id") or row.get("video_id") or "unknown").strip() or "unknown",
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def load_input_rows(*, performance_path: Path, routing_guard_path: Path | None = None) -> list[dict[str, Any]]:
    rows = _load_jsonl(performance_path)
    if not rows:
        return []

    guard_by_video: dict[str, bool] = {}
    for event in _load_jsonl(routing_guard_path or Path("logs/routing_guard_decisions.jsonl")):
        decision = str(event.get("decision") or "").strip().lower()
        key = str(event.get("video_id") or event.get("content_id") or "").strip()
        if not key:
            continue
        if decision == "block":
            guard_by_video[key] = True

    normalized: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        key = str(row.get("video_id") or row.get("content_id") or "").strip()
        if key and key in guard_by_video:
            merged["guard_blocked"] = True
        normalized.append(_normalize_row(merged))
    return normalized


def _slice_by_days(rows: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    cutoff = _utcnow() - timedelta(days=max(1, int(days)))
    out: list[dict[str, Any]] = []
    for row in rows:
        dt = _parse_dt(row.get("created_at"))
        if dt and dt >= cutoff:
            out.append(row)
    return out


def _summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "sample_size": 0,
            "avg_quality": None,
            "avg_channel_topic_fit": None,
            "avg_ctr": None,
            "avg_watch_time_hours": None,
            "content_similarity": None,
            "visual_reuse_rate": None,
            "upload_failure_rate": None,
            "guard_block_rate": None,
            "topic_leakage_rate": None,
            "metadata_completeness": None,
            "channel_health_score": None,
        }

    ctr_values = [_normalize_ctr(r.get("click_through_rate")) for r in rows]
    wt_values = [_safe_float(r.get("watch_time_hours")) for r in rows]
    quality_values = [
        _safe_float(r.get("quality_score"))
        if _safe_float(r.get("quality_score")) is not None
        else _safe_float(r.get("overall_quality_score"))
        for r in rows
    ]
    topic_fit_values: list[float | None] = []
    for r in rows:
        component_fit = _safe_float((r.get("component_scores") or {}).get("channel_topic_fit"))
        if component_fit is not None:
            topic_fit_values.append(component_fit)
            continue
        explicit_fit = _safe_float(r.get("channel_topic_fit_score"))
        if explicit_fit is not None:
            topic_fit_values.append(explicit_fit)
            continue
        topic_fit_values.append(35.0 if _as_bool(r.get("topic_leakage")) else 75.0)
    metadata_values = [_safe_float((r.get("component_scores") or {}).get("metadata_completeness")) for r in rows]
    visual_reuse = [_safe_float(r.get("visual_reuse_ratio")) for r in rows]

    similarities: list[float] = []
    for idx in range(1, len(rows)):
        prev = rows[idx - 1]
        cur = rows[idx]
        tokens_a = set(prev.get("title_tokens") or []) | set(prev.get("script_tokens") or [])
        tokens_b = set(cur.get("title_tokens") or []) | set(cur.get("script_tokens") or [])
        similarities.append(_jaccard_similarity(tokens_a, tokens_b) * 100.0)

    failure_rate = (sum(1 for r in rows if not bool(r.get("upload_success", True))) / len(rows)) * 100.0
    guard_block_rate = (sum(1 for r in rows if bool(r.get("guard_blocked", False))) / len(rows)) * 100.0
    leakage_rate = (sum(1 for r in rows if bool(r.get("topic_leakage", False))) / len(rows)) * 100.0

    avg_quality = _mean([v for v in quality_values if v is not None])
    avg_topic_fit = _mean([v for v in topic_fit_values if v is not None])
    avg_ctr = _mean([v for v in ctr_values if v is not None])
    avg_wt = _mean([v for v in wt_values if v is not None])
    avg_similarity = _mean(similarities)
    avg_visual_reuse = _mean([v for v in visual_reuse if v is not None])
    avg_meta = _mean([v for v in metadata_values if v is not None])

    health_parts = [
        avg_quality or 0.0,
        _clamp((avg_ctr or 0.0) * 10.0),
        _clamp((avg_wt or 0.0) * 7.0),
        _clamp(100.0 - failure_rate),
        _clamp(100.0 - guard_block_rate),
        _clamp(100.0 - leakage_rate),
    ]

    return {
        "sample_size": len(rows),
        "avg_quality": round(avg_quality, 3) if avg_quality is not None else None,
        "avg_channel_topic_fit": round(avg_topic_fit, 3) if avg_topic_fit is not None else None,
        "avg_ctr": round(avg_ctr, 3) if avg_ctr is not None else None,
        "avg_watch_time_hours": round(avg_wt, 3) if avg_wt is not None else None,
        "content_similarity": round(avg_similarity, 3) if avg_similarity is not None else 0.0,
        "visual_reuse_rate": round(avg_visual_reuse, 3) if avg_visual_reuse is not None else 0.0,
        "upload_failure_rate": round(failure_rate, 3),
        "guard_block_rate": round(guard_block_rate, 3),
        "topic_leakage_rate": round(leakage_rate, 3),
        "metadata_completeness": round(avg_meta, 3) if avg_meta is not None else None,
        "channel_health_score": round(_clamp(mean(health_parts)), 3),
    }


def build_baselines(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_channel[str(row.get("channel_id") or "unknown")].append(row)

    recent_7 = _slice_by_days(rows, 7)
    recent_30 = _slice_by_days(rows, 30)

    per_channel: dict[str, Any] = {}
    for channel_id, bucket in by_channel.items():
        per_channel[channel_id] = {
            "all_time": _summary_from_rows(bucket),
            "recent_7d": _summary_from_rows(_slice_by_days(bucket, 7)),
            "recent_30d": _summary_from_rows(_slice_by_days(bucket, 30)),
        }

    return {
        "recent_7d": _summary_from_rows(recent_7),
        "recent_30d": _summary_from_rows(recent_30),
        "per_channel": per_channel,
        "system_wide": _summary_from_rows(rows),
    }


def _regression_check(
    *,
    name: str,
    direction: str,
    current: float | None,
    baseline: float | None,
    threshold: float,
    sample_size: int,
    min_sample: int,
) -> dict[str, Any]:
    if current is None or baseline is None:
        return {
            "name": name,
            "triggered": False,
            "reason": "missing_data",
            "confidence": 0.0,
            "sample_size": sample_size,
        }

    if sample_size < min_sample:
        return {
            "name": name,
            "triggered": False,
            "reason": "weak_sample",
            "confidence": 0.0,
            "sample_size": sample_size,
        }

    delta = current - baseline
    if direction == "down":
        triggered = delta <= (-abs(threshold))
        magnitude = abs(delta) / max(0.01, abs(baseline))
    else:
        triggered = delta >= abs(threshold)
        magnitude = abs(delta) / max(0.01, abs(baseline))

    confidence = _clamp((sample_size / max(min_sample, 1)) * 45.0 + magnitude * 55.0, 0.0, 100.0) / 100.0
    return {
        "name": name,
        "triggered": bool(triggered),
        "current": round(current, 4),
        "baseline": round(baseline, 4),
        "delta": round(delta, 4),
        "threshold": threshold,
        "confidence": round(confidence, 3),
        "sample_size": sample_size,
    }


def detect_regressions(
    *,
    rows: list[dict[str, Any]],
    baselines: dict[str, Any],
    min_sample_size: int = MIN_SAMPLE_DEFAULTS["regression"],
) -> list[dict[str, Any]]:
    recent_7 = _slice_by_days(rows, 7)
    base_30 = _slice_by_days(rows, 30)
    cur = _summary_from_rows(recent_7)
    base = _summary_from_rows(base_30)

    checks = [
        _regression_check(
            name="falling_ctr",
            direction="down",
            current=_safe_float(cur.get("avg_ctr")),
            baseline=_safe_float(base.get("avg_ctr")),
            threshold=0.4,
            sample_size=int(cur.get("sample_size", 0) or 0),
            min_sample=min_sample_size,
        ),
        _regression_check(
            name="falling_watch_time",
            direction="down",
            current=_safe_float(cur.get("avg_watch_time_hours")),
            baseline=_safe_float(base.get("avg_watch_time_hours")),
            threshold=0.25,
            sample_size=int(cur.get("sample_size", 0) or 0),
            min_sample=min_sample_size,
        ),
        _regression_check(
            name="rising_content_similarity",
            direction="up",
            current=_safe_float(cur.get("content_similarity")),
            baseline=_safe_float(base.get("content_similarity")),
            threshold=8.0,
            sample_size=int(cur.get("sample_size", 0) or 0),
            min_sample=min_sample_size,
        ),
        _regression_check(
            name="rising_visual_reuse",
            direction="up",
            current=_safe_float(cur.get("visual_reuse_rate")),
            baseline=_safe_float(base.get("visual_reuse_rate")),
            threshold=7.0,
            sample_size=int(cur.get("sample_size", 0) or 0),
            min_sample=min_sample_size,
        ),
        _regression_check(
            name="rising_upload_failures",
            direction="up",
            current=_safe_float(cur.get("upload_failure_rate")),
            baseline=_safe_float(base.get("upload_failure_rate")),
            threshold=5.0,
            sample_size=int(cur.get("sample_size", 0) or 0),
            min_sample=min_sample_size,
        ),
        _regression_check(
            name="rising_guard_blocks",
            direction="up",
            current=_safe_float(cur.get("guard_block_rate")),
            baseline=_safe_float(base.get("guard_block_rate")),
            threshold=5.0,
            sample_size=int(cur.get("sample_size", 0) or 0),
            min_sample=min_sample_size,
        ),
        _regression_check(
            name="channel_topic_leakage",
            direction="up",
            current=_safe_float(cur.get("topic_leakage_rate")),
            baseline=_safe_float(base.get("topic_leakage_rate")),
            threshold=4.0,
            sample_size=int(cur.get("sample_size", 0) or 0),
            min_sample=min_sample_size,
        ),
        _regression_check(
            name="metadata_degradation",
            direction="down",
            current=_safe_float(cur.get("metadata_completeness")),
            baseline=_safe_float(base.get("metadata_completeness")),
            threshold=5.0,
            sample_size=int(cur.get("sample_size", 0) or 0),
            min_sample=min_sample_size,
        ),
    ]

    for check in checks:
        if check.get("reason") == "weak_sample":
            check["blocked_by_learning_rules"] = True
            check["rule"] = "minimum_sample_sizes"

    return checks


@dataclass(frozen=True)
class LearningRules:
    min_channel_sample_size: int = MIN_SAMPLE_DEFAULTS["channel"]
    min_system_sample_size: int = MIN_SAMPLE_DEFAULTS["system"]
    min_regression_sample_size: int = MIN_SAMPLE_DEFAULTS["regression"]
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    max_relative_change: float = MAX_RELATIVE_CHANGE
    topic_accuracy_floor: float = TOPIC_ACCURACY_FLOOR
    safety_floor: float = SAFETY_FLOOR


def _bounded_change(value: float, direction: str, max_relative_change: float) -> float:
    delta = abs(value) * max_relative_change
    if direction == "decrease":
        return value - delta
    return value + delta


def _topic_priority(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_channel[row["channel_id"]].append(row)

    priorities: list[dict[str, Any]] = []
    for channel_id, bucket in by_channel.items():
        quality = _summary_from_rows(bucket).get("avg_quality")
        leakage = _summary_from_rows(bucket).get("topic_leakage_rate")
        direction = "increase" if (quality or 0.0) >= 65.0 and (leakage or 100.0) <= 10.0 else "review"
        priorities.append(
            {
                "channel_id": channel_id,
                "priority": "high" if direction == "increase" else "guarded",
                "confidence": round(min(0.95, (len(bucket) / 30.0) + 0.25), 3),
                "trace": {
                    "avg_quality": quality,
                    "topic_leakage_rate": leakage,
                    "sample_size": len(bucket),
                },
            }
        )
    priorities.sort(key=lambda item: str(item.get("channel_id") or ""))
    return priorities


def build_recommendations(
    *,
    rows: list[dict[str, Any]],
    baselines: dict[str, Any],
    regressions: list[dict[str, Any]],
    rules: LearningRules,
) -> list[dict[str, Any]]:
    summary_7 = dict(baselines.get("recent_7d") or {})
    sample_size = int(summary_7.get("sample_size", 0) or 0)
    quality = _safe_float(summary_7.get("avg_quality")) or 0.0

    reg_by_name = {item.get("name"): item for item in regressions}

    recommendations = [
        {
            "type": "topic_priorities",
            "action": "focus_on_high_fit_topics",
            "confidence": round(min(0.95, 0.3 + (sample_size / 40.0)), 3),
            "trace": {
                "priorities": _topic_priority(rows),
                "system_quality_7d": quality,
            },
        },
        {
            "type": "thumbnail_style",
            "action": "increase_contrast_and_specificity",
            "confidence": 0.7,
            "trace": {
                "trigger": "falling_ctr" if reg_by_name.get("falling_ctr", {}).get("triggered") else "steady_ctr",
                "avg_thumbnail_quality": _safe_float(summary_7.get("avg_quality")),
            },
        },
        {
            "type": "hook_style",
            "action": "prefer_problem_solution_opening",
            "confidence": 0.68,
            "trace": {
                "trigger": "falling_watch_time" if reg_by_name.get("falling_watch_time", {}).get("triggered") else "stable_watch_time",
            },
        },
        {
            "type": "script_length",
            "action": "trim_10_percent_for_low_retention_channels",
            "confidence": 0.66,
            "trace": {"bound": rules.max_relative_change},
        },
        {
            "type": "publication_time",
            "action": "run_slot_canary_before_rollout",
            "confidence": 0.64,
            "trace": {"policy": "canary_only"},
        },
        {
            "type": "visual_strategy",
            "action": "increase_visual_diversity_budget",
            "confidence": 0.71,
            "trace": {
                "trigger": "rising_visual_reuse" if reg_by_name.get("rising_visual_reuse", {}).get("triggered") else "normal_reuse",
            },
        },
        {
            "type": "retry_policy",
            "action": "exponential_backoff_with_cap",
            "confidence": 0.69,
            "trace": {
                "trigger": "rising_upload_failures" if reg_by_name.get("rising_upload_failures", {}).get("triggered") else "stable_uploads",
            },
        },
    ]

    for item in recommendations:
        if sample_size < rules.min_channel_sample_size:
            item["status"] = "rejected"
            item["reason"] = "weak_sample"
            item["blocked_by_rule"] = "minimum_sample_sizes"
            continue

        if float(item.get("confidence", 0.0) or 0.0) < rules.confidence_threshold:
            item["status"] = "rejected"
            item["reason"] = "low_confidence"
            item["blocked_by_rule"] = "confidence_threshold"
            continue

        item["status"] = "recommended"

    return recommendations


def apply_learning_rules(
    *,
    recommendations: list[dict[str, Any]],
    baselines: dict[str, Any],
    regressions: list[dict[str, Any]],
    rules: LearningRules,
) -> dict[str, Any]:
    summary_7 = dict(baselines.get("recent_7d") or {})
    sample_size = int(summary_7.get("sample_size", 0) or 0)
    topic_fit = _safe_float(summary_7.get("avg_channel_topic_fit"))
    if topic_fit is None:
        topic_fit = _safe_float(summary_7.get("avg_quality")) or 0.0
    safety_score = _clamp(100.0 - (_safe_float(summary_7.get("guard_block_rate")) or 0.0))

    approved_changes: list[dict[str, Any]] = []
    canary_changes: list[dict[str, Any]] = []
    rollout_changes: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for rec in recommendations:
        rec_type = str(rec.get("type") or "unknown")
        conf = float(rec.get("confidence", 0.0) or 0.0)
        rec_status = str(rec.get("status") or "rejected")

        event = {
            "event": "recommendation_reviewed",
            "recommendation_type": rec_type,
            "status": rec_status,
            "confidence": conf,
            "timestamp_utc": _utcnow().isoformat(),
        }

        if rec_status != "recommended":
            event["decision"] = "blocked"
            event["reason"] = str(rec.get("reason") or "rule_block")
            blocked.append({**rec, "decision": "blocked"})
            audit.append(event)
            continue

        if sample_size <= 1:
            event["decision"] = "blocked"
            event["reason"] = "single_video_decision_forbidden"
            blocked.append({**rec, "decision": "blocked", "reason": "single_video_decision_forbidden"})
            audit.append(event)
            continue

        if topic_fit < rules.topic_accuracy_floor:
            event["decision"] = "blocked"
            event["reason"] = "topic_accuracy_floor"
            blocked.append({**rec, "decision": "blocked", "reason": "topic_accuracy_floor"})
            audit.append(event)
            continue

        if safety_score < rules.safety_floor:
            event["decision"] = "blocked"
            event["reason"] = "safety_floor"
            blocked.append({**rec, "decision": "blocked", "reason": "safety_floor"})
            audit.append(event)
            continue

        bounded = {
            "parameter": rec_type,
            "max_relative_change": rules.max_relative_change,
            "proposed_value": _bounded_change(1.0, "increase", rules.max_relative_change),
        }
        approved = {
            **rec,
            "decision": "approved_configuration_change",
            "bounded_change": bounded,
        }
        approved_changes.append(approved)

        canary = {
            **approved,
            "decision": "experimental_canary_change",
            "canary_scope": "single_channel_10_percent",
        }
        canary_changes.append(canary)

        event["decision"] = "canary_only"
        event["bounded_change"] = bounded
        audit.append(event)

    # No automatic production rollout without explicit validation evidence.
    for rec in canary_changes:
        rollout_changes.append(
            {
                **rec,
                "decision": "production_rollout",
                "status": "blocked",
                "reason": "requires_validated_canary_and_manual_approval",
            }
        )

    return {
        "rules": {
            "minimum_sample_sizes": {
                "channel": rules.min_channel_sample_size,
                "system": rules.min_system_sample_size,
                "regression": rules.min_regression_sample_size,
            },
            "confidence_threshold": rules.confidence_threshold,
            "single_video_optimization_forbidden": True,
            "topic_accuracy_floor": rules.topic_accuracy_floor,
            "safety_floor": rules.safety_floor,
            "bounded_parameter_changes": {
                "max_relative_change": rules.max_relative_change,
            },
            "no_unsafe_automatic_optimization": True,
        },
        "approved_configuration_changes": approved_changes,
        "experimental_canary_changes": canary_changes,
        "production_rollouts": rollout_changes,
        "blocked_adjustments": blocked,
        "audit_trail": audit,
    }


def _stable_experiment_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"exp_{digest[:12]}"


def build_experiment_tracking(
    *,
    recommendations: list[dict[str, Any]],
    learning: dict[str, Any],
    channel_ids: list[str],
    registry_path: Path,
) -> dict[str, Any]:
    experiments: list[dict[str, Any]] = []

    for idx, rec in enumerate(recommendations, start=1):
        payload = {
            "type": rec.get("type"),
            "action": rec.get("action"),
            "index": idx,
            "channels": channel_ids,
        }
        exp_id = _stable_experiment_id(payload)
        decision = "rollback"
        if rec.get("status") == "recommended":
            decision = "continue_canary"

        experiments.append(
            {
                "experiment_id": exp_id,
                "hypothesis": f"{rec.get('type')} improves quality without safety regressions",
                "channel": channel_ids[0] if channel_ids else "unknown",
                "control": "current_policy",
                "variant": str(rec.get("action") or "candidate_policy"),
                "start": (_utcnow() - timedelta(days=2)).isoformat(),
                "end": (_utcnow() + timedelta(days=5)).isoformat(),
                "metrics": ["quality_score", "click_through_rate", "watch_time_hours", "guard_block_rate"],
                "decision": decision,
                "rollback": {
                    "status": "triggered" if decision == "rollback" else "none",
                    "reason": "safety_or_confidence_guardrail" if decision == "rollback" else None,
                },
                "stage": "experimental_canary_change",
                "traceability": {
                    "recommendation_type": rec.get("type"),
                    "recommendation_status": rec.get("status"),
                },
            }
        )

    registry_snapshot = list_experiments(registry_path=registry_path)

    return {
        "generated_at_utc": _utcnow().isoformat(),
        "schema_version": "v1",
        "experiments": experiments,
        "registry_snapshot_count": len(registry_snapshot),
        "registry_path": str(registry_path),
    }


def run_control_loop(
    *,
    performance_path: Path,
    routing_guard_path: Path,
    experiment_registry_path: Path,
    learning_audit_path: Path,
    rules: LearningRules | None = None,
) -> dict[str, Any]:
    resolved_rules = rules or LearningRules()
    rows = load_input_rows(performance_path=performance_path, routing_guard_path=routing_guard_path)
    baselines = build_baselines(rows)
    regressions = detect_regressions(
        rows=rows,
        baselines=baselines,
        min_sample_size=resolved_rules.min_regression_sample_size,
    )

    recommendations = build_recommendations(
        rows=rows,
        baselines=baselines,
        regressions=regressions,
        rules=resolved_rules,
    )
    learning = apply_learning_rules(
        recommendations=recommendations,
        baselines=baselines,
        regressions=regressions,
        rules=resolved_rules,
    )

    channels: dict[str, float] = {}
    for channel_id, details in dict(baselines.get("per_channel") or {}).items():
        score = _safe_float(((details.get("recent_7d") or {}).get("channel_health_score")))
        if score is None:
            score = _safe_float(((details.get("all_time") or {}).get("channel_health_score"))) or 0.0
        channels[channel_id] = round(score, 3)

    item_scores: list[dict[str, Any]] = []
    for row in rows:
        item_scores.append(
            {
                "channel_id": row.get("channel_id"),
                "content_id": row.get("content_id"),
                "quality_score": row.get("quality_score"),
                "component_scores": row.get("component_scores"),
            }
        )

    experiment_tracking = build_experiment_tracking(
        recommendations=recommendations,
        learning=learning,
        channel_ids=sorted(channels.keys()),
        registry_path=experiment_registry_path,
    )

    learning_audit_path.parent.mkdir(parents=True, exist_ok=True)
    with learning_audit_path.open("a", encoding="utf-8") as handle:
        for event in list(learning.get("audit_trail") or []):
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    health = {
        "generated_at_utc": _utcnow().isoformat(),
        "schema_version": "v1",
        "quality_model": {
            "components": list(QUALITY_COMPONENTS),
            "weights": QUALITY_WEIGHTS,
            "item_quality_scores": item_scores,
            "normalized": True,
        },
        "channel_health": {
            "channel_scores": channels,
            "system_health_score": baselines.get("recent_7d", {}).get("channel_health_score"),
        },
        "baselines": baselines,
        "regressions": regressions,
        "learning_rules": learning,
    }

    recommendations_payload = {
        "generated_at_utc": _utcnow().isoformat(),
        "schema_version": "v1",
        "recommendations": recommendations,
        "separation_of_stages": {
            "recommendation": [r.get("type") for r in recommendations],
            "approved_configuration_change": [r.get("type") for r in learning.get("approved_configuration_changes", [])],
            "experimental_canary_change": [r.get("type") for r in learning.get("experimental_canary_changes", [])],
            "production_rollout": [r.get("type") for r in learning.get("production_rollouts", [])],
        },
    }

    return {
        "health": health,
        "recommendations": recommendations_payload,
        "experiments": experiment_tracking,
    }
