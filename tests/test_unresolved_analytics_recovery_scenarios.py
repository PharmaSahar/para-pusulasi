from __future__ import annotations

from src.unresolved_analytics_recovery import EvidenceIndexes, EvidenceReference, FinalDisposition, PHASE4C_SCHEMA_VERSION, TaxonomyCategory, classify_unresolved_row


def _proof(name: str) -> EvidenceReference:
    return EvidenceReference(source_type=name, path=f"/{name}.json", identity_key="k", identity_value="v", proof_hash=f"hash_{name}", payload={"name": name})


def _base_row(**overrides):
    row = {
        "schema_version": PHASE4C_SCHEMA_VERSION,
        "unresolved_record_id": "uar_case",
        "canonical_analytics_record_id": "car_case",
        "provider": "ExistingLocalAnalyticsProvider",
        "source_file_hash": "hash",
        "source_row_number": 1,
        "channel_id": "chan_a",
        "youtube_video_id": "vid_a",
        "content_id": "content_a",
        "upload_id": None,
        "run_id": "run_a",
        "forward_session_id": None,
        "script_lineage_evidence_id": None,
        "planning_blueprint_hash": None,
        "snapshot_start": "2026-07-10",
        "snapshot_end": "2026-07-10",
        "metric_fields_present": ["views"],
        "original_join_status": "UNRESOLVED",
        "original_join_reason": "deterministic_keys_missing",
        "row_hash": "hash_row",
        "source_row": {"title": "Example"},
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    row.update(overrides)
    return row


def _single_target_indexes(**kwargs) -> EvidenceIndexes:
    indexes = EvidenceIndexes()
    indexes.add_target(proof=_proof("runtime"), **kwargs)
    return indexes


def test_scenarios_cover_required_cases() -> None:
    cases = []
    cases.append(classify_unresolved_row(row=_base_row(content_id=None, run_id=None, youtube_video_id="vid_x"), indexes=_single_target_indexes(content_id="content_x", run_id="run_x", channel_id="chan_a", youtube_video_id="vid_x", upload_id=None), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(content_id=None, run_id=None, youtube_video_id=None, upload_id="upl_x"), indexes=_single_target_indexes(content_id="content_x", run_id="run_x", channel_id="chan_a", youtube_video_id=None, upload_id="upl_x"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(youtube_video_id=None, run_id=None), indexes=_single_target_indexes(content_id="content_a", run_id="run_x", channel_id="chan_a", youtube_video_id=None, upload_id=None), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(content_id=None, youtube_video_id=None), indexes=_single_target_indexes(content_id="content_x", run_id="run_a", channel_id="chan_a", youtube_video_id=None, upload_id=None), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    idx = EvidenceIndexes(); idx.add_target(content_id="content_a", run_id="run_a", channel_id="chan_a", youtube_video_id=None, upload_id=None, proof=_proof("runtime"), forward_session_id="fes_x")
    cases.append(classify_unresolved_row(row=_base_row(content_id=None, run_id=None, youtube_video_id=None, forward_session_id="fes_x"), indexes=idx, snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(content_id=None, run_id=None, youtube_video_id=None), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(source_row={"legacy_upload": True}), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(source_row={"video_state": "deleted"}), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(source_row={"video_state": "private"}), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    idx = _single_target_indexes(content_id="content_a", run_id="run_a", channel_id="other_chan", youtube_video_id="vid_a", upload_id=None)
    cases.append(classify_unresolved_row(row=_base_row(channel_id="chan_a"), indexes=idx, snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(provider="UnknownProvider"), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    idx = EvidenceIndexes(); idx.add_target(content_id="content_a", run_id="run_a", channel_id="chan_a", youtube_video_id="dup_vid", upload_id=None, proof=_proof("a")); idx.add_target(content_id="content_b", run_id="run_b", channel_id="chan_a", youtube_video_id="dup_vid", upload_id=None, proof=_proof("b"))
    cases.append(classify_unresolved_row(row=_base_row(content_id=None, run_id=None, youtube_video_id="dup_vid"), indexes=idx, snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(source_row={"title": "Example"}), indexes=EvidenceIndexes(), snapshot_disposition={"status": "DUPLICATE_SOURCE_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(source_row={"title": "Example"}), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW", "later_valid_snapshot": True, "overlapping_snapshot": False, "incompatible_snapshot_definition": False}))
    cases.append(classify_unresolved_row(row=_base_row(source_row={"title": "Total"}, content_id="", youtube_video_id="", run_id=""), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW", "aggregate_row": True}))
    cases.append(classify_unresolved_row(row=_base_row(source_row={"views": {"bad": 1}}), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(content_id=None, youtube_video_id=None, run_id="run_x"), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(content_id="content_x", youtube_video_id="vid_x", run_id="run_x"), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(content_id=None, youtube_video_id=None, run_id=None, upload_id=None), indexes=EvidenceIndexes(), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))
    cases.append(classify_unresolved_row(row=_base_row(script_lineage_evidence_id="sle_x", content_id=None, run_id=None, youtube_video_id=None), indexes=_single_target_indexes(content_id="content_z", run_id="run_z", channel_id="chan_a", youtube_video_id=None, upload_id=None, script_evidence_id="sle_x"), snapshot_disposition={"status": "CONTENT_LEVEL_ROW"}))

    assert len(cases) == 20
    assert all(case["pipeline_output_changed"] is False for case in cases)
    assert any(case["final_set"] == FinalDisposition.RECOVERED.value for case in cases)
    assert any(case["primary_category"] == TaxonomyCategory.AMBIGUOUS_IDENTITY.value for case in cases)
    assert any(case["primary_category"] == TaxonomyCategory.MALFORMED_ROW.value or case["primary_category"] == TaxonomyCategory.UNSUPPORTED_METRIC_SHAPE.value for case in cases)