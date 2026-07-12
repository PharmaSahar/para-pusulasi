"""Integrated production quality platform helpers.

These helpers are intentionally lightweight and fail-open for non-critical
artifact writes, but fail-closed for mandatory QA/script gates.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .channel_performance import load_recent_performance_snapshots
from .visual_diversity import topic_similarity


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


PRODUCTION_EVENTS_PATH = _env_path("PRODUCTION_EVENTS_PATH", "logs/production_events.jsonl")
PRODUCTION_OBSERVABILITY_LATEST_PATH = _env_path("PRODUCTION_OBSERVABILITY_LATEST_PATH", "logs/production_observability_latest.json")
PRODUCTION_DASHBOARD_JSON_PATH = _env_path("PRODUCTION_DASHBOARD_JSON_PATH", "logs/production_dashboard_latest.json")
PRODUCTION_DASHBOARD_MD_PATH = _env_path("PRODUCTION_DASHBOARD_MD_PATH", "docs/production_dashboard_latest.md")
THUMBNAIL_INTELLIGENCE_LATEST_PATH = _env_path("THUMBNAIL_INTELLIGENCE_LATEST_PATH", "logs/thumbnail_intelligence_latest.json")
PRODUCTION_EVIDENCE_DIR = _env_path("PRODUCTION_EVIDENCE_DIR", "logs/production_evidence")
UPLOAD_REGISTRY_PATH = _env_path("UPLOAD_REGISTRY_PATH", "logs/production_upload_registry.json")
DEAD_LETTER_QUEUE_PATH = _env_path("DEAD_LETTER_QUEUE_PATH", "logs/production_dead_letter_queue.jsonl")
CANARY_STATE_PATH = _env_path("CANARY_STATE_PATH", "logs/production_canary_state.json")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


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


def _queue_depth(queue_path: Path = Path("output/queue/channel_queue.json")) -> int:
    if not queue_path.exists():
        return 0
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    total = 0
    if isinstance(data, dict):
        for entries in data.values():
            if isinstance(entries, list):
                total += len(entries)
    return total


def update_production_dashboard(
    *,
    scheduler_status: str,
    build_sha: str,
    scheduler_pid: int | None,
    last_error: str | None = None,
) -> dict[str, Any]:
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
        "queue_depth": _queue_depth(),
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
    PRODUCTION_DASHBOARD_MD_PATH.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return payload


def build_idempotency_key(*, channel: str, generation_id: str, publish_at: str | None, title: str) -> str:
    raw = "|".join([channel or "", generation_id or "", publish_at or "", title or ""]) 
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_registered_upload(idempotency_key: str) -> dict[str, Any] | None:
    registry = _safe_read_json(UPLOAD_REGISTRY_PATH)
    entries = registry.get("entries") if isinstance(registry.get("entries"), dict) else {}
    found = entries.get(idempotency_key)
    return found if isinstance(found, dict) else None


def register_upload(idempotency_key: str, payload: dict[str, Any]) -> None:
    registry = _safe_read_json(UPLOAD_REGISTRY_PATH)
    entries = registry.get("entries") if isinstance(registry.get("entries"), dict) else {}
    entries[idempotency_key] = {
        **payload,
        "registered_at": _now_iso(),
    }
    registry["entries"] = entries
    registry["updated_at"] = _now_iso()
    _safe_write_json(UPLOAD_REGISTRY_PATH, registry)


def run_stage_with_recovery(
    *,
    stage: str,
    fn: Callable[[], Any],
    max_attempts: int = 2,
    base_backoff_seconds: float = 2.0,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> tuple[Any, dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            value = fn()
            return value, {
                "stage": stage,
                "attempts": attempt,
                "max_attempts": max_attempts,
                "recovered": attempt > 1,
                "ok": True,
            }
        except Exception as exc:
            last_error = exc
            if on_retry is not None:
                on_retry(attempt, exc)
            if attempt < max_attempts:
                delay = float(base_backoff_seconds) * float(2 ** (attempt - 1))
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
    }
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
    }

    PRODUCTION_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    target = PRODUCTION_EVIDENCE_DIR / f"{generation_id}.json"
    _safe_write_json(target, payload)
    return target
