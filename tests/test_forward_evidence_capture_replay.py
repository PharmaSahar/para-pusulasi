from __future__ import annotations

from pathlib import Path

from src.forward_evidence_capture import (
    ForwardEvidenceRecorder,
    ForwardEvidenceStage,
    compute_forward_completeness_scores,
    reconstruct_forward_sessions,
    verify_forward_evidence_integrity,
)


def test_replay_integrity_and_completeness(tmp_path: Path) -> None:
    path = tmp_path / "forward.jsonl"
    recorder = ForwardEvidenceRecorder(
        content_id="content_1",
        run_id="run_1",
        channel_id="chan_1",
        evidence_path=path,
    )

    recorder.record_stage(
        stage=ForwardEvidenceStage.PLANNING_COMPLETE,
        planning_context_id="run_1",
        blueprint_id=None,
        prompt_metadata_hash=None,
        script_hash=None,
        thumbnail_hash=None,
        render_hash=None,
        upload_id=None,
        ownership_id=None,
    )
    recorder.record_stage(
        stage=ForwardEvidenceStage.BLUEPRINT_FINALIZED,
        planning_context_id="run_1",
        blueprint_id="bp_1",
        prompt_metadata_hash=None,
        script_hash=None,
        thumbnail_hash=None,
        render_hash=None,
        upload_id=None,
        ownership_id=None,
    )
    recorder.record_stage(
        stage=ForwardEvidenceStage.PROMPT_FINALIZED,
        planning_context_id="run_1",
        blueprint_id="bp_1",
        prompt_metadata_hash="ph_1",
        script_hash=None,
        thumbnail_hash=None,
        render_hash=None,
        upload_id=None,
        ownership_id=None,
    )
    recorder.record_stage(
        stage=ForwardEvidenceStage.SCRIPT_FINALIZED,
        planning_context_id="run_1",
        blueprint_id="bp_1",
        prompt_metadata_hash="ph_1",
        script_hash="sh_1",
        thumbnail_hash=None,
        render_hash=None,
        upload_id=None,
        ownership_id=None,
    )
    recorder.record_stage(
        stage=ForwardEvidenceStage.THUMBNAIL_FINALIZED,
        planning_context_id="run_1",
        blueprint_id="bp_1",
        prompt_metadata_hash="ph_1",
        script_hash="sh_1",
        thumbnail_hash="th_1",
        render_hash=None,
        upload_id=None,
        ownership_id="own_1",
    )
    recorder.record_stage(
        stage=ForwardEvidenceStage.RENDER_COMPLETE,
        planning_context_id="run_1",
        blueprint_id="bp_1",
        prompt_metadata_hash="ph_1",
        script_hash="sh_1",
        thumbnail_hash="th_1",
        render_hash="rh_1",
        upload_id=None,
        ownership_id="own_1",
    )
    recorder.record_stage(
        stage=ForwardEvidenceStage.UPLOAD_COMPLETE,
        planning_context_id="run_1",
        blueprint_id="bp_1",
        prompt_metadata_hash="ph_1",
        script_hash="sh_1",
        thumbnail_hash="th_1",
        render_hash="rh_1",
        upload_id="vid_1",
        ownership_id="own_1",
    )

    sessions, diagnostics = reconstruct_forward_sessions(evidence_path=path)
    assert diagnostics.malformed_rows == 0
    assert diagnostics.replay_errors == []

    integrity = verify_forward_evidence_integrity(sessions=sessions)
    assert integrity["summary"]["total_sessions"] == 1
    assert integrity["summary"]["missing_stage"] == 0
    assert integrity["summary"]["broken_lineage"] == 0

    scores = compute_forward_completeness_scores(sessions=sessions)
    assert scores["aggregate"]["lineage_completeness"] == 100.0
    assert scores["aggregate"]["overall_traceability"] == 100.0
