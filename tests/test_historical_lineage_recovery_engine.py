from __future__ import annotations

import json
from pathlib import Path

from src.historical_lineage_recovery import build_historical_recovery


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_recovery_engine_builds_proven_chain(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    ownership_dir = tmp_path / "ownership"
    planning_path = tmp_path / "planning.jsonl"
    alignment_path = tmp_path / "alignment.jsonl"
    script_lineage_path = tmp_path / "script_lineage.jsonl"
    prompt_exp_path = tmp_path / "prompt_exp.jsonl"
    offline_path = tmp_path / "offline.jsonl"

    _write_json(
        runtime_dir / "content_c1.json",
        {
            "generation_id": "content_c1",
            "script_hash": "sh1",
            "render_result": {"render_status": "completed"},
            "upload_result": {"video_id": "vid1", "youtube_url": "https://youtube.com/watch?v=vid1"},
        },
    )
    _write_json(
        ownership_dir / "content_c1_run_r1.json",
        {"content_id": "content_c1", "run_id": "run_r1"},
    )
    planning_path.write_text(
        json.dumps({"run_id": "run_r1", "blueprint_id": "bp1", "blueprint_hash": "bh1"}) + "\n",
        encoding="utf-8",
    )
    alignment_path.write_text(
        json.dumps({"run_id": "run_r1", "blueprint_hash": "bh1", "prompt_hash": "ph1"}) + "\n",
        encoding="utf-8",
    )
    script_lineage_path.write_text("", encoding="utf-8")
    prompt_exp_path.write_text("", encoding="utf-8")
    offline_path.write_text("", encoding="utf-8")

    output = build_historical_recovery(
        runtime_dir=runtime_dir,
        ownership_dir=ownership_dir,
        planning_path=planning_path,
        alignment_path=alignment_path,
        script_lineage_path=script_lineage_path,
        prompt_experiments_path=prompt_exp_path,
        offline_prompt_candidates_path=offline_path,
        limit=10,
    )

    payload = output.to_dict()
    assert payload["counts"]["recoverable"] == 1
    assert payload["coverage_after"]["fully_traceable_content_rate"] == 100.0
    assert len(payload["records"]) >= 5
