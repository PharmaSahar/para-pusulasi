from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from src.historical_lineage_recovery import (
    build_historical_recovery,
    run_historical_recovery_dry_run,
)


def run_assessment(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    recovery_report = run_historical_recovery_dry_run(
        output_path=output_dir / "historical_recovery_report.json",
        limit=300,
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": dict(recovery_report.get("counts") or {}),
        "coverage_before": dict(recovery_report.get("coverage_before") or {}),
        "coverage_after": dict(recovery_report.get("coverage_after") or {}),
        "coverage_delta": dict(recovery_report.get("coverage_delta") or {}),
        "quality_audit": dict(recovery_report.get("quality_audit") or {}),
        "source_inventory": dict(recovery_report.get("source_inventory") or {}),
        "recovery_graph": dict(recovery_report.get("recovery_graph") or {}),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    recoverable = int(summary["counts"].get("recoverable", 0))
    unrecoverable = int(summary["counts"].get("unrecoverable", 0))
    ambiguous = int(summary["counts"].get("ambiguous", 0))
    total = int(summary["counts"].get("runtime_total", 0))
    summary["recovery_overview"] = {
        "runtime_total": total,
        "recoverable": recoverable,
        "unrecoverable": unrecoverable,
        "ambiguous": ambiguous,
        "deterministic_only": True,
        "non_guessing": True,
        "dry_run": True,
    }

    assessment_summary_path = output_dir / "assessment_summary.json"
    coverage_delta_path = output_dir / "coverage_delta.json"
    quality_audit_path = output_dir / "quality_audit.json"

    assessment_summary_path.write_text(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    coverage_delta_path.write_text(
        json.dumps(summary["coverage_delta"], ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    quality_audit_path.write_text(
        json.dumps(summary["quality_audit"], ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    return summary


def main() -> None:
    output_dir = Path("artifacts/latest/project002_sprint1e_phase2b_historical_lineage_recovery")
    summary = run_assessment(output_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
