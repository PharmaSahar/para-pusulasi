"""
Scheduler Sağlık ve Bakım Araçları
- Disk temizleme (eski render dosyaları)
- Bellek temizleme
- Akıllı retry
- Telegram bildirimleri
- Topic deduplication
"""
import gc
import hashlib
import json
import logging
import os
import re
import shutil
import time
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fcntl

from dotenv import dotenv_values
from .channel_manager import resolve_allow_market_language
from .retry_policy import classify_retry_decision, consume_retry_budget, get_retry_budget_state, retry_budget_context

logger = logging.getLogger("SchedulerUtils")
STARTUP_BANNER_NAME = "Parapusulasi"
CHANNEL_REGISTRY_PATH = Path("channels/channel_registry.json")
ACTIVE_QUEUE_STATUSES = {"active", "restored"}
QUARANTINE_TRAIL_PATH = Path("logs/queue_quarantine_decisions.jsonl")
QUEUE_FORBIDDEN_MARKET_RE = re.compile(
    r"\b(bist\w*|borsa\w*|hisse\w*|dolar\w*|usd\w*|try\w*|bitcoin\w*|ethereum\w*|btc\w*|eth\w*|kripto\w*|altin\w*|faiz\w*|enflasyon\w*|yatirim\w*|temettu\w*|portfoy\w*|teknik\s+analiz|temel\s+analiz|risk\s+yonetimi|finans\w*|doviz\w*|kur\w*)\b",
    re.IGNORECASE,
)

PROVIDER_HEALTH_FILE = "output/state/provider_health.json"
PROVIDER_HEALTH_LOCK_FILE = "output/state/provider_health.lock"
PROVIDER_HEALTH_DIAGNOSTICS_FILE = Path("output/state/provider_health_diagnostics.jsonl")
PROVIDER_HEALTH_CORRUPTION_FILE = Path("output/state/provider_health_corruption.json")
INCIDENT_STATE_FILE = Path("output/state/incident_state.json")
INCIDENT_EVENTS_FILE = Path("logs/production_incidents.jsonl")
INCIDENT_METRICS_FILE = Path("output/state/incident_metrics_latest.json")
INCIDENT_LOCK_FILE = Path("output/state/incident_state.lock")
_INCIDENT_THREAD_LOCK = threading.Lock()
_PROVIDER_HEALTH_THREAD_LOCK = threading.Lock()


def _incident_debug_mode_enabled() -> bool:
    return str(os.getenv("PRODUCTION_ALERT_DEBUG_MODE", "false")).strip().lower() in {"1", "true", "yes", "on"}


