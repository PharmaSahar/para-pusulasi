from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
import time

from src.planning_blueprint_lineage_evidence import (
    PlanningLineageRecorder,
    PlanningLineageSourceStage,
    build_historical_planning_lineage_assessment,
    build_identifier_audit,
    reconstruct_planning_lineage_state,
)


def _pct(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((100.0 * float(value) / float(total)), 2)


def _coverage(assessment: dict[str, int], total: int) -> dict[str, float]:
    linked = int(assessment.get("linked", 0))
    partial = int(assessment.get("partial", 0))
    missing = int(assessment.get("missing", 0))
    ambiguous = int(assessment.get("ambiguous", 0))
    invalid = int(assessment.get("invalid", 0))
    planning_linked = int(assessment.get("planning_linked", 0))
    blueprint_linked = int(assessment.get("blueprint_linked", 0))
    prompt_metadata_linked = int(assessment.get("prompt_metadata_linked", 0))
    fully_traceable = int(assessment.get("fully_traceable", 0))

    return {
        "planning_linkage_rate": _pct(planning_linked, total),
        "blueprint_linkage_rate": _pct(blueprint_linked, total),
        "prompt_metadata_linkage_rate": _pct(prompt_metadata_linked, total),
        "fully_traceable_content_rate": _pct(fully_traceable, total),
        "partial_traceability_rate": _pct(partial, total),
        "ambiguous_traceability_rate": _pct(ambiguous, total),
        "missing_traceability_rate": _pct(missing + invalid, total),
        "linked_status_rate": _pct(linked, total),
    }


def _cqga_qualitative_impact() -> dict[str, dict[str, str]]:
    return {
        "root_cause_analysis": {
            "impact": "HIGH",
            "reason": "Planning-to-script joins add deterministic upstream context for each future script.",
            "confidence": "MEDIUM",
        },
        "planning_consistency": {
            "impact": "HIGH",
            "reason": "Planning context and blueprint fields become explicit traceability inputs.",
            "confidence": "HIGH",
        },
        "blueprint_consistency": {
            "impact": "HIGH",
            "reason": "Blueprint identifiers and hashes can be compared across regeneration attempts.",
            "confidence": "HIGH",
        },
        "duplicate_detection": {
            "impact": "MEDIUM",
            "reason": "Deterministic prompt/script hashes improve duplicate and near-duplicate diagnostics.",
            "confidence": "MEDIUM",
        },
        "narrative_analysis": {
            "impact": "MEDIUM",
            "reason": "Lineage enables comparing narrative drift between planning and finalized script states.",
            "confidence": "MEDIUM",
        },
        "hook_analysis": {
            "impact": "MEDIUM",
            "reason": "Prompt metadata hash and blueprint linkage provide stronger hook provenance context.",
            "confidence": "MEDIUM",
        },
    }


def _benchmark(output_dir: Path) -> dict[str, float]:
    events_path = output_dir / "benchmark_planning_lineage.jsonl"
    if events_path.exists():
        events_path.unlink()

    recorder = PlanningLineageRecorder(
        content_id="bench_content",
        run_id="bench_run",
        experiment_id="bench_exp",
        evidence_path=events_path,
    )

    t0 = time.perf_counter()
    recorder.record_linkage(
        planning_context_id="bench_run",
        blueprint_id="bp_bench",
        blueprint_hash="bh_bench",
        prompt_metadata={"prompt_hash": "ph_bench"},
        script_text="benchmark script one",
        source_stage=PlanningLineageSourceStage.INITIAL_GENERATION,
        generation_attempt=1,
    )
    append_one = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    for idx in range(2, 102):
        recorder.record_linkage(
            planning_context_id="bench_run",
            blueprint_id="bp_bench",
            blueprint_hash="bh_bench",
            prompt_metadata={"prompt_hash": f"ph_{idx}"},
            script_text=f"benchmark script {idx}",
            source_stage=PlanningLineageSourceStage.QUALITY_REGENERATION,
            generation_attempt=idx,
        )
    append_hundred = (time.perf_counter() - t1) * 1000.0

    t2 = time.perf_counter()
    state, diagnostics = reconstruct_planning_lineage_state(evidence_path=events_path)
    replay = (time.perf_counter() - t2) * 1000.0

    script_counts = [len(list(item.get("script_hashes") or [])) for item in state.values()]
    return {
        "append_one_event_ms": round(append_one, 3),
        "append_100_events_ms": round(append_hundred, 3),
        "replay_events_ms": round(replay, 3),
        "reconstructed_state_count": len(state),
        "avg_script_hashes_per_content": round(mean(script_counts), 3) if script_counts else 0.0,
        "replay_malformed_rows": int(diagnostics.malformed_rows),
        "replay_error_count": len(list(diagnostics.replay_errors or [])),
    }


def run_assessment(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    identifier_audit = build_identifier_audit(limit=300).to_dict()
    historical = build_historical_planning_lineage_assessment(limit=300).to_dict()
    total = max(1, int(historical.get("sample_count", 0)))

    coverage = _coverage(historical, total)
    cqga_impact = _cqga_qualitative_impact()
    performance = _benchmark(output_dir)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identifier_audit": identifier_audit,
        "historical_assessment": historical,
        "coverage_metrics": coverage,
        "cqga_impact_estimate": cqga_impact,
        "performance": performance,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    (output_dir / "identifier_audit.json").write_text(
        json.dumps(identifier_audit, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "historical_linkage_dry_run_report.json").write_text(
        json.dumps(historical | {"dry_run": True}, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "coverage_metrics.json").write_text(
        json.dumps(coverage, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "cqga_impact_estimate.json").write_text(
        json.dumps(cqga_impact, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "performance_benchmarks.json").write_text(
        json.dumps(performance, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "assessment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    return summary


def main() -> None:
    output_dir = Path("artifacts/latest/project002_sprint1e_phase2_planning_blueprint_linkage")
    summary = run_assessment(output_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
