from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.analytics_snapshot_foundation import (
    AnalyticsSnapshotStore,
    AnalyticsSnapshotStoreError,
    AnalyticsSnapshotValidationError,
    build_snapshot_id,
    canonicalize_snapshot_payload,
)


def _base_payload(**overrides):
    payload = {
        "schema_version": "1.0",
        "snapshot_timestamp": "2026-07-24T12:00:00+00:00",
        "snapshot_date": "2026-07-24",
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
        "views": 90,
        "watch_time_minutes": 15,
        "subscribers_gained": 2,
        "subscribers_lost": 0,
        "likes": 5,
        "comments": 1,
        "shares": 1,
        "impressions_ctr": 0.12,
        "average_view_duration_seconds": 45.5,
        "average_percentage_viewed": 42.1,
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


def test_valid_complete_snapshot_is_canonicalized_and_has_id():
    payload = canonicalize_snapshot_payload(_base_payload())
    assert payload["schema_version"] == "1.0"
    assert payload["snapshot_id"]
    assert payload["content_type"] == "LONG_FORM"


def test_valid_partial_snapshot_is_allowed_with_explicit_missing_fields():
    payload = canonicalize_snapshot_payload(_base_payload(completeness_status="partial", missing_fields=["average_percentage_viewed"], average_percentage_viewed=None))
    assert payload["completeness_status"] == "partial"
    assert payload["missing_fields"] == ["average_percentage_viewed"]


def test_snapshot_id_is_deterministic_for_identical_payloads():
    first = canonicalize_snapshot_payload(_base_payload())
    second = canonicalize_snapshot_payload(_base_payload())
    assert first["snapshot_id"] == second["snapshot_id"]


def test_field_order_does_not_affect_snapshot_id():
    first = _base_payload()
    second = dict(reversed(list(first.items())))
    assert build_snapshot_id(first) == build_snapshot_id(second)


def test_timezone_equivalent_timestamps_produce_same_id():
    first = canonicalize_snapshot_payload(_base_payload(snapshot_timestamp="2026-07-24T12:00:00+00:00"))
    second = canonicalize_snapshot_payload(_base_payload(snapshot_timestamp="2026-07-24T14:00:00+02:00"))
    assert first["snapshot_id"] == second["snapshot_id"]


def test_title_changes_do_not_affect_snapshot_id():
    first = canonicalize_snapshot_payload(_base_payload(title_at_snapshot="Example title"))
    second = canonicalize_snapshot_payload(_base_payload(title_at_snapshot="Changed title"))
    assert first["snapshot_id"] == second["snapshot_id"]


def test_channel_identity_affects_snapshot_id():
    first = canonicalize_snapshot_payload(_base_payload(channel_id="channel_alpha"))
    second = canonicalize_snapshot_payload(_base_payload(channel_id="channel_beta"))
    assert first["snapshot_id"] != second["snapshot_id"]


def test_missing_required_identity_is_rejected():
    with pytest.raises(AnalyticsSnapshotValidationError):
        canonicalize_snapshot_payload(_base_payload(youtube_video_id=""))


def test_naive_timestamp_is_rejected():
    with pytest.raises(AnalyticsSnapshotValidationError):
        canonicalize_snapshot_payload(_base_payload(snapshot_timestamp="2026-07-24T12:00:00"))


def test_invalid_content_type_is_rejected():
    with pytest.raises(AnalyticsSnapshotValidationError):
        canonicalize_snapshot_payload(_base_payload(content_type="video"))


def test_negative_cumulative_metric_is_rejected():
    with pytest.raises(AnalyticsSnapshotValidationError):
        canonicalize_snapshot_payload(_base_payload(views=-1))


def test_invalid_ctr_is_rejected():
    with pytest.raises(AnalyticsSnapshotValidationError):
        canonicalize_snapshot_payload(_base_payload(impressions_ctr=1.2))


def test_invalid_percentage_viewed_is_rejected():
    with pytest.raises(AnalyticsSnapshotValidationError):
        canonicalize_snapshot_payload(_base_payload(average_percentage_viewed=101))


def test_null_and_zero_are_distinct():
    zero_payload = canonicalize_snapshot_payload(_base_payload(impressions=0))
    null_payload = canonicalize_snapshot_payload(_base_payload(impressions=None))
    assert zero_payload["impressions"] == 0
    assert null_payload["impressions"] is None
    assert zero_payload["snapshot_id"] != null_payload["snapshot_id"]


def test_append_valid_snapshot_persists_a_row(tmp_path):
    store = AnalyticsSnapshotStore(tmp_path, channel_id="channel_alpha")
    payload = store.append_snapshot(_base_payload())
    assert payload["status"] == "appended"
    assert store.load_snapshots()[0]["snapshot_id"] == payload["snapshot_id"]


def test_duplicate_append_is_idempotent(tmp_path):
    store = AnalyticsSnapshotStore(tmp_path, channel_id="channel_alpha")
    first = store.append_snapshot(_base_payload())
    second = store.append_snapshot(_base_payload())
    assert first["status"] == "appended"
    assert second["status"] == "duplicate"
    assert len(store.load_snapshots()) == 1


def test_conflicting_duplicate_is_rejected(tmp_path):
    store = AnalyticsSnapshotStore(tmp_path, channel_id="channel_alpha")
    store.append_snapshot(_base_payload())
    with pytest.raises(AnalyticsSnapshotStoreError):
        store.append_snapshot(_base_payload(title_at_snapshot="different title"))


def test_cross_channel_append_is_rejected(tmp_path):
    store = AnalyticsSnapshotStore(tmp_path, channel_id="channel_alpha")
    with pytest.raises(AnalyticsSnapshotValidationError):
        store.append_snapshot(_base_payload(channel_id="channel_beta"))


def test_malformed_ledger_fails_closed(tmp_path):
    store = AnalyticsSnapshotStore(tmp_path, channel_id="channel_alpha")
    ledger_path = store.store_path
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text('{bad json}\n', encoding='utf-8')
    with pytest.raises(AnalyticsSnapshotStoreError):
        store.load_snapshots()


def test_path_traversal_is_rejected(tmp_path):
    with pytest.raises(AnalyticsSnapshotValidationError):
        AnalyticsSnapshotStore(tmp_path / ".." / "escape", channel_id="channel_alpha")


def test_shorts_record_is_accepted(tmp_path):
    store = AnalyticsSnapshotStore(tmp_path, channel_id="channel_alpha")
    payload = store.append_snapshot(_base_payload(content_type="SHORT"))
    assert payload["status"] == "appended"


def test_long_form_record_is_accepted(tmp_path):
    store = AnalyticsSnapshotStore(tmp_path, channel_id="channel_alpha")
    payload = store.append_snapshot(_base_payload(content_type="LONG_FORM"))
    assert payload["status"] == "appended"


def test_schema_version_mismatch_is_rejected():
    with pytest.raises(AnalyticsSnapshotValidationError):
        canonicalize_snapshot_payload(_base_payload(schema_version="2.0"))


def test_fixture_storage_is_isolated(tmp_path):
    first_store = AnalyticsSnapshotStore(tmp_path / "root_a", channel_id="channel_alpha")
    second_store = AnalyticsSnapshotStore(tmp_path / "root_b", channel_id="channel_alpha")
    first_store.append_snapshot(_base_payload())
    assert len(first_store.load_snapshots()) == 1
    assert len(second_store.load_snapshots()) == 0


def test_no_network_or_production_mutation_is_required(tmp_path, monkeypatch):
    store = AnalyticsSnapshotStore(tmp_path, channel_id="channel_alpha")

    def fail_network(*args, **kwargs):
        raise AssertionError("network call attempted")

    monkeypatch.setattr("socket.create_connection", fail_network)
    payload = store.append_snapshot(_base_payload())
    assert payload["status"] == "appended"
    assert (tmp_path / "channel_alpha" / "snapshots.jsonl").exists()
