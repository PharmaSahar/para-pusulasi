from __future__ import annotations

from src.unresolved_analytics_recovery import (
    EvidenceIndexes,
    EvidenceReference,
    FinalDisposition,
    PHASE4C_SCHEMA_VERSION,
    RecoveryMethod,
    classify_unresolved_row,
)


def _row(**overrides):
    row = {
        "schema_version": PHASE4C_SCHEMA_VERSION,
        "unresolved_record_id": "uar_test",
        "canonical_analytics_record_id": "car_test",
        "provider": "ExistingLocalAnalyticsProvider",
        "source_file_hash": "hash",
        "source_row_number": 1,
        "channel_id": "chan_a",
        "youtube_video_id": None,
        "content_id": None,
        "upload_id": None,
        "run_id": None,
        "forward_session_id": None,
        "script_lineage_evidence_id": None,
        "planning_blueprint_hash": None,
        "snapshot_start": "2026-07-10",
        "snapshot_end": "2026-07-10",
        "metric_fields_present": ["views"],
        "original_join_status": "UNRESOLVED",
        "original_join_reason": "deterministic_keys_missing",
        "row_hash": "rowhash",
        "source_row": {"title": "Example"},
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    row.update(overrides)
    return row


def _proof(name: str) -> EvidenceReference:
    return EvidenceReference(source_type=name, path=f"/{name}.json", identity_key="k", identity_value="v", proof_hash=f"hash_{name}", payload={"name": name})


def _indexes_with_target(*, content_id=None, run_id=None, channel_id="chan_a", youtube_video_id=None, upload_id=None, forward_session_id=None, script_evidence_id=None, blueprint_hash=None, ownership_id=None):
    indexes = EvidenceIndexes()
    indexes.add_target(
        content_id=content_id,
        run_id=run_id,
        channel_id=channel_id,
        youtube_video_id=youtube_video_id,
        upload_id=upload_id,
        proof=_proof("runtime"),
        forward_session_id=forward_session_id,
        script_evidence_id=script_evidence_id,
        blueprint_hash=blueprint_hash,
        ownership_id=ownership_id,
    )
    return indexes


def test_exact_video_id_recovery() -> None:
    row = _row(youtube_video_id="vid_1")
    out = classify_unresolved_row(row=row, indexes=_indexes_with_target(youtube_video_id="vid_1", channel_id="chan_a"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] == FinalDisposition.RECOVERED.value
    assert out["recovery"]["recovery_method"] == RecoveryMethod.VIDEO_ID.value


def test_exact_upload_id_recovery() -> None:
    row = _row(upload_id="upl_1")
    out = classify_unresolved_row(row=row, indexes=_indexes_with_target(upload_id="upl_1", channel_id="chan_a"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] == FinalDisposition.RECOVERED.value
    assert out["recovery"]["recovery_method"] == RecoveryMethod.UPLOAD_ID.value


def test_exact_content_id_recovery() -> None:
    row = _row(content_id="content_1")
    out = classify_unresolved_row(row=row, indexes=_indexes_with_target(content_id="content_1", channel_id="chan_a"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] == FinalDisposition.RECOVERED.value
    assert out["recovery"]["recovery_method"] == RecoveryMethod.CONTENT_ID.value


def test_exact_run_id_recovery() -> None:
    row = _row(run_id="run_1")
    out = classify_unresolved_row(row=row, indexes=_indexes_with_target(run_id="run_1", channel_id="chan_a"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] == FinalDisposition.RECOVERED.value
    assert out["recovery"]["recovery_method"] == RecoveryMethod.RUN_ID.value


def test_exact_ownership_recovery() -> None:
    row = _row(content_id="content_x", source_row={"title": "Example"}, ownership_id="owner_1")
    out = classify_unresolved_row(row=row, indexes=_indexes_with_target(content_id="content_x", channel_id="chan_a", ownership_id="owner_1"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] == FinalDisposition.RECOVERED.value
    assert out["recovery"]["recovery_method"] == RecoveryMethod.OWNERSHIP.value


def test_exact_forward_evidence_recovery() -> None:
    row = _row(forward_session_id="fes_1")
    out = classify_unresolved_row(row=row, indexes=_indexes_with_target(content_id="content_1", run_id="run_1", channel_id="chan_a", forward_session_id="fes_1"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] == FinalDisposition.RECOVERED.value
    assert out["recovery"]["recovery_method"] == RecoveryMethod.FORWARD_EVIDENCE.value


def test_exact_lineage_hash_recovery() -> None:
    row = _row(script_lineage_evidence_id="sle_1")
    out = classify_unresolved_row(row=row, indexes=_indexes_with_target(content_id="content_1", run_id="run_1", channel_id="chan_a", script_evidence_id="sle_1"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] == FinalDisposition.RECOVERED.value
    assert out["recovery"]["recovery_method"] == RecoveryMethod.LINEAGE_HASH.value


def test_ambiguous_multi_match_rejected() -> None:
    indexes = EvidenceIndexes()
    indexes.add_target(content_id="content_a", run_id="run_a", channel_id="chan_a", youtube_video_id="dup_vid", upload_id=None, proof=_proof("a"))
    indexes.add_target(content_id="content_b", run_id="run_b", channel_id="chan_a", youtube_video_id="dup_vid", upload_id=None, proof=_proof("b"))
    out = classify_unresolved_row(row=_row(youtube_video_id="dup_vid"), indexes=indexes, snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] == FinalDisposition.AMBIGUOUS.value


def test_no_title_join_or_timestamp_only_join() -> None:
    row = _row(source_row={"title": "Looks similar"}, snapshot_start="2026-07-10", snapshot_end="2026-07-10")
    out = classify_unresolved_row(row=row, indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"})
    assert out["final_set"] != FinalDisposition.RECOVERED.value