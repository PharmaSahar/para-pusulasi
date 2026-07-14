from __future__ import annotations

import pytest

from src.studio_analytics_learning_bridge import SCHEMA_VERSION, provider_priority, validate_canonical_record


def test_canonical_record_validation() -> None:
    row = {
        "schema_version": SCHEMA_VERSION,
        "analytics_record_id": "car_1",
        "provider": "StudioExportProvider",
        "source_file_hash": "hash_1",
        "source_row_number": 2,
        "canonical_channel_id": "chan_1",
        "content_id": "content_1",
        "youtube_video_id": "vid_1",
        "content_type": "LONG_FORM",
        "snapshot_start": "2026-07-10",
        "snapshot_end": "2026-07-10",
        "imported_at": "2026-07-14T00:00:00+00:00",
        "metrics_version": "v1",
        "provenance": {"source_type": "studio_export"},
        "advisory_only": True,
        "pipeline_output_changed": False,
        "metrics": {"views": {"state": "OBSERVED", "value": 10, "raw_name": "Views"}},
    }
    out = validate_canonical_record(row)
    assert out["schema_version"] == SCHEMA_VERSION


def test_pipeline_output_invariant() -> None:
    row = {
        "schema_version": SCHEMA_VERSION,
        "analytics_record_id": "car_2",
        "provider": "StudioExportProvider",
        "source_file_hash": "hash_2",
        "source_row_number": 2,
        "canonical_channel_id": "chan_1",
        "content_id": "content_1",
        "youtube_video_id": "vid_1",
        "content_type": "LONG_FORM",
        "snapshot_start": "2026-07-10",
        "snapshot_end": "2026-07-10",
        "imported_at": "2026-07-14T00:00:00+00:00",
        "metrics_version": "v1",
        "provenance": {"source_type": "studio_export"},
        "advisory_only": True,
        "pipeline_output_changed": True,
        "metrics": {"views": {"state": "OBSERVED", "value": 10, "raw_name": "Views"}},
    }
    with pytest.raises(ValueError):
        validate_canonical_record(row)


def test_provider_priority_contract() -> None:
    order = provider_priority()
    assert order == [
        "FutureOfficialYouTubeProvider",
        "StudioExportProvider",
        "ExistingLocalAnalyticsProvider",
        "UNAVAILABLE",
    ]
