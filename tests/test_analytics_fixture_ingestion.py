from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.analytics_fixture_ingestion import (
    FixtureIngestionError,
    build_fixture_identity,
    ingest_fixture,
    load_fixture_records,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "analytics"


def _complete_record(**overrides):
    payload = {
        "schema_version": "1.0",
        "snapshot_timestamp": "2026-07-24T12:00:00+00:00",
        "channel_id": "channel_alpha",
        "youtube_channel_id": "UC-alpha",
        "internal_video_id": "video-001",
        "youtube_video_id": "yt-video-001",
        "content_job_id": "job-001",
        "content_type": "LONG_FORM",
        "metric_source": "fixture",
        "provenance_reference": "fixture://evidence/001",
        "title_at_snapshot": "Example title",
        "topic": "analytics",
        "topic_domain": "growth",
        "language": "en",
        "duration_seconds": 180,
        "publication_timestamp": "2026-07-23T10:00:00+00:00",
        "thumbnail_identity": "thumb-001",
        "prompt_template_version": "v1",
        "impressions": 100,
        "impressions_ctr": 0.12,
        "views": 90,
        "watch_time_minutes": 15,
        "average_view_duration_seconds": 45.5,
        "average_percentage_viewed": 42.1,
        "subscribers_gained": 2,
        "subscribers_lost": 0,
        "likes": 5,
        "comments": 1,
        "shares": 1,
        "fetched_at": "2026-07-24T12:05:00+00:00",
        "freshness_status": "fresh",
        "completeness_status": "complete",
        "missing_fields": [],
        "partial_data_reason": None,
        "validation_status": "accepted",
        "source_query_version": "v1",
    }
    payload.update(overrides)
    return payload


def test_load_complete_fixture_records_from_json_file(tmp_path):
    fixture_path = tmp_path / "complete.json"
    fixture_path.write_text(json.dumps(_complete_record()), encoding="utf-8")
    records = load_fixture_records(fixture_path)
    assert len(records) == 1
    assert records[0]["channel_id"] == "channel_alpha"


def test_ingest_complete_fixture_appends_snapshot(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    result = ingest_fixture(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    assert result["appended_count"] == 1
    assert result["rejected_count"] == 0
    assert result["dry_run"] is False
    assert (tmp_path / "store" / "channel_alpha" / "snapshots.jsonl").exists()


def test_ingest_partial_fixture_is_accepted(tmp_path):
    fixture_path = FIXTURE_DIR / "partial_snapshot.json"
    result = ingest_fixture(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    assert result["appended_count"] == 1
    assert result["valid_record_count"] == 1


def test_duplicate_ingestion_is_idempotent(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    first = ingest_fixture(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    second = ingest_fixture(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    assert first["appended_count"] == 1
    assert second["duplicate_count"] == 1
    assert second["appended_count"] == 0


def test_dry_run_writes_nothing(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    store_root = tmp_path / "store"
    result = ingest_fixture(fixture_path, store_root, expected_channel_id="channel_alpha", dry_run=True)
    assert result["dry_run"] is True
    assert not (store_root / "channel_alpha" / "snapshots.jsonl").exists()


def test_mixed_channel_fixture_is_rejected(tmp_path):
    fixture_path = tmp_path / "mixed.json"
    fixture_path.write_text(json.dumps([_complete_record(), _complete_record(channel_id="channel_beta")]), encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store", expected_channel_id=None)


def test_expected_channel_mismatch_is_rejected(tmp_path):
    fixture_path = tmp_path / "mismatch.json"
    fixture_path.write_text(json.dumps(_complete_record()), encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store", expected_channel_id="channel_beta")


def test_youtube_channel_mismatch_is_rejected(tmp_path):
    fixture_path = tmp_path / "mismatch.json"
    fixture_path.write_text(json.dumps(_complete_record(youtube_channel_id="UC-beta")), encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_invalid_json_is_rejected(tmp_path):
    fixture_path = tmp_path / "bad.json"
    fixture_path.write_text('{bad json', encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_unsupported_root_object_is_rejected(tmp_path):
    fixture_path = tmp_path / "bad.json"
    fixture_path.write_text(json.dumps({"not": "supported"}), encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_empty_fixture_is_rejected(tmp_path):
    fixture_path = tmp_path / "empty.json"
    fixture_path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_unsupported_extension_is_rejected(tmp_path):
    fixture_path = tmp_path / "fixture.txt"
    fixture_path.write_text("{}", encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_missing_fixture_is_rejected(tmp_path):
    fixture_path = tmp_path / "missing.json"
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_excessive_record_count_is_rejected(tmp_path):
    fixture_path = tmp_path / "big.json"
    fixture_path.write_text(json.dumps([_complete_record() for _ in range(1001)]), encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_unknown_field_is_rejected(tmp_path):
    fixture_path = tmp_path / "bad.json"
    fixture_path.write_text(json.dumps(_complete_record(unknown_field="nope")), encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_empty_identity_after_trimming_is_rejected(tmp_path):
    fixture_path = tmp_path / "bad.json"
    fixture_path.write_text(json.dumps(_complete_record(channel_id="   ")),
                            encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_naive_timestamp_is_rejected(tmp_path):
    fixture_path = tmp_path / "bad.json"
    fixture_path.write_text(json.dumps(_complete_record(snapshot_timestamp="2026-07-24T12:00:00")), encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_null_and_zero_remain_distinct(tmp_path):
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps([_complete_record(impressions=0), _complete_record(impressions=None)]), encoding="utf-8")
    result = ingest_fixture(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    assert result["appended_count"] == 2
    assert len(result["snapshot_ids"]) == 2
    assert result["snapshot_ids"][0] != result["snapshot_ids"][1]


def test_fixture_identity_is_deterministic(tmp_path):
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps([_complete_record(), _complete_record()]), encoding="utf-8")
    first = build_fixture_identity(fixture_path)
    second = build_fixture_identity(fixture_path)
    assert first == second
