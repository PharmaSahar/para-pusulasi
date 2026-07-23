"""Integrated production quality platform helpers.

These helpers are intentionally lightweight and fail-open for non-critical
artifact writes, but fail-closed for mandatory QA/script gates.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import time
import threading
import traceback
import fcntl
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .channel_performance import load_recent_performance_snapshots
from .runtime_storage import (
    docs_dashboard_path,
    env_or_runtime_path,
    validate_runtime_write_path,
)
from .retry_policy import (
    EXHAUSTED_RETRY,
    classify_retry_decision,
    compute_backoff_delay,
    consume_retry_budget,
    get_retry_budget_state,
    retry_budget_context,
)
from .forensic_telemetry import (
    FORENSIC_COMPONENT,
    FORENSIC_SCHEMA_VERSION,
    average_hash_8x8,
    compute_record_hash,
    sanitize_url,
    sha256_file,
    sha256_text,
    validate_forensic_record,
    write_immutable_forensic_record,
)
from .visual_diversity import topic_similarity


logger = logging.getLogger("ProductionQualityPlatform")


def _env_path(key: str, default: str) -> Path:
    raw = str(os.getenv(key, default)).strip()
    return Path(raw if raw else default)


def _preprod_isolation_enabled() -> bool:
    raw = str(os.getenv("PREPROD_ISOLATION_MODE", "false")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _assert_preprod_mutable_path(path: Path, *, env_key: str) -> None:
    if not _preprod_isolation_enabled():
        return

    root_raw = str(os.getenv("PREPROD_STATE_ROOT", "")).strip()
    if not root_raw:
        raise RuntimeError("preprod_isolation_invalid: PREPROD_STATE_ROOT missing")

    if not str(os.getenv(env_key, "")).strip():
        raise RuntimeError(f"preprod_isolation_invalid: {env_key} missing")

    resolved = path.resolve()
    state_root = Path(root_raw).resolve()
    repo_root = Path(__file__).resolve().parents[1]

    inside_state_root = resolved == state_root or state_root in resolved.parents
    inside_repo = resolved == repo_root or repo_root in resolved.parents
    if (not inside_state_root) or inside_repo:
        raise RuntimeError(
            f"preprod_isolation_violation: {env_key}={resolved} outside PREPROD_STATE_ROOT or inside repo"
        )


PRODUCTION_EVENTS_PATH = env_or_runtime_path("PRODUCTION_EVENTS_PATH", "telemetry/production_events.jsonl")
PRODUCTION_OBSERVABILITY_LATEST_PATH = env_or_runtime_path(
    "PRODUCTION_OBSERVABILITY_LATEST_PATH",
    "telemetry/production_observability_latest.json",
)
PRODUCTION_DASHBOARD_JSON_PATH = env_or_runtime_path("PRODUCTION_DASHBOARD_JSON_PATH", "state/production_dashboard_latest.json")
PRODUCTION_DASHBOARD_MD_PATH = env_or_runtime_path("PRODUCTION_DASHBOARD_MD_PATH", "state/production_dashboard_latest.md")
THUMBNAIL_INTELLIGENCE_LATEST_PATH = env_or_runtime_path(
    "THUMBNAIL_INTELLIGENCE_LATEST_PATH",
    "telemetry/thumbnail_intelligence_latest.json",
)
PRODUCTION_EVIDENCE_DIR = env_or_runtime_path("PRODUCTION_EVIDENCE_DIR", "evidence")
UPLOAD_REGISTRY_PATH = env_or_runtime_path("UPLOAD_REGISTRY_PATH", "state/production_upload_registry.json")
UPLOAD_REGISTRY_LOCK_PATH = env_or_runtime_path("UPLOAD_REGISTRY_LOCK_PATH", "state/production_upload_registry.lock")
DEAD_LETTER_QUEUE_PATH = env_or_runtime_path("DEAD_LETTER_QUEUE_PATH", "telemetry/production_dead_letter_queue.jsonl")
CANARY_STATE_PATH = env_or_runtime_path("CANARY_STATE_PATH", "state/production_canary_state.json")
FORENSIC_GENERATION_ROOT = env_or_runtime_path("FORENSIC_GENERATION_ROOT", "forensics/generation")


def _trace_dashboard_write(*, target: Path, write_mode: str, atomic: bool, bytes_written: int) -> None:
    trace_path_raw = str(os.getenv("DASHBOARD_WRITE_TRACE_PATH", "")).strip()
    if not trace_path_raw:
        return

    payload = {
        "timestamp": _now_iso(),
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
        "test_node_id": str(os.getenv("PYTEST_CURRENT_TEST", "") or ""),
        "caller_function": inspect.stack()[1].function,
        "target_path": str(target),
        "write_mode": write_mode,
        "atomic": bool(atomic),
        "bytes_written": int(max(0, bytes_written)),
        "stack_trace": traceback.format_stack(),
    }

    try:
        trace_path = Path(trace_path_raw)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # Tracing must stay fail-open for production logic.
        return


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    if not validate_runtime_write_path(path, purpose="safe_write_json", logger=logger):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.write_text(encoded, encoding="utf-8")
    _trace_dashboard_write(target=tmp, write_mode="overwrite", atomic=False, bytes_written=len(encoded.encode("utf-8")))
    tmp.replace(path)
    _trace_dashboard_write(target=path, write_mode="replace", atomic=True, bytes_written=len(encoded.encode("utf-8")))


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except Exception:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_json_with_fsync(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_directory(path.parent)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    if not validate_runtime_write_path(path, purpose="append_jsonl", logger=logger):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
    _trace_dashboard_write(target=path, write_mode="append", atomic=False, bytes_written=len(encoded.encode("utf-8")))


def _tokenize(text: str) -> set[str]:
    tokens = []
    current = []
    for ch in (text or "").lower():
        if ch.isalnum():
            current.append(ch)
        elif current:
            token = "".join(current)
            if len(token) >= 3:
                tokens.append(token)
            current = []
    if current:
        token = "".join(current)
        if len(token) >= 3:
            tokens.append(token)
    return set(tokens)


def _similarity(a: str, b: str) -> float:
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return (inter / union) if union else 0.0


def score_script_quality(
    *,
    title: str,
    script: str,
    description: str,
    topic: str,
    cta_text: str = "",
    recent_scripts: list[str] | None = None,
) -> dict[str, Any]:
    script_text = (script or "").strip()
    desc_text = (description or "").strip()
    title_text = (title or "").strip()
    topic_text = (topic or "").strip()
    cta = (cta_text or "").strip()

    script_tokens = _tokenize(script_text)
    sentences = [s.strip() for s in script_text.replace("\n", ". ").split(".") if s.strip()]
    word_count = sum(1 for _ in script_tokens) or 1

    hook_quality = 1.0 if ("?" in title_text or any(ch.isdigit() for ch in title_text)) else 0.6
    info_density = min(1.0, word_count / 220.0)
    unique_ratio = min(1.0, (len(script_tokens) / float(max(1, len(script_text.split())))))
    repetition = 1.0 - unique_ratio
    readability = 1.0 if 6 <= (sum(len(s.split()) for s in sentences) / float(max(1, len(sentences)))) <= 20 else 0.65
    specificity = 1.0 if any(ch.isdigit() for ch in script_text) else 0.7
    structure = min(1.0, len(sentences) / 12.0)
    cta_quality = 1.0 if len(cta) >= 8 and any(k in cta.lower() for k in ("abone", "yorum", "paylas", "subscribe", "comment")) else 0.6
    novelty = 1.0
    recent_similarity = 0.0
    for candidate in recent_scripts or []:
        sim = _similarity(script_text, str(candidate))
        if sim > recent_similarity:
            recent_similarity = sim
    novelty = max(0.0, 1.0 - recent_similarity)

    title_topic_alignment = _similarity(title_text, topic_text)
    if title_topic_alignment < 0.1:
        hook_quality = min(hook_quality, 0.7)

    weighted = {
        "hook_quality": hook_quality,
        "information_density": info_density,
        "repetition": 1.0 - repetition,
        "readability": readability,
        "specificity": specificity,
        "structure": structure,
        "cta_quality": cta_quality,
        "novelty": novelty,
        "recent_script_similarity": 1.0 - recent_similarity,
    }
    overall = sum(weighted.values()) / float(len(weighted))

    return {
        "overall_score": round(overall * 100.0, 2),
        "metrics": {k: round(v * 100.0, 2) for k, v in weighted.items()},
        "recent_script_similarity": round(recent_similarity, 4),
        "threshold": float(os.getenv("SCRIPT_QUALITY_MIN_SCORE", "62")),
    }


def evaluate_thumbnail_intelligence(
    *,
    channel_id: str,
    topic: str,
    thumbnail_prompt: str,
    rejection_reasons: list[str] | None,
    recent_thumbnail_prompts: list[str] | None,
    ctr_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    reasons = [str(x) for x in (rejection_reasons or []) if str(x).strip()]
    prompt = (thumbnail_prompt or "").strip()
    semantic_fit = round(_similarity(topic or "", prompt), 4)

    duplicate_similarity = 0.0
    for prev in recent_thumbnail_prompts or []:
        sim = topic_similarity(prompt, str(prev))
        if sim > duplicate_similarity:
            duplicate_similarity = sim

    text_readability = 1.0
    lower_prompt = prompt.lower()
    if any(k in lower_prompt for k in ("tiny text", "dense text", "paragraph")):
        text_readability = 0.5

    unsafe = any(k in lower_prompt for k in ("blood", "weapon", "nsfw", "gore"))
    composition = max(0.0, min(1.0, 1.0 - (len(prompt) / 420.0)))
    quality = {
        "semantic_topic_fit": semantic_fit,
        "duplicate_similarity": round(duplicate_similarity, 4),
        "recent_similarity": round(duplicate_similarity, 4),
        "text_readability": round(text_readability, 4),
        "unsafe_content": bool(unsafe),
        "composition_score": round(composition, 4),
    }

    payload = {
        "generated_at": _now_iso(),
        "channel_id": channel_id,
        "topic": topic,
        "thumbnail_prompt": prompt,
        "rejection_reasons": reasons,
        "quality": quality,
        "ctr_evidence": ctr_evidence or {},
    }
    _safe_write_json(THUMBNAIL_INTELLIGENCE_LATEST_PATH, payload)
    return payload


def evaluate_automatic_qa(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "")
    script = str(payload.get("script") or "")
    description = str(payload.get("description") or "")
    tags = [str(x).strip() for x in (payload.get("tags") or []) if str(x).strip()]
    topic = str(payload.get("topic") or title)
    niche = str(payload.get("niche") or "")
    thumbnail_prompt = str(payload.get("thumbnail_prompt") or "")
    selected_visuals = [str(x) for x in (payload.get("selected_visuals") or []) if str(x).strip()]
    rejection_reasons = [str(x) for x in (payload.get("rejection_reasons") or []) if str(x).strip()]

    checks = {
        "channel_topic_fit": _similarity(topic, niche) > 0.02 or bool(niche),
        "title_script_description_tags_consistency": _similarity(title + " " + description, script) > 0.02 and len(tags) >= 3,
        "thumbnail_relevance": _similarity(topic, thumbnail_prompt) >= 0.05,
        "metadata_completeness": bool(title and script and description and tags),
        "repeated_script_detection": float(payload.get("script_similarity", 0.0) or 0.0) < 0.55,
        "repeated_visual_detection": len(selected_visuals) == len(set(selected_visuals)),
        "unsafe_imagery": not any(k in thumbnail_prompt.lower() for k in ("blood", "weapon", "nsfw", "gore")),
        "visual_diversity": "DUPLICATE_OR_LOW_DIVERSITY" not in rejection_reasons,
        "shorts_metadata": bool(payload.get("shorts_enabled", True)) or True,
    }

    blocked = [name for name, ok in checks.items() if not bool(ok)]
    decision = "allow" if not blocked else "block"

    return {
        "generated_at": _now_iso(),
        "decision": decision,
        "blocked_checks": blocked,
        "checks": checks,
    }


def record_production_event(event: dict[str, Any]) -> None:
    payload = dict(event)
    payload.setdefault("timestamp", _now_iso())
    _append_jsonl(PRODUCTION_EVENTS_PATH, payload)
    update_production_observability_latest()


def _parse_recent_events(hours: int = 24) -> list[dict[str, Any]]:
    if not PRODUCTION_EVENTS_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    out: list[dict[str, Any]] = []
    for line in PRODUCTION_EVENTS_PATH.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except Exception:
            continue
        ts = str(item.get("timestamp") or item.get("occurred_at_utc") or "")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt >= cutoff:
            out.append(item)
    return out


def update_production_observability_latest() -> dict[str, Any]:
    events = _parse_recent_events(hours=24)
    success = sum(1 for e in events if str(e.get("final_status") or "").lower() in {"success", "completed"})
    failed = sum(1 for e in events if str(e.get("final_status") or "").lower() in {"failed", "error", "blocked"})
    by_channel: dict[str, dict[str, int]] = {}
    for item in events:
        channel = str(item.get("channel") or item.get("channel_id") or "unknown")
        info = by_channel.setdefault(channel, {"total": 0, "success": 0, "failed": 0})
        info["total"] += 1
        status = str(item.get("final_status") or "").lower()
        if status in {"success", "completed"}:
            info["success"] += 1
        elif status in {"failed", "error", "blocked"}:
            info["failed"] += 1

    latest = {
        "generated_at": _now_iso(),
        "window_hours": 24,
        "events_count": len(events),
        "success_count": success,
        "failure_count": failed,
        "channel_health": by_channel,
        "last_event": events[-1] if events else {},
    }
    _safe_write_json(PRODUCTION_OBSERVABILITY_LATEST_PATH, latest)
    return latest


def _queue_observability_metrics(queue_path: Path = Path("output/queue/channel_queue.json")) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "queue_retained_total": 0,
        "queue_actionable_total": 0,
        "queue_terminal_by_status": {
            "quarantined": 0,
            "permanently_rejected": 0,
        },
        "queue_source_identity": {
            "path": str(queue_path),
            "exists": queue_path.exists(),
            "source": "dashboard_default_queue",
        },
    }
    if not queue_path.exists():
        return metrics
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
    except Exception:
        return metrics
    if not isinstance(data, dict):
        return metrics

    terminal_by_status = dict(metrics["queue_terminal_by_status"])
    for entries in data.values():
        if not isinstance(entries, list):
            continue
        metrics["queue_retained_total"] += len(entries)
        for entry in entries:
            row = entry if isinstance(entry, dict) else {}
            status = str(row.get("status") or "active").strip().lower()
            if status in {"active", "restored"}:
                metrics["queue_actionable_total"] += 1
            elif status in terminal_by_status:
                terminal_by_status[status] += 1
    metrics["queue_terminal_by_status"] = terminal_by_status
    return metrics


def _queue_depth(queue_path: Path = Path("output/queue/channel_queue.json")) -> int:
    return int(_queue_observability_metrics(queue_path).get("queue_retained_total", 0) or 0)


def update_production_dashboard(
    *,
    scheduler_status: str,
    build_sha: str,
    scheduler_pid: int | None,
    last_error: str | None = None,
) -> dict[str, Any]:
    if not validate_runtime_write_path(PRODUCTION_DASHBOARD_JSON_PATH, purpose="dashboard_json", logger=logger):
        return {}
    if not validate_runtime_write_path(PRODUCTION_DASHBOARD_MD_PATH, purpose="dashboard_markdown", logger=logger):
        return {}

    _assert_preprod_mutable_path(
        PRODUCTION_DASHBOARD_MD_PATH,
        env_key="PRODUCTION_DASHBOARD_MD_PATH",
    )

    events = _parse_recent_events(hours=24)
    snapshots = load_recent_performance_snapshots(lookback_days=2, max_items=800)
    videos = [e for e in events if str(e.get("content_type") or "video") == "video"]
    shorts = [e for e in events if str(e.get("content_type") or "").lower() == "short"]
    success = sum(1 for e in events if str(e.get("final_status") or "").lower() in {"success", "completed"})
    failed = sum(1 for e in events if str(e.get("final_status") or "").lower() in {"failed", "error", "blocked"})
    total = max(1, success + failed)

    render_durations = [
        float(s.get("render_duration_seconds"))
        for s in snapshots
        if isinstance(s.get("render_duration_seconds"), (int, float))
    ]
    avg_render_duration = (sum(render_durations) / len(render_durations)) if render_durations else None

    blocked_quality = sum(1 for e in events if str(e.get("final_status") or "").lower() == "blocked")
    retries = sum(int(e.get("retry_count") or 0) for e in events)
    upload_success = sum(1 for e in events if bool(e.get("upload_result", {}).get("video_id")))

    channel_health: dict[str, dict[str, int]] = {}
    for e in events:
        channel = str(e.get("channel") or e.get("channel_id") or "unknown")
        row = channel_health.setdefault(channel, {"total": 0, "success": 0, "failed": 0})
        row["total"] += 1
        status = str(e.get("final_status") or "").lower()
        if status in {"success", "completed"}:
            row["success"] += 1
        elif status in {"failed", "error", "blocked"}:
            row["failed"] += 1

    queue_metrics = _queue_observability_metrics()

    payload = {
        "generated_at": _now_iso(),
        "scheduler_status": scheduler_status,
        "build_sha": build_sha,
        "scheduler_pid": scheduler_pid,
        "last_24h": {
            "videos": len(videos),
            "shorts": len(shorts),
            "success_rate": round(success / float(total), 4),
            "failure_rate": round(failed / float(total), 4),
            "avg_render_duration_seconds": round(avg_render_duration, 3) if avg_render_duration is not None else None,
            "upload_success_count": upload_success,
            "blocked_quality_items": blocked_quality,
            "retries": retries,
        },
        "channel_level_health": channel_health,
        "queue_depth": queue_metrics["queue_retained_total"],
        "queue_retained_total": queue_metrics["queue_retained_total"],
        "queue_actionable_total": queue_metrics["queue_actionable_total"],
        "queue_terminal_by_status": queue_metrics["queue_terminal_by_status"],
        "queue_source_identity": queue_metrics["queue_source_identity"],
        "last_error": (last_error or ""),
    }
    _safe_write_json(PRODUCTION_DASHBOARD_JSON_PATH, payload)

    md_lines = [
        "# Production Dashboard (Latest)",
        "",
        f"- Generated at: {payload['generated_at']}",
        f"- Scheduler status: {scheduler_status}",
        f"- Build SHA: {build_sha}",
        f"- Scheduler PID: {scheduler_pid}",
        f"- Queue depth: {payload['queue_depth']}",
        f"- Queue retained total: {payload['queue_retained_total']}",
        f"- Queue actionable total: {payload['queue_actionable_total']}",
        f"- Queue terminal quarantined: {payload['queue_terminal_by_status']['quarantined']}",
        f"- Queue terminal permanently rejected: {payload['queue_terminal_by_status']['permanently_rejected']}",
        f"- Last error: {payload['last_error'] or '-'}",
        "",
        "## Last 24h",
        f"- Videos: {payload['last_24h']['videos']}",
        f"- Shorts: {payload['last_24h']['shorts']}",
        f"- Success rate: {payload['last_24h']['success_rate']}",
        f"- Failure rate: {payload['last_24h']['failure_rate']}",
        f"- Avg render duration (s): {payload['last_24h']['avg_render_duration_seconds']}",
        f"- Upload success count: {payload['last_24h']['upload_success_count']}",
        f"- Blocked quality items: {payload['last_24h']['blocked_quality_items']}",
        f"- Retries: {payload['last_24h']['retries']}",
        "",
        "## Channel Health",
    ]
    for channel, row in sorted(channel_health.items()):
        md_lines.append(f"- {channel}: total={row['total']} success={row['success']} failed={row['failed']}")

    PRODUCTION_DASHBOARD_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    dashboard_md = "\n".join(md_lines) + "\n"
    PRODUCTION_DASHBOARD_MD_PATH.write_text(dashboard_md, encoding="utf-8")
    _trace_dashboard_write(
        target=PRODUCTION_DASHBOARD_MD_PATH,
        write_mode="overwrite",
        atomic=False,
        bytes_written=len(dashboard_md.encode("utf-8")),
    )
    return payload


def export_runtime_dashboard_to_docs(
    *,
    source_path: Path | None = None,
    docs_path: Path | None = None,
) -> dict[str, Any]:
    source = source_path or PRODUCTION_DASHBOARD_MD_PATH
    target = docs_path or docs_dashboard_path()
    if not source.exists():
        raise FileNotFoundError(f"runtime_dashboard_missing: {source}")

    content = source.read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)
    logger.info("runtime_dashboard_exported: source=%s target=%s bytes=%s", source, target, len(content.encode("utf-8")))
    return {
        "source": str(source),
        "target": str(target),
        "bytes": len(content.encode("utf-8")),
        "ok": True,
    }


def build_idempotency_key(*, channel: str, generation_id: str, publish_at: str | None, title: str) -> str:
    raw = "|".join([channel or "", generation_id or "", publish_at or "", title or ""]) 
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _upload_registry_empty() -> dict[str, Any]:
    return {
        "entries": {},
        "updated_at": _now_iso(),
    }


def _read_upload_registry_unlocked() -> dict[str, Any]:
    registry = _safe_read_json(UPLOAD_REGISTRY_PATH)
    if not isinstance(registry, dict):
        registry = _upload_registry_empty()
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        registry["entries"] = {}
    return registry


def _write_upload_registry_unlocked(registry: dict[str, Any]) -> None:
    payload = dict(registry or {})
    entries = payload.get("entries")
    payload["entries"] = dict(entries or {})
    payload["updated_at"] = _now_iso()
    if not validate_runtime_write_path(UPLOAD_REGISTRY_PATH, purpose="upload_registry_write", logger=logger):
        raise RuntimeError("upload_registry_path_invalid")
    _atomic_write_json_with_fsync(UPLOAD_REGISTRY_PATH, payload)


UPLOAD_STATE_CLAIMED = "claimed"
UPLOAD_STATE_UPLOADING = "uploading"
UPLOAD_STATE_UPLOADED_PENDING_COMMIT = "uploaded_pending_commit"
UPLOAD_STATE_COMMITTED = "committed"
UPLOAD_STATE_ROLLED_BACK = "rolled_back"
UPLOAD_STATE_FAILED = "failed"

_UPLOAD_ALLOWED_TRANSITIONS: dict[str | None, set[str]] = {
    None: {UPLOAD_STATE_CLAIMED},
    UPLOAD_STATE_CLAIMED: {
        UPLOAD_STATE_UPLOADING,
        UPLOAD_STATE_COMMITTED,
        UPLOAD_STATE_FAILED,
        UPLOAD_STATE_ROLLED_BACK,
    },
    UPLOAD_STATE_UPLOADING: {
        UPLOAD_STATE_UPLOADED_PENDING_COMMIT,
        UPLOAD_STATE_COMMITTED,
        UPLOAD_STATE_FAILED,
        UPLOAD_STATE_ROLLED_BACK,
    },
    UPLOAD_STATE_UPLOADED_PENDING_COMMIT: {
        UPLOAD_STATE_COMMITTED,
        UPLOAD_STATE_FAILED,
        UPLOAD_STATE_ROLLED_BACK,
    },
    UPLOAD_STATE_FAILED: {UPLOAD_STATE_ROLLED_BACK},
    UPLOAD_STATE_ROLLED_BACK: {UPLOAD_STATE_CLAIMED},
    UPLOAD_STATE_COMMITTED: set(),
}


def _normalize_upload_state(value: Any) -> str | None:
    if value is None:
        return None
    state = str(value).strip().lower()
    if not state:
        return None
    if state not in _UPLOAD_ALLOWED_TRANSITIONS:
        raise RuntimeError(f"upload_state_invalid:{state}")
    return state


def _assert_upload_transition(*, current_state: str | None, next_state: str, op: str) -> None:
    current = _normalize_upload_state(current_state)
    target = _normalize_upload_state(next_state)
    if target is None:
        raise RuntimeError(f"upload_state_invalid_target:{op}")
    if current == target:
        return
    allowed = _UPLOAD_ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise RuntimeError(f"upload_state_transition_invalid:{current or 'none'}->{target}:{op}")


@contextmanager
def _upload_registry_lock():
    if not validate_runtime_write_path(UPLOAD_REGISTRY_LOCK_PATH, purpose="upload_registry_lock", logger=logger):
        raise RuntimeError("upload_registry_lock_path_invalid")
    UPLOAD_REGISTRY_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with UPLOAD_REGISTRY_LOCK_PATH.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def claim_upload_before_side_effect(
    *,
    idempotency_key: str,
    claim_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key_missing")

    token = hashlib.sha256(
        f"{key}|{os.getpid()}|{threading.get_ident()}|{time.time_ns()}".encode("utf-8")
    ).hexdigest()[:24]
    now = _now_iso()

    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.setdefault("entries", {})
        existing = entries.get(key)
        if isinstance(existing, dict):
            status = str(existing.get("status") or "").strip().lower()
            _normalize_upload_state(status)
            if status == UPLOAD_STATE_COMMITTED and str(existing.get("video_id") or "").strip():
                return {
                    "status": "already_committed",
                    "idempotency_key": key,
                    "entry": dict(existing),
                }
            if status == UPLOAD_STATE_UPLOADED_PENDING_COMMIT and str(existing.get("video_id") or "").strip():
                return {
                    "status": "already_uploaded_pending_commit",
                    "idempotency_key": key,
                    "entry": dict(existing),
                }
            if status in {UPLOAD_STATE_CLAIMED, UPLOAD_STATE_UPLOADING} and str(existing.get("claim_token") or "").strip():
                return {
                    "status": "already_claimed",
                    "idempotency_key": key,
                    "entry": dict(existing),
                }
            if status == UPLOAD_STATE_FAILED:
                return {
                    "status": "already_failed",
                    "idempotency_key": key,
                    "entry": dict(existing),
                }
            if status == UPLOAD_STATE_ROLLED_BACK and str(existing.get("rollback_from_state") or "").strip().lower() == UPLOAD_STATE_UPLOADED_PENDING_COMMIT:
                return {
                    "status": "already_rolled_back_needs_operator",
                    "idempotency_key": key,
                    "entry": dict(existing),
                }

        _assert_upload_transition(current_state=status if isinstance(existing, dict) else None, next_state=UPLOAD_STATE_CLAIMED, op="claim")
        claim_entry = {
            "status": UPLOAD_STATE_CLAIMED,
            "claim_token": token,
            "claimed_at": now,
            "claim_owner": {
                "pid": os.getpid(),
                "thread_id": threading.get_ident(),
            },
            "claim_payload": dict(claim_payload or {}),
        }
        entries[key] = claim_entry
        _write_upload_registry_unlocked(registry)

    return {
        "status": "claimed",
        "idempotency_key": key,
        "claim_token": token,
        "entry": claim_entry,
    }


def commit_upload_claim(
    *,
    idempotency_key: str,
    claim_token: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    key = str(idempotency_key or "").strip()
    token = str(claim_token or "").strip()
    if not key:
        raise ValueError("idempotency_key_missing")
    if not token:
        raise ValueError("claim_token_missing")

    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.setdefault("entries", {})
        existing = entries.get(key)
        if not isinstance(existing, dict):
            raise RuntimeError("upload_claim_missing")

        status = _normalize_upload_state(existing.get("status"))
        existing_video = str(existing.get("video_id") or "").strip()
        if status == UPLOAD_STATE_COMMITTED and existing_video:
            return dict(existing)

        if str(existing.get("claim_token") or "").strip() != token:
            raise RuntimeError("upload_claim_mismatch")
        _assert_upload_transition(current_state=status, next_state=UPLOAD_STATE_COMMITTED, op="commit")

        resolved_video_id = str((payload or {}).get("video_id") or existing.get("video_id") or "").strip()
        if not resolved_video_id:
            raise RuntimeError("upload_commit_missing_video_id")

        committed = {
            **dict(existing),
            **dict(payload or {}),
            "video_id": resolved_video_id,
            "status": UPLOAD_STATE_COMMITTED,
            "committed_at": _now_iso(),
            "registered_at": _now_iso(),
            "claim_token": token,
        }
        entries[key] = committed
        _write_upload_registry_unlocked(registry)
        return committed


def mark_upload_in_progress(
    *,
    idempotency_key: str,
    claim_token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = str(idempotency_key or "").strip()
    token = str(claim_token or "").strip()
    if not key:
        raise ValueError("idempotency_key_missing")
    if not token:
        raise ValueError("claim_token_missing")

    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.setdefault("entries", {})
        existing = entries.get(key)
        if not isinstance(existing, dict):
            raise RuntimeError("upload_claim_missing")

        status = _normalize_upload_state(existing.get("status"))
        if status == UPLOAD_STATE_COMMITTED and str(existing.get("video_id") or "").strip():
            return dict(existing)

        if str(existing.get("claim_token") or "").strip() != token:
            raise RuntimeError("upload_claim_mismatch")
        _assert_upload_transition(current_state=status, next_state=UPLOAD_STATE_UPLOADING, op="mark_upload_in_progress")

        uploading = {
            **dict(existing),
            **dict(payload or {}),
            "status": UPLOAD_STATE_UPLOADING,
            "upload_started_at": _now_iso(),
            "claim_token": token,
        }
        entries[key] = uploading
        _write_upload_registry_unlocked(registry)
        return uploading


def mark_upload_pending_commit(
    *,
    idempotency_key: str,
    claim_token: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    key = str(idempotency_key or "").strip()
    token = str(claim_token or "").strip()
    if not key:
        raise ValueError("idempotency_key_missing")
    if not token:
        raise ValueError("claim_token_missing")

    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.setdefault("entries", {})
        existing = entries.get(key)
        if not isinstance(existing, dict):
            raise RuntimeError("upload_claim_missing")

        status = _normalize_upload_state(existing.get("status"))
        existing_video = str(existing.get("video_id") or "").strip()
        if status == UPLOAD_STATE_COMMITTED and existing_video:
            return dict(existing)

        if str(existing.get("claim_token") or "").strip() != token:
            raise RuntimeError("upload_claim_mismatch")
        _assert_upload_transition(current_state=status, next_state=UPLOAD_STATE_UPLOADED_PENDING_COMMIT, op="mark_upload_pending_commit")

        resolved_video_id = str((payload or {}).get("video_id") or existing_video).strip()
        if not resolved_video_id:
            raise RuntimeError("upload_pending_commit_missing_video_id")

        pending_commit = {
            **dict(existing),
            **dict(payload or {}),
            "video_id": resolved_video_id,
            "status": UPLOAD_STATE_UPLOADED_PENDING_COMMIT,
            "uploaded_at": _now_iso(),
            "claim_token": token,
        }
        entries[key] = pending_commit
        _write_upload_registry_unlocked(registry)
        return pending_commit


def fail_upload_claim(
    *,
    idempotency_key: str,
    claim_token: str,
    error_text: str,
) -> dict[str, Any]:
    key = str(idempotency_key or "").strip()
    token = str(claim_token or "").strip()
    if not key:
        raise ValueError("idempotency_key_missing")
    if not token:
        raise ValueError("claim_token_missing")

    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.setdefault("entries", {})
        existing = entries.get(key)
        if not isinstance(existing, dict):
            return {"status": "missing", "idempotency_key": key}

        status = _normalize_upload_state(existing.get("status"))
        if status == UPLOAD_STATE_COMMITTED and str(existing.get("video_id") or "").strip():
            return {"status": "already_committed", "idempotency_key": key, "entry": dict(existing)}

        if str(existing.get("claim_token") or "").strip() != token:
            return {"status": "not_owner", "idempotency_key": key, "entry": dict(existing)}

        _assert_upload_transition(current_state=status, next_state=UPLOAD_STATE_FAILED, op="fail_upload_claim")

        failed = {
            **dict(existing),
            "status": UPLOAD_STATE_FAILED,
            "failed_at": _now_iso(),
            "last_error": str(error_text or "")[:400],
            "failed_from_state": status,
            "claim_token": token,
        }
        entries[key] = failed
        _write_upload_registry_unlocked(registry)
        return {"status": UPLOAD_STATE_FAILED, "idempotency_key": key, "entry": failed}


def rollback_upload_claim(
    *,
    idempotency_key: str,
    claim_token: str,
    error_text: str,
) -> dict[str, Any]:
    key = str(idempotency_key or "").strip()
    token = str(claim_token or "").strip()
    if not key:
        raise ValueError("idempotency_key_missing")
    if not token:
        raise ValueError("claim_token_missing")

    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.setdefault("entries", {})
        existing = entries.get(key)
        if not isinstance(existing, dict):
            return {"status": "missing", "idempotency_key": key}

        status = _normalize_upload_state(existing.get("status"))
        if status == UPLOAD_STATE_COMMITTED and str(existing.get("video_id") or "").strip():
            return {"status": "already_committed", "idempotency_key": key, "entry": dict(existing)}

        if str(existing.get("claim_token") or "").strip() != token:
            return {"status": "not_owner", "idempotency_key": key, "entry": dict(existing)}

        _assert_upload_transition(current_state=status, next_state=UPLOAD_STATE_ROLLED_BACK, op="rollback")

        released = {
            **dict(existing),
            "status": UPLOAD_STATE_ROLLED_BACK,
            "released_at": _now_iso(),
            "last_error": str(error_text or "")[:400],
            "rollback_from_state": status,
            "claim_token": "",
        }
        entries[key] = released
        _write_upload_registry_unlocked(registry)
        return {"status": UPLOAD_STATE_ROLLED_BACK, "idempotency_key": key, "entry": released}


def get_registered_upload(idempotency_key: str) -> dict[str, Any] | None:
    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.get("entries") if isinstance(registry.get("entries"), dict) else {}
        found = entries.get(idempotency_key)
        if not isinstance(found, dict):
            return None
        status = _normalize_upload_state(found.get("status"))
        if status == UPLOAD_STATE_COMMITTED and str(found.get("video_id") or "").strip():
            return found
        return None


def get_registered_upload_compat(idempotency_key: str) -> dict[str, Any] | None:
    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.get("entries") if isinstance(registry.get("entries"), dict) else {}
        found = entries.get(idempotency_key)
        if not isinstance(found, dict):
            return None
        status = _normalize_upload_state(found.get("status"))
        if status == UPLOAD_STATE_COMMITTED and str(found.get("video_id") or "").strip():
            return found
        if str(found.get("video_id") or "").strip():
            return found
        return None


def register_upload(idempotency_key: str, payload: dict[str, Any]) -> None:
    with _upload_registry_lock():
        registry = _read_upload_registry_unlocked()
        entries = registry.setdefault("entries", {})
        existing = entries.get(idempotency_key)
        if isinstance(existing, dict):
            existing_status = _normalize_upload_state(existing.get("status"))
            existing_video_id = str(existing.get("video_id") or "").strip()
            # Backward compatibility: older registry rows may have been committed
            # without an explicit status field. Treat those as committed rather than
            # failing a new write on a legacy none -> committed transition.
            current_state = existing_status
            if current_state is None and existing_video_id:
                current_state = UPLOAD_STATE_COMMITTED
            _assert_upload_transition(
                current_state=current_state,
                next_state=UPLOAD_STATE_COMMITTED,
                op="register_upload",
            )
        entries[idempotency_key] = {
            **dict(payload or {}),
            "status": UPLOAD_STATE_COMMITTED,
            "registered_at": _now_iso(),
            "committed_at": _now_iso(),
        }
        _write_upload_registry_unlocked(registry)


def run_stage_with_recovery(
    *,
    stage: str,
    fn: Callable[[], Any],
    max_attempts: int = 2,
    base_backoff_seconds: float = 2.0,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> tuple[Any, dict[str, Any]]:
    last_error: Exception | None = None
    max_attempts = max(1, int(max_attempts))
    existing_budget = get_retry_budget_state()

    @contextmanager
    def _budget_context_if_needed():
        if existing_budget is not None:
            yield
            return
        with retry_budget_context(total_retries=max(0, max_attempts - 1), scope=stage):
            yield

    with _budget_context_if_needed():
        for attempt in range(1, max_attempts + 1):
            try:
                value = fn()
                budget_state = get_retry_budget_state()
                return value, {
                    "stage": stage,
                    "attempts": attempt,
                    "max_attempts": max_attempts,
                    "recovered": attempt > 1,
                    "ok": True,
                    "retry_budget": budget_state,
                }
            except Exception as exc:
                last_error = exc
                decision = classify_retry_decision(error_text=str(exc), exc=exc, stage=stage)
                if on_retry is not None:
                    on_retry(attempt, exc)
                can_retry = False
                remaining_budget = None
                if attempt < max_attempts and decision.retryable:
                    can_retry, remaining_budget = consume_retry_budget(reason_code=decision.reason_code)

                if can_retry:
                    delay = compute_backoff_delay(base_delay_seconds=base_backoff_seconds, attempt=attempt, stage=stage)
                    record_production_event(
                        {
                            "event_type": "retry_scheduled",
                            "timestamp": _now_iso(),
                            "severity": "WARNING",
                            "status": "scheduled",
                            "reason": decision.reason_code,
                            "operation": stage,
                            "attempt": attempt,
                            "source_component": "run_stage_with_recovery",
                            "evidence": {
                                "classification": decision.classification,
                                "delay_seconds": delay,
                                "retry_budget_remaining": remaining_budget,
                            },
                        }
                    )
                    time.sleep(delay)
                else:
                    break

    failure = {
        "stage": stage,
        "attempts": max_attempts,
        "max_attempts": max_attempts,
        "recovered": False,
        "ok": False,
        "error": str(last_error) if last_error else "unknown_error",
        "retry_budget": get_retry_budget_state(),
    }
    record_production_event(
        {
            "event_type": "retry_exhausted",
            "timestamp": _now_iso(),
            "severity": "ERROR",
            "status": "blocked",
            "reason": EXHAUSTED_RETRY,
            "operation": stage,
            "attempt": max_attempts,
            "source_component": "run_stage_with_recovery",
            "evidence": failure,
        }
    )
    record_dead_letter(failure)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{stage}_failed_without_error")


def record_dead_letter(item: dict[str, Any]) -> None:
    payload = dict(item)
    payload.setdefault("timestamp", _now_iso())
    _append_jsonl(DEAD_LETTER_QUEUE_PATH, payload)


def canary_gate_decision(channel_id: str) -> dict[str, Any]:
    canary_enabled = _is_enabled(os.getenv("PRODUCTION_CANARY_ENABLED", "false"))
    if not canary_enabled:
        return {"allow": True, "reason": "canary_disabled", "mode": "full_rollout"}

    selected = (os.getenv("PRODUCTION_CANARY_CHANNEL", "") or "").strip()
    observation_minutes = int(os.getenv("PRODUCTION_CANARY_OBSERVATION_MINUTES", "60") or "60")
    min_success_rate = float(os.getenv("PRODUCTION_CANARY_MIN_SUCCESS_RATE", "0.8") or "0.8")

    state = _safe_read_json(CANARY_STATE_PATH)
    promoted = bool(state.get("promoted"))
    if promoted:
        return {"allow": True, "reason": "manual_promoted", "mode": "global"}

    if selected and channel_id != selected:
        return {
            "allow": False,
            "reason": "canary_only_single_channel",
            "mode": "canary",
            "selected_channel": selected,
        }

    recent = _parse_recent_events(hours=max(1, int((observation_minutes / 60.0) + 1)))
    canary_events = [e for e in recent if str(e.get("channel") or e.get("channel_id") or "") == channel_id]
    completed = [e for e in canary_events if str(e.get("final_status") or "").lower() in {"success", "completed", "failed", "error", "blocked"}]
    if completed:
        success = sum(1 for e in completed if str(e.get("final_status") or "").lower() in {"success", "completed"})
        rate = success / float(len(completed))
    else:
        rate = 1.0

    if completed and rate < min_success_rate:
        state.update(
            {
                "updated_at": _now_iso(),
                "canary_channel": channel_id,
                "promoted": False,
                "stopped": True,
                "stop_reason": "health_regression",
                "success_rate": round(rate, 4),
                "observation_minutes": observation_minutes,
            }
        )
        _safe_write_json(CANARY_STATE_PATH, state)
        return {"allow": False, "reason": "health_regression_stop", "mode": "canary"}

    state.update(
        {
            "updated_at": _now_iso(),
            "canary_channel": channel_id,
            "promoted": False,
            "stopped": False,
            "success_rate": round(rate, 4),
            "observation_minutes": observation_minutes,
        }
    )
    _safe_write_json(CANARY_STATE_PATH, state)
    return {"allow": True, "reason": "canary_allowed", "mode": "canary"}


def _safe_read_manifest(path_value: str | None) -> dict[str, Any]:
    path_text = str(path_value or "").strip()
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_manifest_asset_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in list(manifest.get("assets") or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("asset") or "").strip()
        if not key:
            continue
        index[key] = item
    return index


def _normalize_media_queries(query_attempts: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    for item in query_attempts:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if query:
            ordered.append(query)
    return ordered


def _infer_scene_role(index: int, total: int, *, thumbnail_path: str | None, scene_path: str) -> str:
    if thumbnail_path and str(scene_path) == str(thumbnail_path):
        return "thumbnail-source"
    if index == 0:
        return "intro"
    if index == max(0, total - 1):
        return "outro"
    return "body"


def _scene_perceptual_entry(scene_path: str) -> dict[str, Any]:
    phash = average_hash_8x8(scene_path)
    return {
        "perceptual_hash": phash.get("value"),
        "perceptual_hash_status": phash.get("status"),
        "perceptual_hash_algorithm": phash.get("algorithm"),
    }


def _build_upload_precheck_observability(result: dict[str, Any]) -> dict[str, Any]:
    precheck = dict(result.get("upload_precheck") or {})
    tags = [str(tag) for tag in list(result.get("tags") or [])]
    guard_reason_codes = [str(code) for code in list(precheck.get("guard_reason_codes") or [])]
    metadata_consistency = "fail" if "upload_precheck_metadata_consistency_failed" in guard_reason_codes else "pass"
    return {
        "run_id": str(result.get("run_id") or ""),
        "content_id": str(result.get("content_id") or result.get("generation_id") or ""),
        "channel_id": str(result.get("channel") or result.get("channel_id") or ""),
        "decision": str(precheck.get("status") or "unknown"),
        "metadata_consistency": metadata_consistency,
        "guard_reason_codes": guard_reason_codes,
        "quarantine_reason": str(precheck.get("quarantine_reason") or ""),
        "title": str(result.get("title") or ""),
        "topic": str(result.get("topic") or result.get("title") or ""),
        "first_five_tags": tags[:5],
    }


def build_generation_forensic_record(result: dict[str, Any]) -> dict[str, Any]:
    selected_visuals = [str(item) for item in (result.get("selected_visuals") or []) if str(item).strip()]
    thumbnail_path = str(result.get("thumbnail_path") or "").strip()
    video_path = str(result.get("video_path") or "").strip()

    media_trace = dict(result.get("forensic_media_trace") or {})
    query_attempts = list(media_trace.get("query_attempts") or [])
    selected_assets = list(media_trace.get("selected_assets") or [])
    metadata_by_path = dict(media_trace.get("asset_metadata_by_local_path") or {})

    visual_manifest = _safe_read_manifest(str(result.get("visual_manifest_path") or ""))
    manifest_index = _build_manifest_asset_index(visual_manifest)

    provider_asset_ids: list[str] = []
    asset_urls_sanitized: list[str] = []
    for item in selected_assets:
        if not isinstance(item, dict):
            continue
        provider_asset_id = str(item.get("provider_asset_id") or "").strip()
        source_url = sanitize_url(str(item.get("source_url") or ""))
        if provider_asset_id:
            provider_asset_ids.append(provider_asset_id)
        if source_url:
            asset_urls_sanitized.append(source_url)

    scene_order: list[dict[str, Any]] = []
    perceptual_hashes: list[dict[str, Any]] = []
    asset_fingerprints: list[str] = []
    for scene_index, scene_path in enumerate(selected_visuals):
        manifest_item = dict(manifest_index.get(scene_path) or {})
        meta_item = dict(metadata_by_path.get(scene_path) or {})
        fingerprint = str(manifest_item.get("asset_fingerprint") or "").strip()
        if not fingerprint:
            fallback_hash = sha256_file(scene_path)
            fingerprint = str(fallback_hash or sha256_text(scene_path)).strip().lower()
        local_asset_hash = sha256_file(scene_path)
        pentry = _scene_perceptual_entry(scene_path)
        provider_asset_id = str(meta_item.get("provider_asset_id") or manifest_item.get("provider_asset_id") or "").strip() or None

        scene_record = {
            "scene_index": int(scene_index),
            "asset_fingerprint": fingerprint,
            "perceptual_hash": pentry.get("perceptual_hash"),
            "provider_asset_id": provider_asset_id,
            "local_asset_hash": local_asset_hash,
            "source_type": str(meta_item.get("source_type") or manifest_item.get("source_type") or meta_item.get("media_type") or "unknown"),
            "duration": None,
            "role": _infer_scene_role(scene_index, len(selected_visuals), thumbnail_path=thumbnail_path, scene_path=scene_path),
            "perceptual_hash_status": pentry.get("perceptual_hash_status"),
            "perceptual_hash_algorithm": pentry.get("perceptual_hash_algorithm"),
        }
        scene_order.append(scene_record)
        perceptual_hashes.append(
            {
                "asset_fingerprint": fingerprint,
                "value": pentry.get("perceptual_hash"),
                "status": pentry.get("perceptual_hash_status"),
                "algorithm": pentry.get("perceptual_hash_algorithm"),
            }
        )
        asset_fingerprints.append(fingerprint)

    dedup_provider = sorted({item for item in provider_asset_ids if item})
    dedup_urls = sorted({item for item in asset_urls_sanitized if item})
    dedup_fingerprints = sorted({item for item in asset_fingerprints if item})

    qa_result = {
        "automatic_qa": dict(result.get("automatic_qa") or {}),
        "content_quality": dict(result.get("content_quality") or {}),
        "script_quality": dict(result.get("script_quality") or {}),
        "thumbnail_intelligence": dict(result.get("thumbnail_intelligence") or {}),
        "rejection_reasons": list(result.get("rejection_reasons") or []),
    }

    provider_values = [
        str(media_trace.get("provider") or "").strip(),
        str(result.get("content_provider") or "anthropic").strip(),
        "youtube",
    ]
    provider = ",".join(sorted({p for p in provider_values if p}))

    record = {
        "forensic_schema_version": FORENSIC_SCHEMA_VERSION,
        "timestamp_utc": str(result.get("finished_at") or _now_iso()),
        "release_sha": str(result.get("build_sha") or result.get("commit_sha") or ""),
        "run_id": str(result.get("run_id") or ""),
        "content_id": str(result.get("content_id") or result.get("generation_id") or ""),
        "channel_id": str(result.get("channel") or result.get("channel_id") or ""),
        "topic": str(result.get("topic") or result.get("title") or ""),
        "provider": provider,
        "media_queries": _normalize_media_queries(query_attempts),
        "provider_asset_ids": dedup_provider,
        "asset_urls_sanitized": dedup_urls,
        "asset_fingerprints": dedup_fingerprints,
        "perceptual_hashes": perceptual_hashes,
        "selected_visuals": selected_visuals,
        "scene_order": scene_order,
        "thumbnail_prompt": str(result.get("thumbnail_prompt") or ""),
        "thumbnail_hash": sha256_file(thumbnail_path),
        "render_hash": sha256_file(video_path),
        "video_id": str(result.get("video_id") or "") or None,
        "youtube_url": str(result.get("youtube_url") or "") or None,
        "qa_result": qa_result,
        "generation_result": str(result.get("final_status") or "unknown"),
        "upload_precheck": _build_upload_precheck_observability(result),
        "record_hash": "",
        "created_by_component": FORENSIC_COMPONENT,
        "cache_provenance": list(media_trace.get("cache_provenance") or []),
    }
    record["record_hash"] = compute_record_hash(record)
    validate_forensic_record(record)
    return record


def write_immutable_generation_forensic_record(result: dict[str, Any]) -> Path | None:
    if str(result.get("final_status") or "").lower() != "success":
        return None
    record = build_generation_forensic_record(result)
    return write_immutable_forensic_record(root_dir=FORENSIC_GENERATION_ROOT, record=record)


def write_production_evidence(result: dict[str, Any]) -> Path:
    generation_id = str(result.get("content_id") or result.get("generation_id") or "")
    if not generation_id:
        generation_id = hashlib.sha256(json.dumps(result, sort_keys=True).encode("utf-8")).hexdigest()[:18]

    payload = {
        "generated_at": _now_iso(),
        "generation_id": generation_id,
        "commit_sha": str(result.get("commit_sha") or ""),
        "build_sha": str(result.get("build_sha") or result.get("commit_sha") or ""),
        "scheduler_pid": result.get("scheduler_pid"),
        "channel": result.get("channel"),
        "topic": result.get("topic") or result.get("title"),
        "prompt_version": result.get("prompt_version") or result.get("experiment_id"),
        "script_hash": hashlib.sha256(str(result.get("script") or "").encode("utf-8")).hexdigest(),
        "metadata": {
            "title": result.get("title"),
            "description": result.get("description"),
            "tags": result.get("tags") or [],
            "privacy": result.get("upload_metadata", {}).get("privacy"),
            "publish_at": result.get("upload_metadata", {}).get("publish_at"),
        },
        "selected_assets": result.get("selected_visuals") or [],
        "rejected_assets": result.get("rejected_assets") or [],
        "guard_scores": {
            "script_quality": result.get("script_quality"),
            "automatic_qa": result.get("automatic_qa"),
            "thumbnail_intelligence": result.get("thumbnail_intelligence"),
            "content_quality": result.get("content_quality"),
        },
        "render_result": result.get("render_metrics") or {},
        "upload_result": {
            "video_id": result.get("video_id"),
            "youtube_url": result.get("youtube_url"),
            "short_url": result.get("short_url"),
            "error": result.get("upload_error"),
        },
        "timestamps": {
            "started_at": result.get("started_at"),
            "finished_at": result.get("finished_at"),
            "fact_check_checked_at": ((result.get("fact_check") or {}).get("checked_at")),
        },
        "retries": {
            "pipeline_retry_count": result.get("pipeline_retry_count", 0),
            "upload_retry_count": result.get("upload_retry_count", 0),
        },
        "final_decision": result.get("final_status") or "unknown",
        "upload_precheck": _build_upload_precheck_observability(result),
    }

    PRODUCTION_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    target = PRODUCTION_EVIDENCE_DIR / f"{generation_id}.json"
    _safe_write_json(target, payload)
    return target
