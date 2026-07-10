from __future__ import annotations

import json
from pathlib import Path

from src.chapter_validation_trail import write_latest_chapter_validator_artifact


def test_write_latest_chapter_validator_artifact_writes_required_fields(tmp_path: Path):
    latest_path = tmp_path / "chapter_validator_latest.json"

    write_latest_chapter_validator_artifact(
        channel_id="test-channel",
        title="Test title",
        duration_seconds=130,
        input_description="Aciklama\n\nBOLUMLER:\n00:00 Giris\n00:20 Analiz",
        chapter_result={
            "schema_version": "2.0",
            "validator_version": "1.1.0",
            "issue_codes": ["CH007"],
            "issue_labels": ["short_segment_detected"],
            "auto_fix_actions": ["merge_short_segments"],
            "fix_counts": {
                "cta_removed_count": 0,
                "merge_count": 1,
                "ending_trim_count": 0,
                "duplicate_removed_count": 0,
            },
            "valid_before": False,
            "valid_after": True,
            "chapter_contract_pass": True,
            "bypass_reason": None,
            "input_chapter_count": 3,
            "chapter_count": 3,
        },
        latest_path=latest_path,
    )

    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert payload["artifact_type"] == "chapter_validator_latest"
    assert payload["schema_version"] == "2.0"
    assert payload["validator_version"] == "1.1.0"
    assert payload["channel"] == "test-channel"
    assert payload["duration"] == 130
    assert payload["issues"] == ["CH007"]
    assert payload["actions"] == ["merge_short_segments"]
    assert payload["fix_counts"]["merge_count"] == 1
    assert isinstance(payload["input_hash"], str) and len(payload["input_hash"]) == 64
