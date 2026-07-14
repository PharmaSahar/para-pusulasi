from __future__ import annotations

import json
import re
from pathlib import Path
import pytest


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_nonempty_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _extract_backtick_paths(markdown_text: str) -> list[str]:
    candidates = re.findall(r"(?<!`)`([^`\n]+)`(?!`)", markdown_text)
    return [c for c in candidates if "/" in c and not c.startswith("#")]


def _normalize_rel_path(rel_path: str) -> str:
    return str(rel_path or "").strip().replace("\\", "/").lstrip("./")


def _is_local_runtime_provenance_path(rel_path: str) -> bool:
    """Historical runtime provenance is advisory in clean-checkout validation.

    These paths are intentionally gitignored local outputs, not repository-
    contained dependencies required for deterministic reconciliation.
    """
    normalized = _normalize_rel_path(rel_path)
    if not normalized:
        return False
    if normalized.startswith("/") or normalized.startswith("../"):
        return False
    return normalized.startswith(
        ("output/runtime/", "output/state/", "output/telemetry/", "output/queue/", "logs/")
    )


def _reference_exists(repo: Path, rel_path: str) -> bool:
    if any(ch in rel_path for ch in "*?[]"):
        return any((repo / ".").glob(rel_path))
    return (repo / rel_path).exists()


def _validate_reconciliation_contract(repo: Path, sprint1c_doc: Path, sprint1d_doc: Path) -> None:
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
        if _is_local_runtime_provenance_path(rel_path):
            continue
        assert _reference_exists(repo, rel_path), f"Broken reference: {rel_path}"

    agreement = _load_json(sprint1c_dir / "agreement_summary.json")
    audit_summary = _load_json(sprint1d_dir / "audit_summary.json")
    coverage_matrix = _load_json(sprint1d_dir / "coverage_matrix.json")
    critical_path = _load_json(sprint1d_dir / "critical_path_top20.json")
    enrichment_plan = _load_json(sprint1d_dir / "enrichment_plan.json")

    recall = float(agreement["overall"]["recall"])
    root_agreement = float(agreement["overall"]["root_cause_agreement"])
    dataset_size = int(agreement.get("dataset_size") or 0)
    real_sample_count = int(agreement.get("real_sample_count") or 0)

    if dataset_size > 0 and real_sample_count > 0:
        assert recall < 0.85
        assert root_agreement < 0.85
    elif dataset_size == 0 and real_sample_count == 0:
        assert recall == 1.0
        if "precision" in dict(agreement.get("overall") or {}):
            assert float(agreement["overall"]["precision"]) == 1.0

        assert _read_nonempty_lines(sprint1c_dir / "blind_dataset.jsonl") == []
        assert _read_nonempty_lines(sprint1c_dir / "reference_labels.jsonl") == []
        assert _read_nonempty_lines(sprint1c_dir / "cqga_predictions.jsonl") == []
    else:
        raise AssertionError(
            f"inconsistent_dataset_state: dataset_size={dataset_size}, real_sample_count={real_sample_count}"
        )

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


def test_project002_sprint1_reconciliation_cross_references() -> None:
    repo = Path(".")

    sprint1c_doc = repo / "docs/PROJECT_002_SPRINT1C_REAL_WORLD_VALIDATION.md"
    sprint1d_doc = repo / "docs/PROJECT_002_SPRINT1D_EVIDENCE_COVERAGE_AUDIT.md"

    _validate_reconciliation_contract(repo, sprint1c_doc, sprint1d_doc)


def test_runtime_provenance_paths_are_classified_narrowly() -> None:
    assert _is_local_runtime_provenance_path("output/runtime/evidence/content_*.json")
    assert _is_local_runtime_provenance_path("output/state/content_ownership/content_*_run_*.json")
    assert _is_local_runtime_provenance_path("output/telemetry/")
    assert _is_local_runtime_provenance_path("output/queue/")
    assert _is_local_runtime_provenance_path("logs/shadow_content_quality_results.jsonl")

    assert not _is_local_runtime_provenance_path("artifacts/latest/project002_sprint1c_real_world_validation/agreement_summary.json")
    assert not _is_local_runtime_provenance_path("docs/PROJECT_002_SPRINT1C_REAL_WORLD_VALIDATION.md")
    assert not _is_local_runtime_provenance_path("src/pipeline.py")


