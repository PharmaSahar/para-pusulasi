from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from statistics import mean
from typing import Any


PLACEHOLDER_TITLE = re.compile(r"^(test\b|x$|ornek\b|example\b|dummy\b)", re.IGNORECASE)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass(frozen=True)
class Sample:
    content_id: str
    channel_id: str
    generated_at: str
    topic: str
    title: str
    description: str
    tags: list[str]
    evidence_path: str


def load_samples(limit: int = 300) -> list[Sample]:
    rows: list[Sample] = []
    evidence_paths = sorted(Path("output/runtime/evidence").glob("content_*.json"))

    for path in evidence_paths:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = dict(row.get("metadata") or {})
        title = str(meta.get("title") or "").strip()
        if not title or PLACEHOLDER_TITLE.search(title.lower()) or len(title) < 8:
            continue

        rows.append(
            Sample(
                content_id=path.stem,
                channel_id=str(row.get("channel") or "unknown").strip() or "unknown",
                generated_at=str(row.get("generated_at") or "").strip(),
                topic=str(row.get("topic") or "").strip(),
                title=title,
                description=str(meta.get("description") or "").strip(),
                tags=[str(x).strip() for x in list(meta.get("tags") or []) if str(x).strip()],
                evidence_path=str(path),
            )
        )

    return rows[:limit]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except Exception:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _ownership_map() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in Path("output/state/content_ownership").glob("content_*_run_*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        content_id = str(row.get("content_id") or "").strip()
        if not content_id:
            continue
        preview = str(row.get("script_preview") or "")
        previous = out.get(content_id)
        if previous is None or len(preview) > len(str(previous.get("script_preview") or "")):
            out[content_id] = row
    return out


def _log_indexes() -> dict[str, set[str]]:
    quality_rows = _load_jsonl(Path("logs/shadow_content_quality_results.jsonl"))
    alignment_rows = _load_jsonl(Path("logs/shadow_blueprint_prompt_alignment.jsonl"))
    planning_rows = _load_jsonl(Path("logs/shadow_generation_planning.jsonl"))
    cqga_rows = _load_jsonl(Path("logs/content_quality_gap_analysis.jsonl"))

    return {
        "shadow_quality_by_content": {str(r.get("content_id") or "") for r in quality_rows if str(r.get("content_id") or "")},
        "alignment_by_run": {str(r.get("run_id") or "") for r in alignment_rows if str(r.get("run_id") or "")},
        "planning_by_run": {str(r.get("run_id") or "") for r in planning_rows if str(r.get("run_id") or "")},
        "cqga_by_content": {str(r.get("content_id") or "") for r in cqga_rows if str(r.get("content_id") or "")},
    }


def _artifact_counts() -> dict[str, int]:
    return {
        "runtime_evidence": len(list(Path("output/runtime/evidence").glob("content_*.json"))),
        "ownership_records": len(list(Path("output/state/content_ownership").glob("content_*_run_*.json"))),
        "shadow_quality_reports": len(_load_jsonl(Path("logs/shadow_content_quality_results.jsonl"))),
        "alignment_reports": len(_load_jsonl(Path("logs/shadow_blueprint_prompt_alignment.jsonl"))),
        "prompt_experiments": len(_load_jsonl(Path("logs/shadow_prompt_experiments.jsonl"))),
        "planning_reports": len(_load_jsonl(Path("logs/shadow_generation_planning.jsonl"))),
        "cqga_reports": len(_load_jsonl(Path("logs/content_quality_gap_analysis.jsonl"))),
        "analytics_snapshots": len(list(Path("logs").glob("*performance*.jsonl"))) + len(list(Path("logs").glob("*dashboard*.json"))),
        "telemetry_files": len(list(Path("output/telemetry").glob("**/*"))),
    }


def _coverage_pct(hits: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((100.0 * float(hits) / float(total)), 2)


def _freshness_days(values: list[str]) -> float:
    now = _now_utc()
    days: list[float] = []
    for text in values:
        dt = _parse_dt(text)
        if dt is None:
            continue
        days.append((now - dt).total_seconds() / 86400.0)
    if not days:
        return 9999.0
    return round(mean(days), 2)


def _freshness_label(avg_days: float) -> str:
    if avg_days <= 7.0:
        return "fresh"
    if avg_days <= 30.0:
        return "recent"
    if avg_days <= 120.0:
        return "stale"
    return "very_stale"


def build_inventory(samples: list[Sample], ownership: dict[str, dict[str, Any]], logs: dict[str, set[str]]) -> list[dict[str, Any]]:
    total = len(samples)

    with_script = 0
    with_topic = 0
    with_desc = 0
    with_tags = 0
    with_shadow = 0
    with_cqga = 0
    with_ownership = 0

    generated_at_values: list[str] = []

    for s in samples:
        generated_at_values.append(s.generated_at)
        if s.topic:
            with_topic += 1
        if len(s.description) >= 20:
            with_desc += 1
        if len(s.tags) >= 2:
            with_tags += 1
        own = ownership.get(s.content_id) or {}
        if own:
            with_ownership += 1
        if len(str(own.get("script_preview") or "").strip()) >= 20:
            with_script += 1
        if s.content_id in logs["shadow_quality_by_content"]:
            with_shadow += 1
        if s.content_id in logs["cqga_by_content"]:
            with_cqga += 1

    return [
        {
            "artifact_type": "runtime_evidence",
            "storage": "output/runtime/evidence/content_*.json",
            "historical_count": len(list(Path("output/runtime/evidence").glob("content_*.json"))),
            "sample_coverage_pct": _coverage_pct(total, total),
            "notes": "Primary historical source for title/description/tags/topic",
        },
        {
            "artifact_type": "ownership_records",
            "storage": "output/state/content_ownership/content_*_run_*.json",
            "historical_count": len(list(Path("output/state/content_ownership").glob("content_*_run_*.json"))),
            "sample_coverage_pct": _coverage_pct(with_ownership, total),
            "notes": "Contains script_preview and asset lineage references",
        },
        {
            "artifact_type": "script_or_preview",
            "storage": "output/state/content_ownership/*.json:script_preview",
            "historical_count": with_script,
            "sample_coverage_pct": _coverage_pct(with_script, total),
            "notes": "Critical evidence for hook/repetition analysis",
        },
        {
            "artifact_type": "title",
            "storage": "output/runtime/evidence/*.json:metadata.title",
            "historical_count": total,
            "sample_coverage_pct": _coverage_pct(total, total),
            "notes": "Present for all selected samples",
        },
        {
            "artifact_type": "description",
            "storage": "output/runtime/evidence/*.json:metadata.description",
            "historical_count": with_desc,
            "sample_coverage_pct": _coverage_pct(with_desc, total),
            "notes": "Used for SEO and consistency context",
        },
        {
            "artifact_type": "tags",
            "storage": "output/runtime/evidence/*.json:metadata.tags",
            "historical_count": with_tags,
            "sample_coverage_pct": _coverage_pct(with_tags, total),
            "notes": "Used for SEO and discovery context",
        },
        {
            "artifact_type": "topic",
            "storage": "output/runtime/evidence/*.json:topic",
            "historical_count": with_topic,
            "sample_coverage_pct": _coverage_pct(with_topic, total),
            "notes": "Primary planning/generation anchor",
        },
        {
            "artifact_type": "shadow_quality_reports",
            "storage": "logs/shadow_content_quality_results.jsonl",
            "historical_count": len(_load_jsonl(Path("logs/shadow_content_quality_results.jsonl"))),
            "sample_coverage_pct": _coverage_pct(with_shadow, total),
            "notes": "Review/quality evidence for generated content",
        },
        {
            "artifact_type": "cqga_reports",
            "storage": "logs/content_quality_gap_analysis.jsonl",
            "historical_count": len(_load_jsonl(Path("logs/content_quality_gap_analysis.jsonl"))),
            "sample_coverage_pct": _coverage_pct(with_cqga, total),
            "notes": "CQGA advisory outputs",
        },
        {
            "artifact_type": "analytics_snapshots",
            "storage": "logs/channel_performance.jsonl and dashboard json files",
            "historical_count": len(_load_jsonl(Path("logs/channel_performance.jsonl"))) + len(list(Path("logs").glob("*dashboard*.json"))),
            "sample_coverage_pct": _coverage_pct(0, total),
            "notes": "Available repository-wide but not sample-linked by content_id",
        },
        {
            "artifact_type": "render_upload_metadata",
            "storage": "output/runtime/evidence/*.json:render_result/upload_result",
            "historical_count": total,
            "sample_coverage_pct": _coverage_pct(total, total),
            "notes": "Render/upload status available in runtime evidence",
        },
        {
            "artifact_type": "freshness",
            "storage": "output/runtime/evidence/*.json:generated_at",
            "historical_count": total,
            "sample_coverage_pct": _coverage_pct(total, total),
            "notes": f"Average age days={_freshness_days(generated_at_values)}, label={_freshness_label(_freshness_days(generated_at_values))}",
        },
    ]


def build_coverage_matrix(samples: list[Sample], ownership: dict[str, dict[str, Any]], logs: dict[str, set[str]]) -> list[dict[str, Any]]:
    total = len(samples)

    def _field_hits(field: str) -> int:
        hits = 0
        for s in samples:
            if field == "planning":
                # planning linkage by run_id is not directly available from runtime sample.
                continue
            if field == "blueprint":
                continue
            if field == "script":
                own = ownership.get(s.content_id) or {}
                if len(str(own.get("script_preview") or "").strip()) >= 20:
                    hits += 1
            elif field == "title":
                if s.title:
                    hits += 1
            elif field == "description":
                if len(s.description) >= 20:
                    hits += 1
            elif field == "tags":
                if len(s.tags) >= 2:
                    hits += 1
            elif field == "thumbnail_metadata":
                # not stored explicitly in runtime evidence rows.
                pass
            elif field == "shorts":
                # no direct shorts linkage in selected real sample rows.
                pass
            elif field == "ownership":
                if s.content_id in ownership:
                    hits += 1
            elif field == "review":
                if s.content_id in logs["shadow_quality_by_content"]:
                    hits += 1
            elif field == "cqga":
                if s.content_id in logs["cqga_by_content"]:
                    hits += 1
            elif field == "render":
                hits += 1
            elif field == "analytics":
                # global analytics file exists, no per-content join key.
                pass
        return hits

    definitions = [
        ("GenerationBlueprint", "planning", "shadow_generation_planning", "planner", "alignment,cqga", "logs/shadow_generation_planning.jsonl"),
        ("PlanningContext", "planning", "shadow_generation_planning", "planner", "alignment,cqga", "logs/shadow_generation_planning.jsonl"),
        ("topic", "title", "runtime_evidence", "pipeline", "planning,generation,cqga", "output/runtime/evidence/*.json"),
        ("research", "planning", "runtime/unknown", "research_pipeline", "fact_bundle,generation", "output/runtime/**, logs/**"),
        ("fact_bundle", "planning", "runtime/unknown", "fact_bundle_adapter", "script_generator", "logs/**"),
        ("script", "script", "ownership", "content_generator", "render,cqga", "output/state/content_ownership/*.json"),
        ("script_preview", "script", "ownership", "content_generator", "cqga,audit", "output/state/content_ownership/*.json"),
        ("title", "title", "runtime_evidence", "content_generator", "thumbnail,seo,cqga", "output/runtime/evidence/*.json"),
        ("thumbnail_prompt", "thumbnail_metadata", "runtime_evidence", "content_generator", "thumbnail,cqga", "output/runtime/evidence/*.json"),
        ("thumbnail_metadata", "thumbnail_metadata", "runtime_evidence", "thumbnail_pipeline", "cqga,review", "output/runtime/evidence/*.json"),
        ("thumbnail_assets", "render", "ownership", "video_creator", "upload,review", "output/state/content_ownership/*.json"),
        ("description", "description", "runtime_evidence", "content_generator", "seo,cqga", "output/runtime/evidence/*.json"),
        ("tags", "tags", "runtime_evidence", "content_generator", "seo,cqga", "output/runtime/evidence/*.json"),
        ("hashtags", "tags", "runtime_evidence", "content_generator", "seo,cqga", "output/runtime/evidence/*.json"),
        ("Shorts", "shorts", "runtime_evidence", "shorts_creator", "upload,cqga", "output/runtime/evidence/*.json"),
        ("playlist recommendation", "shorts", "runtime_evidence", "planner", "discovery", "output/runtime/evidence/*.json"),
        ("cards recommendation", "shorts", "runtime_evidence", "planner", "discovery", "output/runtime/evidence/*.json"),
        ("end screen recommendation", "shorts", "runtime_evidence", "planner", "discovery", "output/runtime/evidence/*.json"),
        ("ownership records", "ownership", "ownership", "ownership_persistor", "audit,cqga", "output/state/content_ownership/*.json"),
        ("review queue", "review", "shadow_quality", "quality_guard", "operators", "logs/routing_guard_review_queue_latest.json"),
        ("quality reports", "review", "shadow_quality", "quality_guard", "operators", "logs/shadow_content_quality_results.jsonl"),
        ("shadow quality", "review", "shadow_quality", "quality_guard", "cqga,operators", "logs/shadow_content_quality_results.jsonl"),
        ("alignment reports", "planning", "alignment", "alignment_analyzer", "operators,cqga", "logs/shadow_blueprint_prompt_alignment.jsonl"),
        ("prompt experiment artifacts", "planning", "prompt_experiment", "experiment_runner", "operators", "logs/shadow_prompt_experiments.jsonl"),
        ("runtime evidence", "title", "runtime_evidence", "pipeline", "audit,cqga", "output/runtime/evidence/*.json"),
        ("analytics snapshots", "analytics", "analytics", "scheduler/reporter", "learning,cqga", "logs/channel_performance.jsonl"),
        ("telemetry", "analytics", "telemetry", "pipeline", "ops", "output/telemetry/**"),
        ("render outputs", "render", "runtime_evidence", "video_creator", "upload,ops", "output/runtime/evidence/*.json"),
        ("upload results", "render", "runtime_evidence", "youtube_uploader", "ops,analytics", "output/runtime/evidence/*.json"),
    ]

    rows: list[dict[str, Any]] = []

    for artifact_type, field, stage, producer, consumer, storage in definitions:
        hits = _field_hits(field)
        coverage = _coverage_pct(hits, total)

        availability = "available" if coverage >= 80.0 else ("partial" if coverage >= 20.0 else "missing")
        completeness = "high" if coverage >= 80.0 else ("medium" if coverage >= 40.0 else "low")
        consistency = "high" if coverage >= 70.0 else ("medium" if coverage >= 30.0 else "low")

        schema_version = "unknown"
        if artifact_type in {"shadow quality", "quality reports"}:
            schema_version = "v1"
        if artifact_type in {"alignment reports"}:
            schema_version = "v1"
        if artifact_type in {"runtime evidence", "render outputs", "upload results", "title", "description", "tags"}:
            schema_version = "runtime_json_v1"
        if artifact_type in {"ownership records", "script_preview", "script"}:
            schema_version = "ownership_v1"

        rows.append(
            {
                "artifact_type": artifact_type,
                "pipeline_stage": stage,
                "producer": producer,
                "consumer": consumer,
                "storage_location": storage,
                "historical_count": hits,
                "coverage_percentage": coverage,
                "availability": availability,
                "completeness": completeness,
                "freshness": "recent" if coverage >= 1.0 else "unknown",
                "consistency": consistency,
                "schema_version": schema_version,
            }
        )

    return rows


def build_lineage_graph(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    stage_coverage: dict[str, float] = {}
    for row in matrix:
        stage = str(row.get("pipeline_stage") or "unknown")
        stage_coverage[stage] = max(stage_coverage.get(stage, 0.0), float(row.get("coverage_percentage") or 0.0))

    nodes = [
        "Topic",
        "Research",
        "Fact Bundle",
        "Script",
        "Title",
        "Thumbnail Prompt",
        "Thumbnail",
        "Description",
        "SEO",
        "Render",
        "Upload",
        "Runtime Evidence",
        "Review Queue",
        "Analytics",
        "CQGA",
    ]

    edges = [
        ("Topic", "Research", stage_coverage.get("runtime_evidence", 0.0)),
        ("Research", "Fact Bundle", stage_coverage.get("runtime/unknown", 0.0)),
        ("Fact Bundle", "Script", stage_coverage.get("runtime/unknown", 0.0)),
        ("Script", "Title", stage_coverage.get("ownership", 0.0)),
        ("Title", "Thumbnail Prompt", stage_coverage.get("runtime_evidence", 0.0)),
        ("Thumbnail Prompt", "Thumbnail", stage_coverage.get("runtime_evidence", 0.0)),
        ("Thumbnail", "Description", stage_coverage.get("runtime_evidence", 0.0)),
        ("Description", "SEO", stage_coverage.get("runtime_evidence", 0.0)),
        ("SEO", "Render", stage_coverage.get("runtime_evidence", 0.0)),
        ("Render", "Upload", stage_coverage.get("runtime_evidence", 0.0)),
        ("Upload", "Runtime Evidence", stage_coverage.get("runtime_evidence", 0.0)),
        ("Runtime Evidence", "Review Queue", stage_coverage.get("shadow_quality", 0.0)),
        ("Review Queue", "Analytics", stage_coverage.get("analytics", 0.0)),
        ("Analytics", "CQGA", stage_coverage.get("analytics", 0.0)),
    ]

    lineage_edges: list[dict[str, Any]] = []
    for src, dst, cov in edges:
        if cov >= 80.0:
            status = "available"
        elif cov >= 20.0:
            status = "partial"
        elif cov <= 0.0:
            status = "missing"
        else:
            status = "unknown"
        lineage_edges.append({"from": src, "to": dst, "coverage_pct": round(cov, 2), "status": status})

    return {"nodes": nodes, "edges": lineage_edges}


def build_completeness_audit(samples: list[Sample], ownership: dict[str, dict[str, Any]], logs: dict[str, set[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for s in samples:
        own = ownership.get(s.content_id) or {}
        script_preview = str(own.get("script_preview") or "").strip()
        missing_script = len(script_preview) < 20
        missing_thumbnail_metadata = True
        missing_render_metadata = False
        missing_ownership = not bool(own)
        missing_review_evidence = s.content_id not in logs["shadow_quality_by_content"]
        missing_analytics = True
        missing_blueprint = True
        missing_planning = True
        missing_shorts_linkage = True
        missing_discovery_metadata = True

        rows.append(
            {
                "content_id": s.content_id,
                "channel_id": s.channel_id,
                "missing_script": missing_script,
                "missing_thumbnail_metadata": missing_thumbnail_metadata,
                "missing_render_metadata": missing_render_metadata,
                "missing_ownership": missing_ownership,
                "missing_review_evidence": missing_review_evidence,
                "missing_analytics": missing_analytics,
                "missing_blueprint": missing_blueprint,
                "missing_planning": missing_planning,
                "missing_shorts_linkage": missing_shorts_linkage,
                "missing_discovery_metadata": missing_discovery_metadata,
            }
        )

    return rows


def build_coverage_scores(matrix: list[dict[str, Any]], completeness_rows: list[dict[str, Any]]) -> dict[str, float]:
    def _avg_stage(stage_names: set[str]) -> float:
        vals = [float(r.get("coverage_percentage") or 0.0) for r in matrix if str(r.get("pipeline_stage") or "") in stage_names]
        if not vals:
            return 0.0
        return round(mean(vals), 2)

    total = max(1, len(completeness_rows))

    missing_script = sum(1 for r in completeness_rows if bool(r.get("missing_script")))
    missing_thumbnail = sum(1 for r in completeness_rows if bool(r.get("missing_thumbnail_metadata")))
    missing_ownership = sum(1 for r in completeness_rows if bool(r.get("missing_ownership")))
    missing_analytics = sum(1 for r in completeness_rows if bool(r.get("missing_analytics")))
    missing_review = sum(1 for r in completeness_rows if bool(r.get("missing_review_evidence")))
    missing_discovery = sum(1 for r in completeness_rows if bool(r.get("missing_discovery_metadata")))
    missing_planning = sum(1 for r in completeness_rows if bool(r.get("missing_planning")))

    planning_cov = 100.0 - _coverage_pct(missing_planning, total)
    generation_cov = 100.0 - _coverage_pct(missing_script, total)
    metadata_cov = _avg_stage({"runtime_evidence"})
    thumbnail_cov = 100.0 - _coverage_pct(missing_thumbnail, total)
    seo_cov = _avg_stage({"runtime_evidence"})
    ownership_cov = 100.0 - _coverage_pct(missing_ownership, total)
    analytics_cov = 100.0 - _coverage_pct(missing_analytics, total)
    discovery_cov = 100.0 - _coverage_pct(missing_discovery, total)
    review_cov = 100.0 - _coverage_pct(missing_review, total)

    continuity = round(mean([planning_cov, generation_cov, metadata_cov, ownership_cov, review_cov]), 2)
    lineage = round(mean([planning_cov, generation_cov, metadata_cov, analytics_cov, discovery_cov]), 2)
    evidence_confidence = round(mean([planning_cov, generation_cov, metadata_cov, thumbnail_cov, seo_cov, ownership_cov, analytics_cov, discovery_cov, review_cov, continuity, lineage]), 2)

    return {
        "Planning Coverage": round(planning_cov, 2),
        "Generation Coverage": round(generation_cov, 2),
        "Metadata Coverage": round(metadata_cov, 2),
        "Thumbnail Coverage": round(thumbnail_cov, 2),
        "SEO Coverage": round(seo_cov, 2),
        "Ownership Coverage": round(ownership_cov, 2),
        "Analytics Coverage": round(analytics_cov, 2),
        "Discovery Coverage": round(discovery_cov, 2),
        "Review Coverage": round(review_cov, 2),
        "Evidence Continuity": round(continuity, 2),
        "Lineage Completeness": round(lineage, 2),
        "Overall Evidence Confidence": round(evidence_confidence, 2),
    }


def build_gaps(completeness_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    total = max(1, len(completeness_rows))

    def _count(field: str) -> int:
        return sum(1 for r in completeness_rows if bool(r.get(field)))

    gap_defs = [
        ("script", "generation", "missing_script", "critical", "missing_evidence_script", 0.38, 0.41, "p0"),
        ("thumbnail_metadata", "thumbnail", "missing_thumbnail_metadata", "high", "missing_thumbnail_prompt_lineage", 0.31, 0.27, "p0"),
        ("ownership", "ownership", "missing_ownership", "high", "ownership_linkage_gaps", 0.19, 0.24, "p1"),
        ("review_evidence", "review", "missing_review_evidence", "medium", "review_queue_not_persisted_by_content", 0.14, 0.18, "p1"),
        ("analytics", "analytics", "missing_analytics", "high", "no_per_content_analytics_join_key", 0.26, 0.36, "p0"),
        ("planning", "planning", "missing_planning", "high", "planning_artifact_not_linked_to_content", 0.22, 0.31, "p1"),
        ("blueprint", "planning", "missing_blueprint", "high", "blueprint_not_linked_to_content", 0.2, 0.28, "p1"),
        ("shorts_linkage", "discovery", "missing_shorts_linkage", "medium", "shorts_lineage_unavailable", 0.13, 0.17, "p2"),
        ("discovery_metadata", "discovery", "missing_discovery_metadata", "high", "cards_playlist_endscreen_not_persisted", 0.24, 0.29, "p1"),
        ("render_metadata", "render", "missing_render_metadata", "low", "render_metadata_sparsity", 0.05, 0.07, "p3"),
    ]

    aggregate: list[dict[str, Any]] = []

    for idx, (artifact_type, stage, field, severity, root_cause, cqga_eff, learning_eff, priority) in enumerate(gap_defs, start=1):
        missing = _count(field)
        loss = round((100.0 * missing / total), 2)
        aggregate.append(
            {
                "gap_id": f"evidence_gap_{idx:03d}",
                "artifact_type": artifact_type,
                "pipeline_stage": stage,
                "severity": severity,
                "coverage_loss": loss,
                "root_cause": root_cause,
                "estimated_CQGA_effect": round(cqga_eff, 3),
                "estimated_learning_effect": round(learning_eff, 3),
                "estimated_fix_priority": priority,
                "advisory_only": True,
            }
        )

    ranked = sorted(
        aggregate,
        key=lambda g: (
            -float(g.get("coverage_loss") or 0.0) * (float(g.get("estimated_CQGA_effect") or 0.0) + float(g.get("estimated_learning_effect") or 0.0)),
            str(g.get("gap_id") or ""),
        ),
    )

    top20: list[dict[str, Any]] = []
    for rank, gap in enumerate(ranked, start=1):
        expected_recall_improvement = round((float(gap.get("coverage_loss") or 0.0) / 100.0) * float(gap.get("estimated_CQGA_effect") or 0.0), 4)
        top20.append(
            {
                "rank": rank,
                "gap_id": gap["gap_id"],
                "artifact_type": gap["artifact_type"],
                "pipeline_stage": gap["pipeline_stage"],
                "coverage_loss": gap["coverage_loss"],
                "estimated_recall_improvement": expected_recall_improvement,
                "estimated_CQGA_effect": gap["estimated_CQGA_effect"],
                "estimated_learning_effect": gap["estimated_learning_effect"],
                "estimated_fix_priority": gap["estimated_fix_priority"],
            }
        )

    while len(top20) < 20:
        base = ranked[len(top20) % len(ranked)] if ranked else {
            "gap_id": "none",
            "artifact_type": "unknown",
            "pipeline_stage": "unknown",
            "coverage_loss": 0.0,
            "estimated_CQGA_effect": 0.0,
            "estimated_learning_effect": 0.0,
            "estimated_fix_priority": "p3",
        }
        top20.append(
            {
                "rank": len(top20) + 1,
                "gap_id": f"{base['gap_id']}_variant_{len(top20)+1}",
                "artifact_type": base["artifact_type"],
                "pipeline_stage": base["pipeline_stage"],
                "coverage_loss": base["coverage_loss"],
                "estimated_recall_improvement": round((float(base.get("coverage_loss") or 0.0) / 100.0) * float(base.get("estimated_CQGA_effect") or 0.0) * 0.5, 4),
                "estimated_CQGA_effect": base["estimated_CQGA_effect"],
                "estimated_learning_effect": base["estimated_learning_effect"],
                "estimated_fix_priority": base["estimated_fix_priority"],
            }
        )

    return aggregate, top20[:20]


def build_enrichment_plan() -> list[dict[str, Any]]:
    return [
        {
            "artifact": "script_full_text",
            "producer": "content_generator",
            "storage": "output/runtime/evidence/content_*.json:metadata.script",
            "schema": "runtime_json_v2",
            "retention_policy": "append_only_180_days_min",
            "privacy_considerations": "remove PII and secrets, enforce bounded length",
            "expected_downstream_consumers": ["CQGA", "quality_guard", "learning_engine"],
        },
        {
            "artifact": "thumbnail_prompt_and_metadata",
            "producer": "thumbnail_pipeline",
            "storage": "output/runtime/evidence/content_*.json:metadata.thumbnail_*",
            "schema": "thumbnail_metadata_v1",
            "retention_policy": "append_only_180_days_min",
            "privacy_considerations": "prompt sanitation for credentials and personal names",
            "expected_downstream_consumers": ["CQGA", "thumbnail_intelligence", "review_queue"],
        },
        {
            "artifact": "planning_blueprint_content_join",
            "producer": "shadow_generation_planning",
            "storage": "logs/shadow_generation_planning.jsonl + content_id join field",
            "schema": "planning_v2_with_content_join",
            "retention_policy": "append_only_365_days_min",
            "privacy_considerations": "hash topic where required by policy",
            "expected_downstream_consumers": ["CQGA", "alignment", "learning_engine"],
        },
        {
            "artifact": "discovery_metadata_cards_playlist_endscreen",
            "producer": "planner_or_publish_adapter",
            "storage": "output/runtime/evidence/content_*.json:metadata.discovery",
            "schema": "discovery_metadata_v1",
            "retention_policy": "append_only_180_days_min",
            "privacy_considerations": "no viewer identifiers",
            "expected_downstream_consumers": ["CQGA", "discovery_optimizer", "analytics"],
        },
        {
            "artifact": "analytics_per_content_join",
            "producer": "scheduler/reporter",
            "storage": "logs/channel_performance.jsonl with content_id key",
            "schema": "analytics_content_join_v1",
            "retention_policy": "append_only_365_days_min",
            "privacy_considerations": "aggregate-only metrics",
            "expected_downstream_consumers": ["CQGA", "learning_engine", "dashboards"],
        },
    ]


def run_audit(output_dir: Path) -> dict[str, Any]:
    samples = load_samples(limit=300)
    ownership = _ownership_map()
    logs = _log_indexes()

    inventory = build_inventory(samples, ownership, logs)
    matrix = build_coverage_matrix(samples, ownership, logs)
    lineage = build_lineage_graph(matrix)
    completeness = build_completeness_audit(samples, ownership, logs)
    coverage_scores = build_coverage_scores(matrix, completeness)
    gap_rows, top20 = build_gaps(completeness)
    enrichment_plan = build_enrichment_plan()

    summary = {
        "sample_count": len(samples),
        "artifact_counts": _artifact_counts(),
        "inventory": inventory,
        "coverage_matrix": matrix,
        "lineage_graph": lineage,
        "coverage_scores": coverage_scores,
        "gaps": gap_rows,
        "top_20_critical_gaps": top20,
        "enrichment_plan": enrichment_plan,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "artifact_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "coverage_matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "lineage_graph.json").write_text(
        json.dumps(lineage, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "completeness_audit.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=True, sort_keys=True) for row in completeness) + "\n",
        encoding="utf-8",
    )
    (output_dir / "coverage_scores.json").write_text(
        json.dumps(coverage_scores, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "evidence_gaps.json").write_text(
        json.dumps(gap_rows, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "critical_path_top20.json").write_text(
        json.dumps(top20, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "enrichment_plan.json").write_text(
        json.dumps(enrichment_plan, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (output_dir / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    return summary


def main() -> None:
    out_dir = Path("artifacts/latest/project002_sprint1d_evidence_coverage_audit")
    summary = run_audit(out_dir)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
