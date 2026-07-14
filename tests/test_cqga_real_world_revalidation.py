from __future__ import annotations

import json
from pathlib import Path

from src.cqga_real_world_revalidation import (
    build_evidence_completeness_matrix,
    reconstruct_cqga_inputs,
    replay_cqga_revalidation,
    run_cqga_real_world_revalidation,
)


def _runtime_row(content_id: str, run_id: str) -> dict:
    return {
        "generation_id": content_id,
        "run_id": run_id,
        "channel": "test_channel",
        "topic": "test topic",
        "metadata": {
            "title": "Deterministic title",
            "description": "Deterministic description for replay stability.",
            "tags": ["test", "quality", "revalidation"],
            "hashtags": ["#test"],
            "playlist": "main",
            "cards": ["card_a"],
            "end_screens": ["end_a"],
        },
        "guard_scores": {
            "thumbnail_intelligence": {
                "thumbnail_prompt": "high contrast deterministic prompt",
                "quality": {"semantic_topic_fit": 0.7},
            }
        },
        "channel_profile": {"niche": "general", "tone": "neutral"},
        "render_result": {"render_status": "completed"},
        "upload_result": {"video_id": "vid-1", "youtube_url": "https://youtube.com/watch?v=vid-1"},
        "generated_at": "2026-07-14T00:00:00+00:00",
    }


def _ownership_row(content_id: str, run_id: str) -> dict:
    return {
        "content_id": content_id,
        "run_id": run_id,
        "channel_id": "test_channel",
        "title": "Deterministic title",
        "topic": "test topic",
        "script_preview": "Deterministic script preview for replay stability.",
        "created_at": "2026-07-14T00:00:00+00:00",
        "artifacts": {
            "thumbnail": {
                "path": "thumb.jpg",
                "sha256": "abc123",
            }
        },
    }


def _analytics_row(content_id: str) -> dict:
    return {
        "content_id": content_id,
        "snapshot_start": "2026-07-14",
        "snapshot_end": "2026-07-14",
        "provenance": {"join_outcome": "LINKED"},
        "metrics": {
            "click_through_rate": {"state": "OBSERVED", "value": 0.02},
            "average_view_percentage": {"state": "OBSERVED", "value": 0.2},
            "average_view_duration_seconds": {"state": "OBSERVED", "value": 12.0},
            "watch_time_hours": {"state": "OBSERVED", "value": 0.3},
            "card_ctr": {"state": "OBSERVED", "value": 0.0},
            "end_screen_ctr": {"state": "OBSERVED", "value": 0.0},
            "playlist_additions": {"state": "OBSERVED", "value": 0.0},
            "traffic_sources": {"state": "OBSERVED", "value": {"browse_features": 0.1, "suggested_videos": 0.05, "youtube_search": 0.85}},
        },
    }


def _cqga_storage(content_id: str, run_id: str) -> dict:
    return {
        "schema_version": "v1",
        "analysis_id": "cqga_test",
        "run_id": run_id,
        "content_id": content_id,
        "channel_id": "test_channel",
        "content_type": "video",
        "topic_hash": "t",
        "gap_count": 1,
        "high_severity_gap_count": 1,
        "root_causes": ["Weak hook", "Weak search intent"],
        "score_summary": {
            "hook": 0.2,
            "narrative": 0.5,
            "retention": 0.25,
            "ctr": 0.2,
            "thumbnail": 0.3,
            "seo": 0.2,
            "discovery": 0.25,
            "consistency": 0.45,
            "finance_safety": 1.0,
            "educational_quality": 0.4,
            "maintainability": 0.95,
            "overall_confidence": 0.8,
        },
        "advisory_only": True,
        "pipeline_output_changed": False,
        "created_at": "2026-07-14T00:00:00+00:00",
    }


def test_reconstruction_and_coverage_accounting() -> None:
    records, coverage = reconstruct_cqga_inputs(
        runtime_rows=[_runtime_row("content_a", "run_a")],
        ownership_rows=[_ownership_row("content_a", "run_a")],
        analytics_rows=[_analytics_row("content_a")],
        cqga_rows=[_cqga_storage("content_a", "run_a")],
    )

    assert len(records) == 1
    record = records[0]
    assert record["content_id"] == "content_a"
    assert record["reconstructable_for_replay"] is True
    assert record["missing_fields"] == []
    assert coverage["complete_evidence"] == 1
    assert coverage["coverage_pct"] == 100.0


