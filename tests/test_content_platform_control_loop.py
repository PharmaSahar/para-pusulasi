from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.content_platform_control_loop import (
    LearningRules,
    apply_learning_rules,
    build_baselines,
    build_recommendations,
    detect_regressions,
)


def _row(
    *,
    idx: int,
    days_ago: int,
    channel_id: str = "ch_1",
    ctr: float = 0.05,
    watch_time: float = 2.0,
    upload_success: bool = True,
    visual_reuse_ratio: float = 0.1,
    topic_leakage: bool = False,
    guard_blocked: bool = False,
    metadata_ok: bool = True,
    title_suffix: str = "alpha",
) -> dict:
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "created_at": created.isoformat(),
        "channel_id": channel_id,
        "content_id": f"c_{idx}",
        "video_id": f"v_{idx}",
        "title": f"Title {title_suffix} {idx}",
        "script": f"Script {title_suffix} {idx}",
        "description": "desc" if metadata_ok else "",
        "tags": ["finance"] if metadata_ok else [],
        "thumbnail_path": "thumb.jpg" if metadata_ok else "",
        "overall_quality_score": 72,
        "hook_score": 70,
        "structure_score": 70,
        "retention_signal_score": 68,
        "thumbnail_attention_score": 69,
        "click_through_rate": ctr,
        "watch_time_hours": watch_time,
        "render_status": "ok",
        "upload_success": upload_success,
        "visual_reuse_ratio": visual_reuse_ratio,
        "topic_leakage": topic_leakage,
        "guard_blocked": guard_blocked,
    }


def test_weak_sample_rejection():
    rows = [_row(idx=1, days_ago=1)]
    baselines = build_baselines(rows)
    regressions = detect_regressions(rows=rows, baselines=baselines, min_sample_size=5)

    recs = build_recommendations(
        rows=rows,
        baselines=baselines,
        regressions=regressions,
        rules=LearningRules(min_channel_sample_size=5),
    )

    assert recs
    assert all(item["status"] == "rejected" for item in recs)
    assert all(item.get("reason") == "weak_sample" for item in recs)


def test_regression_detection_for_ctr_and_watch_time_drop():
    rows = []
    for i in range(18):
        rows.append(_row(idx=i, days_ago=20, ctr=0.08, watch_time=2.8, title_suffix=f"base{i}"))
    for i in range(18, 36):
        rows.append(_row(idx=i, days_ago=2, ctr=0.02, watch_time=1.1, title_suffix=f"new{i}"))

    baselines = build_baselines(rows)
    regressions = detect_regressions(rows=rows, baselines=baselines, min_sample_size=8)
    by_name = {item["name"]: item for item in regressions}

    assert by_name["falling_ctr"]["triggered"] is True
    assert by_name["falling_watch_time"]["triggered"] is True


def test_safe_bounded_changes_are_enforced():
    rows = [_row(idx=i, days_ago=2, ctr=0.06, watch_time=2.2) for i in range(10)]
    baselines = build_baselines(rows)
    regressions = detect_regressions(rows=rows, baselines=baselines, min_sample_size=5)
    rules = LearningRules(min_channel_sample_size=3, confidence_threshold=0.6, max_relative_change=0.1)

    recs = build_recommendations(rows=rows, baselines=baselines, regressions=regressions, rules=rules)
    learning = apply_learning_rules(recommendations=recs, baselines=baselines, regressions=regressions, rules=rules)

    assert learning["approved_configuration_changes"]
    for item in learning["approved_configuration_changes"]:
        assert item["bounded_change"]["max_relative_change"] == 0.1


def test_canary_only_experiments_no_auto_rollout():
    rows = [_row(idx=i, days_ago=1, ctr=0.07, watch_time=2.4) for i in range(12)]
    baselines = build_baselines(rows)
    regressions = detect_regressions(rows=rows, baselines=baselines, min_sample_size=5)
    rules = LearningRules(min_channel_sample_size=3, confidence_threshold=0.6)

    recs = build_recommendations(rows=rows, baselines=baselines, regressions=regressions, rules=rules)
    learning = apply_learning_rules(recommendations=recs, baselines=baselines, regressions=regressions, rules=rules)

    assert learning["experimental_canary_changes"]
    assert all(item["status"] == "blocked" for item in learning["production_rollouts"])


def test_rollback_path_for_unsafe_or_low_confidence_changes():
    rows = [_row(idx=i, days_ago=1, ctr=0.02, watch_time=0.5, guard_blocked=True) for i in range(8)]
    baselines = build_baselines(rows)
    regressions = detect_regressions(rows=rows, baselines=baselines, min_sample_size=5)
    rules = LearningRules(min_channel_sample_size=3, confidence_threshold=0.95, safety_floor=99.0)

    recs = build_recommendations(rows=rows, baselines=baselines, regressions=regressions, rules=rules)
    learning = apply_learning_rules(recommendations=recs, baselines=baselines, regressions=regressions, rules=rules)

    assert learning["blocked_adjustments"]
    assert any(item.get("reason") in {"low_confidence", "safety_floor"} for item in learning["blocked_adjustments"])


def test_recommendation_traceability_fields_present():
    rows = [_row(idx=i, days_ago=1, ctr=0.06, watch_time=2.1, channel_id="ch_trace") for i in range(9)]
    baselines = build_baselines(rows)
    regressions = detect_regressions(rows=rows, baselines=baselines, min_sample_size=5)

    recs = build_recommendations(
        rows=rows,
        baselines=baselines,
        regressions=regressions,
        rules=LearningRules(min_channel_sample_size=3, confidence_threshold=0.6),
    )

    assert recs
    assert all("trace" in item for item in recs)
    assert all(isinstance(item["trace"], dict) for item in recs)


def test_no_unsafe_automatic_optimization_policy_present():
    rows = [_row(idx=i, days_ago=1, ctr=0.06, watch_time=2.0) for i in range(11)]
    baselines = build_baselines(rows)
    regressions = detect_regressions(rows=rows, baselines=baselines, min_sample_size=5)
    rules = LearningRules(min_channel_sample_size=3, confidence_threshold=0.6)

    recs = build_recommendations(rows=rows, baselines=baselines, regressions=regressions, rules=rules)
    learning = apply_learning_rules(recommendations=recs, baselines=baselines, regressions=regressions, rules=rules)

    assert learning["rules"]["no_unsafe_automatic_optimization"] is True
    assert all(item["status"] == "blocked" for item in learning["production_rollouts"])
