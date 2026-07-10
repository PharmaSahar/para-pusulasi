import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_fleet_health_classification_red_for_blocked_channel():
    from ops.fleet_health_report import classify_channel_health

    status, score, reasons = classify_channel_health(
        can_upload_thumbnail=False,
        success_streak=0,
        has_last_24h_data=False,
        uploaded_last_24h=False,
        had_upload_error=True,
        avg_ctr=0.02,
        avg_retention=40.0,
    )

    assert status == "RED"
    assert score >= 65
    assert "thumbnail_permission_blocked" in reasons


def test_fleet_health_no_evidence_is_not_red():
    from ops.fleet_health_report import classify_channel_health

    status, score, reasons = classify_channel_health(
        can_upload_thumbnail=True,
        success_streak=5,
        has_last_24h_data=False,
        uploaded_last_24h=False,
        had_upload_error=False,
        avg_ctr=None,
        avg_retention=None,
        analytics_data_status="NO_EVIDENCE",
    )

    assert status in {"GREEN", "YELLOW"}
    assert score < 65
    assert "no_evidence" in reasons


def test_backlog_items_include_engineering_fields():
    from ops import optimization_backlog_engine as backlog

    report = backlog.build_backlog()

    assert "backlog" in report
    first = report["backlog"][0]
    assert "reason" in first
    assert "expected_impact" in first
    assert "estimated_risk" in first
    assert "affected_modules" in first
    assert "evidence_source" in first
    assert "evidence_status" in first
    assert "sample_count" in first
    assert "confidence" in first


def test_optimization_memory_builds_title_pattern_insight(tmp_path, monkeypatch):
    from ops import optimization_memory_engine as memory

    path = tmp_path / "perf.jsonl"
    rows = []
    for i in range(6):
        rows.append({"title": f"Question title {i}?", "click_through_rate": 0.08, "overall_quality_score": 80 + i})
    for i in range(6):
        rows.append({"title": f"Plain title {i}", "click_through_rate": 0.05, "overall_quality_score": 60 + i})
    path.write_text("\n".join(json.dumps(r, ensure_ascii=True) for r in rows), encoding="utf-8")

    monkeypatch.setattr(memory, "PERFORMANCE_PATH", path)
    monkeypatch.setattr(memory, "MIN_REQUIRED_SAMPLE_COUNT", 10)

    report = memory.build_optimization_memory(max_rows=100)

    insight_types = {item.get("type") for item in report["insights"]}
    assert "title_question_pattern" in insight_types


def test_optimization_memory_insufficient_data_returns_status(tmp_path, monkeypatch):
    from ops import optimization_memory_engine as memory

    path = tmp_path / "perf_small.jsonl"
    rows = [{"title": "Only few", "click_through_rate": 0.05, "overall_quality_score": 70} for _ in range(4)]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=True) for r in rows), encoding="utf-8")

    monkeypatch.setattr(memory, "PERFORMANCE_PATH", path)
    monkeypatch.setattr(memory, "MIN_REQUIRED_SAMPLE_COUNT", 10)

    report = memory.build_optimization_memory(max_rows=100)

    assert report["status"] == "insufficient_data"
    assert report["sample_count"] == 4
    assert report["required_sample_count"] == 10
    assert report["insights"] == []
