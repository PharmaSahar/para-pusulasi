from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analytics_evidence_join import run_analytics_evidence_join_dry_run


def run_assessment(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    dry_run_path = output_dir / "analytics_evidence_join_dry_run.json"
    report = run_analytics_evidence_join_dry_run(output_path=dry_run_path, limit=500)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_inventory": dict(report.get("source_inventory") or {}),
        "counts": dict(report.get("counts") or {}),
        "coverage": dict(report.get("coverage") or {}),
        "replay_diagnostics": dict(report.get("replay_diagnostics") or {}),
        "cqga_impact_estimate": dict(report.get("cqga_impact_estimate") or {}),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    assessment_summary_path = output_dir / "assessment_summary.json"
    coverage_path = output_dir / "coverage_report.json"
    cqga_impact_path = output_dir / "cqga_impact_estimate.json"

    assessment_summary_path.write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    coverage_path.write_text(json.dumps(summary["coverage"], ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    cqga_impact_path.write_text(json.dumps(summary["cqga_impact_estimate"], ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")

    return summary


def main() -> None:
    output_dir = Path("artifacts/latest/project002_sprint1e_phase4_analytics_evidence_join")
    summary = run_assessment(output_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
