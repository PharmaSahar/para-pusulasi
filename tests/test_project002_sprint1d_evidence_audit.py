from __future__ import annotations

from pathlib import Path

from tools.project002_sprint1d_evidence_coverage_audit import run_audit


def test_sprint1d_audit_outputs_contract(tmp_path: Path) -> None:
    output_dir = tmp_path / "audit"
    summary = run_audit(output_dir)

    assert summary["advisory_only"] is True
    assert summary["pipeline_output_changed"] is False
    assert int(summary["sample_count"]) <= 300
    assert int(summary["sample_count"]) > 0

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

    critical = list(summary.get("top_20_critical_gaps") or [])
    assert len(critical) == 20
    for row in critical:
        assert row["rank"] >= 1
        assert "gap_id" in row
        assert "estimated_recall_improvement" in row

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