def _jsonl_append(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    _enforce_jsonl_bounds(path)


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _incident_io_lock():
    INCIDENT_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _INCIDENT_THREAD_LOCK:
        with INCIDENT_LOCK_FILE.open("a+", encoding="utf-8") as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _get_incident_max_records() -> int:
    return max(100, _get_int_env("INCIDENT_STATE_MAX_RECORDS", 5000))


def _get_incident_retention_days() -> int:
    return max(1, _get_int_env("INCIDENT_STATE_RETENTION_DAYS", 14))


def _get_incident_events_max_lines() -> int:
    return max(1, _get_int_env("INCIDENT_EVENTS_MAX_LINES", 50000))


def _prune_incident_state(state: dict) -> dict:
    incidents = dict(state.get("incidents") or {})
    if not incidents:
        return state

    now = _now_utc()
    cutoff = now - timedelta(days=_get_incident_retention_days())
    max_records = _get_incident_max_records()

    def _incident_ts(inc: dict) -> datetime:
        for key in ("updated_at", "resolved_at", "opened_at"):
            parsed = _parse_iso_utc(str((inc or {}).get(key) or ""))
            if parsed is not None:
                return parsed
        return datetime.fromtimestamp(0, tz=timezone.utc)

    kept: dict[str, dict] = {}
    for incident_id, inc in incidents.items():
        ts = _incident_ts(inc)
        if ts < cutoff:
            continue
        kept[str(incident_id)] = dict(inc or {})

    if len(kept) > max_records:
        sorted_items = sorted(
            kept.items(),
            key=lambda item: _incident_ts(item[1]),
            reverse=True,
        )
        kept = dict(sorted_items[:max_records])

    open_map = dict(state.get("open_by_fingerprint") or {})
    live_ids = set(kept.keys())
    cleaned_open = {
        key: value
        for key, value in open_map.items()
        if str((value or {}).get("incident_id") or "") in live_ids
    }

    state["incidents"] = kept
    state["open_by_fingerprint"] = cleaned_open
    return state


def _enforce_jsonl_bounds(path: Path) -> None:
    max_lines = _get_incident_events_max_lines()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    if len(lines) <= max_lines:
        return
    trimmed = "\n".join(lines[-max_lines:]) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(trimmed, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        logger.warning("Incident JSONL rotation failed: %s", path)


def _load_incident_state() -> dict:
    if not INCIDENT_STATE_FILE.exists():
        return {"open_by_fingerprint": {}, "incidents": {}}
    try:
        payload = json.loads(INCIDENT_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"open_by_fingerprint": {}, "incidents": {}}
    if not isinstance(payload, dict):
        return {"open_by_fingerprint": {}, "incidents": {}}
    payload.setdefault("open_by_fingerprint", {})
    payload.setdefault("incidents", {})
    return _prune_incident_state(payload)


def _save_incident_state(payload: dict) -> None:
    _atomic_write_json(INCIDENT_STATE_FILE, payload)


def _sanitize_operator_text(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return text
    if _incident_debug_mode_enabled():
        return text
    # Keep alerts operator-friendly: hide raw filesystem paths unless debug is on.
    path_patterns = (
        r"[A-Za-z]:\\[^\s]+",  # Windows drive path
        r"\\\\[^\s]+",  # UNC path
        r"/(?:Users|home|var|opt|tmp|private|etc|Volumes)/[^\s]+",  # Unix absolute paths
        r"(?:^|\s)(?:\.{1,2}/)?(?:channels|output|logs|artifacts|config|src|tests)/[^\s]+",  # Relative project paths
    )
    for pattern in path_patterns:
        text = re.sub(pattern, " [path_hidden]" if pattern.startswith("(?:^|\\s)") else "[path_hidden]", text)
    text = re.sub(r"(?<!https:)(?<!http:)(?<!ftp:)\b[\w.-]+(?:/[\w.-]+)+", "[path_hidden]", text)
    return " ".join(text.split())


def _classify_collision_reason(*, error_text: str, trace: dict | None = None, expected_channel: str = "", detected_channel: str = "") -> str:
    txt = str(error_text or "").lower()
    tr = dict(trace or {})
    rejected = [str((item or {}).get("reason") or "").lower() for item in (tr.get("rejected_candidates") or [])]

    if expected_channel and detected_channel and expected_channel != detected_channel:
        return "metadata mismatch"
    if "cross_channel_topic_contamination" in txt or "topic_provenance_collision" in txt:
        return "cross-channel cache reuse"
    if "inherit" in txt or "fallback_source" in tr:
        return "wrong topic inheritance"
    if any("market_term_not_allowed_for_non_market_niche" in r for r in rejected):
        return "llm hallucinated category"
    if any("missing_expected_domain_anchor" in r or "missing_market_domain_anchor" in r for r in rejected):
        return "planner selected invalid topic"
    if "overlap" in txt or "similar" in txt:
        return "keyword overlap"
    return "unknown"


def _incident_error_type(summary_text: str) -> str:
    txt = str(summary_text or "").lower()
    if "topic_provenance_collision" in txt:
        return "topic_provenance_collision"
    if "topic_domain_blocked" in txt:
        return "topic_domain_blocked"
    if "credit balance" in txt:
        return "credit"
    if "quota" in txt:
        return "quota"
    if "anthropic circuit open" in txt:
        return "provider_circuit_open"
    if "failed_fact_check" in txt:
        return "failed_fact_check"
    if "timeout" in txt or "dns" in txt or "connection" in txt:
        return "network"
    return "unknown"


def _compute_incident_fingerprint(*, channel_name: str, error_type: str, decision: str, run_id: str, content_id: str, pipeline_stage: str) -> str:
    key = "|".join(
        [
            str(channel_name or "").strip().lower(),
            str(error_type or "unknown").strip().lower(),
            str(decision or "").strip().lower(),
            str(run_id or "").strip(),
            str(content_id or "").strip(),
            str(pipeline_stage or "").strip().lower(),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _extract_collision_path(error_text: str, context: dict) -> str:
    explicit = str(context.get("collision_path") or "").strip()
    if explicit:
        return explicit
    raw = str(error_text or "")
    if "topic_provenance_collision:" not in raw:
        return ""
    return raw.split("topic_provenance_collision:", 1)[-1].strip()


def _load_collision_trace(collision_path: str) -> dict:
    path = Path(str(collision_path or "").strip())
    if not collision_path or not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _build_incident_event(*, lifecycle_event: str, incident_id: str, channel_name: str, severity: str, event_type: str, decision: str, duration_ms: int, retry_count: int, regeneration_count: int, run_id: str, pipeline_stage: str, context: dict) -> dict:
    now_iso = _format_iso_utc(_now_utc())
    payload = {
        "timestamp": now_iso,
        "incident_id": incident_id,
        "run_id": run_id,
        "channel": channel_name,
        "pipeline_stage": pipeline_stage or str(context.get("pipeline_stage") or "unknown"),
        "severity": severity,
        "event_type": event_type,
        "decision": decision,
        "duration_ms": max(0, _safe_int(duration_ms, 0)),
        "retry_count": max(0, retry_count),
        "regeneration_count": max(0, regeneration_count),
        "incident_lifecycle": lifecycle_event,
        "next_action": str(context.get("next_action") or ""),
        "error_type": str(context.get("error_type") or "unknown"),
        "error_summary": str(context.get("error_summary") or ""),
    }

    if str(context.get("error_type") or "") == "topic_provenance_collision":
        collision_path = _extract_collision_path(str(context.get("raw_error") or ""), context)
        trace_payload = _load_collision_trace(collision_path)
        expected_channel = str(context.get("expected_channel") or channel_name)
        detected_channel = str(context.get("detected_channel") or trace_payload.get("channel_id") or expected_channel)
        selected_topic = str(context.get("selected_topic") or trace_payload.get("selected_topic") or "")
        original_topic_source = str(
            context.get("original_topic_source")
            or trace_payload.get("provider_name")
            or (trace_payload.get("runtime_build_identity") or {}).get("git_sha_short")
            or "unknown"
        )
        collision_reason = _classify_collision_reason(
            error_text=str(context.get("raw_error") or ""),
            trace=trace_payload,
            expected_channel=expected_channel,
            detected_channel=detected_channel,
        )

        payload.update(
            {
                "expected_channel": expected_channel,
                "detected_channel": detected_channel,
                "selected_topic": selected_topic,
                "original_topic_source": original_topic_source,
                "provenance_score": context.get("provenance_score") if context.get("provenance_score") is not None else trace_payload.get("provenance_score"),
                "confidence_score": context.get("confidence_score") if context.get("confidence_score") is not None else trace_payload.get("confidence_score"),
                "triggering_validator": str(
                    context.get("triggering_validator")
                    or ((context.get("guard_reason_codes") or [""])[0] if isinstance(context.get("guard_reason_codes"), list) else "")
                    or "topic_provenance_validator"
                ),
                "retry_number": max(0, retry_count),
                "regeneration_number": max(0, regeneration_count),
                "decision_taken": decision,
                "next_action": str(context.get("next_action") or "quarantine_for_review"),
                "collision_diagnostics": collision_reason,
                "collision_path": collision_path if _incident_debug_mode_enabled() else "",
            }
        )
    return payload


def _update_incident_metrics(state: dict) -> dict:
    incidents = dict(state.get("incidents") or {})
    now = _now_utc()
    one_hour_ago = now - timedelta(hours=1)

    collisions_hour = 0
    collisions_channel: dict[str, int] = {}
    collision_reasons: dict[str, int] = {}
    regen_total = 0
    regen_success = 0
    retry_total = 0
    retry_success = 0
    recovery_durations_ms: list[int] = []

    for _, inc in incidents.items():
        channel = str(inc.get("channel") or "unknown")
        error_type = str(inc.get("error_type") or "unknown")
        opened_at = _parse_iso_utc(str(inc.get("opened_at") or ""))
        status = str(inc.get("status") or "open")
        retry_max = max(0, _safe_int(inc.get("max_retry_count"), 0))
        regen_max = max(0, _safe_int(inc.get("max_regeneration_count"), 0))
        collision_reason = str(inc.get("top_collision_reason") or "unknown")

        if error_type == "topic_provenance_collision":
            collisions_channel[channel] = collisions_channel.get(channel, 0) + 1
            collision_reasons[collision_reason] = collision_reasons.get(collision_reason, 0) + 1
            if opened_at and opened_at >= one_hour_ago.replace(tzinfo=opened_at.tzinfo):
                collisions_hour += 1

        if retry_max > 0:
            retry_total += 1
            if status == "resolved":
                retry_success += 1

        if regen_max > 0:
            regen_total += 1
            if status == "resolved":
                regen_success += 1

        if status == "resolved":
            resolved_at = _parse_iso_utc(str(inc.get("resolved_at") or ""))
            if opened_at and resolved_at:
                recovery_durations_ms.append(max(0, int((resolved_at - opened_at).total_seconds() * 1000)))

    mean_recovery = int(sum(recovery_durations_ms) / len(recovery_durations_ms)) if recovery_durations_ms else 0
    top_collision_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(collision_reasons.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    snapshot = {
        "generated_at": _format_iso_utc(now),
        "collisions_per_hour": collisions_hour,
        "collisions_per_channel": collisions_channel,
        "regeneration_success_rate": (regen_success / regen_total) if regen_total else 0.0,
        "retry_success_rate": (retry_success / retry_total) if retry_total else 0.0,
        "mean_recovery_time_ms": mean_recovery,
        "top_collision_reasons": top_collision_reasons,
        "incident_count": len(incidents),
    }
    _atomic_write_json(INCIDENT_METRICS_FILE, snapshot)
    return snapshot


def _register_incident_event(*, lifecycle_event: str, channel_name: str, severity: str, decision: str, next_action: str, error_summary: str, raw_error: str, context: dict | None = None) -> dict:
    ctx = dict(context or {})
    run_id = str(ctx.get("run_id") or "")
    content_id = str(ctx.get("content_id") or "")
    pipeline_stage = str(ctx.get("pipeline_stage") or "scheduler")
    retry_count = max(0, _safe_int(ctx.get("retry_count"), 0))
    regeneration_count = max(0, _safe_int(ctx.get("regeneration_count"), 0))
    retry_limit = max(0, _safe_int(ctx.get("retry_limit"), 0))
    regeneration_limit = max(0, _safe_int(ctx.get("regeneration_limit"), 0))
    error_type = str(ctx.get("error_type") or _incident_error_type(error_summary)).strip().lower() or "unknown"
    ctx["error_type"] = error_type
    ctx["next_action"] = next_action
    ctx["error_summary"] = error_summary
    ctx["raw_error"] = raw_error

    fingerprint = str(ctx.get("incident_fingerprint") or _compute_incident_fingerprint(
        channel_name=channel_name,
        error_type=error_type,
        decision=decision,
        run_id=run_id,
        content_id=content_id,
        pipeline_stage=pipeline_stage,
    ))

    with _incident_io_lock():
        state = _load_incident_state()
        open_map = state.setdefault("open_by_fingerprint", {})
        incidents = state.setdefault("incidents", {})
        now = _now_utc()
        now_iso = _format_iso_utc(now)
        opened = open_map.get(fingerprint)

        if lifecycle_event == "INCIDENT_RESOLVED":
            if not opened:
                return {"lifecycle_event": "INCIDENT_RESOLVED_SKIPPED"}
            incident_id = str(opened.get("incident_id") or "")
            summary = dict(incidents.get(incident_id) or {})
            summary["status"] = "resolved"
            summary["resolved_at"] = now_iso
            summary["last_error_summary"] = error_summary
            summary["last_decision"] = decision
            summary["max_retry_count"] = max(_safe_int(summary.get("max_retry_count"), 0), retry_count)
            summary["max_regeneration_count"] = max(_safe_int(summary.get("max_regeneration_count"), 0), regeneration_count)
            incidents[incident_id] = summary
            open_map.pop(fingerprint, None)

            event_payload = _build_incident_event(
                lifecycle_event="INCIDENT_RESOLVED",
                incident_id=incident_id,
                channel_name=channel_name,
                severity=severity,
                event_type="incident_resolved",
                decision=decision,
                duration_ms=int((now - _parse_iso_utc(str(summary.get("opened_at") or now_iso)) ).total_seconds() * 1000) if _parse_iso_utc(str(summary.get("opened_at") or "")) else 0,
                retry_count=retry_count,
                regeneration_count=regeneration_count,
                run_id=run_id,
                pipeline_stage=pipeline_stage,
                context=ctx,
            )
            _jsonl_append(INCIDENT_EVENTS_FILE, event_payload)
            _prune_incident_state(state)
            _save_incident_state(state)
            _update_incident_metrics(state)
            return {
                "incident_id": incident_id,
                "lifecycle_event": "INCIDENT_RESOLVED",
                "retry_count": retry_count,
                "retry_limit": retry_limit,
                "regeneration_count": regeneration_count,
                "regeneration_limit": regeneration_limit,
                "event": event_payload,
            }

        if opened:
            incident_id = str(opened.get("incident_id") or "")
            lifecycle = "INCIDENT_UPDATED"
        else:
            incident_id = str(uuid.uuid4())
            lifecycle = "INCIDENT_OPEN"
            open_map[fingerprint] = {
                "incident_id": incident_id,
                "channel": channel_name,
                "opened_at": now_iso,
                "error_type": error_type,
            }

        summary = dict(incidents.get(incident_id) or {})
        summary.update(
            {
                "incident_id": incident_id,
                "fingerprint": fingerprint,
                "channel": channel_name,
                "error_type": error_type,
                "status": "open",
                "opened_at": summary.get("opened_at") or now_iso,
                "updated_at": now_iso,
                "run_id": run_id,
                "pipeline_stage": pipeline_stage,
                "last_error_summary": error_summary,
                "last_decision": decision,
                "max_retry_count": max(_safe_int(summary.get("max_retry_count"), 0), retry_count),
                "max_regeneration_count": max(_safe_int(summary.get("max_regeneration_count"), 0), regeneration_count),
                "top_collision_reason": str(ctx.get("collision_diagnostics") or summary.get("top_collision_reason") or "unknown"),
            }
        )
        incidents[incident_id] = summary

        event_payload = _build_incident_event(
            lifecycle_event=lifecycle,
            incident_id=incident_id,
            channel_name=channel_name,
            severity=severity,
            event_type="incident_opened" if lifecycle == "INCIDENT_OPEN" else "incident_updated",
            decision=decision,
            duration_ms=0,
            retry_count=retry_count,
            regeneration_count=regeneration_count,
            run_id=run_id,
            pipeline_stage=pipeline_stage,
            context=ctx,
        )
        _jsonl_append(INCIDENT_EVENTS_FILE, event_payload)
        _prune_incident_state(state)
        _save_incident_state(state)
        _update_incident_metrics(state)
        return {
            "incident_id": incident_id,
            "lifecycle_event": lifecycle,
            "retry_count": retry_count,
            "retry_limit": retry_limit,
            "regeneration_count": regeneration_count,
            "regeneration_limit": regeneration_limit,
            "event": event_payload,
        }


def _resolve_open_incidents_for_channel(channel_name: str, *, run_id: str = "", pipeline_stage: str = "upload", severity: str = "INFO") -> list[dict]:
    state = _load_incident_state()
    open_map = dict(state.get("open_by_fingerprint") or {})
    resolved: list[dict] = []
    for fingerprint, meta in open_map.items():
        if str(meta.get("channel") or "") != str(channel_name or ""):
            continue
        result = _register_incident_event(
            lifecycle_event="INCIDENT_RESOLVED",
            channel_name=channel_name,
            severity=severity,
            decision="resolved_after_successful_upload",
            next_action="monitor_next_cycle",
            error_summary="Upload successful; incident resolved.",
            raw_error="",
            context={
                "incident_fingerprint": fingerprint,
                "run_id": run_id,
                "pipeline_stage": pipeline_stage,
            },
        )
        if result.get("lifecycle_event") == "INCIDENT_RESOLVED":
            resolved.append(result)
    return resolved


def _get_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except Exception:
        return default
    return value if value > 0 else default

# ─── BÜYÜME MİLESTONE TAKİBİ ─────────────────────────────────────────────────
# Toplam yüklenen video sayısına göre otomatik yükseltme hatırlatması

MILESTONES_FILE = "output/queue/milestones.json"

UPGRADE_MILESTONES = [
    {
        "videos": 300,
        "title": "🎯 Milestone: 300 Video!",
        "message": (
            "Tebrikler! 300 video yüklendi.\n\n"
            "💡 <b>ElevenLabs Pro'ya geçme zamanı</b> ($99/ay)\n"
            "• 600k kredi/ay → 1 kanal için tüm yıl yeter\n"
            "• Ses kalitesi dramatik artış\n"
            "• Ticari lisans dahil\n"
            "• elevenlabs.io/app/subscription"
        ),
    },
    {
        "videos": 1500,
        "title": "🚀 Milestone: 1.500 Video!",
        "message": (
            "1.500 video — sistem tam otomasyonda!\n\n"
            "💡 <b>ElevenLabs Scale değerlendirin</b> ($299/ay)\n"
            "• 1.8M kredi/ay → 5-6 kanal için yeter\n"
            "• Ekip işbirliği özelliği\n"
            "• elevenlabs.io/app/subscription"
        ),
    },
    {
        "videos": 5000,
        "title": "🏆 Milestone: 5.000 Video!",
        "message": (
            "5.000 video — profesyonel medya şirketi seviyesi!\n\n"
            "💡 <b>ElevenLabs Business düşünün</b> ($990/ay)\n"
            "• 6M kredi/ay → tüm 10 kanal ElevenLabs ile çalışır\n"
            "• 10 Profesyonel Ses Klonu hakkı\n"
            "• Düşük gecikme streaming API\n"
            "• elevenlabs.io/app/subscription"
        ),
    },
    {
        "videos": 15000,
        "title": "🌟 Milestone: 15.000 Video!",
        "message": (
            "15.000 video — Enterprise seviyesi!\n\n"
            "💡 <b>ElevenLabs Enterprise</b> (özel fiyat)\n"
            "• Özel kredi hacmi + volume indirim\n"
            "• SLA garantisi\n"
            "• Satış ekibiyle görüş: elevenlabs.io/enterprise"
        ),
    },
]


def _load_milestones() -> dict:
    p = Path(MILESTONES_FILE)
    if not p.exists():
        return {"reached": [], "total_videos": 0}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"reached": [], "total_videos": 0}


def _save_milestones(data: dict):
    Path(MILESTONES_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(MILESTONES_FILE).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def check_growth_milestones(new_video_count: int = 1):
    """
    Her video yüklemesinde çağır.
    Milestone geçildiyse Telegram'a hatırlatma gönderir (bir kez).
    """
    data = _load_milestones()
    data["total_videos"] = data.get("total_videos", 0) + new_video_count
    total = data["total_videos"]
    reached = set(data.get("reached", []))

    for ms in UPGRADE_MILESTONES:
        key = str(ms["videos"])
        if total >= ms["videos"] and key not in reached:
            reached.add(key)
            send_telegram(
                f"{ms['title']}\n"
                f"📊 Toplam yüklenen video: <b>{total}</b>\n\n"
                f"{ms['message']}"
            )
            logger.info(f"Milestone ulaşıldı: {ms['videos']} video")

    data["reached"] = list(reached)
    _save_milestones(data)


def get_total_uploaded_videos() -> int:
    """Şimdiye kadar yüklenen toplam video sayısını döndür."""
    return _load_milestones().get("total_videos", 0)


# ─── DISK TEMİZLEME ──────────────────────────────────────────────────────────

def cleanup_old_renders(max_age_hours: int = 48, min_free_gb: float = 2.0):
    """
    48 saatten eski render dosyalarını sil.
    Disk dolmak üzereyse daha agresif temizlik yap.
    """
    deleted_mb = 0
    free_gb = get_free_disk_gb()

    # Disk kritik seviyedeyse daha agresif temizle
    age_hours = max_age_hours if free_gb > min_free_gb else 6

    cutoff = datetime.now() - timedelta(hours=age_hours)
    cleanup_dirs = []

    # Kanal bazlı output klasörleri
    for channel_dir in Path("channels").glob("*/output"):
        cleanup_dirs.append(channel_dir)

    # Ana output klasörü
    cleanup_dirs.append(Path("output"))

    for base_dir in cleanup_dirs:
        for subdir in ["videos", "audio", "clips", "shorts"]:
            target = base_dir / subdir
            if not target.exists():
                continue
            for f in target.iterdir():
                if not f.is_file():
                    continue
                # Thumbnail'leri koru
                if f.suffix in (".jpg", ".jpeg", ".png"):
                    continue
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        size_mb = f.stat().st_size / 1_048_576
                        f.unlink()
                        deleted_mb += size_mb
                except Exception as e:
                    logger.warning(f"Silme hatası {f}: {e}")

    if deleted_mb > 0:
        logger.info(f"Disk temizleme: {deleted_mb:.0f} MB silindi. Boş: {get_free_disk_gb():.1f} GB")

    return deleted_mb


def get_free_disk_gb() -> float:
    """Mevcut boş disk alanını GB olarak döndür."""
    try:
        stat = shutil.disk_usage(".")
        return stat.free / 1_073_741_824
    except Exception:
        return 99.0


def check_disk_space(min_gb: float = 1.5) -> bool:
    """Disk yeterliyse True, kritik seviyedeyse False döndür."""
    free = get_free_disk_gb()
    if free < min_gb:
        logger.error(f"⚠️ DİSK KRİTİK: {free:.1f} GB kaldı! Temizlik başlıyor...")
        cleanup_old_renders(max_age_hours=6)
        return get_free_disk_gb() > 0.5
    return True


# ─── BELLEK YÖNETİMİ ─────────────────────────────────────────────────────────

def force_cleanup():
    """MoviePy ve diğer kütüphanelerden sonra belleği temizle."""
    try:
        # MoviePy video clip'lerini kapat
        import moviepy
        # Garbage collection
        gc.collect()
        # Önbelleği boşalt
        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass
    except Exception:
        pass
    gc.collect()


# ─── TELEGRAM BİLDİRİMLERİ ───────────────────────────────────────────────────

def send_telegram(message: str):
    """Telegram üzerinden bildirim gönder. Token her çağrıda env'den okunur."""
    # Her çağrıda env'den oku — modül import sırasında değil (dotenv geç yükleniyor)
    from dotenv import dotenv_values
    import pathlib
    env = {}
    for env_path in [".env", "/opt/parapusulasi/.env"]:
        if pathlib.Path(env_path).exists():
            env = dotenv_values(env_path)
            break
    token = env.get("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
    except Exception as e:
        logger.warning(f"Telegram bildirimi gönderilemedi: {e}")


def notify_upload(channel_name: str, title: str, url: str, short_url: str = ""):
    try:
        resolved = _resolve_open_incidents_for_channel(channel_name, pipeline_stage="upload")
    except Exception as e:
        logger.warning("Incident resolve telemetry failed (non-blocking): %s", e)
        resolved = []
    send_telegram(
        f"✅ <b>Yeni Video Yüklendi!</b>\n"
        f"📺 Kanal: {channel_name}\n"
        f"🎬 {title[:60]}\n"
        f"🔗 {url}"
        + (f"\n📱 Short: {short_url}" if short_url else "")
        + (f"\n🟢 Incident Resolved: {', '.join(str(item.get('incident_id') or '') for item in resolved if item.get('incident_id'))}" if resolved else "")
    )


def notify_error(channel_name: str, error: str, context: dict | None = None) -> dict:
    raw_error = str(error or "")
    context_payload = dict(context or {})
    error_text = _sanitize_operator_text(_summarize_error_for_telegram(raw_error))
    decision = _classify_error_decision(error_text)
    retry_count = max(0, _safe_int(context_payload.get("retry_count"), 0))
    retry_limit = max(0, _safe_int(context_payload.get("retry_limit"), 3))
    regeneration_count = max(0, _safe_int(context_payload.get("regeneration_count"), 0))
    regeneration_limit = max(0, _safe_int(context_payload.get("regeneration_limit"), 1))
    severity = str(context_payload.get("severity") or ("ERROR" if "fatal" in raw_error.lower() else "WARNING")).upper()

    context_payload.setdefault("error_type", _incident_error_type(raw_error or error_text))
    context_payload.setdefault("run_id", str(context_payload.get("run_id") or ""))
    context_payload.setdefault("pipeline_stage", str(context_payload.get("pipeline_stage") or "scheduler_render"))
    context_payload.setdefault("retry_count", retry_count)
    context_payload.setdefault("retry_limit", retry_limit)
    context_payload.setdefault("regeneration_count", regeneration_count)
    context_payload.setdefault("regeneration_limit", regeneration_limit)
    context_payload.setdefault("next_action", decision["action_label"])

    try:
        incident_state = _register_incident_event(
            lifecycle_event="INCIDENT_UPDATED",
            channel_name=channel_name,
            severity=severity,
            decision=decision["decision"],
            next_action=decision["action_label"],
            error_summary=error_text,
            raw_error=raw_error,
            context=context_payload,
        )
    except Exception as e:
        logger.warning("Incident telemetry write failed (non-blocking): %s", e)
        incident_state = {
            "incident_id": "",
            "lifecycle_event": "INCIDENT_OBSERVABILITY_UNAVAILABLE",
        }

    alert_key = _build_render_error_alert_key(channel_name, error_text, decision["decision"], severity=severity)
    cooldown_hours = 6 if decision["decision"] == "skip_current_item" else 2
    if not _should_alert(alert_key, cooldown_hours=cooldown_hours):
        logger.info(
            "Telegram render error alert suppressed by cooldown: %s incident_id=%s",
            alert_key,
            incident_state.get("incident_id", ""),
        )
        merged = dict(decision)
        merged.update(
            {
                "incident_id": incident_state.get("incident_id", ""),
                "incident_lifecycle": incident_state.get("lifecycle_event", "INCIDENT_UPDATED"),
                "retry_count": retry_count,
                "retry_limit": retry_limit,
                "regeneration_count": regeneration_count,
                "regeneration_limit": regeneration_limit,
            }
        )
        return merged

    incident_id = str(incident_state.get("incident_id") or "")
    lifecycle = str(incident_state.get("lifecycle_event") or "INCIDENT_UPDATED")

    send_telegram(
        f"🚨 <b>{lifecycle}</b>\n"
        f"📌 Severity: {severity}\n"
        f"🆔 Incident ID: {incident_id or 'N/A'}\n"
        f"📺 Kanal: {channel_name}\n"
        f"🧩 Error Type: {context_payload.get('error_type', 'unknown')}\n"
        f"❌ {error_text}\n"
        f"🧭 Decision: {decision['decision_label']}\n"
        f"🔧 Next Action: {decision['action_label']}\n"
        f"🔁 Retry: {retry_count}/{retry_limit}\n"
        f"♻️ Regeneration: {regeneration_count}/{regeneration_limit}"
    )
    _mark_alert_sent(alert_key)
    merged = dict(decision)
    merged.update(
        {
            "incident_id": incident_id,
            "incident_lifecycle": lifecycle,
            "retry_count": retry_count,
            "retry_limit": retry_limit,
            "regeneration_count": regeneration_count,
            "regeneration_limit": regeneration_limit,
        }
    )
    return merged


def _build_render_error_alert_key(channel_name: str, error_text: str, decision_name: str, severity: str = "WARNING") -> str:
    """Create a stable alert key so provider cooldown storms do not spam per channel."""
    normalized_channel = channel_name.strip().lower()
    normalized_error = " ".join(str(error_text or "").strip().lower().split())
    # Retry-after seconds change every run; collapse them for stable dedupe keys.
    normalized_error = re.sub(r"\(\s*\d+\s*s\s*\)", "(cooldown)", normalized_error)
    normalized_severity = str(severity or "WARNING").strip().upper() or "WARNING"

    scope = f"channel::{normalized_channel}"
    if "anthropic circuit open" in normalized_error or "provider is cooling down" in normalized_error:
        scope = "provider::anthropic::cooldown"
    elif "global overload pause open" in normalized_error:
        scope = "global::overload_pause"

    return f"render_error::{scope}::{normalized_severity}::{decision_name}::{normalized_error}"


def _summarize_error_for_telegram(error: str, max_len: int = 220) -> str:
    """Ham exception metnini Telegram için okunur bir özete indirger."""
    raw = " ".join(str(error or "").split())
    if not raw:
        return "Bilinmeyen hata"

    status_match = re.search(r"status_code:\s*(\d+)", raw)
    status_code = status_match.group(1) if status_match else None

    detail = None
    for pattern in (
        r"['\"]message['\"]:\s*['\"]([^'\"]+)['\"]",
        r"['\"]code['\"]:\s*['\"]([^'\"]+)['\"]",
    ):
        m = re.search(pattern, raw)
        if m:
            detail = m.group(1)
            break

    cleaned = re.sub(r"headers:\s*\{.*?\},\s*", "", raw)
    summary = cleaned
    if status_code and detail:
        summary = f"HTTP {status_code} - {detail}"
    elif status_code:
        summary = f"HTTP {status_code} - {cleaned}"
    elif detail:
        summary = detail

    if len(summary) > max_len:
        summary = summary[: max_len - 3] + "..."
    return summary


def _classify_error_decision(summary: str) -> dict:
    """Render hatasından operasyon kararı türetir."""
    txt = str(summary or "").lower()

    if any(k in txt for k in ("invalid api key", "unauthorized", "http 401", "authentication")):
        return {
            "decision": "continue_without_provider",
            "decision_label": "Uretim devam (problemli provider disi)",
            "action_label": "API anahtari kontrol et; fallback TTS ile devam",
            "retry": False,
        }

    if any(k in txt for k in (
        "quota",
        "credit balance",
        "http 429",
        "http 529",
        "rate limit",
        "overloaded",
        "overloaded_error",
        "service unavailable",
        "internal server error",
    )):
        return {
            "decision": "continue_with_backoff",
            "decision_label": "Uretim devam (bekleme/backoff)",
            "action_label": "Kota/kredi yenilenene kadar yeniden deneme araligini artir",
            "retry": True,
        }

    if any(k in txt for k in ("failed_fact_check", "fact check fail", "niche_alignment_failed")):
        return {
            "decision": "skip_current_item",
            "decision_label": "Bu icerik atlandi, sonraki isleme gec",
            "action_label": "Kanal ve topic policy kontrolu",
            "retry": False,
        }

    if any(k in txt for k in ("timeout", "connection", "response ended prematurely", "dns", "chunkedencodingerror")):
        return {
            "decision": "retry_then_continue",
            "decision_label": "Gecici hata: retry sonra devam",
            "action_label": "Ag kararliligi kontrolu, fallback kullan",
            "retry": True,
        }

    return {
        "decision": "continue_with_monitoring",
        "decision_label": "Uretim devam, izleme artirildi",
        "action_label": "Ayni hata tekrarlarsa manuel inceleme",
        "retry": True,
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _provider_health_path() -> Path:
    return Path(PROVIDER_HEALTH_FILE)


def _provider_health_lock_path() -> Path:
    return Path(PROVIDER_HEALTH_LOCK_FILE)


def _emit_provider_health_diagnostic(event: str, payload: dict) -> None:
    row = {
        "event": str(event or "unknown"),
        "timestamp": _format_iso_utc(_now_utc()),
        "payload": dict(payload or {}),
    }
    try:
        PROVIDER_HEALTH_DIAGNOSTICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PROVIDER_HEALTH_DIAGNOSTICS_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except Exception:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_json_with_fsync(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    blob = json.dumps(payload, ensure_ascii=False, indent=2)
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(blob)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_directory(path.parent)


@contextmanager
def _provider_health_io_lock():
    lock_path = _provider_health_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _PROVIDER_HEALTH_THREAD_LOCK:
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _mark_provider_health_corruption(*, path: Path, raw: str, error: str) -> dict:
    details = {
        "status": "corrupt",
        "detected_at": _format_iso_utc(_now_utc()),
        "provider_health_path": str(path),
        "error": str(error or "provider_health_parse_error"),
        "raw_size": len(raw.encode("utf-8", errors="ignore")),
        "raw_sha256": hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest(),
    }
    try:
        _atomic_write_json_with_fsync(PROVIDER_HEALTH_CORRUPTION_FILE, details)
    except Exception:
        pass
    _emit_provider_health_diagnostic("provider_health_corruption_detected", details)
    return details


def _clear_provider_health_corruption_if_recovered(*, path: Path) -> None:
    if not PROVIDER_HEALTH_CORRUPTION_FILE.exists():
        return
    try:
        previous = json.loads(PROVIDER_HEALTH_CORRUPTION_FILE.read_text(encoding="utf-8"))
    except Exception:
        previous = {}
    try:
        PROVIDER_HEALTH_CORRUPTION_FILE.unlink(missing_ok=True)
    except Exception:
        return
    _emit_provider_health_diagnostic(
        "provider_health_corruption_recovered",
        {
            "provider_health_path": str(path),
            "previous_corruption": previous,
        },
    )


def _load_provider_health_state_unlocked() -> tuple[dict | None, dict | None]:
    path = _provider_health_path()
    if not path.exists():
        _clear_provider_health_corruption_if_recovered(path=path)
        return {"providers": {}}, None

    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        return None, _mark_provider_health_corruption(path=path, raw="", error=f"read_error:{exc}")

    try:
        data = json.loads(raw)
    except Exception as exc:
        return None, _mark_provider_health_corruption(path=path, raw=raw, error=f"json_parse_error:{exc}")

    if not isinstance(data, dict):
        return None, _mark_provider_health_corruption(path=path, raw=raw, error="json_root_not_object")

    providers = data.get("providers")
    if providers is None:
        data["providers"] = {}
    elif not isinstance(providers, dict):
        return None, _mark_provider_health_corruption(path=path, raw=raw, error="providers_not_object")

    _clear_provider_health_corruption_if_recovered(path=path)
    return data, None


def _provider_health_corruption_state(corruption: dict) -> dict:
    base = {
        "providers": {},
        "corruption": {
            "active": True,
            "diagnostic": dict(corruption or {}),
        },
    }
    return base


def _load_provider_health_state(*, fail_closed: bool = True) -> dict:
    with _provider_health_io_lock():
        state, corruption = _load_provider_health_state_unlocked()

    if corruption:
        if fail_closed:
            return _provider_health_corruption_state(corruption)
        return {"providers": {}}

    return dict(state or {"providers": {}})


def _mutate_provider_health_state(mutator, *, mutation_name: str) -> tuple[dict, dict | None]:
    with _provider_health_io_lock():
        state, corruption = _load_provider_health_state_unlocked()
        if corruption:
            _emit_provider_health_diagnostic(
                "provider_health_mutation_blocked",
                {
                    "mutation": mutation_name,
                    "reason": "provider_health_corrupt",
                    "corruption": corruption,
                },
            )
            return _provider_health_corruption_state(corruption), corruption

        mutable = dict(state or {"providers": {}})
        mutable.setdefault("providers", {})
        mutator(mutable)
        _atomic_write_json_with_fsync(_provider_health_path(), mutable)
        return mutable, None


def _error_type_from_text(error_text: str) -> str:
    txt = str(error_text or "").lower()
    if any(key in txt for key in ("billing", "payment required", "invoice", "card declined")):
        return "billing"
    if any(key in txt for key in ("credit balance", "insufficient credit")):
        return "credit"
    if "quota" in txt:
        return "quota"
    if any(key in txt for key in ("rate limit", "http 429")):
        return "rate_limit"
    if any(
        key in txt
        for key in ("overloaded", "overloaded_error", "http 529", "service unavailable", "internal server error")
    ):
        return "overload"
    if any(key in txt for key in ("authentication", "invalid api key", "unauthorized", "http 401")):
        return "auth"
    if any(key in txt for key in ("timeout", "connection", "dns", "chunkedencodingerror")):
        return "network"
    return "unknown"


def classify_provider_preflight_degraded_mode_error(error_text: str) -> dict:
    txt = str(error_text or "").strip()
    normalized = txt.lower()
    err_type = _error_type_from_text(normalized)

    eligible_types = {"billing", "credit", "quota", "rate_limit", "overload", "network"}
    eligible = err_type in eligible_types

    if not eligible and any(token in normalized for token in ("http 429", "http 500", "http 503", "http 529")):
        eligible = True
        err_type = "overload" if "http 529" in normalized else "rate_limit"

    reason_code = "provider_preflight_external_dependency_degraded" if eligible else f"provider_preflight_non_degradable_{err_type}"
    return {
        "eligible": eligible,
        "error_type": err_type,
        "reason_code": reason_code,
        "summary": _summarize_error_for_telegram(txt, max_len=240),
    }


def _extract_request_id(error_text: str) -> str:
    raw = str(error_text or "")
    match = re.search(r"(req_[A-Za-z0-9]+)", raw)
    return match.group(1) if match else ""


def _parse_iso_utc(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _format_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def get_global_overload_pause_status() -> dict:
    state = _load_provider_health_state(fail_closed=True)
    corruption = dict(state.get("corruption") or {})
    if bool(corruption.get("active")):
        return {
            "is_open": True,
            "retry_after_seconds": max(300, _get_int_env("PROVIDER_CORRUPTION_BLOCK_SECONDS", 900)),
            "pause_until": "",
            "reason": "provider_health_corrupt",
            "window_seconds": _get_int_env("PROVIDER_OVERLOAD_WINDOW_SECONDS", 300),
            "trigger_count": _get_int_env("PROVIDER_OVERLOAD_TRIGGER_COUNT", 3),
            "corruption": corruption,
        }

    pause_until_raw = str(state.get("global_overload_pause_until") or "").strip()
    retry_after_seconds = 0
    is_open = False
    parsed = _parse_iso_utc(pause_until_raw)
    if parsed is not None:
        now_utc = _now_utc().replace(tzinfo=parsed.tzinfo)
        if parsed > now_utc:
            is_open = True
            retry_after_seconds = max(0, int((parsed - now_utc).total_seconds()))

    return {
        "is_open": is_open,
        "retry_after_seconds": retry_after_seconds,
        "pause_until": pause_until_raw,
        "reason": str(state.get("global_overload_pause_reason") or ""),
        "window_seconds": _get_int_env("PROVIDER_OVERLOAD_WINDOW_SECONDS", 300),
        "trigger_count": _get_int_env("PROVIDER_OVERLOAD_TRIGGER_COUNT", 3),
        "corruption": {"active": False},
    }


def record_provider_failure(provider: str, error_text: str) -> dict:
    result_holder = {"provider_state": {}}

    def _mutator(state: dict) -> None:
        providers = state.setdefault("providers", {})
        provider_state = providers.setdefault(provider, {})

        failure_count = int(provider_state.get("consecutive_failures", 0)) + 1
        err_type = _error_type_from_text(error_text)
        now = _now_utc()

        open_seconds = 0
        if err_type in {"billing", "credit", "quota", "rate_limit", "auth", "overload", "network"}:
            open_seconds = min(7200, 300 * (2 ** max(0, failure_count - 1)))

        open_until = ""
        if open_seconds > 0:
            open_until = _format_iso_utc(now + timedelta(seconds=open_seconds))

        if err_type == "overload":
            window_seconds = _get_int_env("PROVIDER_OVERLOAD_WINDOW_SECONDS", 300)
            trigger_count = _get_int_env("PROVIDER_OVERLOAD_TRIGGER_COUNT", 3)
            pause_seconds = _get_int_env("PROVIDER_OVERLOAD_GLOBAL_PAUSE_SECONDS", 600)

            cutoff = now - timedelta(seconds=window_seconds)
            raw_events = list(state.get("overload_events") or [])
            kept_events = []
            for raw in raw_events:
                parsed = _parse_iso_utc(raw)
                if parsed is None:
                    continue
                if parsed >= cutoff.replace(tzinfo=parsed.tzinfo):
                    kept_events.append(_format_iso_utc(parsed))
            kept_events.append(_format_iso_utc(now.replace(tzinfo=timezone.utc)))
            state["overload_events"] = kept_events[-100:]

            if len(kept_events) >= trigger_count:
                proposed_until = _format_iso_utc(now.replace(tzinfo=timezone.utc) + timedelta(seconds=pause_seconds))
                existing_until_raw = str(state.get("global_overload_pause_until") or "")
                existing_dt = _parse_iso_utc(existing_until_raw)
                proposed_dt = _parse_iso_utc(proposed_until)
                if proposed_dt is not None and (existing_dt is None or proposed_dt > existing_dt):
                    state["global_overload_pause_until"] = proposed_until
                    state["global_overload_pause_reason"] = (
                        f"overload_storm:{len(kept_events)}/{window_seconds}s"
                    )

        provider_state.update(
            {
                "provider": provider,
                "consecutive_failures": failure_count,
                "last_failed_at": _format_iso_utc(now),
                "last_error": _summarize_error_for_telegram(error_text, max_len=400),
                "last_error_type": err_type,
                "last_request_id": _extract_request_id(error_text),
                "open_until": open_until,
            }
        )
        result_holder["provider_state"] = dict(provider_state)

    _, corruption = _mutate_provider_health_state(_mutator, mutation_name="record_provider_failure")
    if corruption:
        return {
            "provider": provider,
            "consecutive_failures": 0,
            "last_error_type": "provider_health_corrupt",
            "open_until": "",
            "corruption": dict(corruption),
        }
    return dict(result_holder["provider_state"])


def record_provider_success(provider: str, note: str = "") -> dict:
    result_holder = {"provider_state": {}}

    def _mutator(state: dict) -> None:
        providers = state.setdefault("providers", {})
        provider_state = providers.setdefault(provider, {})
        now = _now_utc()
        provider_state.update(
            {
                "provider": provider,
                "consecutive_failures": 0,
                "last_success_at": _format_iso_utc(now),
                "last_success_note": note,
                "open_until": "",
            }
        )
        result_holder["provider_state"] = dict(provider_state)

    _, corruption = _mutate_provider_health_state(_mutator, mutation_name="record_provider_success")
    if corruption:
        return {
            "provider": provider,
            "consecutive_failures": 0,
            "last_success_note": note,
            "open_until": "",
            "corruption": dict(corruption),
        }
    return dict(result_holder["provider_state"])


def get_provider_circuit_status(provider: str) -> dict:
    state = _load_provider_health_state(fail_closed=True)
    corruption = dict(state.get("corruption") or {})
    if bool(corruption.get("active")):
        return {
            "provider": provider,
            "is_open": True,
            "retry_after_seconds": max(300, _get_int_env("PROVIDER_CORRUPTION_BLOCK_SECONDS", 900)),
            "state": {
                "provider": provider,
                "last_error_type": "provider_health_corrupt",
                "corruption": corruption,
            },
            "corruption": corruption,
        }

    provider_state = state.get("providers", {}).get(provider, {})
    open_until_raw = str(provider_state.get("open_until") or "").strip()
    is_open = False
    retry_after_seconds = 0
    if open_until_raw:
        try:
            parsed = datetime.fromisoformat(open_until_raw.replace("Z", "+00:00"))
            now_utc = _now_utc().replace(tzinfo=parsed.tzinfo)
            if parsed > now_utc:
                is_open = True
                retry_after_seconds = max(0, int((parsed - now_utc).total_seconds()))
        except Exception:
            pass

    return {
        "provider": provider,
        "is_open": is_open,
        "retry_after_seconds": retry_after_seconds,
        "state": provider_state,
        "corruption": {"active": False},
    }


def _get_anthropic_key() -> str:
    for env_path in (".env", "/opt/parapusulasi/.env"):
        if Path(env_path).exists():
            env = dotenv_values(env_path)
            key = str(env.get("ANTHROPIC_API_KEY") or "").strip()
            if key:
                return key
    return str(os.getenv("ANTHROPIC_API_KEY") or "").strip()


def run_anthropic_preflight(model: str = "claude-opus-4-5") -> tuple[bool, str]:
    key = _get_anthropic_key()
    if not key:
        record_provider_failure("anthropic", "ANTHROPIC_API_KEY missing")
        return False, "missing_anthropic_api_key"

    try:
        from anthropic import Anthropic
    except Exception as e:
        record_provider_failure("anthropic", str(e))
        return False, _summarize_error_for_telegram(str(e), max_len=240)

    max_retries_raw = str(os.getenv("ANTHROPIC_MAX_RETRIES", "1")).strip()
    try:
        max_retries = max(0, int(max_retries_raw))
    except Exception:
        max_retries = 1

    max_attempts = max(1, max_retries + 1)
    client = Anthropic(api_key=key, max_retries=0)

    last_error: Exception | None = None
    existing_budget = get_retry_budget_state()

    @contextmanager
    def _preflight_retry_budget_if_needed():
        if existing_budget is not None:
            yield
            return
        with retry_budget_context(total_retries=max(0, max_attempts - 1), scope="anthropic_preflight"):
            yield

    with _preflight_retry_budget_if_needed():
        for attempt in range(1, max_attempts + 1):
            try:
                resp = client.messages.create(
                    model=model,
                    max_tokens=8,
                    messages=[{"role": "user", "content": "ok"}],
                )
                record_provider_success("anthropic", note=f"preflight_ok:{getattr(resp, 'id', 'no_id')}")
                return True, getattr(resp, "id", "ok")
            except Exception as e:
                last_error = e
                decision = classify_retry_decision(error_text=str(e), exc=e, stage="anthropic_preflight")
                if attempt < max_attempts and decision.retryable:
                    can_retry, _remaining = consume_retry_budget(reason_code=decision.reason_code)
                    if can_retry:
                        time.sleep(min(5.0, float(2 ** max(0, attempt - 1))))
                        continue
                record_provider_failure("anthropic", str(e))
                return False, _summarize_error_for_telegram(str(e), max_len=240)

    if last_error is not None:
        record_provider_failure("anthropic", str(last_error))
        return False, _summarize_error_for_telegram(str(last_error), max_len=240)
    return False, "anthropic_preflight_unknown_error"


def notify_startup(active_channels: int):
    send_telegram(
        f"🚀 <b>{STARTUP_BANNER_NAME} Scheduler Basladi</b>\n"
        f"📡 {active_channels} aktif kanal\n"
        f"💾 Boş disk: {get_free_disk_gb():.1f} GB"
    )


# ─── TOPIC DEDUPLİKASYON ─────────────────────────────────────────────────────

USED_TOPICS_FILE = "output/queue/used_topics.json"


def load_used_topics() -> dict:
    """Daha önce kullanılmış konuları yükle."""
    Path(USED_TOPICS_FILE).parent.mkdir(parents=True, exist_ok=True)
    if not Path(USED_TOPICS_FILE).exists():
        return {}
    try:
        return json.loads(Path(USED_TOPICS_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_used_topic(channel_id: str, title: str):
    """Kullanılmış konuyu kaydet."""
    topics = load_used_topics()
    if channel_id not in topics:
        topics[channel_id] = []
    # Sadece son 200 başlığı tut
    topics[channel_id] = (topics[channel_id] + [title])[-200:]
    Path(USED_TOPICS_FILE).write_text(
        json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_topic_used(channel_id: str, title: str, similarity_threshold: float = 0.7) -> bool:
    """Bu başlık veya çok benzeri daha önce kullanıldı mı?"""
    topics = load_used_topics()
    used = topics.get(channel_id, [])
    if not used:
        return False

    title_lower = title.lower()
    title_words = set(title_lower.split())

    for prev in used[-50:]:  # Son 50 başlığa bak
        prev_words = set(prev.lower().split())
        if not prev_words:
            continue
        # Jaccard benzerlik
        intersection = len(title_words & prev_words)
        union = len(title_words | prev_words)
        if union > 0 and intersection / union >= similarity_threshold:
            return True

    return False


# ─── SİSTEM SAĞLIK KONTROLÜ ──────────────────────────────────────────────────

def health_check() -> dict:
    """Sistemin genel sağlığını kontrol et."""
    from pathlib import Path
    status = {
        "timestamp": datetime.now().isoformat(),
        "disk_free_gb": get_free_disk_gb(),
        "disk_ok": get_free_disk_gb() > 1.5,
        "scheduler_running": True,
    }

    # Kanal tokenlarını kontrol et
    from src.channel_manager import list_channels, get_channel
    active = 0
    for cid in list_channels():
        try:
            cfg = get_channel(cid)
            if Path(cfg.token_path).exists():
                active += 1
        except Exception:
            pass
    status["active_channels"] = active

    return status


# ─── AKILLI UYARI SİSTEMİ ────────────────────────────────────────────────────
# Her bakımda kapasite eşiklerini kontrol et, gerektiğinde Telegram'a uyar

ALERTS_FILE = "output/queue/alerts_sent.json"

def _load_alerts() -> dict:
    p = Path(ALERTS_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_alerts(data: dict):
    Path(ALERTS_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(ALERTS_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _should_alert(key: str, cooldown_hours: int = 24) -> bool:
    """Aynı uyarıyı belirli süre içinde tekrar gönderme."""
    alerts = _load_alerts()
    last = alerts.get(key)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.now() - last_dt).total_seconds() > cooldown_hours * 3600
    except Exception:
        return True

def _mark_alert_sent(key: str):
    try:
        alerts = _load_alerts()
        alerts[key] = datetime.now().isoformat()
        _save_alerts(alerts)
    except Exception as exc:
        logger.warning("Alert cooldown state write failed (non-blocking): %s", exc)


def check_capacity_alerts():
    """
    Kapasite eşiklerini kontrol et — kritik noktalarda Telegram uyarısı gönder.
    Her gece bakımda çağrılır.
    """
    alerts_sent = []

    # ── 1. RAM KULLANIMI ─────────────────────────────────────────────────────
    try:
        import psutil
        ram = psutil.virtual_memory()
        ram_pct = ram.percent
        ram_used_gb = ram.used / 1e9
        ram_total_gb = ram.total / 1e9

        if ram_pct > 90 and _should_alert("ram_critical", cooldown_hours=6):
            send_telegram(
                f"🚨 <b>ACİL: RAM KRİTİK %{ram_pct:.0f}</b>\n"
                f"💾 {ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB kullanılıyor\n"
                f"⚡ Hemen VPS yükselt:\n"
                f"• CPX32 → CPX42 (16 GB, €69/ay)\n"
                f"• console.hetzner.com → Servers → Rescale"
            )
            _mark_alert_sent("ram_critical")
            alerts_sent.append("RAM KRİTİK")

        elif ram_pct > 75 and _should_alert("ram_warning", cooldown_hours=24):
            send_telegram(
                f"⚠️ <b>RAM Uyarısı: %{ram_pct:.0f}</b>\n"
                f"💾 {ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB\n"
                f"💡 Yakında VPS planı yükseltmesini düşün:\n"
                f"• CPX32 (8 GB) → CPX42 (16 GB, €69/ay)\n"
                f"• console.hetzner.com"
            )
            _mark_alert_sent("ram_warning")
            alerts_sent.append("RAM uyarı")
    except ImportError:
        pass  # psutil yoksa atla

    # ── 2. DİSK KULLANIMI ───────────────────────────────────────────────────
    free_gb = get_free_disk_gb()
    total_gb = shutil.disk_usage(".").total / 1e9
    used_pct = (1 - free_gb / total_gb) * 100

    if used_pct > 85 and _should_alert("disk_critical", cooldown_hours=12):
        send_telegram(
            f"🚨 <b>Disk %{used_pct:.0f} Dolu!</b>\n"
            f"💾 {free_gb:.1f} GB kaldı / {total_gb:.0f} GB toplam\n"
            f"🔧 Çözüm:\n"
            f"• Eski render dosyaları temizleniyor...\n"
            f"• Veya Hetzner'da Volume ekle"
        )
        _mark_alert_sent("disk_critical")
        cleanup_old_renders(max_age_hours=24)
        alerts_sent.append("Disk kritik")

    elif used_pct > 70 and _should_alert("disk_warning", cooldown_hours=24):
        send_telegram(
            f"⚠️ <b>Disk %{used_pct:.0f} Dolu</b>\n"
            f"💾 {free_gb:.1f} GB kaldı\n"
            f"💡 Yakında yer açmak gerekebilir"
        )
        _mark_alert_sent("disk_warning")
        alerts_sent.append("Disk uyarı")

    # ── 3. KANAL SAYISI EŞİKLERİ ────────────────────────────────────────────
    try:
        from src.channel_manager import list_channels, get_channel
        active_channels = sum(
            1 for cid in list_channels()
            if Path(get_channel(cid).token_path).exists()
        )

        if active_channels >= 18 and _should_alert("channel_vps2", cooldown_hours=72):
            send_telegram(
                f"📡 <b>2. VPS Zamanı! ({active_channels} kanal)</b>\n"
                f"🔴 Tek VPS ile 20+ kanal verimli çalışmaz\n"
                f"💡 Yapılacak:\n"
                f"• 2. VPS aç (Hetzner CPX32)\n"
                f"• Kanalları ikiye böl (9+9)\n"
                f"• Ben kurulumu yaparım, söyle yeter"
            )
            _mark_alert_sent("channel_vps2")
            alerts_sent.append(f"{active_channels} kanal → 2. VPS")

        elif active_channels >= 13 and _should_alert("channel_cpx42", cooldown_hours=72):
            send_telegram(
                f"📊 <b>VPS Yükseltme Zamanı! ({active_channels} kanal)</b>\n"
                f"💡 CPX32 → CPX42 (16 GB RAM) yükselt\n"
                f"• console.hetzner.com → Servers → Rescale → CPX42\n"
                f"• €69/ay — 30 kanala kadar yeterli"
            )
            _mark_alert_sent("channel_cpx42")
            alerts_sent.append(f"{active_channels} kanal → CPX42")
    except Exception:
        pass

    # ── 4. ELEVENLABS KREDİ ──────────────────────────────────────────────────
    try:
        el_key = os.getenv("ELEVENLABS_API_KEY", "")
        if el_key and not el_key.startswith("your_"):
            import requests as _req
            r = _req.get("https://api.elevenlabs.io/v1/user",
                        headers={"xi-api-key": el_key}, timeout=8)
            if r.status_code == 200:
                sub = r.json().get("subscription", {})
                used = sub.get("character_count", 0)
                limit = sub.get("character_limit", 1)
                remaining_pct = (1 - used / limit) * 100

                if remaining_pct < 10 and _should_alert("el_critical", cooldown_hours=12):
                    send_telegram(
                        f"🔴 <b>ElevenLabs Kredi %{remaining_pct:.0f} Kaldı!</b>\n"
                        f"📊 {limit - used:,} / {limit:,} karakter\n"
                        f"💡 Seçenekler:\n"
                        f"• Creator → Pro yükselt ($99/ay, 600k kredi)\n"
                        f"• elevenlabs.io/app/subscription\n"
                        f"• Veya o 2 kanalı Azure'a geç (ücretsiz)"
                    )
                    _mark_alert_sent("el_critical")
                    alerts_sent.append("ElevenLabs kritik")

                elif remaining_pct < 25 and _should_alert("el_warning", cooldown_hours=24):
                    send_telegram(
                        f"⚠️ <b>ElevenLabs Kredi %{remaining_pct:.0f} Kaldı</b>\n"
                        f"📊 {limit - used:,} karakter kaldı\n"
                        f"💡 Yakında yükseltme gerekebilir:\n"
                        f"• elevenlabs.io/app/subscription → Pro ($99/ay)"
                    )
                    _mark_alert_sent("el_warning")
                    alerts_sent.append("ElevenLabs uyarı")
    except Exception:
        pass

    if alerts_sent:
        logger.info(f"Kapasite uyarıları gönderildi: {alerts_sent}")

    return alerts_sent


# ─── TOKEN SAĞLIK KONTROLÜ ───────────────────────────────────────────────────

def check_token_health(channel_cfg) -> tuple:
    """
    OAuth token geçerliliğini kontrol et.
    Süresi dolmuşsa yenilemeyi dene.
    Döner: (gecerli: bool, mesaj: str)
    """
    try:
        import pickle
        token_path = Path(channel_cfg.token_path)
        if not token_path.exists():
            return False, "Token dosyası yok — yeniden auth gerekli"

        with open(token_path, "rb") as f:
            creds = pickle.load(f)

        if not creds:
            return False, "Token boş"

        # Süresi dolmuş ama refresh_token varsa yenile
        if creds.expired:
            if not creds.refresh_token:
                return False, "Token süresi dolmuş, yenileme imkânsız — auth.py çalıştır"
            try:
                from google.auth.transport.requests import Request as GRequest
                creds.refresh(GRequest())
                with open(token_path, "wb") as f:
                    pickle.dump(creds, f)
                return True, "Token otomatik yenilendi ✅"
            except Exception as e:
                return False, f"Token yenileme başarısız: {e}"

        return True, "Token geçerli"
    except Exception as e:
        return False, f"Token kontrol hatası: {e}"


def verify_all_tokens() -> dict:
    """
    Tüm kanalların tokenlarını kontrol et.
    Sorunlu kanalları Telegram'a bildir.
    """
    from src.channel_manager import list_channels, get_channel
    results = {}
    broken = []

    for cid in list_channels():
        try:
            cfg = get_channel(cid)
            if not Path(cfg.token_path).exists():
                continue  # Token yoksa zaten inactive
            ok, msg = check_token_health(cfg)
            results[cid] = {"ok": ok, "msg": msg}
            if not ok:
                broken.append(f"• {cfg.name}: {msg}")
                logger.warning(f"[{cid}] Token sorunu: {msg}")
        except Exception as e:
            results[cid] = {"ok": False, "msg": str(e)}

    if broken:
        send_telegram(
            f"🔑 <b>Token Sorunu Tespit Edildi!</b>\n"
            f"Aşağıdaki kanallarda yeniden OAuth gerekiyor:\n\n"
            + "\n".join(broken)
            + "\n\n<code>python auth.py --channel KANAL_ID</code>"
        )

    return results


# ─── LOG ROTATION ─────────────────────────────────────────────────────────────

def rotate_log_file(log_path: str, max_lines: int = 8000):
    """
    Log dosyasını max_lines satıra kırp (en eski satırları at).
    Her gece maintenance_job tarafından çağrılır.
    """
    p = Path(log_path)
    if not p.exists():
        return
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        if len(lines) > max_lines:
            trimmed = lines[-max_lines:]
            p.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
            logger.info(f"Log rotate: {p.name} {len(lines)} → {max_lines} satır")
    except Exception as e:
        logger.warning(f"Log rotate hatası: {e}")


# ─── KUYRUK BAYAT GİRİŞ TEMİZLEME ────────────────────────────────────────────

def cleanup_stale_queue(queue: dict, tz, stale_hours: int = 3) -> tuple:
    """
    publishAt süresi geçmiş kuyruk girişlerini temizle.
    Servis o saatte kapalıysa kanal sıkışıp kalmasın.
    Döner: (temizlenmiş_kuyruk, temizlenen_kanal_listesi)
    """
    now = datetime.now(tz)
    cleaned = {}
    freed_channels = []

    for cid, entries in queue.items():
        valid = []
        removed = 0
        for raw_entry in entries:
            entry = _ensure_queue_entry_shape(raw_entry)
            current_status = str(entry.get("status") or "active").strip().lower()

            # Quarantined/rejected items are preserved; cleanup only evaluates publishable states.
            if current_status not in ACTIVE_QUEUE_STATUSES:
                valid.append(entry)
                continue

            if _is_misrouted_queue_entry(cid, entry):
                removed += 1
                _transition_queue_entry_status(
                    entry,
                    new_status="quarantined",
                    reason="channel_dna_mismatch",
                    guard_reason_codes=["channel_dna_mismatch", "title_market_mismatch"],
                    recoverable=True,
                )
                _append_queue_quarantine_decision(
                    {
                        "event": "queue_entry_quarantined",
                        "channel_id": cid,
                        "queue_entry_id": entry.get("queue_entry_id"),
                        "reason": "channel_dna_mismatch",
                        "guard_reason_codes": ["channel_dna_mismatch", "title_market_mismatch"],
                        "source": "cleanup_stale_queue",
                        "title_preview": str(entry.get("title") or "")[:180],
                    }
                )
                logger.info(
                    f"[{cid}] Yanlis kanal kuyruk girisi quarantine: {str(entry.get('title') or '')[:80]}"
                )
                valid.append(entry)
                continue

            publish_at_str = entry.get("publish_at", "")
            if not publish_at_str:
                valid.append(entry)
                continue
            try:
                pub_time = datetime.fromisoformat(publish_at_str)
                if pub_time.tzinfo is None:
                    import pytz
                    pub_time = pytz.utc.localize(pub_time)
                age = (now - pub_time).total_seconds() / 3600
                if age < stale_hours:
                    valid.append(entry)  # Henüz taze, tut
                else:
                    removed += 1
                    _transition_queue_entry_status(
                        entry,
                        new_status="permanently_rejected",
                        reason="stale_publish_window_expired",
                        guard_reason_codes=["stale_publish_window_expired"],
                        recoverable=False,
                    )
                    _append_queue_quarantine_decision(
                        {
                            "event": "queue_entry_rejected",
                            "channel_id": cid,
                            "queue_entry_id": entry.get("queue_entry_id"),
                            "reason": "stale_publish_window_expired",
                            "guard_reason_codes": ["stale_publish_window_expired"],
                            "source": "cleanup_stale_queue",
                            "title_preview": str(entry.get("title") or "")[:180],
                        }
                    )
                    valid.append(entry)
            except Exception:
                valid.append(entry)  # Parse edilemezse tut

        cleaned[cid] = valid
        if removed > 0:
            freed_channels.append(cid)
            logger.info(f"[{cid}] {removed} bayat kuyruk girişi temizlendi → yeni render tetiklenecek")

    return cleaned, freed_channels


def _load_channel_registry() -> dict:
    try:
        if not CHANNEL_REGISTRY_PATH.exists():
            return {}
        payload = json.loads(CHANNEL_REGISTRY_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _is_misrouted_queue_entry(channel_id: str, entry: dict) -> bool:
    registry = _load_channel_registry()
    channels = dict(registry.get("channels") or {})
    channel_cfg = dict(channels.get(channel_id) or {})
    niche = str(channel_cfg.get("niche") or "").strip().lower()
    allow_market_language = resolve_allow_market_language(
        niche=niche,
        explicit_value=channel_cfg.get("allow_market_language"),
    )
    if allow_market_language:
        return False
    title = str(entry.get("title") or "")
    return bool(title and QUEUE_FORBIDDEN_MARKET_RE.search(title))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_queue_quarantine_decision(entry: dict) -> None:
    try:
        payload = dict(entry)
        payload.setdefault("created_at", _utc_now_iso())
        QUARANTINE_TRAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUARANTINE_TRAIL_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        return


def _ensure_queue_entry_shape(entry: dict) -> dict:
    data = dict(entry or {})
    data.setdefault("queue_entry_id", _build_queue_entry_id(data))
    status = str(data.get("status") or "active").strip().lower()
    if status not in {"active", "quarantined", "restored", "permanently_rejected"}:
        status = "active"
    data["status"] = status
    return data


def _build_queue_entry_id(entry: dict) -> str:
    base = "|".join(
        [
            str(entry.get("video_id") or ""),
            str(entry.get("publish_at") or ""),
            str(entry.get("title") or ""),
            str(entry.get("rendered_at") or ""),
        ]
    )
    if not base.strip("|"):
        base = _utc_now_iso()
    digest = __import__("hashlib").sha256(base.encode("utf-8")).hexdigest()[:16]
    return f"qe_{digest}"


def _transition_queue_entry_status(
    entry: dict,
    *,
    new_status: str,
    reason: str,
    guard_reason_codes: list[str],
    recoverable: bool,
) -> dict:
    status = str(new_status or "").strip().lower()
    if status not in {"quarantined", "restored", "permanently_rejected", "active"}:
        return entry
    now_iso = _utc_now_iso()
    entry["status"] = status
    entry["quarantine_reason"] = reason
    entry["guard_reason_codes"] = list(guard_reason_codes or [])
    entry["recoverable"] = bool(recoverable)
    if status == "quarantined":
        entry["quarantined_at"] = now_iso
    elif status == "restored":
        entry["restored_at"] = now_iso
    elif status == "permanently_rejected":
        entry["rejected_at"] = now_iso
    return entry


def restore_quarantined_entry(
    queue: dict,
    *,
    channel_id: str,
    queue_entry_id: str,
    reviewer: str = "manual",
    review_note: str = "",
) -> bool:
    """Restore quarantined queue entry in-place. Idempotent and append-only audited."""
    entries = list(queue.get(channel_id, []) or [])
    changed = False
    for idx, item in enumerate(entries):
        entry = _ensure_queue_entry_shape(item)
        entries[idx] = entry
        if str(entry.get("queue_entry_id") or "") != str(queue_entry_id or ""):
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status == "restored":
            return False
        if status != "quarantined":
            return False
        _transition_queue_entry_status(
            entry,
            new_status="restored",
            reason="manual_review_restored",
            guard_reason_codes=["manual_review_restored"],
            recoverable=True,
        )
        entry["review_status"] = "approved"
        entry["reviewed_by"] = reviewer
        entry["reviewed_at"] = _utc_now_iso()
        if review_note:
            entry["review_note"] = str(review_note)
        _append_queue_quarantine_decision(
            {
                "event": "queue_entry_restored",
                "channel_id": channel_id,
                "queue_entry_id": entry.get("queue_entry_id"),
                "reason": "manual_review_restored",
                "guard_reason_codes": ["manual_review_restored"],
                "reviewed_by": reviewer,
            }
        )
        changed = True
        break

    if changed:
        queue[channel_id] = entries
    return changed

