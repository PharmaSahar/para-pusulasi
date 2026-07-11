from __future__ import annotations

import json


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_ops_control_loop_generates_required_artifacts(tmp_path, monkeypatch):
    from ops import content_platform_control_loop as control

    perf = tmp_path / "channel_performance.jsonl"
    guards = tmp_path / "routing_guard_decisions.jsonl"
    registry = tmp_path / "experiments.jsonl"
    audit = tmp_path / "audit.jsonl"

    _write_jsonl(
        perf,
        [
            {
                "created_at": "2026-07-10T10:00:00+00:00",
                "channel_id": "ch1",
                "content_id": "c1",
                "video_id": "v1",
                "title": "Alpha",
                "script": "alpha script",
                "description": "desc",
                "tags": ["finance"],
                "thumbnail_path": "a.jpg",
                "overall_quality_score": 70,
                "hook_score": 70,
                "structure_score": 68,
                "retention_signal_score": 66,
                "thumbnail_attention_score": 71,
                "click_through_rate": 0.05,
                "watch_time_hours": 2.0,
                "render_status": "ok",
                "upload_success": True,
                "visual_reuse_ratio": 0.1,
                "topic_leakage": False,
            }
        ],
    )
    _write_jsonl(guards, [])
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text("", encoding="utf-8")

    monkeypatch.setattr(control, "HEALTH_OUTPUT", tmp_path / "content_platform_health_latest.json")
    monkeypatch.setattr(control, "RECOMMENDATIONS_OUTPUT", tmp_path / "content_platform_recommendations_latest.json")
    monkeypatch.setattr(control, "EXPERIMENTS_OUTPUT", tmp_path / "content_platform_experiments_latest.json")
    monkeypatch.setattr(control, "WEEKLY_REVIEW_OUTPUT", tmp_path / "content_platform_weekly_review.md")

    summary = control.run(
        performance_path=perf,
        routing_guard_path=guards,
        experiment_registry_path=registry,
        learning_audit_path=audit,
    )

    assert summary["ok"] is True
    assert (tmp_path / "content_platform_health_latest.json").exists()
    assert (tmp_path / "content_platform_recommendations_latest.json").exists()
    assert (tmp_path / "content_platform_experiments_latest.json").exists()
    assert (tmp_path / "content_platform_weekly_review.md").exists()
