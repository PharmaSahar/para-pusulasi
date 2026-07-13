from __future__ import annotations

import json
import re
from pathlib import Path


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_backtick_paths(markdown_text: str) -> list[str]:
    candidates = re.findall(r"(?<!`)`([^`\n]+)`(?!`)", markdown_text)
    return [c for c in candidates if "/" in c and not c.startswith("#")]


def _reference_exists(repo: Path, rel_path: str) -> bool:
    if any(ch in rel_path for ch in "*?[]"):
        return any((repo / ".").glob(rel_path))
    return (repo / rel_path).exists()


def test_project002_sprint1_reconciliation_cross_references() -> None:
    repo = Path(".")

    sprint1c_doc = repo / "docs/PROJECT_002_SPRINT1C_REAL_WORLD_VALIDATION.md"
    sprint1d_doc = repo / "docs/PROJECT_002_SPRINT1D_EVIDENCE_COVERAGE_AUDIT.md"

    sprint1c_dir = repo / "artifacts/latest/project002_sprint1c_real_world_validation"
    sprint1d_dir = repo / "artifacts/latest/project002_sprint1d_evidence_coverage_audit"

    required_sprint1c = {
        sprint1c_dir / "blind_dataset.jsonl",
        sprint1c_dir / "cqga_predictions.jsonl",
        sprint1c_dir / "reference_labels.jsonl",
        sprint1c_dir / "agreement_summary.json",
    }
    required_sprint1d = {
        sprint1d_dir / "artifact_inventory.json",
        sprint1d_dir / "audit_summary.json",
        sprint1d_dir / "coverage_matrix.json",
        sprint1d_dir / "critical_path_top20.json",
        sprint1d_dir / "enrichment_plan.json",
    }

    assert sprint1c_doc.exists()
    assert sprint1d_doc.exists()
    assert all(p.exists() for p in required_sprint1c)
    assert all(p.exists() for p in required_sprint1d)

    sprint1c_text = sprint1c_doc.read_text(encoding="utf-8")
    sprint1d_text = sprint1d_doc.read_text(encoding="utf-8")

    for rel_path in _extract_backtick_paths(sprint1c_text) + _extract_backtick_paths(sprint1d_text):
        # Only validate in-repo references.
        if rel_path.startswith(("http://", "https://")):
            continue
        assert _reference_exists(repo, rel_path), f"Broken reference: {rel_path}"

    agreement = _load_json(sprint1c_dir / "agreement_summary.json")
    audit_summary = _load_json(sprint1d_dir / "audit_summary.json")
    coverage_matrix = _load_json(sprint1d_dir / "coverage_matrix.json")
    critical_path = _load_json(sprint1d_dir / "critical_path_top20.json")
    enrichment_plan = _load_json(sprint1d_dir / "enrichment_plan.json")

    recall = float(agreement["overall"]["recall"])
    root_agreement = float(agreement["overall"]["root_cause_agreement"])
    assert recall < 0.85
    assert root_agreement < 0.85

    matrix_by_type = {
        str(row.get("artifact_type") or ""): row
        for row in coverage_matrix
        if isinstance(row, dict)
    }
    assert float(matrix_by_type["script"]["coverage_percentage"]) <= 5.0
    assert float(matrix_by_type["thumbnail_metadata"]["coverage_percentage"]) == 0.0
    assert float(matrix_by_type["analytics snapshots"]["coverage_percentage"]) == 0.0

    top_rank = critical_path[0]
    assert str(top_rank["artifact_type"]) == "script"
    assert str(top_rank["pipeline_stage"]) == "generation"

    enrichment_artifacts = {str(row.get("artifact") or "") for row in enrichment_plan}
    assert "script_full_text" in enrichment_artifacts
    assert "thumbnail_prompt_and_metadata" in enrichment_artifacts
    assert "analytics_per_content_join" in enrichment_artifacts

    assert bool(audit_summary.get("advisory_only")) is True
    assert bool(audit_summary.get("pipeline_output_changed")) is False
