from __future__ import annotations

from pathlib import Path

from src.studio_analytics_learning_bridge import (
    ProviderName,
    import_records_append_only,
    load_canonical_records,
    load_import_manifest,
)


def _row(record_id: str) -> dict:
    return {
        "schema_version": "v1",
        "analytics_record_id": record_id,
        "provider": ProviderName.STUDIO_EXPORT.value,
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


def test_append_only_and_idempotent_duplicate_file(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    store = tmp_path / "canonical.jsonl"
    source_file = tmp_path / "source.csv"
    source_file.write_text("Video ID,Date\nvid_1,2026-07-10\n", encoding="utf-8")

    result1 = import_records_append_only(
        provider=ProviderName.STUDIO_EXPORT.value,
        source_file=source_file,
        candidate_rows=[_row("car_1")],
        manifest_path=manifest,
        canonical_store_path=store,
    )
    result2 = import_records_append_only(
        provider=ProviderName.STUDIO_EXPORT.value,
        source_file=source_file,
        candidate_rows=[_row("car_2")],
        manifest_path=manifest,
        canonical_store_path=store,
    )

    assert result1["status"] == "imported"
    assert result2["status"] == "duplicate_file_skipped"

    records, malformed = load_canonical_records(path=store)
    assert malformed == 0
    assert len(records) == 1


def test_multiple_snapshots_preserved(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    store = tmp_path / "canonical.jsonl"
    source1 = tmp_path / "source1.csv"
    source2 = tmp_path / "source2.csv"
    source1.write_text("a", encoding="utf-8")
    source2.write_text("b", encoding="utf-8")

    import_records_append_only(
        provider=ProviderName.STUDIO_EXPORT.value,
        source_file=source1,
        candidate_rows=[_row("car_1")],
        manifest_path=manifest,
        canonical_store_path=store,
    )
    import_records_append_only(
        provider=ProviderName.STUDIO_EXPORT.value,
        source_file=source2,
        candidate_rows=[_row("car_2")],
        manifest_path=manifest,
        canonical_store_path=store,
    )

    records, _ = load_canonical_records(path=store)
    assert len(records) == 2


def test_replay_malformed_tolerance(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    store = tmp_path / "canonical.jsonl"
    source = tmp_path / "source.csv"
    source.write_text("x", encoding="utf-8")

    import_records_append_only(
        provider=ProviderName.STUDIO_EXPORT.value,
        source_file=source,
        candidate_rows=[_row("car_1")],
        manifest_path=manifest,
        canonical_store_path=store,
    )

    with store.open("a", encoding="utf-8") as h:
        h.write("{bad json}\n")

    records, malformed = load_canonical_records(path=store)
    assert len(records) == 1
    assert malformed >= 1


def test_manifest_written_append_only(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    store = tmp_path / "canonical.jsonl"
    source = tmp_path / "source.csv"
    source.write_text("x", encoding="utf-8")

    import_records_append_only(
        provider=ProviderName.STUDIO_EXPORT.value,
        source_file=source,
        candidate_rows=[_row("car_1")],
        manifest_path=manifest,
        canonical_store_path=store,
    )

    rows, malformed = load_import_manifest(path=manifest)
    assert malformed == 0
    assert len(rows) == 1
    assert rows[0]["advisory_only"] is True
    assert rows[0]["pipeline_output_changed"] is False
