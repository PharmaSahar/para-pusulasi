from __future__ import annotations

import json
from pathlib import Path

from src.unresolved_analytics_recovery import build_studio_export_request_spec, run_phase4c_unresolved_analytics_recovery


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_phase4c_repeat_audit_is_deterministic_and_append_only(tmp_path: Path) -> None:
    kwargs = {
        "repository_root": REPO_ROOT,
        "output_dir": tmp_path / "output",
        "manifest_path": tmp_path / "manifest.jsonl",
        "audit_results_path": tmp_path / "audit.jsonl",
        "recovery_evidence_path": tmp_path / "recovery.jsonl",
        "duplicate_disposition_path": tmp_path / "duplicates.jsonl",
    }
    first = run_phase4c_unresolved_analytics_recovery(**kwargs)
    second = run_phase4c_unresolved_analytics_recovery(**kwargs)

    assert first["manifest_count"] == 102
    assert second["manifest_count"] == 102
    assert first["coverage_delta"] == second["coverage_delta"]
    assert first["append_only_audit"]["audit_results"]["appended"] == 102
    assert second["append_only_audit"]["audit_results"]["duplicates"] == 102

    manifest_lines = [json.loads(line) for line in (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(manifest_lines) == 102
    assert all(line["pipeline_output_changed"] is False for line in manifest_lines)


def test_phase4c_real_local_result_is_full_recovery(tmp_path: Path) -> None:
    summary = run_phase4c_unresolved_analytics_recovery(
        repository_root=REPO_ROOT,
        output_dir=tmp_path / "output",
        manifest_path=tmp_path / "manifest.jsonl",
        audit_results_path=tmp_path / "audit.jsonl",
        recovery_evidence_path=tmp_path / "recovery.jsonl",
        duplicate_disposition_path=tmp_path / "duplicates.jsonl",
    )
    after = summary["coverage_delta"]["after"]
    assert after["recovered"] == 102
    assert after["still_unresolved"] == 0
    assert after["ambiguous"] == 0
    assert after["invalid"] == 0
    assert summary["classification_results"] == [
        {
            "category": "MISSING_OWNERSHIP_RECORD",
            "count": 102,
            "recoverability": {"RECOVERABLE_NOW": 102},
            "required_proof": {"NONE": 102},
        }
    ]


def test_studio_export_spec_keeps_video_id_as_identity() -> None:
    spec = build_studio_export_request_spec()
    assert "Video ID" in spec["required_fields"]
    assert "title is descriptive only" in spec["identity_rule"]