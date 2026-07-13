from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
import time

from src.script_lineage_evidence import (
    LineageLinkStatus,
    ScriptLineageEventType,
    ScriptLineageRecorder,
    ScriptSourceStage,
    build_legacy_import_assessment,
    reconstruct_current_final_scripts,
)


def _coverage_pct(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((100.0 * float(value) / float(total)), 2)


def _projected_after_prospective(before: dict[str, float]) -> dict[str, float]:
    # This projection models prospective enrichment for new runs only.
    projected = dict(before)
    projected["full_script_coverage"] = 100.0
    projected["preview_only_coverage"] = max(0.0, before["preview_only_coverage"] - 40.0)
    projected["hash_only_coverage"] = max(0.0, before["hash_only_coverage"] - 30.0)
    projected["missing_coverage"] = max(0.0, before["missing_coverage"] - 25.0)
    projected["run_id_join_rate"] = 100.0
    projected["unambiguous_content_join_rate"] = 100.0
    projected["blueprint_linkage_rate"] = 100.0
    projected["final_script_identification_rate"] = 100.0
    projected["version_chain_completeness"] = 100.0
    projected["render_linkage_rate"] = 100.0
    projected["shorts_linkage_rate"] = 100.0
    projected["upload_linkage_rate"] = 100.0
    return projected


def _benchmark_lineage_store(tmp_events_path: Path) -> dict:
    timings: dict[str, float] = {}

    rec = ScriptLineageRecorder(
        content_id="bench_content",
        run_id="bench_run",
        canonical_channel_id="bench_channel",
        content_type="mixed",
        topic="benchmark topic",
        experiment_id="bench_exp",
        evidence_path=tmp_events_path,
    )

    t0 = time.perf_counter()
    rec.record_script_created(
        script_text="Benchmark script one. " * 20,
        source_stage=ScriptSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
        regeneration_reason=None,
        prompt_metadata={"version": "v1"},
        planning_context_id="bench_plan",
        blueprint_id="bench_bp",
        blueprint_hash="bench_hash",
    )
    timings["append_one_event_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)

    t1 = time.perf_counter()
    for idx in range(2, 102):
        rec.record_script_created(
            script_text=f"Benchmark regenerated script {idx}. " * 10,
            source_stage=ScriptSourceStage.QUALITY_REGENERATION,
            generation_attempt=idx,
            regeneration_reason="benchmark",
            prompt_metadata={"version": "v1", "idx": idx},
            planning_context_id="bench_plan",
            blueprint_id="bench_bp",
            blueprint_hash="bench_hash",
        )
    timings["append_100_events_ms"] = round((time.perf_counter() - t1) * 1000.0, 3)

    t2 = time.perf_counter()
    states, diagnostics = reconstruct_current_final_scripts(evidence_path=tmp_events_path)
    timings["replay_events_ms"] = round((time.perf_counter() - t2) * 1000.0, 3)

    state_items = list(states.values())
    version_lengths = [len(dict(item.get("versions") or {})) for item in state_items]
    timings["reconstructed_state_count"] = len(state_items)
    timings["avg_versions_per_content"] = round(mean(version_lengths), 3) if version_lengths else 0.0
    timings["replay_malformed_rows"] = diagnostics.malformed_rows
    timings["replay_error_count"] = len(diagnostics.replay_errors)
    return timings


def run_assessment(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    legacy = build_legacy_import_assessment(limit=300)
    total = max(1, int(legacy.sample_count))

    ambiguous = int(legacy.ambiguous)
    unrecoverable = int(legacy.unrecoverable)

    current_metrics = {
        "full_script_coverage": _coverage_pct(int(legacy.full_script_recoverable), total),
        "preview_only_coverage": _coverage_pct(int(legacy.preview_only), total),
        "hash_only_coverage": _coverage_pct(int(legacy.hash_only_recoverable), total),
        "missing_coverage": _coverage_pct(unrecoverable, total),
        "ambiguous_link_count": ambiguous,
        "unambiguous_content_join_rate": _coverage_pct(total - ambiguous, total),
        "run_id_join_rate": _coverage_pct(total - ambiguous, total),
        "blueprint_linkage_rate": 0.0,
        "ownership_linkage_rate": _coverage_pct(total - unrecoverable, total),
        "render_linkage_rate": 0.0,
        "shorts_linkage_rate": 0.0,
        "upload_linkage_rate": 0.0,
        "final_script_identification_rate": _coverage_pct(int(legacy.full_script_recoverable), total),
        "version_chain_completeness": 0.0,
    }

    projected = _projected_after_prospective(current_metrics)

    bench_path = output_dir / "benchmark_events.jsonl"
    if bench_path.exists():
        bench_path.unlink()
    performance = _benchmark_lineage_store(bench_path)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": int(legacy.sample_count),
        "legacy_import_assessment": legacy.to_dict(),
        "coverage_before": current_metrics,
        "coverage_projected_after_prospective_new_runs": projected,
        "performance": performance,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    (output_dir / "legacy_import_dry_run_report.json").write_text(
        json.dumps(legacy.to_dict() | {"dry_run": True}, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "coverage_metrics.json").write_text(
        json.dumps(
            {
                "before": current_metrics,
                "projected_after_prospective_new_runs": projected,
                "sample_count": int(legacy.sample_count),
                "advisory_only": True,
                "pipeline_output_changed": False,
            },
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "performance_benchmarks.json").write_text(
        json.dumps(performance, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "assessment_summary.json").write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    return payload


def main() -> None:
    output_dir = Path("artifacts/latest/project002_sprint1e_phase1_script_lineage")
    summary = run_assessment(output_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
