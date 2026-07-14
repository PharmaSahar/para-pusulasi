from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.studio_analytics_learning_bridge import (  # noqa: E402
    CANONICAL_ANALYTICS_PATH,
    IMPORT_MANIFEST_PATH,
    compute_coverage,
    load_canonical_records,
    load_import_manifest,
    run_phase4b_local_assessment,
)


def discover_studio_exports(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".csv", ".tsv", ".zip"}:
            continue
        rel = str(p.relative_to(root)).lower()
        if ".venv" in rel or "site-packages" in rel:
            continue
        if "channels_tracker.csv" in rel or "client_secrets" in rel:
            continue
        out.append(p)
    return sorted(out)


def run_assessment(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    root = PROJECT_ROOT

    studio_files = discover_studio_exports(root)
    result = run_phase4b_local_assessment(
        studio_files=studio_files,
        channel_performance_path=root / "logs/channel_performance.jsonl",
        runtime_dir=root / "output/runtime/evidence",
        ownership_dir=root / "output/state/content_ownership",
        manifest_path=root / IMPORT_MANIFEST_PATH,
        canonical_store_path=root / CANONICAL_ANALYTICS_PATH,
    )

    manifest_rows, manifest_malformed = load_import_manifest(path=root / IMPORT_MANIFEST_PATH)
    canonical_rows, canonical_malformed = load_canonical_records(path=root / CANONICAL_ANALYTICS_PATH)

    coverage = compute_coverage(canonical_rows)
    coverage["files_discovered"] = len(studio_files)
    coverage["files_imported"] = sum(1 for item in manifest_rows if str(item.get("provider")) == "StudioExportProvider")
    coverage["duplicate_rows"] = int(sum(int(item.get("duplicate_rows", 0) or 0) for item in manifest_rows))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "studio_export_files": [str(p.relative_to(root)) for p in studio_files],
        "imports": result["summary"].get("imports"),
        "format_inventory": result["summary"].get("format_inventory"),
        "coverage": coverage,
        "signal_count": result["summary"].get("signal_count", 0),
        "signal_counts": result["summary"].get("signal_counts", {}),
        "recommendation_count": result["summary"].get("recommendation_count", 0),
        "review_payload_count": result["summary"].get("review_payload_count", 0),
        "provider_priority": result["summary"].get("provider_priority"),
        "future_official_provider": result["summary"].get("future_official_provider"),
        "manifest_rows": len(manifest_rows),
        "manifest_malformed": manifest_malformed,
        "canonical_rows": len(canonical_rows),
        "canonical_malformed": canonical_malformed,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    (output_dir / "assessment_summary.json").write_text(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    (output_dir / "coverage_report.json").write_text(json.dumps(coverage, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
    (output_dir / "signals_report.json").write_text(
        json.dumps(
            {
                "signal_count": result["summary"].get("signal_count", 0),
                "signal_counts": result["summary"].get("signal_counts", {}),
                "recommendation_count": result["summary"].get("recommendation_count", 0),
                "review_payload_count": result["summary"].get("review_payload_count", 0),
                "advisory_only": True,
                "pipeline_output_changed": False,
            },
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "provider_handoff_report.json").write_text(
        json.dumps(
            {
                "provider_priority": result["summary"].get("provider_priority"),
                "future_official_provider": result["summary"].get("future_official_provider"),
                "api_calls_made": False,
                "oauth_implemented": False,
                "advisory_only": True,
                "pipeline_output_changed": False,
            },
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    return summary


def main() -> None:
    out_dir = PROJECT_ROOT / "artifacts/latest/project002_sprint1e_phase4b_studio_export_learning"
    summary = run_assessment(out_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
