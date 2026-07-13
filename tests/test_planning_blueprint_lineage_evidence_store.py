from __future__ import annotations

import json
from pathlib import Path

from src.planning_blueprint_lineage_evidence import (
    PlanningLineageEvidenceStore,
    PlanningLineageRecorder,
    PlanningLineageSourceStage,
    load_planning_lineage_rows,
)


def test_append_only_and_malformed_tolerance(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")

    recorder = PlanningLineageRecorder(
        content_id="c1",
        run_id="r1",
        experiment_id="exp1",
        evidence_path=path,
    )
    result = recorder.record_linkage(
        planning_context_id="r1",
        blueprint_id="bp1",
        blueprint_hash="bh1",
        prompt_metadata={"prompt_hash": "ph1"},
        script_text="script one",
        source_stage=PlanningLineageSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
    )
    assert result.appended is True

    rows, malformed, _errors = load_planning_lineage_rows(input_path=path)
    assert malformed >= 1
    assert len(rows) == 1


def test_duplicate_protection(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = PlanningLineageRecorder(content_id="c", run_id="r", experiment_id="e", evidence_path=path)

    first = recorder.record_linkage(
        planning_context_id="r",
        blueprint_id="bp",
        blueprint_hash="bh",
        prompt_metadata={"prompt_hash": "ph"},
        script_text="same",
        source_stage=PlanningLineageSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
    )
    second = recorder.record_linkage(
        planning_context_id="r",
        blueprint_id="bp",
        blueprint_hash="bh",
        prompt_metadata={"prompt_hash": "ph"},
        script_text="same",
        source_stage=PlanningLineageSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
    )

    assert first.appended is True
    assert second.duplicate is True


def test_deterministic_serialization(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = PlanningLineageEvidenceStore(evidence_path=path)
    row = {
        "schema_version": "v1",
        "evidence_id": "pble_demo",
        "planning_context_id": "r",
        "blueprint_id": "bp",
        "blueprint_hash": "bh",
        "prompt_metadata_hash": "ph",
        "experiment_id": "e",
        "content_id": "c",
        "run_id": "r",
        "script_hash": "sh",
        "link_status": "LINKED",
        "source_stage": "INITIAL_GENERATION",
        "generation_attempt": 1,
        "created_at": "2026-07-13T00:00:00+00:00",
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    result = store.append(row)
    assert result.appended is True

    line = path.read_text(encoding="utf-8").strip()
    decoded = json.loads(line)
    assert list(decoded.keys()) == sorted(decoded.keys())
