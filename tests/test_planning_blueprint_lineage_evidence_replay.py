from __future__ import annotations

from pathlib import Path

from src.planning_blueprint_lineage_evidence import (
    PlanningLineageRecorder,
    PlanningLineageSourceStage,
    reconstruct_planning_lineage_state,
)


def test_replay_reconstructs_latest_state(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = PlanningLineageRecorder(
        content_id="content_1",
        run_id="run_1",
        experiment_id="exp_1",
        evidence_path=path,
    )

    recorder.record_linkage(
        planning_context_id="run_1",
        blueprint_id="bp_1",
        blueprint_hash="bh_1",
        prompt_metadata={"prompt_hash": "ph_1"},
        script_text="script one",
        source_stage=PlanningLineageSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
    )
    recorder.record_linkage(
        planning_context_id="run_1",
        blueprint_id="bp_1",
        blueprint_hash="bh_1",
        prompt_metadata={"prompt_hash": "ph_2"},
        script_text="script two",
        source_stage=PlanningLineageSourceStage.QUALITY_REGENERATION,
        generation_attempt=2,
    )

    state, diagnostics = reconstruct_planning_lineage_state(evidence_path=path)
    assert diagnostics.replay_errors == []
    key = "content_1::run_1"
    assert key in state
    assert state[key]["latest_link_status"] in {"LINKED", "PARTIAL"}
    assert len(state[key]["script_hashes"]) == 2
