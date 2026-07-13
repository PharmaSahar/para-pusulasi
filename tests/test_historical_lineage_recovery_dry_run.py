from __future__ import annotations

import json
from pathlib import Path

from src.historical_lineage_recovery import run_historical_recovery_dry_run


def test_dry_run_writes_report_without_mutating_sources(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    ownership_dir = tmp_path / "ownership"
    planning_path = tmp_path / "planning.jsonl"
    alignment_path = tmp_path / "alignment.jsonl"
    script_lineage_path = tmp_path / "script_lineage.jsonl"
    prompt_exp_path = tmp_path / "prompt_exp.jsonl"
    offline_path = tmp_path / "offline.jsonl"

    runtime_dir.mkdir(parents=True)
    ownership_dir.mkdir(parents=True)
    src_file = runtime_dir / "content_x.json"
    src_file.write_text(json.dumps({"generation_id": "content_x", "script_hash": "shx"}), encoding="utf-8")

    planning_path.write_text("", encoding="utf-8")
    alignment_path.write_text("", encoding="utf-8")
    script_lineage_path.write_text("", encoding="utf-8")
    prompt_exp_path.write_text("", encoding="utf-8")
    offline_path.write_text("", encoding="utf-8")

    before = src_file.read_text(encoding="utf-8")
    report_path = tmp_path / "report.json"

    payload = run_historical_recovery_dry_run(
        output_path=report_path,
        runtime_dir=runtime_dir,
        ownership_dir=ownership_dir,
        planning_path=planning_path,
        alignment_path=alignment_path,
        script_lineage_path=script_lineage_path,
        prompt_experiments_path=prompt_exp_path,
        offline_prompt_candidates_path=offline_path,
        limit=10,
    )

    after = src_file.read_text(encoding="utf-8")
    assert before == after
    assert payload["dry_run"] is True
    assert report_path.exists()