def test_deterministic_replay_stability_and_metrics() -> None:
    records, _coverage = reconstruct_cqga_inputs(
        runtime_rows=[_runtime_row("content_a", "run_a")],
        ownership_rows=[_ownership_row("content_a", "run_a")],
        analytics_rows=[_analytics_row("content_a")],
        cqga_rows=[_cqga_storage("content_a", "run_a")],
    )

    result = replay_cqga_revalidation(reconstructed_records=records, replay_repeats=3)

    assert result["replayable_count"] == 1
    assert result["excluded_count"] == 0
    assert result["stability"]["deterministic_replay"] is True
    assert result["stability"]["stable_rankings"] is True
    assert result["agreement"]["precision"] >= 0.0
    assert result["agreement"]["recall"] >= 0.0
    assert result["agreement"]["balanced_accuracy"] >= 0.0
    assert result["agreement"]["false_positives"] >= 0
    assert result["agreement"]["false_negatives"] >= 0


def test_review_payloads_are_advisory_only() -> None:
    records, _coverage = reconstruct_cqga_inputs(
        runtime_rows=[_runtime_row("content_a", "run_a")],
        ownership_rows=[_ownership_row("content_a", "run_a")],
        analytics_rows=[_analytics_row("content_a")],
        cqga_rows=[_cqga_storage("content_a", "run_a")],
    )

    result = replay_cqga_revalidation(reconstructed_records=records, replay_repeats=2)
    payloads = result["review_payloads"]
    assert len(payloads) == 1
    assert payloads[0]["advisory_only"] is True
    assert payloads[0]["pipeline_output_changed"] is False
    assert payloads[0]["automatic_action"] is None


def test_end_to_end_artifact_generation_and_exclusion_handling(tmp_path: Path) -> None:
    root = tmp_path
    (root / "output/runtime/evidence").mkdir(parents=True, exist_ok=True)
    (root / "output/state/content_ownership").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    # replayable content
    (root / "output/runtime/evidence/content_a.json").write_text(json.dumps(_runtime_row("content_a", "run_a")), encoding="utf-8")
    (root / "output/state/content_ownership/content_a_run_a.json").write_text(json.dumps(_ownership_row("content_a", "run_a")), encoding="utf-8")

    # excluded content (missing CQGA storage and missing replay fields)
    runtime_b = _runtime_row("content_b", "run_b")
    runtime_b["metadata"]["title"] = ""
    runtime_b["guard_scores"]["thumbnail_intelligence"]["thumbnail_prompt"] = ""
    runtime_b["metadata"]["description"] = ""
    (root / "output/runtime/evidence/content_b.json").write_text(json.dumps(runtime_b), encoding="utf-8")

    with (root / "logs/canonical_content_analytics.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(_analytics_row("content_a")) + "\n")

    with (root / "logs/content_quality_gap_analysis.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(_cqga_storage("content_a", "run_a")) + "\n")

    summary = run_cqga_real_world_revalidation(repository_root=root, output_dir=root / "artifacts/latest/out", replay_repeats=3)

    assert summary["replay"]["replayable_count"] == 1
    assert summary["replay"]["excluded_count"] == 1
    assert summary["replay"]["stability"]["deterministic_replay"] is True

    out = root / "artifacts/latest/out"
    assert (out / "evidence_completeness_matrix.json").exists()
    assert (out / "reconstructed_inputs.jsonl").exists()
    assert (out / "replay_results.jsonl").exists()
    assert (out / "agreement_metrics.json").exists()
    assert (out / "stability_report.json").exists()
    assert (out / "coverage_report.json").exists()
    assert (out / "review_payloads.jsonl").exists()
    assert (out / "gap_report.json").exists()
    assert (out / "assessment_summary.json").exists()


def test_evidence_matrix_reports_missing_lineage_without_repair() -> None:
    matrix = build_evidence_completeness_matrix(
        repository_root=Path("."),
        runtime_rows=[_runtime_row("content_a", "run_a")],
        ownership_rows=[_ownership_row("content_a", "run_a")],
        analytics_rows=[_analytics_row("content_a")],
        planning_rows=[],
        script_rows=[],
        forward_rows=[],
        thumbnail_rows=[],
    )

    payload = matrix["matrix"]
    assert payload["planning_lineage"]["status"] == "missing"
    assert payload["script_lineage"]["status"] == "missing"
    assert payload["forward_evidence"]["status"] == "missing"
    assert matrix["advisory_only"] is True
    assert matrix["pipeline_output_changed"] is False
