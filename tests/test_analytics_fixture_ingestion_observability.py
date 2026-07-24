from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.analytics_fixture_ingestion import (
    FixtureIngestionError,
    IngestionRunReport,
    build_fixture_identity,
    ingest_fixture,
    ingest_fixture_with_observability,
    write_ingestion_evidence,
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


def test_successful_append_report(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    summary, report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    assert summary["appended_count"] == 1
    assert summary["duplicate_count"] == 0
    assert report.outcome == "SUCCESS"
    assert report.storage_mutated is True
    assert report.record_results[0].result == "APPENDED"
    assert report.error_categories == tuple()


def test_duplicate_only_report(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    first = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")[0]
    assert first["appended_count"] == 1
    second_summary, second_report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    assert second_summary["appended_count"] == 0
    assert second_summary["duplicate_count"] == 1
    assert second_report.outcome == "SUCCESS_WITH_DUPLICATES"
    assert second_report.storage_mutated is False


def test_dry_run_report(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    summary, report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha", dry_run=True)
    assert summary["dry_run"] is True
    assert report.dry_run is True
    assert report.storage_mutated is False
    assert report.outcome == "SUCCESS"


def test_rejected_fixture_report(tmp_path):
    fixture_path = tmp_path / "bad.json"
    fixture_path.write_text('{bad json', encoding="utf-8")
    with pytest.raises(FixtureIngestionError):
        ingest_fixture(fixture_path, tmp_path / "store")


def test_failed_malformed_store_report(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    store_root = tmp_path / "store"
    store_path = store_root / "channel_alpha" / "snapshots.jsonl"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text('{not-json}\n', encoding="utf-8")
    summary, report = ingest_fixture_with_observability(fixture_path, store_root, expected_channel_id="channel_alpha")
    assert summary["rejected_count"] == 1
    assert report.outcome == "FAILED"
    assert report.storage_mutated is False


def test_deterministic_run_id_and_channel_change(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    first, first_report = ingest_fixture_with_observability(fixture_path, tmp_path / "store1", expected_channel_id="channel_alpha")
    second, second_report = ingest_fixture_with_observability(fixture_path, tmp_path / "store2", expected_channel_id="channel_beta")
    assert first_report.run_id != second_report.run_id
    assert first_report.run_id == first["run_id"]
    assert second_report.run_id == second["run_id"]


def test_dry_run_and_write_mode_have_different_run_ids(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    dry_run_result, dry_run_report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha", dry_run=True)
    write_result, write_report = ingest_fixture_with_observability(fixture_path, tmp_path / "store2", expected_channel_id="channel_alpha")
    assert dry_run_report.run_id != write_report.run_id
    assert dry_run_result["run_id"] != write_result["run_id"]


def test_timestamps_are_utc_and_duration_nonnegative(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    _, report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    assert report.started_at.endswith("+00:00")
    assert report.completed_at.endswith("+00:00")
    assert report.duration_ms >= 0


def test_serialization_is_deterministic_and_round_trippable(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    _, report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    payload = report.to_payload()
    serialized = report.to_json()
    assert json.loads(serialized) == payload
    assert serialized == json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_evidence_writer_is_atomic_and_idempotent(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    _, report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    output_path = tmp_path / "evidence.json"
    first = write_ingestion_evidence(report, output_path)
    second = write_ingestion_evidence(report, output_path)
    assert first["status"] == "written"
    assert second["status"] == "unchanged"
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8")


def test_evidence_contains_no_raw_payload_or_traceback(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    _, report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    payload = report.to_payload()
    assert "traceback" not in json.dumps(payload)
    assert "fixture://" not in json.dumps(payload)


def test_fixture_identity_is_preserved(tmp_path):
    fixture_path = FIXTURE_DIR / "complete_snapshot.json"
    _, report = ingest_fixture_with_observability(fixture_path, tmp_path / "store", expected_channel_id="channel_alpha")
    assert report.fixture_identity == build_fixture_identity(fixture_path)
