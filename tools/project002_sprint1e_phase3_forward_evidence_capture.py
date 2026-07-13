from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.forward_evidence_capture import (
    compute_forward_completeness_scores,
    reconstruct_forward_sessions,
    verify_forward_evidence_integrity,
)


def run_assessment(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    sessions, diagnostics = reconstruct_forward_sessions()
    integrity = verify_forward_evidence_integrity(sessions=sessions)
    completeness = compute_forward_completeness_scores(sessions=sessions)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_count": len(sessions),
        "diagnostics": {
            "malformed_rows": diagnostics.malformed_rows,
            "replay_errors": list(diagnostics.replay_errors),
        },
        "integrity": integrity,
        "completeness": completeness,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    summary_path = output_dir / "assessment_summary.json"
    integrity_path = output_dir / "integrity_report.json"
    completeness_path = output_dir / "completeness_report.json"

    summary_path.write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    integrity_path.write_text(json.dumps(integrity, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    completeness_path.write_text(json.dumps(completeness, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")

    return summary


def main() -> None:
    output_dir = Path("artifacts/latest/project002_sprint1e_phase3_forward_evidence_capture")
    summary = run_assessment(output_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