def test_wildcard_provenance_reference_absence_is_not_a_hard_failure(tmp_path: Path) -> None:
    repo = tmp_path
    rel_path = "output/runtime/evidence/content_*.json"
    assert _is_local_runtime_provenance_path(rel_path) is True
    assert _reference_exists(repo, rel_path) is False


def test_non_provenance_missing_reference_still_fails() -> None:
    repo = Path(".")
    rel_path = "docs/DOES_NOT_EXIST.md"
    assert _is_local_runtime_provenance_path(rel_path) is False
    assert _reference_exists(repo, rel_path) is False
    with pytest.raises(AssertionError, match="Broken reference"):
        assert _reference_exists(repo, rel_path), f"Broken reference: {rel_path}"


def test_required_artifact_files_remain_mandatory(tmp_path: Path) -> None:
    repo = tmp_path
    sprint1c_doc = repo / "docs/PROJECT_002_SPRINT1C_REAL_WORLD_VALIDATION.md"
    sprint1d_doc = repo / "docs/PROJECT_002_SPRINT1D_EVIDENCE_COVERAGE_AUDIT.md"
    sprint1c_doc.parent.mkdir(parents=True, exist_ok=True)
    sprint1c_doc.write_text("`docs/PROJECT_002_SPRINT1D_EVIDENCE_COVERAGE_AUDIT.md`", encoding="utf-8")
    sprint1d_doc.write_text("`docs/PROJECT_002_SPRINT1C_REAL_WORLD_VALIDATION.md`", encoding="utf-8")

    with pytest.raises(AssertionError):
        _validate_reconciliation_contract(repo, sprint1c_doc, sprint1d_doc)


def test_malformed_generated_artifact_data_still_fails(tmp_path: Path) -> None:
    repo = tmp_path
    sprint1c_doc = repo / "docs/PROJECT_002_SPRINT1C_REAL_WORLD_VALIDATION.md"
    sprint1d_doc = repo / "docs/PROJECT_002_SPRINT1D_EVIDENCE_COVERAGE_AUDIT.md"
    sprint1c_doc.parent.mkdir(parents=True, exist_ok=True)
    sprint1c_doc.write_text("`docs/PROJECT_002_SPRINT1D_EVIDENCE_COVERAGE_AUDIT.md`", encoding="utf-8")
    sprint1d_doc.write_text("`docs/PROJECT_002_SPRINT1C_REAL_WORLD_VALIDATION.md`", encoding="utf-8")

    s1c = repo / "artifacts/latest/project002_sprint1c_real_world_validation"
    s1d = repo / "artifacts/latest/project002_sprint1d_evidence_coverage_audit"
    s1c.mkdir(parents=True, exist_ok=True)
    s1d.mkdir(parents=True, exist_ok=True)

    (s1c / "blind_dataset.jsonl").write_text("\n", encoding="utf-8")
    (s1c / "cqga_predictions.jsonl").write_text("\n", encoding="utf-8")
    (s1c / "reference_labels.jsonl").write_text("\n", encoding="utf-8")
    (s1c / "agreement_summary.json").write_text("{\"overall\": {\"recall\": 0.1, \"root_cause_agreement\": 0.1}}", encoding="utf-8")

    (s1d / "artifact_inventory.json").write_text("[]", encoding="utf-8")
    (s1d / "audit_summary.json").write_text("{\"advisory_only\": true, \"pipeline_output_changed\": false}", encoding="utf-8")
    (s1d / "coverage_matrix.json").write_text("not-json", encoding="utf-8")
    (s1d / "critical_path_top20.json").write_text("[]", encoding="utf-8")
    (s1d / "enrichment_plan.json").write_text("[]", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        _validate_reconciliation_contract(repo, sprint1c_doc, sprint1d_doc)
