from __future__ import annotations

import json
from pathlib import Path

import ops.p0_validation_metrics_report as report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_p0a_reads_routing_guard_decisions(monkeypatch, tmp_path):
    perf_path = tmp_path / "channel_performance.jsonl"
    thumb_path = tmp_path / "thumbnail_history.jsonl"
    guard_path = tmp_path / "routing_guard_decisions.jsonl"
    shorts_safety_path = tmp_path / "shorts_safety_decisions.jsonl"
    chapter_validation_path = tmp_path / "chapter_validation_trail.jsonl"

    _write_jsonl(
        perf_path,
        [
            {"video_id": "v1", "dna_violations": 0},
            {"video_id": "v2", "dna_violations": 0},
        ],
    )
    _write_jsonl(thumb_path, [])
    _write_jsonl(shorts_safety_path, [])
    _write_jsonl(chapter_validation_path, [])
    _write_jsonl(
        guard_path,
        [
            {
                "guard_name": "niche_alignment_guard",
                "decision": "block",
                "review_outcome": "false_block",
                "fail_closed": False,
            },
            {
                "guard_name": "niche_alignment_guard",
                "decision": "allow",
                "fail_closed": False,
            },
        ],
    )

    monkeypatch.setattr(report, "PERF_PATH", perf_path)
    monkeypatch.setattr(report, "THUMB_HISTORY_PATH", thumb_path)
    monkeypatch.setattr(report, "ROUTING_GUARD_DECISIONS_PATH", guard_path)
    monkeypatch.setattr(report, "SHORTS_SAFETY_DECISIONS_PATH", shorts_safety_path)
    monkeypatch.setattr(report, "CHAPTER_VALIDATION_TRAIL_PATH", chapter_validation_path)

    payload = report.build_report(lookback_rows=500)
    p0a = next(item for item in payload["workstreams"] if item["workstream"] == "P0-A")

    assert p0a["guard_decision_rows"] == 2
    assert p0a["guard_block_rows"] == 1
    assert p0a["guard_reviewed_block_rows"] == 1
    assert p0a["metrics"]["false_block_rate"]["value"] == 100.0
    assert p0a["metrics"]["false_block_rate"]["evidence_status"] == "observed"
    assert p0a["metrics"]["guard_fail_closed_rate"]["value"] == 0.0


def test_p0b_reads_shorts_safety_decisions(monkeypatch, tmp_path):
    perf_path = tmp_path / "channel_performance.jsonl"
    thumb_path = tmp_path / "thumbnail_history.jsonl"
    guard_path = tmp_path / "routing_guard_decisions.jsonl"
    shorts_safety_path = tmp_path / "shorts_safety_decisions.jsonl"
    chapter_validation_path = tmp_path / "chapter_validation_trail.jsonl"

    _write_jsonl(
        perf_path,
        [
            {"short_url": "https://youtube.com/shorts/a", "thumbnail_reject_rate": 0.0},
            {"short_url": "https://youtube.com/shorts/b", "thumbnail_reject_rate": 0.5},
        ],
    )
    _write_jsonl(thumb_path, [])
    _write_jsonl(guard_path, [])
    _write_jsonl(chapter_validation_path, [])
    _write_jsonl(
        shorts_safety_path,
        [
            {
                "content_type": "short",
                "safe_area_pass": True,
                "overall_pass": True,
                "validator_error": False,
            },
            {
                "content_type": "short",
                "safe_area_pass": False,
                "overall_pass": False,
                "validator_error": False,
            },
        ],
    )

    monkeypatch.setattr(report, "PERF_PATH", perf_path)
    monkeypatch.setattr(report, "THUMB_HISTORY_PATH", thumb_path)
    monkeypatch.setattr(report, "ROUTING_GUARD_DECISIONS_PATH", guard_path)
    monkeypatch.setattr(report, "SHORTS_SAFETY_DECISIONS_PATH", shorts_safety_path)
    monkeypatch.setattr(report, "CHAPTER_VALIDATION_TRAIL_PATH", chapter_validation_path)

    payload = report.build_report(lookback_rows=500)
    p0b = next(item for item in payload["workstreams"] if item["workstream"] == "P0-B")

    assert p0b["shorts_safety_decision_rows"] == 2
    assert p0b["shorts_safety_non_error_rows"] == 2
    assert p0b["metrics"]["unsafe_visual_escape_rate"]["value"] == 50.0
    assert p0b["metrics"]["unsafe_visual_escape_rate"]["evidence_status"] == "observed"
    assert p0b["metrics"]["safe_area_compliance"]["value"] == 50.0
    assert p0b["metrics"]["safe_area_compliance"]["evidence_status"] == "observed"


def test_p0c_reads_chapter_validation_trail(monkeypatch, tmp_path):
    perf_path = tmp_path / "channel_performance.jsonl"
    thumb_path = tmp_path / "thumbnail_history.jsonl"
    guard_path = tmp_path / "routing_guard_decisions.jsonl"
    shorts_safety_path = tmp_path / "shorts_safety_decisions.jsonl"
    chapter_validation_path = tmp_path / "chapter_validation_trail.jsonl"

    _write_jsonl(perf_path, [{"video_id": "v1"}, {"video_id": "v2"}])
    _write_jsonl(thumb_path, [])
    _write_jsonl(guard_path, [])
    _write_jsonl(shorts_safety_path, [])
    _write_jsonl(
        chapter_validation_path,
        [
            {
                "revalidate": {"chapter_contract_pass": True},
                "upload_stage_failed": False,
                "post_upload_edit": False,
            },
            {
                "revalidate": {"chapter_contract_pass": False},
                "upload_stage_failed": True,
                "post_upload_edit": True,
            },
        ],
    )

    monkeypatch.setattr(report, "PERF_PATH", perf_path)
    monkeypatch.setattr(report, "THUMB_HISTORY_PATH", thumb_path)
    monkeypatch.setattr(report, "ROUTING_GUARD_DECISIONS_PATH", guard_path)
    monkeypatch.setattr(report, "SHORTS_SAFETY_DECISIONS_PATH", shorts_safety_path)
    monkeypatch.setattr(report, "CHAPTER_VALIDATION_TRAIL_PATH", chapter_validation_path)

    payload = report.build_report(lookback_rows=500)
    p0c = next(item for item in payload["workstreams"] if item["workstream"] == "P0-C")

    assert p0c["chapter_validation_rows"] == 2
    assert p0c["chapter_revalidate_rows"] == 2
    assert p0c["metrics"]["chapter_contract_compliance"]["value"] == 50.0
    assert p0c["metrics"]["chapter_contract_compliance"]["evidence_status"] == "observed"
    assert p0c["metrics"]["upload_time_chapter_failure_rate"]["value"] == 50.0
    assert p0c["metrics"]["post_upload_chapter_edit_rate"]["value"] == 50.0
