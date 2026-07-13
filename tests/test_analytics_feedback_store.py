from __future__ import annotations

from pathlib import Path

import pytest

from src.analytics_feedback_store import (
    ANALYTICS_FEEDBACK_SCHEMA_VERSION,
    AnalyticsFeedbackValidationError,
    append_feedback_record,
    load_feedback_records,
    make_feedback_record,
    validate_feedback_payload,
)


def _valid_payload() -> dict:
    return {
        "schema_version": ANALYTICS_FEEDBACK_SCHEMA_VERSION,
        "channel_id": "channel_1",
        "video_id": "video_1",
        "upload_timestamp": "2026-07-12T10:00:00+00:00",
        "title": "Birikim Plani",
        "thumbnail_hash": "th_abc",
        "topic": "birikim",
        "script_hash": "sc_abc",
        "shorts_hash": "sh_abc",
        "impressions": 1000,
        "ctr": 0.08,
        "average_view_duration": 120.5,
        "average_percentage_viewed": 0.42,
        "audience_retention": {"0": 1.0, "30": 0.55},
        "likes": 10,
        "comments": 2,
        "shares": 1,
        "subscribers_gained": 3,
        "traffic_sources": {"browse": 0.5, "search": 0.3},
        "suggested_video_traffic": 0.2,
        "browse_traffic": 0.5,
        "search_traffic": 0.3,
        "end_screen_ctr": 0.04,
        "card_ctr": 0.01,
        "playlist_additions": 4,
        "recorded_at": "2026-07-12T11:00:00+00:00",
    }


def test_validate_feedback_payload_success() -> None:
    payload = _valid_payload()
    out = validate_feedback_payload(payload)
    assert out["channel_id"] == "channel_1"
    assert out["ctr"] == 0.08
    assert out["impressions"] == 1000


def test_validate_feedback_payload_fails_on_invalid_ctr() -> None:
    payload = _valid_payload()
    payload["ctr"] = 1.5
    with pytest.raises(AnalyticsFeedbackValidationError):
        validate_feedback_payload(payload)


def test_make_record_and_append_load_roundtrip(tmp_path: Path) -> None:
    payload = _valid_payload()
    record = make_feedback_record(**payload)
    out_file = tmp_path / "feedback.jsonl"
    append_feedback_record(record, output_path=out_file)

    loaded = load_feedback_records(input_path=out_file)
    assert len(loaded) == 1
    assert loaded[0].video_id == "video_1"
    assert loaded[0].playlist_additions == 4


def test_append_only_writes_multiple_lines(tmp_path: Path) -> None:
    out_file = tmp_path / "feedback.jsonl"
    record1 = make_feedback_record(**_valid_payload())
    payload2 = _valid_payload()
    payload2["video_id"] = "video_2"
    record2 = make_feedback_record(**payload2)

    append_feedback_record(record1, output_path=out_file)
    append_feedback_record(record2, output_path=out_file)

    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
