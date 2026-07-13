from __future__ import annotations

import json
from pathlib import Path

from src.forward_evidence_capture import (
    ForwardEvidenceRecorder,
    ForwardEvidenceStage,
    ForwardEvidenceStore,
    load_forward_evidence_rows,
)


def test_append_only_and_malformed_tolerance(tmp_path: Path) -> None:
    path = tmp_path / "forward.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")

    recorder = ForwardEvidenceRecorder(
        content_id="content_1",
        run_id="run_1",
        channel_id="chan_1",
        evidence_path=path,
    )
    result = recorder.record_stage(
        stage=ForwardEvidenceStage.PLANNING_COMPLETE,
        planning_context_id="run_1",
        blueprint_id="bp_1",
        prompt_metadata_hash=None,
        script_hash=None,
        thumbnail_hash=None,
        render_hash=None,
        upload_id=None,
        ownership_id=None,
    )
    assert result.appended is True

    rows, malformed, _errors = load_forward_evidence_rows(input_path=path)
    assert malformed >= 1
    assert len(rows) == 1


def test_duplicate_protection(tmp_path: Path) -> None:
    path = tmp_path / "forward.jsonl"
    recorder = ForwardEvidenceRecorder(
        content_id="content_1",
        run_id="run_1",
        channel_id="chan_1",
        evidence_path=path,
    )

    first = recorder.record_stage(
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
    second = recorder.record_stage(
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

    assert first.appended is True
    assert second.duplicate is True


def test_deterministic_serialization(tmp_path: Path) -> None:
    path = tmp_path / "forward.jsonl"
    store = ForwardEvidenceStore(evidence_path=path)

    row = {
        "schema_version": "v1",
        "event_id": "fev_demo",
        "session_id": "fes_demo",
        "stage": "PLANNING_COMPLETE",
        "stage_order": 10,
        "run_id": "run_1",
        "content_id": "content_1",
        "channel_id": "chan_1",
        "planning_context_id": "run_1",
        "blueprint_id": None,
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
    appended = store.append(row)
    assert appended.appended is True

    decoded = json.loads(path.read_text(encoding="utf-8").strip())
    assert list(decoded.keys()) == sorted(decoded.keys())
