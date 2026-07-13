from __future__ import annotations

import json
from pathlib import Path

from src.planning_blueprint_lineage_evidence import (
    build_historical_planning_lineage_assessment,
    run_historical_planning_lineage_dry_run,
)


def test_historical_assessment_dry_run_non_mutating(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True)
    planning = tmp_path / "planning.jsonl"
    alignment = tmp_path / "alignment.jsonl"
    script_lineage = tmp_path / "script_lineage.jsonl"

    (runtime / "content_a.json").write_text(
        json.dumps({"generation_id": "content_a", "run_id": "run_a", "script_hash": "sh_a"}),
        encoding="utf-8",
    )
    planning.write_text(
        json.dumps({"run_id": "run_a", "blueprint_id": "bp_a", "blueprint_hash": "bh_a"}) + "\n",
        encoding="utf-8",
    )
    alignment.write_text(
        json.dumps({"run_id": "run_a", "prompt_hash": "ph_a"}) + "\n",
        encoding="utf-8",
    )
    script_lineage.write_text("", encoding="utf-8")

    before = (runtime / "content_a.json").read_text(encoding="utf-8")
    report_path = tmp_path / "report.json"

    payload = run_historical_planning_lineage_dry_run(
        output_path=report_path,
        runtime_evidence_dir=runtime,
        planning_path=planning,
        alignment_path=alignment,
        script_lineage_path=script_lineage,
        limit=10,
    )

    after = (runtime / "content_a.json").read_text(encoding="utf-8")
    assert before == after
    assert payload["dry_run"] is True
    assert payload["sample_count"] == 1


def test_historical_assessment_classifies_linked(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True)
    planning = tmp_path / "planning.jsonl"
    alignment = tmp_path / "alignment.jsonl"
    script_lineage = tmp_path / "script_lineage.jsonl"

    (runtime / "content_b.json").write_text(
        json.dumps({"generation_id": "content_b", "run_id": "run_b", "script_hash": "sh_b"}),
        encoding="utf-8",
    )
    planning.write_text(
        json.dumps({"run_id": "run_b", "blueprint_id": "bp_b", "blueprint_hash": "bh_b"}) + "\n",
        encoding="utf-8",
    )
    alignment.write_text(
        json.dumps({"run_id": "run_b", "prompt_hash": "ph_b"}) + "\n",
        encoding="utf-8",
    )
    script_lineage.write_text("", encoding="utf-8")

    assessment = build_historical_planning_lineage_assessment(
        runtime_evidence_dir=runtime,
        planning_path=planning,
        alignment_path=alignment,
        script_lineage_path=script_lineage,
        limit=10,
    )
    assert assessment.linked == 1
    assert assessment.fully_traceable == 1
