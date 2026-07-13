from __future__ import annotations

import pytest

from src.forward_evidence_capture import (
    FORWARD_EVIDENCE_SCHEMA_VERSION,
    ForwardEvidenceStage,
    compute_event_id,
    compute_session_id,
    extract_prompt_metadata_hash,
    validate_forward_evidence_event,
)


def test_enum_values_stable() -> None:
    assert ForwardEvidenceStage.PLANNING_COMPLETE.value == "PLANNING_COMPLETE"
    assert ForwardEvidenceStage.UPLOAD_COMPLETE.value == "UPLOAD_COMPLETE"


def test_compute_ids_are_deterministic() -> None:
    session_a = compute_session_id(content_id="c1", run_id="r1")
    session_b = compute_session_id(content_id="c1", run_id="r1")
    assert session_a == session_b

    event_a = compute_event_id(
        session_id=session_a,
        stage=ForwardEvidenceStage.SCRIPT_FINALIZED,
        stage_order=40,
        keys=["c1", "r1", "script_hash"],
    )
    event_b = compute_event_id(
        session_id=session_a,
        stage=ForwardEvidenceStage.SCRIPT_FINALIZED,
        stage_order=40,
        keys=["c1", "r1", "script_hash"],
    )
    assert event_a == event_b


def test_extract_prompt_metadata_hash() -> None:
    assert extract_prompt_metadata_hash({"prompt_hash": "abc"}) == "abc"
    assert extract_prompt_metadata_hash({"safe_prompt": {"prompt_hash": "def"}}) == "def"
    assert extract_prompt_metadata_hash({"prompt_hash": "a", "safe_prompt": {"prompt_hash": "b"}}) is None


def test_validate_event_requires_advisory_and_no_mutation() -> None:
    row = {
        "schema_version": FORWARD_EVIDENCE_SCHEMA_VERSION,
        "event_id": "fev_1",
        "session_id": "fes_1",
        "stage": "PLANNING_COMPLETE",
        "stage_order": 10,
        "run_id": "run_1",
        "content_id": "content_1",
        "channel_id": "chan_1",
        "planning_context_id": "run_1",
        "blueprint_id": "bp_1",
        "prompt_metadata_hash": None,
        "script_hash": None,
        "thumbnail_hash": None,
        "render_hash": None,
        "upload_id": None,
        "ownership_id": None,
        "created_at": "2026-07-13T00:00:00+00:00",
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    ok = validate_forward_evidence_event(row)
    assert ok["pipeline_output_changed"] is False

    bad = dict(row)
    bad["pipeline_output_changed"] = True
    with pytest.raises(ValueError):
        validate_forward_evidence_event(bad)
