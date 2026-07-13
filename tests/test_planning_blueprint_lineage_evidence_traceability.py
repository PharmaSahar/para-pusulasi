from __future__ import annotations

import json
from pathlib import Path

from src.planning_blueprint_lineage_evidence import build_identifier_audit


def test_identifier_audit_reports_missing_and_duplicates(tmp_path: Path) -> None:
    planning = tmp_path / "planning.jsonl"
    alignment = tmp_path / "alignment.jsonl"
    script_lineage = tmp_path / "script_lineage.jsonl"
    runtime = tmp_path / "runtime"
    ownership = tmp_path / "ownership"
    runtime.mkdir(parents=True)
    ownership.mkdir(parents=True)

    planning.write_text(
        "\n".join(
            [
                json.dumps({"run_id": "run_1", "blueprint_id": "bp_1", "blueprint_hash": "bh_1"}),
                json.dumps({"run_id": "run_1", "blueprint_id": "bp_2", "blueprint_hash": "bh_2"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    alignment.write_text(json.dumps({"run_id": "run_1", "prompt_hash": "ph_1"}) + "\n", encoding="utf-8")
    script_lineage.write_text(
        json.dumps(
            {
                "content_id": "content_1",
                "run_id": "run_1",
                "script_hash": "sh_1",
                "planning_context_id": "run_1",
                "blueprint_id": "",
                "blueprint_hash": "",
                "prompt_metadata_hash": "",
                "experiment_id": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (runtime / "content_1.json").write_text(json.dumps({"generation_id": "content_1"}), encoding="utf-8")
    (ownership / "content_1_run_1.json").write_text(json.dumps({"content_id": "content_1", "run_id": "run_1"}), encoding="utf-8")

    audit = build_identifier_audit(
        planning_path=planning,
        alignment_path=alignment,
        script_lineage_path=script_lineage,
        runtime_evidence_dir=runtime,
        ownership_dir=ownership,
        limit=50,
    )
    assert audit.duplicate_ids["blueprint_id"] >= 1
    assert audit.inferred_ids["planning_context_id"] >= 1
