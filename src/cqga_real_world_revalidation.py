from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .content_quality_gap_analyzer import QualityAnalysisInput, analyze_content_quality_gaps


REVALIDATION_SCHEMA_VERSION = "v1"
DEFAULT_RUNTIME_EVIDENCE_DIR = Path("output/runtime/evidence")
DEFAULT_OWNERSHIP_DIR = Path("output/state/content_ownership")
DEFAULT_CQGA_STORAGE_PATH = Path("logs/content_quality_gap_analysis.jsonl")
DEFAULT_CANONICAL_ANALYTICS_PATH = Path("logs/canonical_content_analytics.jsonl")
DEFAULT_PLANNING_LINEAGE_PATH = Path("logs/planning_blueprint_lineage_evidence.jsonl")
DEFAULT_SCRIPT_LINEAGE_PATH = Path("logs/script_lineage_evidence.jsonl")
DEFAULT_FORWARD_EVIDENCE_PATH = Path("logs/forward_evidence_capture.jsonl")
DEFAULT_THUMBNAIL_LINEAGE_PATH = Path("logs/thumbnail_metadata_lineage.jsonl")
DEFAULT_OUTPUT_DIR = Path("artifacts/latest/project002_sprint1f_cqga_real_world_revalidation")


REQUIRED_RECONSTRUCTION_FIELDS = (
    "title",
    "thumbnail_prompt",
    "thumbnail_metadata",
    "script",
    "description",
    "hashtags",
    "tags",
    "playlist",
    "cards",
    "end_screen",
    "analytics",
    "ownership",
    "channel_profile",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sha_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(decoded, dict):
            return decoded
    except Exception:
        pass
    return {}


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
            else:
                malformed += 1
        except Exception:
            malformed += 1
    return rows, malformed


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _content_type_from_runtime(runtime_row: dict[str, Any]) -> str:
    raw = _safe_text(runtime_row.get("content_type") or runtime_row.get("type") or runtime_row.get("format")).lower()
    if raw in {"short", "shorts"}:
        return "short"
    if raw in {"video", "long", "long_form"}:
        return "video"
    short_url = _safe_text(((runtime_row.get("upload_result") or {}) if isinstance(runtime_row.get("upload_result"), dict) else {}).get("short_url"))
    if short_url:
        return "short"
    return "mixed"


def _empty_analytics() -> dict[str, Any]:
    return {
        "impressions": None,
        "click_through_rate": None,
        "average_view_duration_seconds": None,
        "average_view_percentage": None,
        "watch_time_hours": None,
        "traffic_sources": None,
        "card_ctr": None,
        "end_screen_ctr": None,
        "playlist_additions": None,
    }


def _analytics_state_to_value(metrics: dict[str, Any], key: str) -> float | None:
    node = metrics.get(key)
    if not isinstance(node, dict):
        return None
    if _safe_text(node.get("state")) != "OBSERVED":
        return None
    return _to_number(node.get("value"))


def _extract_analytics_payload(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    payload = _empty_analytics()
    payload["impressions"] = _analytics_state_to_value(metrics, "impressions")
    payload["click_through_rate"] = _analytics_state_to_value(metrics, "click_through_rate")
    payload["average_view_duration_seconds"] = _analytics_state_to_value(metrics, "average_view_duration_seconds")
    payload["average_view_percentage"] = _analytics_state_to_value(metrics, "average_view_percentage")
    payload["watch_time_hours"] = _analytics_state_to_value(metrics, "watch_time_hours")
    payload["card_ctr"] = _analytics_state_to_value(metrics, "card_ctr")
    payload["end_screen_ctr"] = _analytics_state_to_value(metrics, "end_screen_ctr")
    payload["playlist_additions"] = _analytics_state_to_value(metrics, "playlist_additions")

    traffic = metrics.get("traffic_sources")
    if isinstance(traffic, dict) and _safe_text(traffic.get("state")) == "OBSERVED" and isinstance(traffic.get("value"), dict):
        payload["traffic_sources"] = dict(traffic.get("value") or {})
    else:
        payload["traffic_sources"] = None
    return payload


def build_evidence_completeness_matrix(
    *,
    repository_root: Path,
    runtime_rows: list[dict[str, Any]],
    ownership_rows: list[dict[str, Any]],
    analytics_rows: list[dict[str, Any]],
    planning_rows: list[dict[str, Any]],
    script_rows: list[dict[str, Any]],
    forward_rows: list[dict[str, Any]],
    thumbnail_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total_runtime = len(runtime_rows)

    def _count_runtime(predicate: Any) -> int:
        return sum(1 for row in runtime_rows if bool(predicate(row)))

    matrix = {
        "planning_lineage": {
            "path": str(repository_root / DEFAULT_PLANNING_LINEAGE_PATH),
            "available": len(planning_rows) > 0,
            "rows": len(planning_rows),
        },
        "blueprint_lineage": {
            "path": str(repository_root / DEFAULT_PLANNING_LINEAGE_PATH),
            "available": any(_safe_text(row.get("blueprint_id")) for row in planning_rows),
            "rows_with_blueprint_id": sum(1 for row in planning_rows if _safe_text(row.get("blueprint_id"))),
        },
        "prompt_metadata": {
            "path": str(repository_root / DEFAULT_RUNTIME_EVIDENCE_DIR),
            "available": _count_runtime(
                lambda row: _safe_text((((row.get("guard_scores") or {}) if isinstance(row.get("guard_scores"), dict) else {}).get("thumbnail_intelligence") or {}).get("thumbnail_prompt"))
            )
            > 0,
            "rows_with_prompt": _count_runtime(
                lambda row: _safe_text((((row.get("guard_scores") or {}) if isinstance(row.get("guard_scores"), dict) else {}).get("thumbnail_intelligence") or {}).get("thumbnail_prompt"))
            ),
            "total_runtime_rows": total_runtime,
        },
        "script_lineage": {
            "path": str(repository_root / DEFAULT_SCRIPT_LINEAGE_PATH),
            "available": len(script_rows) > 0,
            "rows": len(script_rows),
        },
        "thumbnail_metadata": {
            "path": str(repository_root / DEFAULT_THUMBNAIL_LINEAGE_PATH),
            "available": len(thumbnail_rows) > 0 or _count_runtime(lambda row: bool((row.get("metadata") or {}).get("title"))) > 0,
            "rows": len(thumbnail_rows),
        },
        "render_metadata": {
            "path": str(repository_root / DEFAULT_RUNTIME_EVIDENCE_DIR),
            "available": _count_runtime(lambda row: isinstance(row.get("render_result"), dict)) > 0,
            "rows_with_render": _count_runtime(lambda row: isinstance(row.get("render_result"), dict)),
            "total_runtime_rows": total_runtime,
        },
        "upload_metadata": {
            "path": str(repository_root / DEFAULT_RUNTIME_EVIDENCE_DIR),
            "available": _count_runtime(lambda row: isinstance(row.get("upload_result"), dict)) > 0,
            "rows_with_upload": _count_runtime(lambda row: isinstance(row.get("upload_result"), dict)),
            "total_runtime_rows": total_runtime,
        },
        "analytics_linkage": {
            "path": str(repository_root / DEFAULT_CANONICAL_ANALYTICS_PATH),
            "available": len(analytics_rows) > 0,
            "rows": len(analytics_rows),
            "linked_rows": sum(1 for row in analytics_rows if _safe_text(((row.get("provenance") or {}).get("join_outcome")) if isinstance(row.get("provenance"), dict) else "") == "LINKED"),
        },
        "ownership": {
            "path": str(repository_root / DEFAULT_OWNERSHIP_DIR),
            "available": len(ownership_rows) > 0,
            "rows": len(ownership_rows),
        },
        "forward_evidence": {
            "path": str(repository_root / DEFAULT_FORWARD_EVIDENCE_PATH),
            "available": len(forward_rows) > 0,
            "rows": len(forward_rows),
        },
    }

    for key, payload in matrix.items():
        if key in {"planning_lineage", "script_lineage", "forward_evidence", "ownership", "analytics_linkage"}:
            total = max(1, int(payload.get("rows") or 0))
            observed = int(payload.get("rows") or 0)
        elif key == "blueprint_lineage":
            total = max(1, int(payload.get("rows_with_blueprint_id") or 0))
            observed = int(payload.get("rows_with_blueprint_id") or 0)
        elif key == "thumbnail_metadata":
            total = max(1, total_runtime)
            observed = int(payload.get("rows") or 0)
        else:
            total = max(1, int(payload.get("total_runtime_rows") or 0))
            observed = int(next((v for k2, v in payload.items() if k2.startswith("rows_with_")), 0) or 0)

        coverage = round(100.0 * _safe_ratio(observed, total), 2)
        payload["coverage_pct"] = coverage
        payload["status"] = "complete" if coverage >= 95.0 else ("partial" if coverage > 0.0 else "missing")

    return {
        "schema_version": REVALIDATION_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "matrix": matrix,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if _safe_text(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if _safe_text(item)]
    return []


def _runtime_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        _safe_text(((row.get("timestamps") or {}) if isinstance(row.get("timestamps"), dict) else {}).get("finished_at") or row.get("generated_at")),
        _safe_text(row.get("generation_id") or row.get("content_id")),
    )


def _ownership_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        _safe_text(row.get("created_at")),
        _safe_text(row.get("content_id")),
    )


def _analytics_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        _safe_text(row.get("snapshot_end") or row.get("snapshot_start")),
        _safe_text(row.get("content_id")),
    )


def reconstruct_cqga_inputs(
    *,
    runtime_rows: list[dict[str, Any]],
    ownership_rows: list[dict[str, Any]],
    analytics_rows: list[dict[str, Any]],
    cqga_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runtime_latest: dict[str, dict[str, Any]] = {}
    runtime_by_run_id: dict[str, dict[str, Any]] = {}
    for row in sorted(runtime_rows, key=_runtime_sort_key):
        content_id = _safe_text(row.get("generation_id") or row.get("content_id"))
        run_id = _safe_text(row.get("run_id"))
        if content_id:
            runtime_latest[content_id] = row
        if run_id:
            runtime_by_run_id[run_id] = row

    ownership_latest: dict[str, dict[str, Any]] = {}
    ownership_by_run_id: dict[str, dict[str, Any]] = {}
    for row in sorted(ownership_rows, key=_ownership_sort_key):
        content_id = _safe_text(row.get("content_id"))
        run_id = _safe_text(row.get("run_id"))
        if content_id:
            ownership_latest[content_id] = row
        if run_id:
            ownership_by_run_id[run_id] = row

    analytics_latest: dict[str, dict[str, Any]] = {}
    for row in sorted(analytics_rows, key=_analytics_sort_key):
        content_id = _safe_text(row.get("content_id"))
        if content_id:
            analytics_latest[content_id] = row

    cqga_latest: dict[str, dict[str, Any]] = {}
    cqga_by_run_id: dict[str, dict[str, Any]] = {}
    for row in cqga_rows:
        content_id = _safe_text(row.get("content_id"))
        run_id = _safe_text(row.get("run_id"))
        if content_id:
            cqga_latest[content_id] = row
        if run_id:
            cqga_by_run_id[run_id] = row

    all_content_ids = sorted(set(runtime_latest.keys()) | set(ownership_latest.keys()) | set(analytics_latest.keys()) | set(cqga_latest.keys()))

    records: list[dict[str, Any]] = []
    excluded_missing_cqga = 0

    for content_id in all_content_ids:
        cqga = dict(cqga_latest.get(content_id) or {})
        cqga_run_id = _safe_text(cqga.get("run_id"))

        runtime = dict(runtime_latest.get(content_id) or runtime_by_run_id.get(cqga_run_id) or {})
        ownership = dict(ownership_latest.get(content_id) or ownership_by_run_id.get(cqga_run_id) or {})
        analytics_row = dict(analytics_latest.get(content_id) or {})

        if not cqga:
            runtime_run_id = _safe_text(runtime.get("run_id"))
            ownership_run_id = _safe_text(ownership.get("run_id"))
            cqga = dict(cqga_by_run_id.get(runtime_run_id) or cqga_by_run_id.get(ownership_run_id) or {})

        metadata = runtime.get("metadata") if isinstance(runtime.get("metadata"), dict) else {}
        guard_scores = runtime.get("guard_scores") if isinstance(runtime.get("guard_scores"), dict) else {}
        thumb_intel = guard_scores.get("thumbnail_intelligence") if isinstance(guard_scores.get("thumbnail_intelligence"), dict) else {}
        upload_result = runtime.get("upload_result") if isinstance(runtime.get("upload_result"), dict) else {}
        render_result = runtime.get("render_result") if isinstance(runtime.get("render_result"), dict) else {}
        ownership_artifacts = ownership.get("artifacts") if isinstance(ownership.get("artifacts"), dict) else {}
        ownership_thumb = ownership_artifacts.get("thumbnail") if isinstance(ownership_artifacts.get("thumbnail"), dict) else {}

        title = _safe_text(metadata.get("title") or ownership.get("title"))
        thumbnail_prompt = _safe_text(thumb_intel.get("thumbnail_prompt"))
        script = _safe_text(runtime.get("script") or ownership.get("script_preview"))
        description = _safe_text(metadata.get("description"))

        tags = _normalize_tags(metadata.get("tags"))
        hashtags = _normalize_tags(metadata.get("hashtags"))
        cards = _normalize_tags(metadata.get("cards"))
        end_screen = _normalize_tags(metadata.get("end_screen") or metadata.get("end_screens"))

        thumbnail_metadata = {
            "thumbnail_path": _safe_text(metadata.get("thumbnail_path") or ownership_thumb.get("path") or runtime.get("thumbnail_path")),
            "thumbnail_hash": _safe_text(ownership_thumb.get("sha256")),
            "thumbnail_prompt": thumbnail_prompt or None,
            "thumbnail_quality": dict(thumb_intel.get("quality") or {}) if isinstance(thumb_intel.get("quality"), dict) else {},
        }

        analytics_payload = _extract_analytics_payload(analytics_row) if analytics_row else _empty_analytics()

        channel_profile = dict(runtime.get("channel_profile") or metadata.get("channel_profile") or {}) if isinstance(runtime.get("channel_profile") or metadata.get("channel_profile") or {}, dict) else {}

        record = {
            "content_id": content_id,
            "channel_id": _safe_text(runtime.get("channel") or ownership.get("channel_id") or cqga.get("channel_id")),
            "run_id": _safe_text(runtime.get("run_id") or ownership.get("run_id") or cqga.get("run_id")),
            "content_type": _content_type_from_runtime(runtime),
            "topic": _safe_text(runtime.get("topic") or ownership.get("topic")),
            "title": title or None,
            "thumbnail_prompt": thumbnail_prompt or None,
            "thumbnail_metadata": thumbnail_metadata,
            "script": script or None,
            "description": description or None,
            "hashtags": hashtags,
            "tags": tags,
            "playlist": _safe_text(metadata.get("playlist")) or None,
            "cards": cards,
            "end_screen": end_screen,
            "analytics": analytics_payload,
            "ownership": {
                "channel_id": _safe_text(ownership.get("channel_id")),
                "run_id": _safe_text(ownership.get("run_id")),
                "title": _safe_text(ownership.get("title")),
                "topic": _safe_text(ownership.get("topic")),
                "script_preview": _safe_text(ownership.get("script_preview")),
            }
            if ownership
            else None,
            "channel_profile": channel_profile,
            "render_metadata": dict(render_result),
            "upload_metadata": dict(upload_result),
            "cqga_storage": cqga or None,
            "advisory_only": True,
            "pipeline_output_changed": False,
        }

        field_presence = {
            "title": bool(record["title"]),
            "thumbnail_prompt": bool(record["thumbnail_prompt"]),
            "thumbnail_metadata": bool(_safe_text(record["thumbnail_metadata"].get("thumbnail_hash")) or _safe_text(record["thumbnail_metadata"].get("thumbnail_path"))),
            "script": bool(record["script"]),
            "description": bool(record["description"]),
            "hashtags": len(record["hashtags"]) > 0,
            "tags": len(record["tags"]) > 0,
            "playlist": bool(record["playlist"]),
            "cards": len(record["cards"]) > 0,
            "end_screen": len(record["end_screen"]) > 0,
            "analytics": any(v is not None for v in record["analytics"].values() if not isinstance(v, dict)),
            "ownership": record["ownership"] is not None,
            "channel_profile": len(record["channel_profile"]) > 0,
        }
        missing = sorted([name for name in REQUIRED_RECONSTRUCTION_FIELDS if not field_presence.get(name, False)])
        record["field_presence"] = field_presence
        record["missing_fields"] = missing
        record["completeness_score"] = round(_safe_ratio(len(REQUIRED_RECONSTRUCTION_FIELDS) - len(missing), len(REQUIRED_RECONSTRUCTION_FIELDS)), 6)
        record["reconstructable_for_replay"] = bool(record.get("cqga_storage")) and bool(record.get("title")) and bool(record.get("thumbnail_prompt")) and bool(record.get("script")) and bool(record.get("description"))

        if not record["cqga_storage"]:
            excluded_missing_cqga += 1

        records.append(record)

    complete = sum(1 for item in records if item.get("completeness_score") == 1.0)
    partial = sum(1 for item in records if 0.0 < float(item.get("completeness_score") or 0.0) < 1.0)
    missing = sum(1 for item in records if float(item.get("completeness_score") or 0.0) == 0.0)

    coverage = {
        "total_reconstructed": len(records),
        "complete_evidence": complete,
        "partial_evidence": partial,
        "missing_evidence": missing,
        "excluded_missing_cqga": excluded_missing_cqga,
        "coverage_pct": round(100.0 * _safe_ratio(complete + partial, max(1, len(records))), 2),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    return records, coverage


def _predicted_weaknesses(score_summary: dict[str, Any], root_causes: list[str]) -> dict[str, bool]:
    ctr_score = float(score_summary.get("ctr") or 0.0)
    retention_score = float(score_summary.get("retention") or 0.0)
    hook_score = float(score_summary.get("hook") or 0.0)
    thumb_score = float(score_summary.get("thumbnail") or 0.0)
    seo_score = float(score_summary.get("seo") or 0.0)
    discovery_score = float(score_summary.get("discovery") or 0.0)
    maintainability_score = float(score_summary.get("maintainability") or 0.0)

    root_blob = " ".join(root_causes).lower()
    return {
        "title_weakness": ctr_score < 0.45 or "promise mismatch" in root_blob,
        "thumbnail_weakness": thumb_score < 0.45 or "thumbnail mismatch" in root_blob,
        "hook_weakness": hook_score < 0.45 or "weak hook" in root_blob,
        "repetition": maintainability_score < 0.6 or "template repetition" in root_blob,
        "cta_weakness": discovery_score < 0.45 or "cta" in root_blob,
        "discovery_weakness": discovery_score < 0.45 or "search intent" in root_blob,
        "metadata_weakness": seo_score < 0.45,
        "retention_weakness": retention_score < 0.45,
    }


def _observed_weaknesses(record: dict[str, Any]) -> tuple[dict[str, bool | None], dict[str, float | None]]:
    analytics = dict(record.get("analytics") or {})
    ctr = _to_number(analytics.get("click_through_rate"))
    avp = _to_number(analytics.get("average_view_percentage"))
    avd = _to_number(analytics.get("average_view_duration_seconds"))
    watch = _to_number(analytics.get("watch_time_hours"))
    card_ctr = _to_number(analytics.get("card_ctr"))
    end_ctr = _to_number(analytics.get("end_screen_ctr"))
    playlist_additions = _to_number(analytics.get("playlist_additions"))
    traffic_sources = analytics.get("traffic_sources") if isinstance(analytics.get("traffic_sources"), dict) else None

    observed: dict[str, bool | None] = {
        "title_weakness": (ctr < 0.035) if ctr is not None else None,
        "thumbnail_weakness": (ctr < 0.03) if ctr is not None else None,
        "hook_weakness": ((avp < 0.35) if avp is not None else (avd < 20.0 if avd is not None else None)),
        "repetition": (avd < 18.0) if avd is not None else None,
        "cta_weakness": (((card_ctr is not None and card_ctr < 0.01) or (end_ctr is not None and end_ctr < 0.01)) if (card_ctr is not None or end_ctr is not None) else None),
        "discovery_weakness": None,
        "metadata_weakness": None,
        "retention_weakness": (avp < 0.35) if avp is not None else None,
        "watch_time_weakness": (watch < 1.0) if watch is not None else None,
        "shorts_completion_weakness": (avp < 0.7) if (record.get("content_type") == "short" and avp is not None) else None,
    }

    if traffic_sources:
        browse = _to_number(traffic_sources.get("browse_features")) or 0.0
        suggested = _to_number(traffic_sources.get("suggested_videos")) or 0.0
        search = _to_number(traffic_sources.get("youtube_search")) or 0.0
        total = browse + suggested + search
        if total > 0:
            observed["discovery_weakness"] = ((browse + suggested) / total) < 0.35
            observed["metadata_weakness"] = (search / total) < 0.15

    if playlist_additions is not None:
        observed["playlist_usage_weakness"] = playlist_additions <= 0.0
    else:
        observed["playlist_usage_weakness"] = None

    measurements = {
        "ctr": ctr,
        "average_percentage_viewed": avp,
        "average_view_duration_seconds": avd,
        "watch_time_hours": watch,
        "card_ctr": card_ctr,
        "end_screen_ctr": end_ctr,
        "playlist_additions": playlist_additions,
    }
    return observed, measurements


def _severity_from_flags(flags: dict[str, bool]) -> str:
    count = sum(1 for value in flags.values() if bool(value))
    if count >= 4:
        return "critical"
    if count >= 3:
        return "high"
    if count >= 2:
        return "medium"
    if count >= 1:
        return "low"
    return "none"


def _confusion_metrics(tp: int, fp: int, fn: int, tn: int) -> dict[str, Any]:
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    specificity = _safe_ratio(tn, tn + fp)
    f1 = _safe_ratio(2 * precision * recall, precision + recall)
    balanced_accuracy = 0.5 * (recall + specificity)

    total = tp + fp + fn + tn
    observed_yes = tp + fn
    observed_no = fp + tn
    pred_yes = tp + fp
    pred_no = fn + tn

    pe = _safe_ratio((observed_yes * pred_yes) + (observed_no * pred_no), total * total) if total else 0.0
    po = _safe_ratio(tp + tn, total)
    kappa = _safe_ratio(po - pe, 1.0 - pe)

    denom = math.sqrt(float((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)))
    mcc = _safe_ratio((tp * tn) - (fp * fn), denom)

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "specificity": round(specificity, 6),
        "f1": round(f1, 6),
        "balanced_accuracy": round(balanced_accuracy, 6),
        "matthews_correlation_coefficient": round(mcc, 6),
        "cohens_kappa": round(kappa, 6),
        "false_positives": fp,
        "false_negatives": fn,
    }


def _roc_auc_from_scores(scores: list[float], labels: list[int]) -> float | None:
    if not scores or not labels or len(scores) != len(labels):
        return None
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None

    wins = 0.0
    ties = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                ties += 1.0
    auc = (wins + 0.5 * ties) / (len(pos) * len(neg))
    return float(auc)


def _rank_correlation(predicted: list[tuple[str, float]], observed: list[tuple[str, float]]) -> float | None:
    if not predicted or not observed:
        return None
    pred_dict = {k: v for k, v in predicted}
    obs_dict = {k: v for k, v in observed}
    common = sorted(set(pred_dict.keys()) & set(obs_dict.keys()))
    if len(common) < 2:
        return None

    pred_sorted = sorted(common, key=lambda key: pred_dict[key], reverse=True)
    obs_sorted = sorted(common, key=lambda key: obs_dict[key], reverse=True)
    pred_rank = {key: idx + 1 for idx, key in enumerate(pred_sorted)}
    obs_rank = {key: idx + 1 for idx, key in enumerate(obs_sorted)}

    n = len(common)
    d2 = sum((pred_rank[key] - obs_rank[key]) ** 2 for key in common)
    return float(1.0 - (6.0 * d2) / (n * (n * n - 1)))


def replay_cqga_revalidation(
    *,
    reconstructed_records: list[dict[str, Any]],
    replay_repeats: int = 3,
) -> dict[str, Any]:
    replayable = [row for row in reconstructed_records if bool(row.get("reconstructable_for_replay"))]
    excluded = [row for row in reconstructed_records if not bool(row.get("reconstructable_for_replay"))]

    run_payloads: list[list[dict[str, Any]]] = []
    per_content_latest: dict[str, dict[str, Any]] = {}

    for replay_idx in range(max(1, replay_repeats)):
        run_rows: list[dict[str, Any]] = []
        for row in replayable:
            content_id = _safe_text(row.get("content_id"))
            channel_id = _safe_text(row.get("channel_id")) or "unknown_channel"
            run_id = _safe_text(row.get("run_id")) or f"replay_{content_id}"
            content_type = _safe_text(row.get("content_type")) or "mixed"
            topic = _safe_text(row.get("topic")) or "unknown_topic"
            title = _safe_text(row.get("title"))
            thumb_prompt = _safe_text(row.get("thumbnail_prompt"))
            script = _safe_text(row.get("script"))
            description = _safe_text(row.get("description"))

            input_data = QualityAnalysisInput(
                content_id=content_id,
                channel_id=channel_id,
                content_type=content_type,
                niche=_safe_text((row.get("channel_profile") or {}).get("niche")) or "general",
                topic=topic,
                title=title,
                thumbnail_prompt=thumb_prompt,
                script=script,
                description=description,
                tags=tuple(str(item) for item in list(row.get("tags") or [])),
                hashtags=tuple(str(item) for item in list(row.get("hashtags") or [])),
                playlist=_safe_text(row.get("playlist")) or "unknown_playlist",
                cards=tuple(str(item) for item in list(row.get("cards") or [])),
                end_screens=tuple(str(item) for item in list(row.get("end_screen") or [])),
                short_title=title,
                short_script=script,
                review_queue={},
                analytics=dict(row.get("analytics") or {}),
                channel_profile=dict(row.get("channel_profile") or {}),
                audience_profile={},
            )

            result = analyze_content_quality_gaps(input_data=input_data, run_id=run_id)
            result_dict = result.to_dict()
            storage = dict(row.get("cqga_storage") or {})
            score_summary = dict(storage.get("score_summary") or {})
            root_causes = [str(item) for item in list(storage.get("root_causes") or [])]
            predicted = _predicted_weaknesses(score_summary=score_summary, root_causes=root_causes)
            observed, observed_measurements = _observed_weaknesses(row)

            predicted_severity = "none"
            if result_dict.get("gaps"):
                severity_map = {"low": 1, "medium": 2, "high": 3, "critical": 4}
                max_level = 0
                for gap in list(result_dict.get("gaps") or []):
                    max_level = max(max_level, int(severity_map.get(_safe_text(gap.get("severity")), 0)))
                predicted_severity = next((k for k, v in severity_map.items() if v == max_level), "none")

            observed_flags = {k: bool(v) for k, v in observed.items() if isinstance(v, bool)}
            observed_severity = _severity_from_flags(observed_flags)
            observed_root_causes = sorted([name for name, value in observed_flags.items() if value])

            row_payload = {
                "content_id": content_id,
                "channel_id": channel_id,
                "run_id": run_id,
                "predicted": {
                    "analysis_id": _safe_text(result_dict.get("analysis_id")),
                    "scorecard": dict(result_dict.get("scorecard") or {}),
                    "root_causes": sorted([str(item) for item in list(result_dict.get("root_causes") or [])]),
                    "gaps": list(result_dict.get("gaps") or []),
                    "weaknesses": predicted,
                    "severity": predicted_severity,
                    "overall_quality": float(((result_dict.get("scorecard") or {}).get("overall_confidence") or 0.0)),
                    "confidence": float(((result_dict.get("scorecard") or {}).get("overall_confidence") or 0.0)),
                },
                "observed": {
                    "measurements": observed_measurements,
                    "weaknesses": observed,
                    "root_causes": observed_root_causes,
                    "severity": observed_severity,
                },
                "advisory_only": True,
                "pipeline_output_changed": False,
            }
            run_rows.append(row_payload)
            per_content_latest[content_id] = row_payload
        run_payloads.append(run_rows)

    reference = [_stable_json({
        "content_id": row.get("content_id"),
        "predicted": row.get("predicted"),
        "observed": row.get("observed"),
    }) for row in run_payloads[0]] if run_payloads else []

    deterministic_replay = True
    stable_rankings = True
    stable_explanations = True
    stable_root_causes = True
    stable_recommendations = True

    def _ranking(rows: list[dict[str, Any]]) -> list[str]:
        return [
            str(item.get("content_id"))
            for item in sorted(
                rows,
                key=lambda x: float(((x.get("predicted") or {}).get("overall_quality") or 0.0)),
                reverse=True,
            )
        ]

    base_ranking = _ranking(run_payloads[0]) if run_payloads else []

    for rows in run_payloads[1:]:
        normalized = [_stable_json({"content_id": row.get("content_id"), "predicted": row.get("predicted"), "observed": row.get("observed")}) for row in rows]
        if normalized != reference:
            deterministic_replay = False

        if _ranking(rows) != base_ranking:
            stable_rankings = False

        base_expl = [sorted([str(item.get("category")) for item in list((row.get("predicted") or {}).get("gaps") or [])]) for row in run_payloads[0]]
        cur_expl = [sorted([str(item.get("category")) for item in list((row.get("predicted") or {}).get("gaps") or [])]) for row in rows]
        if cur_expl != base_expl:
            stable_explanations = False

        base_roots = [list((row.get("predicted") or {}).get("root_causes") or []) for row in run_payloads[0]]
        cur_roots = [list((row.get("predicted") or {}).get("root_causes") or []) for row in rows]
        if cur_roots != base_roots:
            stable_root_causes = False

        base_reco = [sorted([str(item.get("recommended_future_action")) for item in list((row.get("predicted") or {}).get("gaps") or [])]) for row in run_payloads[0]]
        cur_reco = [sorted([str(item.get("recommended_future_action")) for item in list((row.get("predicted") or {}).get("gaps") or [])]) for row in rows]
        if cur_reco != base_reco:
            stable_recommendations = False

    tp = fp = fn = tn = 0
    roc_scores: list[float] = []
    roc_labels: list[int] = []

    severity_agreement_total = 0
    severity_agreement_hits = 0

    root_agreement_total = 0
    root_agreement_hits = 0

    calibration_pairs: list[tuple[float, int]] = []

    predicted_rank: list[tuple[str, float]] = []
    observed_rank: list[tuple[str, float]] = []

    required_dimensions = [
        "title_weakness",
        "thumbnail_weakness",
        "hook_weakness",
        "repetition",
        "cta_weakness",
        "discovery_weakness",
        "metadata_weakness",
        "retention_weakness",
    ]

    for row in per_content_latest.values():
        predicted = dict((row.get("predicted") or {}).get("weaknesses") or {})
        observed = dict((row.get("observed") or {}).get("weaknesses") or {})
        scorecard = dict((row.get("predicted") or {}).get("scorecard") or {})
        confidence = float((row.get("predicted") or {}).get("confidence") or 0.0)

        observed_outcome_signals = [v for v in observed.values() if isinstance(v, bool)]
        if observed_outcome_signals:
            bad_outcome = 1 if any(observed_outcome_signals) else 0
            calibration_pairs.append((confidence, bad_outcome))

        pred_overall = float((row.get("predicted") or {}).get("overall_quality") or 0.0)
        pred_risk = 1.0 - pred_overall
        obs_meas = dict((row.get("observed") or {}).get("measurements") or {})
        ctr = _to_number(obs_meas.get("ctr"))
        avp = _to_number(obs_meas.get("average_percentage_viewed"))
        if ctr is not None or avp is not None:
            obs_quality = _safe_ratio((ctr or 0.0) + (avp or 0.0), (1 if ctr is not None else 0) + (1 if avp is not None else 0))
            predicted_rank.append((str(row.get("content_id")), pred_overall))
            observed_rank.append((str(row.get("content_id")), obs_quality))

        for dim in required_dimensions:
            observed_value = observed.get(dim)
            if not isinstance(observed_value, bool):
                continue
            pred_value = bool(predicted.get(dim, False))
            if pred_value and observed_value:
                tp += 1
            elif pred_value and (not observed_value):
                fp += 1
            elif (not pred_value) and observed_value:
                fn += 1
            else:
                tn += 1

            dimension_score = scorecard.get(dim.replace("_weakness", ""))
            if isinstance(dimension_score, dict):
                s = _to_number(dimension_score.get("score"))
                if s is not None:
                    roc_scores.append(1.0 - float(s))
                    roc_labels.append(1 if observed_value else 0)
            else:
                roc_scores.append(pred_risk)
                roc_labels.append(1 if observed_value else 0)

        pred_severity = _safe_text((row.get("predicted") or {}).get("severity"))
        obs_severity = _safe_text((row.get("observed") or {}).get("severity"))
        if pred_severity and obs_severity:
            severity_agreement_total += 1
            if pred_severity == obs_severity:
                severity_agreement_hits += 1

        pred_roots = set(str(item) for item in list((row.get("predicted") or {}).get("root_causes") or []))
        obs_roots = set(str(item) for item in list((row.get("observed") or {}).get("root_causes") or []))
        if obs_roots:
            root_agreement_total += len(obs_roots)
            root_agreement_hits += len(pred_roots & obs_roots)

    agreement = _confusion_metrics(tp=tp, fp=fp, fn=fn, tn=tn)
    roc_auc = _roc_auc_from_scores(scores=roc_scores, labels=roc_labels)
    agreement["roc_auc"] = (round(float(roc_auc), 6) if roc_auc is not None else None)
    agreement["ranking_agreement"] = _rank_correlation(predicted_rank, observed_rank)
    agreement["root_cause_agreement"] = round(_safe_ratio(root_agreement_hits, root_agreement_total), 6) if root_agreement_total else None
    agreement["severity_agreement"] = round(_safe_ratio(severity_agreement_hits, severity_agreement_total), 6) if severity_agreement_total else None

    if calibration_pairs:
        brier = sum((float(conf) - float(label)) ** 2 for conf, label in calibration_pairs) / len(calibration_pairs)
        bins = [0] * 5
        conf_sums = [0.0] * 5
        label_sums = [0.0] * 5
        for conf, label in calibration_pairs:
            idx = min(4, max(0, int(conf * 5)))
            bins[idx] += 1
            conf_sums[idx] += conf
            label_sums[idx] += label
        ece = 0.0
        for idx in range(5):
            if bins[idx] == 0:
                continue
            avg_conf = conf_sums[idx] / bins[idx]
            avg_label = label_sums[idx] / bins[idx]
            ece += (bins[idx] / len(calibration_pairs)) * abs(avg_conf - avg_label)
        agreement["confidence_calibration"] = {
            "brier_score": round(float(brier), 6),
            "expected_calibration_error": round(float(ece), 6),
            "samples": len(calibration_pairs),
        }
    else:
        agreement["confidence_calibration"] = {
            "brier_score": None,
            "expected_calibration_error": None,
            "samples": 0,
        }

    review_payloads = []
    for row in sorted(per_content_latest.values(), key=lambda item: _safe_text(item.get("content_id"))):
        predicted = dict(row.get("predicted") or {})
        observed = dict(row.get("observed") or {})
        payload = {
            "review_id": "cqga_review_" + _sha_text(_safe_text(row.get("content_id")))[:16],
            "content_id": row.get("content_id"),
            "channel_id": row.get("channel_id"),
            "run_id": row.get("run_id"),
            "predicted_root_causes": list(predicted.get("root_causes") or []),
            "predicted_severity": predicted.get("severity"),
            "predicted_weaknesses": dict(predicted.get("weaknesses") or {}),
            "observed_signals": dict(observed.get("weaknesses") or {}),
            "recommended_actions": sorted(
                {
                    str(item.get("recommended_future_action"))
                    for item in list(predicted.get("gaps") or [])
                    if _safe_text(item.get("recommended_future_action"))
                }
            ),
            "automatic_action": None,
            "advisory_only": True,
            "pipeline_output_changed": False,
        }
        review_payloads.append(payload)

    stability = {
        "replay_repeats": max(1, replay_repeats),
        "deterministic_replay": deterministic_replay,
        "stable_rankings": stable_rankings,
        "stable_explanations": stable_explanations,
        "stable_root_causes": stable_root_causes,
        "stable_recommendations": stable_recommendations,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    return {
        "schema_version": REVALIDATION_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "replayable_count": len(replayable),
        "excluded_count": len(excluded),
        "agreement": agreement,
        "stability": stability,
        "review_payloads": review_payloads,
        "latest_rows": sorted(list(per_content_latest.values()), key=lambda x: _safe_text(x.get("content_id"))),
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def build_gap_report(*, evidence_matrix: dict[str, Any], replay_result: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    matrix = dict(evidence_matrix.get("matrix") or {})
    gaps: list[dict[str, Any]] = []

    for name in [
        "planning_lineage",
        "blueprint_lineage",
        "prompt_metadata",
        "script_lineage",
        "thumbnail_metadata",
        "forward_evidence",
    ]:
        payload = dict(matrix.get(name) or {})
        if _safe_text(payload.get("status")) != "complete":
            gaps.append(
                {
                    "gap": name,
                    "status": payload.get("status"),
                    "coverage_pct": payload.get("coverage_pct"),
                    "impact": "limits deterministic reconstruction breadth",
                }
            )

    agreement = dict(replay_result.get("agreement") or {})
    if agreement.get("roc_auc") is None:
        gaps.append(
            {
                "gap": "insufficient_observed_analytics_for_roc_auc",
                "status": "missing",
                "impact": "binary-discrimination validation is not statistically supported",
            }
        )

    if (agreement.get("confidence_calibration") or {}).get("samples", 0) == 0:
        gaps.append(
            {
                "gap": "insufficient_observed_analytics_for_confidence_calibration",
                "status": "missing",
                "impact": "confidence reliability cannot be validated",
            }
        )

    # Explicitly track known external metrics that are not available in local-only artifacts.
    gaps.extend(
        [
            {
                "gap": "unavailable_studio_metrics",
                "status": "missing",
                "impact": "detailed Studio-only diagnostics unavailable in local snapshots",
            },
            {
                "gap": "unavailable_audience_retention_segments",
                "status": "missing",
                "impact": "segment-level retention root-cause validation is limited",
            },
            {
                "gap": "unavailable_impression_funnel",
                "status": "missing",
                "impact": "impression-to-click conversion decomposition unavailable",
            },
            {
                "gap": "unavailable_browse_suggest_split",
                "status": "missing",
                "impact": "discovery-source attribution confidence limited",
            },
            {
                "gap": "unavailable_experiment_history",
                "status": "missing",
                "impact": "historical treatment effect separation unavailable",
            },
        ]
    )

    return {
        "schema_version": REVALIDATION_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "coverage": coverage,
        "gaps": gaps,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }


def run_cqga_real_world_revalidation(
    *,
    repository_root: Path,
    output_dir: Path | None = None,
    replay_repeats: int = 3,
) -> dict[str, Any]:
    root = Path(repository_root)
    out_dir = Path(output_dir) if output_dir is not None else (root / DEFAULT_OUTPUT_DIR)

    runtime_files = sorted((root / DEFAULT_RUNTIME_EVIDENCE_DIR).glob("*.json")) if (root / DEFAULT_RUNTIME_EVIDENCE_DIR).exists() else []
    runtime_rows = [_read_json(path) for path in runtime_files]

    ownership_files = sorted((root / DEFAULT_OWNERSHIP_DIR).glob("*.json")) if (root / DEFAULT_OWNERSHIP_DIR).exists() else []
    ownership_rows = [_read_json(path) for path in ownership_files]

    analytics_rows, analytics_malformed = _read_jsonl(root / DEFAULT_CANONICAL_ANALYTICS_PATH)
    cqga_rows, cqga_malformed = _read_jsonl(root / DEFAULT_CQGA_STORAGE_PATH)
    planning_rows, planning_malformed = _read_jsonl(root / DEFAULT_PLANNING_LINEAGE_PATH)
    script_rows, script_malformed = _read_jsonl(root / DEFAULT_SCRIPT_LINEAGE_PATH)
    forward_rows, forward_malformed = _read_jsonl(root / DEFAULT_FORWARD_EVIDENCE_PATH)
    thumbnail_rows, thumbnail_malformed = _read_jsonl(root / DEFAULT_THUMBNAIL_LINEAGE_PATH)

    evidence_matrix = build_evidence_completeness_matrix(
        repository_root=root,
        runtime_rows=runtime_rows,
        ownership_rows=ownership_rows,
        analytics_rows=analytics_rows,
        planning_rows=planning_rows,
        script_rows=script_rows,
        forward_rows=forward_rows,
        thumbnail_rows=thumbnail_rows,
    )

    reconstructed, coverage = reconstruct_cqga_inputs(
        runtime_rows=runtime_rows,
        ownership_rows=ownership_rows,
        analytics_rows=analytics_rows,
        cqga_rows=cqga_rows,
    )

    replay_result = replay_cqga_revalidation(
        reconstructed_records=reconstructed,
        replay_repeats=replay_repeats,
    )

    gap_report = build_gap_report(
        evidence_matrix=evidence_matrix,
        replay_result=replay_result,
        coverage=coverage,
    )

    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "evidence_completeness_matrix.json").write_text(
        json.dumps(evidence_matrix, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (out_dir / "reconstructed_inputs.jsonl").write_text(
        "\n".join(_stable_json(row) for row in reconstructed) + ("\n" if reconstructed else ""),
        encoding="utf-8",
    )
    (out_dir / "replay_results.jsonl").write_text(
        "\n".join(_stable_json(row) for row in list(replay_result.get("latest_rows") or []))
        + ("\n" if replay_result.get("latest_rows") else ""),
        encoding="utf-8",
    )
    (out_dir / "agreement_metrics.json").write_text(
        json.dumps(dict(replay_result.get("agreement") or {}), ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (out_dir / "stability_report.json").write_text(
        json.dumps(dict(replay_result.get("stability") or {}), ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (out_dir / "coverage_report.json").write_text(
        json.dumps(coverage, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    (out_dir / "review_payloads.jsonl").write_text(
        "\n".join(_stable_json(row) for row in list(replay_result.get("review_payloads") or []))
        + ("\n" if replay_result.get("review_payloads") else ""),
        encoding="utf-8",
    )
    (out_dir / "gap_report.json").write_text(
        json.dumps(gap_report, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    summary = {
        "schema_version": REVALIDATION_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "sources": {
            "runtime_rows": len(runtime_rows),
            "ownership_rows": len(ownership_rows),
            "analytics_rows": len(analytics_rows),
            "cqga_rows": len(cqga_rows),
            "planning_rows": len(planning_rows),
            "script_rows": len(script_rows),
            "forward_rows": len(forward_rows),
            "thumbnail_rows": len(thumbnail_rows),
        },
        "malformed_rows": {
            "analytics": analytics_malformed,
            "cqga": cqga_malformed,
            "planning": planning_malformed,
            "script": script_malformed,
            "forward": forward_malformed,
            "thumbnail": thumbnail_malformed,
        },
        "coverage": coverage,
        "replay": {
            "replayable_count": replay_result.get("replayable_count"),
            "excluded_count": replay_result.get("excluded_count"),
            "agreement": replay_result.get("agreement"),
            "stability": replay_result.get("stability"),
        },
        "evidence_matrix": evidence_matrix,
        "gap_report": gap_report,
        "advisory_only": True,
        "pipeline_output_changed": False,
    }

    (out_dir / "assessment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    return summary
