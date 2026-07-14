from __future__ import annotations

import json
from pathlib import Path

from tools.project002_sprint1d_evidence_coverage_audit import run_audit


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> tuple[list[dict], int]:
    rows: list[dict] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            malformed += 1
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        else:
            malformed += 1
    return rows, malformed


def test_sprint1d_audit_outputs_contract(tmp_path: Path) -> None:
    output_dir = tmp_path / "audit"
    summary = run_audit(output_dir)

    assert summary["advisory_only"] is True
    assert summary["pipeline_output_changed"] is False
    assert int(summary["sample_count"]) <= 300

    sample_count = int(summary["sample_count"])

    matrix = list(summary.get("coverage_matrix") or [])
    assert len(matrix) >= 20

    scores = dict(summary.get("coverage_scores") or {})
    required_scores = {
        "Planning Coverage",
        "Generation Coverage",
        "Metadata Coverage",
        "Thumbnail Coverage",
        "SEO Coverage",
        "Ownership Coverage",
        "Analytics Coverage",
        "Discovery Coverage",
        "Review Coverage",
        "Evidence Continuity",
        "Lineage Completeness",
        "Overall Evidence Confidence",
    }
    assert required_scores.issubset(set(scores.keys()))
    assert all(0.0 <= float(v) <= 100.0 for v in scores.values())

    expected_files = {
        "artifact_inventory.json",
        "coverage_matrix.json",
        "lineage_graph.json",
        "completeness_audit.jsonl",
        "coverage_scores.json",
        "evidence_gaps.json",
        "critical_path_top20.json",
        "enrichment_plan.json",
        "audit_summary.json",
    }

    produced_files = {path.name for path in output_dir.glob("*") if path.is_file()}
    assert expected_files.issubset(produced_files)

    inventory = _read_json(output_dir / "artifact_inventory.json")
    coverage_matrix = _read_json(output_dir / "coverage_matrix.json")
    _ = _read_json(output_dir / "lineage_graph.json")
    completeness_rows, malformed_rows = _read_jsonl(output_dir / "completeness_audit.jsonl")
    _ = _read_json(output_dir / "coverage_scores.json")
    evidence_gaps = _read_json(output_dir / "evidence_gaps.json")
    critical = _read_json(output_dir / "critical_path_top20.json")
    enrichment = _read_json(output_dir / "enrichment_plan.json")
    persisted_summary = _read_json(output_dir / "audit_summary.json")

    assert malformed_rows == 0
    assert int(persisted_summary.get("sample_count") or 0) == sample_count

    if sample_count > 0:
        assert int(summary["sample_count"]) > 0
        assert len(critical) == 20
        for row in critical:
            assert row["rank"] >= 1
            assert "gap_id" in row
            assert "estimated_recall_improvement" in row
    else:
        artifact_counts = dict(summary.get("artifact_counts") or {})
        assert all(int(v) >= 0 for v in artifact_counts.values())
        assert len(inventory) > 0
        assert len(coverage_matrix) >= 20
        assert completeness_rows == []
        assert len(evidence_gaps) >= 1
        assert len(critical) == 20
        assert len(enrichment) >= 1

        # With zero samples, sample-derived percentages and recall improvements must remain zero.
        assert all(float(row.get("sample_coverage_pct") or 0.0) == 0.0 for row in inventory if isinstance(row, dict))
        assert all(float(row.get("coverage_percentage") or 0.0) == 0.0 for row in coverage_matrix if isinstance(row, dict))
        assert all(float(row.get("coverage_percentage") or 0.0) == 0.0 for row in completeness_rows if isinstance(row, dict))
        assert all(float(row.get("estimated_recall_improvement") or 0.0) == 0.0 for row in critical if isinstance(row, dict))
