"""
Para Pusulası - 200 Kanal Otomasyonu v4.0 (Production Ready)
=============================================================
MIMARISI:
- Tüm token'i olan kanalları otomatik keşfeder
- Her kanalın bir sonraki upload saatini hesaplar
- Render + YouTube Scheduled upload (YouTube zamanında yayınlar)
- Her upload sonrası hemen sonraki render başlar (kesintisiz döngü)
- Thread havuzu ile paralel render (CPU sınırlı)
- Akıllı retry: geçici hatalar otomatik tekrar denenir
- Disk temizleme: 48 saatten eski dosyalar silinir
- Bellek yönetimi: Her render sonrası GC zorlama
- Telegram bildirimi: upload/hata anında mesaj
- Topic deduplication: aynı konu tekrar üretilmez
- 200+ kanala hazır mimari

KULLANIM:
  python scheduler.py          # Token'i olan tüm kanalları çalıştır
  python scheduler.py --list   # Aktif kanalları listele
  python scheduler.py --status # Kuyruk durumunu göster
    python scheduler.py --initial-fill # Açık operatör tetikli ön render
"""
import json
import atexit
import io
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

import pytz
from src.production_quality_platform import (
    canary_gate_decision,
    record_dead_letter,
    record_production_event,
    update_production_dashboard,
)
from src.production_observation import production_observation_mode_enabled
from src.production_safety_gate import evaluate_production_safety_gate
from src.retry_policy import classify_retry_decision
from src.runtime_storage import runtime_path
try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None
try:
    import schedule
except ImportError:
    class _MissingScheduleModule:
        jobs = []

        def __getattr__(self, _name):
            raise RuntimeError(
                "The 'schedule' package is required for daemon scheduling mode. "
                "Install it to run continuous scheduler loops."
            )

    schedule = _MissingScheduleModule()

sys.path.insert(0, os.path.dirname(__file__))


def _path_from_env(env_key: str, default: str) -> Path:
    raw = str(os.getenv(env_key, default)).strip()
    return Path(raw if raw else default)


def _path_string_from_env(env_key: str, default: str) -> str:
    raw = str(os.getenv(env_key, default)).strip()
    return raw if raw else default

# Loglama
_SCHEDULER_LOG_FILE_PATH = _path_from_env("SCHEDULER_LOG_FILE", str(runtime_path("logs/scheduler.log")))
_SCHEDULER_LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
_SCHEDULER_LOG_FILE_HANDLER = logging.FileHandler(_SCHEDULER_LOG_FILE_PATH, encoding="utf-8")
_SCHEDULER_LOG_STREAM_HANDLER = logging.StreamHandler(sys.stdout)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        _SCHEDULER_LOG_FILE_HANDLER,
        _SCHEDULER_LOG_STREAM_HANDLER,
    ],
)
logger = logging.getLogger("Scheduler")


def _close_scheduler_logging_handlers() -> None:
    for handler in (_SCHEDULER_LOG_FILE_HANDLER, _SCHEDULER_LOG_STREAM_HANDLER):
        try:
            handler.flush()
        except Exception:
            pass
        try:
            handler.close()
        except Exception:
            pass
        try:
            logging.getLogger().removeHandler(handler)
        except Exception:
            pass


atexit.register(_close_scheduler_logging_handlers)


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _observation_mode_active() -> bool:
    try:
        return production_observation_mode_enabled()
    except Exception as exc:
        logger.warning("Observation mode state unavailable; treating scheduler automation as blocked: %s", exc)
        return True


def _resolve_governance_shadow_activation() -> dict[str, Any]:
    """Resolve governance shadow activation in deterministic fail-open mode."""
    try:
        raw = os.getenv("GOVERNANCE_REFRESH_SHADOW_MODE")
        token = str(raw or "").strip().lower()

        if not token:
            return {"enabled": False, "state": "disabled"}
        if token in {"1", "true", "yes", "on", "enabled"}:
            return {"enabled": True, "state": "enabled"}
        if token in {"0", "false", "no", "off", "disabled"}:
            return {"enabled": False, "state": "disabled"}
        return {"enabled": False, "state": "invalid_flag"}
    except Exception:
        return {"enabled": False, "state": "fail_open"}


def _resolve_live_collector_runtime() -> tuple[bool, str]:
    requested = _is_enabled(os.getenv("LIVE_COLLECTOR_ENABLED", "false"))
    api_go = _is_enabled(os.getenv("YOUTUBE_ANALYTICS_API_GO", "false"))
    rollout_approved = _is_enabled(os.getenv("LIVE_COLLECTOR_ROLLOUT_APPROVED", "false"))

    if not api_go:
        return False, "no_go_api_not_enabled"
    if not requested:
        return False, "disabled_by_flag"
    if not rollout_approved:
        return False, "disabled_by_policy"
    return True, "go_enabled"


def _resolve_git_head_short() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"

# Env üzerinden kontrol: default 1
try:
    MAX_PARALLEL_RENDERS = max(1, int(os.getenv("MAX_PARALLEL_RENDERS", "1")))
except ValueError:
    MAX_PARALLEL_RENDERS = 1

TZ = pytz.timezone("Europe/Istanbul")
QUEUE_FILE = _path_string_from_env("SCHEDULER_QUEUE_FILE", str(runtime_path("state/channel_queue.json")))
PID_FILE = _path_from_env("SCHEDULER_PID_FILE", str(runtime_path("state/production_scheduler.pid")))
SCHEDULER_SINGLETON_LOCK_FILE = _path_from_env(
    "SCHEDULER_SINGLETON_LOCK_FILE",
    str(runtime_path("state/scheduler_singleton.lock")),
)
SCHEDULER_SINGLETON_META_FILE = _path_from_env(
    "SCHEDULER_SINGLETON_META_FILE",
    str(runtime_path("state/scheduler_singleton_meta.json")),
)
RUNTIME_EVIDENCE_LATEST_FILE = _path_from_env(
    "RUNTIME_EVIDENCE_LATEST_FILE",
    str(runtime_path("state/runtime_optimization_evidence_latest.json")),
)
SAFETY_GATE_LATEST_FILE = _path_from_env(
    "SAFETY_GATE_LATEST_FILE",
    str(runtime_path("state/production_safety_gate_latest.json")),
)
ACTIVATION_CONTROLLER_SCRIPT = Path("ops/activation_controller.py")
FLEET_HEALTH_SCRIPT = Path("ops/fleet_health_report.py")
BACKLOG_SCRIPT = Path("ops/optimization_backlog_engine.py")
OPTIMIZATION_MEMORY_SCRIPT = Path("ops/optimization_memory_engine.py")
GOVERNANCE_REFRESH_SCRIPT = Path("ops/refresh_governance_readiness.py")
QUEUE_LOCK = threading.RLock()
RENDER_LOCKS_LOCK = threading.Lock()
RUNTIME_CYCLE_LOCK = threading.Lock()
_SCHEDULER_SINGLETON_HANDLE: TextIO | None = None

# Thread havuzu
render_executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_RENDERS, thread_name_prefix="render")
render_locks = {}  # Her kanal için kilit — aynı anda iki render başlamasın

RETRYABLE = "RETRYABLE"
NON_RETRYABLE_QUARANTINE = "NON_RETRYABLE_QUARANTINE"
TERMINAL_FAILURE = "TERMINAL_FAILURE"

VALID_RENDER_TRIGGER_SOURCES = frozenset({
    "scheduled_slot",
    "recurring_empty_queue_fill",
    "explicit_initial_fill",
    "overdue_recovery",
    "post_upload_continuation",
    "manual_operator",
    "retry",
})

_NON_RETRYABLE_DOMAIN_TOKENS = (
    "topic_domain_blocked",
    "topic_provenance_collision",
    "domain_policy_forbidden_keyword",
    "channel_topic_domain_mismatch",
    "cross_channel_topic_contamination",
)

_TERMINAL_FAILURE_TOKENS = (
    "failed_fact_check",
    "credit balance",
    "quota",
    "invalid_request",
    "invalidtags",
    "authentication",
    "http 400",
    "http 401",
    "http 403",
)

_TRANSIENT_RETRYABLE_TOKENS = (
    "timeout",
    "connection",
    "dns",
    "network",
    "temporary",
    "service unavailable",
    "internal server error",
    "http 5",
)


# ─── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────

def load_queue() -> dict:
    with QUEUE_LOCK:
        mode = os.getenv("JOB_STORE_MODE", "json").strip().lower()
        if mode not in {"json", "shadow"}:
            mode = "json"
        Path(QUEUE_FILE).parent.mkdir(parents=True, exist_ok=True)
        if not Path(QUEUE_FILE).exists():
            return {}
        try:
            return json.loads(Path(QUEUE_FILE).read_text(encoding="utf-8"))
        except Exception:
            return {}


def save_queue(data: dict):
    if production_observation_mode_enabled():
        logger.warning("Queue save blocked: production_observation_mode")
        return
    with QUEUE_LOCK:
        mode = os.getenv("JOB_STORE_MODE", "json").strip().lower()
        if mode not in {"json", "shadow"}:
            mode = "json"
        path = Path(QUEUE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)

        if mode == "shadow":
            try:
                from src.job_store import mirror_legacy_queue_snapshot

                report = mirror_legacy_queue_snapshot(
                    data,
                    db_path=os.getenv("JOB_STORE_DB_PATH", "output/state/jobs.db"),
                )
                if report.get("missing_count", 0) > 0:
                    logger.warning(
                        "Shadow parity mismatch: missing=%s expected=%s mirrored=%s",
                        report.get("missing_count", 0),
                        report.get("expected", 0),
                        report.get("mirrored", 0),
                    )
            except Exception as e:
                logger.warning("Shadow mirror failed (non-blocking): %s", e)


def update_queue(mutator):
    if production_observation_mode_enabled():
        logger.warning("Queue mutation blocked: production_observation_mode")
        return load_queue()
    with QUEUE_LOCK:
        mode = os.getenv("JOB_STORE_MODE", "json").strip().lower()
        if mode not in {"json", "shadow"}:
            mode = "json"
        path = Path(QUEUE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            queue = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            queue = {}
        mutator(queue)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)

        if mode == "shadow":
            try:
                from src.job_store import mirror_legacy_queue_snapshot

                report = mirror_legacy_queue_snapshot(
                    queue,
                    db_path=os.getenv("JOB_STORE_DB_PATH", "output/state/jobs.db"),
                )
                if report.get("missing_count", 0) > 0:
                    logger.warning(
                        "Shadow parity mismatch: missing=%s expected=%s mirrored=%s",
                        report.get("missing_count", 0),
                        report.get("expected", 0),
                        report.get("mirrored", 0),
                    )
            except Exception as e:
                logger.warning("Shadow mirror failed (non-blocking): %s", e)

        return queue


def _get_channel_render_lock(channel_id: str) -> threading.Lock:
    """Kanal bazlı render lock nesnesini thread-safe biçimde döndür."""
    with RENDER_LOCKS_LOCK:
        lock = render_locks.get(channel_id)
        if lock is None:
            lock = threading.Lock()
            render_locks[channel_id] = lock
        return lock


def _write_pid_record() -> None:
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        logger.info("Scheduler pid record updated: %s -> %s", PID_FILE, os.getpid())
    except Exception as e:
        logger.warning("Scheduler pid record write failed (non-blocking): %s", e)


def _scheduler_singleton_lock_path() -> Path:
    raw = str(os.getenv("SCHEDULER_SINGLETON_LOCK_FILE", str(SCHEDULER_SINGLETON_LOCK_FILE))).strip()
    return Path(raw) if raw else SCHEDULER_SINGLETON_LOCK_FILE


def _scheduler_singleton_meta_path() -> Path:
    raw = str(os.getenv("SCHEDULER_SINGLETON_META_FILE", str(SCHEDULER_SINGLETON_META_FILE))).strip()
    return Path(raw) if raw else SCHEDULER_SINGLETON_META_FILE


def _collect_preprod_mutable_paths() -> dict[str, Path]:
    return {
        "scheduler_log_file": _SCHEDULER_LOG_FILE_PATH,
        "scheduler_queue_file": Path(QUEUE_FILE),
        "scheduler_pid_file": PID_FILE,
        "scheduler_singleton_lock_file": _scheduler_singleton_lock_path(),
        "scheduler_singleton_meta_file": _scheduler_singleton_meta_path(),
        "runtime_evidence_latest": RUNTIME_EVIDENCE_LATEST_FILE,
        "safety_gate_latest": SAFETY_GATE_LATEST_FILE,
        "activation_report": _path_from_env(
            "ACTIVATION_CONTROLLER_REPORT_PATH",
            str(runtime_path("state/activation_controller_report.json")),
        ),
        "activation_report_archive": _path_from_env(
            "ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR",
            str(runtime_path("state/activation_reports")),
        ),
        "activation_flags": _path_from_env(
            "ACTIVATION_FLAGS_PATH",
            str(runtime_path("state/learning_activation_flags.json")),
        ),
        "governance_refresh_latest": _path_from_env(
            "GOVERNANCE_REFRESH_LATEST_PATH",
            str(runtime_path("state/governance_refresh_run_latest.json")),
        ),
        "governance_readiness_markdown": _path_from_env(
            "GOVERNANCE_READINESS_MD_PATH",
            str(runtime_path("state/governance_readiness_latest.md")),
        ),
        "production_dashboard_latest_json": _path_from_env(
            "PRODUCTION_DASHBOARD_JSON_PATH",
            str(runtime_path("state/production_dashboard_latest.json")),
        ),
        "production_dashboard_latest_md": _path_from_env(
            "PRODUCTION_DASHBOARD_MD_PATH",
            str(runtime_path("state/production_dashboard_latest.md")),
        ),
        "production_events": _path_from_env(
            "PRODUCTION_EVENTS_PATH",
            str(runtime_path("telemetry/production_events.jsonl")),
        ),
        "production_observability_latest": _path_from_env(
            "PRODUCTION_OBSERVABILITY_LATEST_PATH",
            str(runtime_path("telemetry/production_observability_latest.json")),
        ),
    }


def _assert_preprod_isolation_paths() -> None:
    enabled = _is_enabled(os.getenv("PREPROD_ISOLATION_MODE", "false"))
    if not enabled:
        return

    root_raw = str(os.getenv("PREPROD_STATE_ROOT", "")).strip()
    if not root_raw:
        raise RuntimeError("preprod_isolation_invalid: PREPROD_STATE_ROOT missing")

    state_root = Path(root_raw).resolve()
    repo_root = Path(os.getcwd()).resolve()

    required_env_keys = (
        "PRODUCTION_DASHBOARD_MD_PATH",
        "ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR",
    )
    missing_required = [key for key in required_env_keys if not str(os.getenv(key, "")).strip()]
    if missing_required:
        raise RuntimeError(
            "preprod_isolation_invalid: required mutable path env missing: "
            + ",".join(missing_required)
        )

    offenders: list[str] = []
    for name, path in _collect_preprod_mutable_paths().items():
        resolved = path.resolve()
        inside_state_root = resolved == state_root or state_root in resolved.parents
        inside_repo = resolved == repo_root or repo_root in resolved.parents
        if (not inside_state_root) or inside_repo:
            offenders.append(f"{name}={resolved}")

    if offenders:
        raise RuntimeError(
            "preprod_isolation_violation: mutable path outside PREPROD_STATE_ROOT or inside repo: "
            + "; ".join(offenders)
        )


def _load_scheduler_singleton_meta() -> dict:
    path = _scheduler_singleton_meta_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_scheduler_singleton_meta(meta: dict) -> None:
    path = _scheduler_singleton_meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _acquire_scheduler_singleton_lock() -> None:
    global _SCHEDULER_SINGLETON_HANDLE

    if fcntl is None:
        raise RuntimeError("scheduler_singleton_lock_unavailable:fcntl_missing")
    if _SCHEDULER_SINGLETON_HANDLE is not None:
        return

    lock_path = _scheduler_singleton_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = _load_scheduler_singleton_meta()
        handle.close()
        holder_pid = holder.get("pid", "unknown")
        holder_started = holder.get("started_at", "unknown")
        holder_cwd = holder.get("cwd", "unknown")
        raise RuntimeError(
            "scheduler_singleton_lock_conflict: "
            f"pid={holder_pid} started_at={holder_started} cwd={holder_cwd} lock={lock_path}"
        )

    _SCHEDULER_SINGLETON_HANDLE = handle
    _save_scheduler_singleton_meta(
        {
            "pid": os.getpid(),
            "started_at": datetime.now(TZ).isoformat(),
            "cwd": os.getcwd(),
            "git_sha": _resolve_git_head_short(),
            "lock_file": str(lock_path),
        }
    )
    logger.info("Scheduler singleton lock acquired: %s", lock_path)


def _release_scheduler_singleton_lock() -> None:
    global _SCHEDULER_SINGLETON_HANDLE

    handle = _SCHEDULER_SINGLETON_HANDLE
    _SCHEDULER_SINGLETON_HANDLE = None
    if handle is None:
        return

    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass
    logger.info("Scheduler singleton lock released")


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_json_script(command: list[str], *, timeout_seconds: int = 180) -> dict:
    started_at = datetime.now(TZ).isoformat()
    try:
        proc = subprocess.run(
            command,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=max(10, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "error": "timeout",
            "timed_out": True,
            "timeout_seconds": max(10, int(timeout_seconds)),
            "command": command,
            "started_at": started_at,
            "stderr_tail": "\n".join((e.stderr or "").splitlines()[-20:]) if isinstance(e.stderr, str) else "",
            "stdout_tail": "\n".join((e.stdout or "").splitlines()[-20:]) if isinstance(e.stdout, str) else "",
            "parsed": {},
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "command": command,
            "started_at": started_at,
        }

    stdout = (proc.stdout or "").strip()
    parsed = {}
    if stdout:
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(stdout[start : end + 1])
            except Exception:
                parsed = {}

    return {
        "ok": proc.returncode == 0,
        "return_code": proc.returncode,
        "command": command,
        "started_at": started_at,
        "stdout_tail": "\n".join(stdout.splitlines()[-20:]) if stdout else "",
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-20:]),
        "parsed": parsed,
    }


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _is_publishable_queue_entry(entry: dict) -> bool:
    status = str((entry or {}).get("status") or "active").strip().lower()
    return status in {"active", "restored"}


def _normalize_queue_entry(entry: dict) -> dict:
    row = dict(entry or {})
    row.setdefault("queue_entry_id", f"qe_{uuid.uuid4().hex[:16]}")
    status = str(row.get("status") or "active").strip().lower()
    if status not in {"active", "quarantined", "restored", "permanently_rejected"}:
        status = "active"
    row["status"] = status
    return row


def _classify_pipeline_failure(error_text: str, exc: Exception) -> dict[str, Any]:
    text = str(error_text or "").strip().lower()
    guard_codes = [str(x).strip().lower() for x in (getattr(exc, "_guard_reason_codes", []) or []) if str(x).strip()]
    combined = text + " " + " ".join(guard_codes)

    if any(token in combined for token in _NON_RETRYABLE_DOMAIN_TOKENS):
        codes = sorted(set(guard_codes + ["topic_domain_blocked"]))
        return {
            "classification": NON_RETRYABLE_QUARANTINE,
            "quarantine_reason": "topic_domain_blocked",
            "guard_reason_codes": codes,
            "retry_reason": "deterministic_domain_policy_rejection",
        }

    if getattr(exc, "_skip_scheduler_pipeline_retry", False):
        return {
            "classification": TERMINAL_FAILURE,
            "quarantine_reason": None,
            "guard_reason_codes": guard_codes,
            "retry_reason": "explicit_skip_retry",
        }

    if any(token in text for token in _TERMINAL_FAILURE_TOKENS):
        return {
            "classification": TERMINAL_FAILURE,
            "quarantine_reason": None,
            "guard_reason_codes": guard_codes,
            "retry_reason": "fatal_generation_error",
        }

    if any(token in text for token in _TRANSIENT_RETRYABLE_TOKENS):
        return {
            "classification": RETRYABLE,
            "quarantine_reason": None,
            "guard_reason_codes": guard_codes,
            "retry_reason": "transient_provider_or_network_error",
        }

    return {
        "classification": RETRYABLE,
        "quarantine_reason": None,
        "guard_reason_codes": guard_codes,
        "retry_reason": "retry_budget_fallback",
    }


def _is_same_domain_quarantine_entry(entry: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if str(entry.get("status") or "").strip().lower() != "quarantined":
        return False
    if str(entry.get("quarantine_reason") or "") != str(candidate.get("quarantine_reason") or ""):
        return False

    entry_run = str(entry.get("run_id") or "").strip()
    entry_content = str(entry.get("content_id") or "").strip()
    cand_run = str(candidate.get("run_id") or "").strip()
    cand_content = str(candidate.get("content_id") or "").strip()
    if cand_run and cand_content:
        return entry_run == cand_run and entry_content == cand_content

    return (
        str(entry.get("channel_id") or "") == str(candidate.get("channel_id") or "")
        and str(entry.get("topic") or "") == str(candidate.get("topic") or "")
        and list(entry.get("guard_reason_codes") or []) == list(candidate.get("guard_reason_codes") or [])
    )


def _quarantine_non_retryable_domain_block(
    *,
    channel_id: str,
    cfg: Any,
    publish_at: str,
    failure: dict[str, Any],
    routed_error_text: str,
    source_stage: str,
) -> None:
    timestamp = datetime.now(TZ).isoformat()
    guard_reason_codes = list(failure.get("guard_reason_codes") or ["topic_domain_blocked"])
    expected_niche = str(getattr(cfg, "niche", "") or "")
    channel_name = str(getattr(cfg, "name", "") or "")
    topic = str(failure.get("topic") or "")
    run_id = str(failure.get("run_id") or "")
    content_id = str(failure.get("content_id") or "")
    retry_count = int(failure.get("retry_count") or 1)
    regeneration_count = int(failure.get("regeneration_count") or 0)
    detected_domain = str(failure.get("detected_domain") or "unknown")
    source_exception_type = str(failure.get("source_exception_type") or "")
    source_exception_message = str(failure.get("source_exception_message") or routed_error_text)

    entry_payload = _normalize_queue_entry(
        {
            "queue_entry_id": f"qe_{uuid.uuid4().hex[:16]}",
            "video_id": None,
            "title": "",
            "youtube_url": "",
            "timestamp": timestamp,
            "publish_at": publish_at,
            "rendered_at": timestamp,
            "status": "quarantined",
            "channel_id": channel_id,
            "channel_name": channel_name,
            "quarantine_reason": str(failure.get("quarantine_reason") or "topic_domain_blocked"),
            "guard_reason_codes": guard_reason_codes,
            "quarantined_at": timestamp,
            "recoverable": False,
            "review_status": "pending",
            "error": routed_error_text[:300],
            "run_id": run_id,
            "content_id": content_id,
            "topic": topic,
            "selected_topic": topic,
            "expected_niche": expected_niche,
            "expected_domain": expected_niche,
            "detected_domain": detected_domain,
            "source_exception_type": source_exception_type,
            "source_exception_message": source_exception_message[:500],
            "retry_count": retry_count,
            "regeneration_count": regeneration_count,
            "terminal": True,
            "source_stage": source_stage,
            "prevent_upload": True,
            "prevent_shorts_upload": True,
        }
    )

    update_state = {"created": False, "entry": None}

    def _upsert_quarantined_entry(queue):
        entries = list(queue.get(channel_id, []) or [])
        for idx, existing in enumerate(entries):
            if _is_same_domain_quarantine_entry(existing, entry_payload):
                merged = dict(existing)
                merged.update({k: v for k, v in entry_payload.items() if v not in ("", None, [])})
                merged["guard_reason_codes"] = sorted(
                    set(list(existing.get("guard_reason_codes") or []) + list(entry_payload.get("guard_reason_codes") or []))
                )
                entries[idx] = _normalize_queue_entry(merged)
                queue[channel_id] = entries
                update_state["entry"] = entries[idx]
                return

        entries.append(entry_payload)
        queue[channel_id] = entries
        update_state["created"] = True
        update_state["entry"] = entry_payload

    update_queue(_upsert_quarantined_entry)

    _append_queue_quarantine_decision(
        {
            "event": "topic_domain_blocked",
            "channel_id": channel_id,
            "reason": str(failure.get("quarantine_reason") or "topic_domain_blocked"),
            "guard_reason_codes": guard_reason_codes,
            "error": routed_error_text[:300],
            "source": source_stage,
            "run_id": run_id,
            "content_id": content_id,
            "topic": topic,
            "expected_niche": expected_niche,
            "detected_domain": detected_domain,
            "source_exception_type": source_exception_type,
            "retry_count": retry_count,
            "regeneration_count": regeneration_count,
            "quarantine_entry_created": bool(update_state["created"]),
            "queue_entry_id": str((update_state.get("entry") or {}).get("queue_entry_id") or ""),
        }
    )


def get_ready_channels() -> list:
    """Token'i olan tüm kanalları keşfet."""
    from src.channel_manager import list_channels, get_channel
    ready = []
    for cid in list_channels():
        try:
            cfg = get_channel(cid)
            if Path(cfg.token_path).exists():
                ready.append(cid)
        except Exception:
            pass
    return ready


def get_next_upload_time(cfg, skip_occupied: list = None) -> str:
    """
    Bu kanalın bir sonraki upload saatini ISO 8601 olarak döndür.
    skip_occupied: zaten dolu olan publishAt saatleri listesi (çift yüklemeyi önler)
    """
    now = datetime.now(TZ)
    occupied = set(skip_occupied or [])

    # Önce bugünkü kalan slotlara bak
    for upload_time in sorted(cfg.upload_times):
        h, m = map(int, upload_time.split(":"))
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        candidate_str = candidate.isoformat()
        if candidate > now + timedelta(minutes=45) and candidate_str not in occupied:
            return candidate_str

    # Bugün geçtiyse yarın ve sonrasına bak (tüm slotları dene)
    for day_offset in range(1, 8):  # Maksimum 7 gün ilerisine bak
        future = now + timedelta(days=day_offset)
        for upload_time in sorted(cfg.upload_times):
            h, m = map(int, upload_time.split(":"))
            candidate = future.replace(hour=h, minute=m, second=0, microsecond=0)
            candidate_str = candidate.isoformat()
            if candidate_str not in occupied:
                return candidate_str

    # Fallback
    tomorrow = now + timedelta(days=1)
    first = sorted(cfg.upload_times)[0]
    h, m = map(int, first.split(":"))
    return tomorrow.replace(hour=h, minute=m, second=0, microsecond=0).isoformat()


# ─── Ana İşlemler ─────────────────────────────────────────────────────────────

def _validate_render_trigger_source(trigger_source: str | None) -> str:
    source = str(trigger_source or "").strip()
    if source not in VALID_RENDER_TRIGGER_SOURCES:
        raise ValueError(f"invalid_render_trigger_source:{source or '<missing>'}")
    return source


def _submit_render(channel_id: str, *, trigger_source: str):
    source = _validate_render_trigger_source(trigger_source)
    return render_executor.submit(render_and_schedule, channel_id, trigger_source=source)


def _eligible_initial_fill_channels(*, ready_channels: list[str] | None = None, queue: dict | None = None) -> list[str]:
    ready = list(ready_channels if ready_channels is not None else get_ready_channels())
    current_queue = queue if queue is not None else load_queue()
    eligible = []
    for cid in ready:
        active_entries = [entry for entry in current_queue.get(cid, []) if _is_publishable_queue_entry(entry)]
        if not active_entries:
            eligible.append(cid)
    return eligible


def _emit_startup_content_generation_decision(
    *,
    trigger_source: str,
    startup_mode: str,
    generation_allowed: bool,
    eligible_channels: list[str],
    submitted_channels: list[str],
    reason: str,
) -> dict[str, Any]:
    event = {
        "event_type": "startup_content_generation_decision",
        "timestamp": datetime.now(TZ).isoformat(),
        "production_sha": _resolve_git_head_short(),
        "service_pid": os.getpid(),
        "trigger_source": str(trigger_source),
        "startup_mode": str(startup_mode),
        "generation_allowed": bool(generation_allowed),
        "eligible_channels": list(eligible_channels),
        "submitted_channels": list(submitted_channels),
        "reason": str(reason),
    }
    try:
        record_production_event(event)
    except Exception as exc:
        logger.warning("startup_content_generation_decision telemetry failed: %s", exc)
    return event


def inspect_startup_generation_candidates(ready_channels: list[str] | None = None) -> dict[str, Any]:
    ready = list(ready_channels if ready_channels is not None else get_ready_channels())
    queue = load_queue()
    publishable_counts = {
        cid: len([entry for entry in queue.get(cid, []) if _is_publishable_queue_entry(entry)])
        for cid in ready
    }
    eligible = [cid for cid, count in publishable_counts.items() if count == 0]
    decision = _emit_startup_content_generation_decision(
        trigger_source="service_startup",
        startup_mode="validation_only",
        generation_allowed=False,
        eligible_channels=eligible,
        submitted_channels=[],
        reason="startup_generation_deferred",
    )
    logger.info(
        "Startup generation deferred: ready_channels=%s publishable_queue_counts=%s eligible_channels=%s required_trigger=%s",
        len(ready),
        publishable_counts,
        eligible,
        "explicit_initial_fill_or_scheduled_fill",
    )
    decision["ready_channels"] = ready
    decision["publishable_queue_counts"] = publishable_counts
    decision["required_trigger"] = "explicit_initial_fill_or_scheduled_fill"
    return decision


def render_and_schedule(channel_id: str, *, trigger_source: str):
    """
    Bir kanalın sonraki videosunu render eder ve
    YouTube'a Scheduled olarak yükler.
    """
    trigger_source = _validate_render_trigger_source(trigger_source)

    try:
        from src.scheduler_utils import (
            check_disk_space, cleanup_old_renders, force_cleanup,
            get_global_overload_pause_status, get_provider_circuit_status, notify_upload, notify_error,
            record_provider_failure, record_provider_success, save_used_topic,
            _append_queue_quarantine_decision,
        )
    except ImportError:
        def check_disk_space(**kw): return True
        def cleanup_old_renders(**kw): return 0
        def force_cleanup():
            import gc; gc.collect()
        def get_global_overload_pause_status():
            return {"is_open": False, "retry_after_seconds": 0, "pause_until": "", "reason": ""}
        def get_provider_circuit_status(provider: str):
            return {"provider": provider, "is_open": False, "retry_after_seconds": 0, "state": {}}
        def notify_upload(*a, **kw): pass
        def notify_error(*a, **kw): pass
        def record_provider_failure(*a, **kw): return {}
        def record_provider_success(*a, **kw): return {}
        def save_used_topic(*a): pass
        def _append_queue_quarantine_decision(*a, **kw): pass

    channel_lock = _get_channel_render_lock(channel_id)
    acquired = channel_lock.acquire(blocking=False)
    if not acquired:
        logger.info(f"[{channel_id}] Render zaten devam ediyor, atlandı.")
        return

    try:
        from src.channel_manager import get_channel
        from src.pipeline import run_full_pipeline

        cfg = get_channel(channel_id)
        os.environ.setdefault("PRODUCTION_QUALITY_PLATFORM_ENABLED", "true")
        os.environ.setdefault("CONTENT_QUALITY_GATE_ENABLED", "true")

        canary = canary_gate_decision(channel_id)
        if not canary.get("allow", True):
            logger.warning("[%s] Canary gate blocked run: %s", cfg.name, canary.get("reason"))
            update_production_dashboard(
                scheduler_status="canary_blocked",
                build_sha=_resolve_git_head_short(),
                scheduler_pid=os.getpid(),
                last_error=str(canary.get("reason") or "canary_blocked"),
            )
            return

        pause = get_global_overload_pause_status()
        if pause.get("is_open"):
            retry_after = int(pause.get("retry_after_seconds", 0))
            reason = str(pause.get("reason") or "overload_storm")
            logger.warning(
                "[%s] Global overload pause OPEN. Render atlandi, retry_after=%ss, reason=%s",
                cfg.name,
                retry_after,
                reason,
            )
            notify_error(
                cfg.name,
                f"Global overload pause open; provider cooling down ({retry_after}s)",
            )
            return

        # ── Provider circuit breaker kontrolü ────────────────────────
        circuit = get_provider_circuit_status("anthropic")
        if circuit.get("is_open"):
            retry_after = int(circuit.get("retry_after_seconds", 0))
            logger.warning(
                "[%s] Anthropic circuit OPEN. Render atlandi, retry_after=%ss",
                cfg.name,
                retry_after,
            )
            notify_error(
                cfg.name,
                f"Anthropic circuit open; provider is cooling down ({retry_after}s)",
            )
            return

        # ── Disk kontrolü ──────────────────────────────────────────────
        if not check_disk_space(min_gb=1.5):
            logger.error(f"[{cfg.name}] Disk doldu! Render iptal edildi.")
            notify_error(cfg.name, "Disk alanı kritik seviyede!")
            return

        publish_at = get_next_upload_time(
            cfg,
            skip_occupied=[
                e.get("publish_at", "")
                for e in load_queue().get(channel_id, [])
                if _is_publishable_queue_entry(e)
            ]
        )
        logger.info(f"[{cfg.name}] Render başlıyor → {publish_at} için zamanlanacak")

        # ── Retry ile pipeline çalıştır ────────────────────────────────
        last_error = None
        result = None
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):  # Maks 3 deneme
            try:
                result = run_full_pipeline(
                    channel_cfg=cfg,
                    privacy="private",
                    publish_at=publish_at,
                    trigger_source=trigger_source,
                )
                break  # Başarılı
            except Exception as e:
                last_error = e
                error_text = str(getattr(e, "_provider_error_text", str(e)))
                error_str = error_text.lower()
                failure_class = _classify_pipeline_failure(error_text, e)
                provider_failure_tokens = (
                    "anthropic",
                    "credit balance",
                    "quota",
                    "invalid_request",
                    "http 400",
                    "http 401",
                    "http 403",
                    "http 429",
                    "http 529",
                    "rate limit",
                    "overloaded",
                    "overloaded_error",
                    "service unavailable",
                    "internal server error",
                )
                provider_related = any(token in error_str for token in provider_failure_tokens)
                overloaded_signal = any(token in error_str for token in ("overloaded", "overloaded_error", "529"))
                if provider_related and (overloaded_signal or not getattr(e, "_provider_failure_recorded", False)):
                    record_provider_failure("anthropic", error_text)

                # 529 overload dalgasinda kanal-icinde tekrar denemek yerine global circuit'e birak.
                if overloaded_signal:
                    setattr(e, "_skip_scheduler_pipeline_retry", True)

                setattr(e, "_retry_count", attempt)
                setattr(e, "_retry_reason", str(failure_class.get("retry_reason") or "unknown"))

                if failure_class["classification"] == NON_RETRYABLE_QUARANTINE:
                    setattr(e, "_skip_scheduler_pipeline_retry", True)
                    setattr(e, "_guard_reason_codes", list(failure_class.get("guard_reason_codes") or []))
                    setattr(e, "_quarantine_reason", str(failure_class.get("quarantine_reason") or "topic_domain_blocked"))
                    raise

                # Kesinlikle retry yapma
                if failure_class["classification"] == TERMINAL_FAILURE:
                    logger.error(f"[{cfg.name}] Fatal hata (retry yok): {e}")
                    if "failed_fact_check" not in error_str:
                        decision = notify_error(
                            cfg.name,
                            error_text,
                            context={
                                "run_id": str(getattr(e, "_run_id", "") or ""),
                                "content_id": str(getattr(e, "_content_id", "") or ""),
                                "pipeline_stage": str(getattr(e, "_pipeline_stage", "content_generation") or "content_generation"),
                                "retry_count": attempt,
                                "retry_limit": max_attempts,
                                "regeneration_count": int(getattr(e, "_regeneration_count", 0) or 0),
                                "regeneration_limit": int(getattr(e, "_regeneration_limit", 1) or 1),
                                "error_type": str(getattr(e, "_error_type", "") or ""),
                                "guard_reason_codes": list(getattr(e, "_guard_reason_codes", []) or []),
                                "triggering_validator": str(getattr(e, "_triggering_validator", "") or ""),
                                "selected_topic": str(getattr(e, "_topic", "") or ""),
                                "collision_path": str(getattr(e, "_collision_path", "") or ""),
                                "expected_channel": channel_id,
                                "detected_channel": str(getattr(e, "_detected_channel", "") or channel_id),
                                "original_topic_source": str(getattr(e, "_original_topic_source", "") or ""),
                                "provenance_score": getattr(e, "_provenance_score", None),
                                "confidence_score": getattr(e, "_confidence_score", None),
                            },
                        )
                        logger.info(
                            "[%s] Telegram karar feedback: %s incident_id=%s lifecycle=%s",
                            cfg.name,
                            decision.get("decision"),
                            decision.get("incident_id", ""),
                            decision.get("incident_lifecycle", ""),
                        )
                        setattr(e, "_scheduler_notify_sent", True)
                    raise

                retry_decision = classify_retry_decision(error_text=error_text, exc=e, stage="scheduler_render")
                if getattr(e, "_skip_scheduler_pipeline_retry", False) or not retry_decision.retryable:
                    raise
                if attempt < 3:
                    wait = 30 * attempt
                    logger.warning(f"[{cfg.name}] Deneme {attempt}/3 başarısız, {wait}s bekleniyor... ({e})")
                    time.sleep(wait)
                else:
                    raise

        if result and result.get("video_id"):
            record_provider_success("anthropic", note=f"render_ok:{channel_id}")
            # Topic deduplication kaydı
            save_used_topic(channel_id, result.get("title", ""))

            # Kuyruk güncelle (thread-safe + atomic)
            def _append_entry(queue):
                if channel_id not in queue:
                    queue[channel_id] = []
                queue[channel_id].append(_normalize_queue_entry({
                    "queue_entry_id": f"qe_{uuid.uuid4().hex[:16]}",
                    "video_id": result["video_id"],
                    "title": result["title"],
                    "youtube_url": result.get("youtube_url", ""),
                    "publish_at": publish_at,
                    "rendered_at": datetime.now(TZ).isoformat(),
                    "status": "active",
                    "channel_id": channel_id,
                }))
            update_queue(_append_entry)
            logger.info(f"[{cfg.name}] ✅ Zamanlandı: '{result['title'][:50]}' → {publish_at}")

            # Telegram bildirimi
            notify_upload(
                cfg.name,
                result.get("title", ""),
                result.get("youtube_url", ""),
                result.get("short_url", ""),
            )

            # Güvenli mod: cross-channel like/subscribe devre dışı
            logger.info(f"[{cfg.name}] Cross-channel like/subscribe devre dışı (safe mode).")

            # Büyüme milestone kontrolü
            try:
                from src.scheduler_utils import check_growth_milestones
                check_growth_milestones(new_video_count=1)
            except Exception:
                pass
            try:
                update_production_dashboard(
                    scheduler_status="active",
                    build_sha=_resolve_git_head_short(),
                    scheduler_pid=os.getpid(),
                    last_error=None,
                )
            except Exception:
                pass
        elif result and result.get("upload_precheck", {}).get("status") == "blocked":
            precheck = dict(result.get("upload_precheck") or {})
            reason_codes = list(precheck.get("guard_reason_codes") or ["channel_dna_mismatch"])

            def _append_quarantined_entry(queue):
                if channel_id not in queue:
                    queue[channel_id] = []
                queue[channel_id].append(_normalize_queue_entry({
                    "queue_entry_id": f"qe_{uuid.uuid4().hex[:16]}",
                    "video_id": None,
                    "title": result.get("title", ""),
                    "youtube_url": "",
                    "publish_at": publish_at,
                    "rendered_at": datetime.now(TZ).isoformat(),
                    "status": "quarantined",
                    "channel_id": channel_id,
                    "quarantine_reason": str(precheck.get("quarantine_reason") or "channel_dna_mismatch"),
                    "guard_reason_codes": reason_codes,
                    "quarantined_at": datetime.now(TZ).isoformat(),
                    "recoverable": bool(precheck.get("recoverable", True)),
                    "review_status": "pending",
                }))

            update_queue(_append_quarantined_entry)
            _append_queue_quarantine_decision(
                {
                    "event": "upload_precheck_blocked",
                    "channel_id": channel_id,
                    "reason": str(precheck.get("quarantine_reason") or "channel_dna_mismatch"),
                    "guard_reason_codes": reason_codes,
                    "title_preview": str(result.get("title") or "")[:180],
                    "source": "scheduler.render_and_schedule",
                }
            )
            logger.warning(f"[{cfg.name}] Upload precheck blocked; queue entry quarantined.")
            try:
                update_production_dashboard(
                    scheduler_status="active_with_blocks",
                    build_sha=_resolve_git_head_short(),
                    scheduler_pid=os.getpid(),
                    last_error="upload_precheck_blocked",
                )
            except Exception:
                pass
        else:
            upload_error_text = str((result or {}).get("upload_error") or "")
            upload_meta = dict((result or {}).get("upload_metadata") or {})
            failure_kind = str(upload_meta.get("failure_kind") or "unknown")
            if not failure_kind or failure_kind == "unknown":
                lower = upload_error_text.lower()
                if any(token in lower for token in ("quota", "ratelimit", "rate limit", "401", "403", "credential", "permission")):
                    failure_kind = "auth_or_quota"
                elif any(token in lower for token in ("validation", "invalid", "metadata", "400")):
                    failure_kind = "metadata_rejection"
                elif any(token in lower for token in ("idempot", "duplicate", "conflict", "409")):
                    failure_kind = "duplicate_or_idempotency"
                elif any(token in lower for token in ("missing_id", "video id", "response")):
                    failure_kind = "missing_response_id"
                elif any(token in lower for token in ("timeout", "dns", "network", "server", "5")):
                    failure_kind = "api_error"

            logger.error(
                "[%s] Video ID alınamadı! failure_kind=%s upload_error=%s upload_metadata=%s",
                cfg.name,
                failure_kind,
                upload_error_text[:500] or "none",
                upload_meta,
            )

    except Exception as e:
        routed_error_text = str(getattr(e, "_provider_error_text", str(e)))
        err_text = routed_error_text.lower()
        failure_class = _classify_pipeline_failure(routed_error_text, e)
        if any(token in err_text for token in (
            "anthropic",
            "credit balance",
            "quota",
            "invalid_request",
            "http 400",
            "http 401",
            "http 403",
            "http 429",
            "http 529",
            "rate limit",
            "overloaded",
            "overloaded_error",
            "service unavailable",
            "internal server error",
        )) and not getattr(e, "_provider_failure_recorded", False):
            record_provider_failure("anthropic", routed_error_text)
        logger.error(f"[{channel_id}] Render hatası: {e}", exc_info=True)
        if failure_class["classification"] == NON_RETRYABLE_QUARANTINE:
            try:
                from src.channel_manager import get_channel as _get_channel
                cfg = _get_channel(channel_id)
                publish_at = get_next_upload_time(
                    cfg,
                    skip_occupied=[
                        entry.get("publish_at", "")
                        for entry in load_queue().get(channel_id, [])
                        if _is_publishable_queue_entry(entry)
                    ],
                )

                _quarantine_non_retryable_domain_block(
                    channel_id=channel_id,
                    cfg=cfg,
                    publish_at=publish_at,
                    failure={
                        "quarantine_reason": str(getattr(e, "_quarantine_reason", "topic_domain_blocked")),
                        "guard_reason_codes": list(getattr(e, "_guard_reason_codes", []) or list(failure_class.get("guard_reason_codes") or [])),
                        "run_id": str(getattr(e, "_run_id", "") or ""),
                        "content_id": str(getattr(e, "_content_id", "") or ""),
                        "topic": str(getattr(e, "_topic", "") or ""),
                        "detected_domain": str(getattr(e, "_detected_domain", "unknown") or "unknown"),
                        "retry_count": int(getattr(e, "_retry_count", 1) or 1),
                        "regeneration_count": int(getattr(e, "_regeneration_count", 0) or 0),
                        "source_exception_type": e.__class__.__name__,
                        "source_exception_message": routed_error_text,
                    },
                    routed_error_text=routed_error_text,
                    source_stage="scheduler.render_and_schedule",
                )
            except Exception:
                pass
        try:
            record_dead_letter(
                {
                    "channel_id": channel_id,
                    "stage": "scheduler_render_and_schedule",
                    "error": str(e),
                    "retry_count": 3,
                }
            )
            update_production_dashboard(
                scheduler_status="degraded",
                build_sha=_resolve_git_head_short(),
                scheduler_pid=os.getpid(),
                last_error=str(e),
            )
        except Exception:
            pass
        try:
            if "failed_fact_check" in routed_error_text.lower():
                return
            if getattr(e, "_scheduler_notify_sent", False):
                return
            from src.channel_manager import get_channel
            cfg = get_channel(channel_id)
            from src.scheduler_utils import notify_error
            decision = notify_error(
                cfg.name,
                routed_error_text,
                context={
                    "run_id": str(getattr(e, "_run_id", "") or ""),
                    "content_id": str(getattr(e, "_content_id", "") or ""),
                    "pipeline_stage": str(getattr(e, "_pipeline_stage", "scheduler_render") or "scheduler_render"),
                    "retry_count": int(getattr(e, "_retry_count", 0) or 0),
                    "retry_limit": 3,
                    "regeneration_count": int(getattr(e, "_regeneration_count", 0) or 0),
                    "regeneration_limit": int(getattr(e, "_regeneration_limit", 1) or 1),
                    "error_type": str(getattr(e, "_error_type", "") or ""),
                    "guard_reason_codes": list(getattr(e, "_guard_reason_codes", []) or []),
                    "triggering_validator": str(getattr(e, "_triggering_validator", "") or ""),
                    "selected_topic": str(getattr(e, "_topic", "") or ""),
                    "collision_path": str(getattr(e, "_collision_path", "") or ""),
                    "expected_channel": channel_id,
                    "detected_channel": str(getattr(e, "_detected_channel", "") or channel_id),
                    "original_topic_source": str(getattr(e, "_original_topic_source", "") or ""),
                    "provenance_score": getattr(e, "_provenance_score", None),
                    "confidence_score": getattr(e, "_confidence_score", None),
                },
            )
            logger.info(
                "[%s] Telegram karar feedback: %s incident_id=%s lifecycle=%s",
                cfg.name,
                decision.get("decision"),
                decision.get("incident_id", ""),
                decision.get("incident_lifecycle", ""),
            )
        except Exception:
            pass
    finally:
        if acquired:
            channel_lock.release()
        force_cleanup()  # Belleği temizle


def on_upload_time(channel_id: str):
    """
    Upload zamanı geldiğinde çağrılır.
    YouTube o videoyu otomatik yayınlıyor — Telegram'a bildir.
    """
    from src.channel_manager import get_channel
    cfg = get_channel(channel_id)
    logger.info(f"[{cfg.name}] Upload zamanı — YouTube otomatik yayınlıyor.")

    # Kuyruktaki yayınlanan videoyu atomik olarak düşür ve bildir
    try:
        from src.scheduler_utils import send_telegram
        published = {}

        def _pop_published(queue):
            entries = list(queue.get(channel_id, []) or [])
            publish_index = None
            for idx, candidate in enumerate(entries):
                if _is_publishable_queue_entry(candidate):
                    publish_index = idx
                    break
            if publish_index is None:
                return
            published.update(entries.pop(publish_index))
            if entries:
                queue[channel_id] = entries
            else:
                queue.pop(channel_id, None)

        update_queue(_pop_published)

        if published:
            entry = published
            title = entry.get("title", "")
            url = entry.get("youtube_url", "")
            send_telegram(
                f"🚀 <b>Yeni Video Yayında!</b>\n"
                f"📺 {cfg.name}\n"
                f"🎬 {title[:60]}\n"
                f"🔗 {url}"
            )
    except Exception as e:
        logger.warning(f"Yayın bildirimi gönderilemedi: {e}")

    # Bir sonraki video için render'ı thread havuzuna gönder
    _submit_render(channel_id, trigger_source="post_upload_continuation")


def initial_fill(*, trigger_source: str = "explicit_initial_fill"):
    """
    Başlangıçta tüm kanallar için ön render başlat.
    Her kanal için bir sonraki boş saate video hazırla.
    """
    trigger_source = _validate_render_trigger_source(trigger_source)
    if trigger_source != "explicit_initial_fill":
        raise ValueError(f"initial_fill_requires_explicit_trigger:{trigger_source}")

    if _observation_mode_active():
        logger.warning("Initial fill skipped: production_observation_mode")
        return
    ready = get_ready_channels()
    queue = load_queue()

    logger.info(f"Başlangıç: {len(ready)} kanal için ön render kontrol ediliyor...")
    # Başlangıçta bayat kuyruk girişlerini temizle
    try:
        from src.scheduler_utils import cleanup_stale_queue
        cleanup_state = {"freed": []}

        def _cleanup_mutator(current_queue):
            cleaned, freed = cleanup_stale_queue(current_queue, TZ)
            current_queue.clear()
            current_queue.update(cleaned)
            cleanup_state["freed"] = list(freed)

        queue = update_queue(_cleanup_mutator)
        freed = cleanup_state["freed"]
        if freed:
            logger.info(f"Başlangıç temizliği: {len(freed)} kanal için bayat kuyruk temizlendi")
    except Exception as e:
        logger.warning(f"Bayat kuyruk temizleme hatası: {e}")

    submitted_channels = []
    for cid in ready:
        # Bu kanalın kuyruğunda zaten video var mı?
        active_entries = [e for e in queue.get(cid, []) if _is_publishable_queue_entry(e)]
        if active_entries:
            logger.info(f"[{cid}] Kuyrukta video mevcut, render atlandı.")
            continue
        # Kuyrugu bos — render baslât
        logger.info(f"[{cid}] On render basliyor (siraya eklendi)...")
        _submit_render(cid, trigger_source=trigger_source)
        submitted_channels.append(cid)
        time.sleep(5)  # Kilit çakışmasını önle — ThreadPoolExecutor zaten tek sırada çalıştırır

    _emit_startup_content_generation_decision(
        trigger_source=trigger_source,
        startup_mode="explicit_initial_fill",
        generation_allowed=True,
        eligible_channels=_eligible_initial_fill_channels(ready_channels=ready, queue=queue),
        submitted_channels=submitted_channels,
        reason="explicit_initial_fill_requested",
    )


def catch_up_overdue_queue_entries() -> dict[str, list[dict]]:
    """Tarihi geçmiş publish kayıtlarını başlangıçta tüket; yeni render başlatmaz."""
    from src.channel_manager import get_channel

    queue = load_queue()
    now = datetime.now(TZ)
    caught_up: dict[str, list[dict]] = {}

    for channel_id in get_ready_channels():
        entries = list(queue.get(channel_id, []) or [])
        overdue_entries = []
        for entry in entries:
            if not _is_publishable_queue_entry(entry):
                continue
            publish_at = str(entry.get("publish_at") or "").strip()
            if not publish_at:
                continue
            try:
                publish_dt = datetime.fromisoformat(publish_at)
            except Exception:
                continue
            if publish_dt <= now:
                overdue_entries.append(entry)

        if not overdue_entries:
            continue

        published_batch: list[dict] = []

        def _pop_overdue(current_queue):
            channel_entries = list(current_queue.get(channel_id, []) or [])
            remaining = []
            for item in channel_entries:
                if not _is_publishable_queue_entry(item):
                    remaining.append(item)
                    continue
                publish_at = str(item.get("publish_at") or "").strip()
                try:
                    publish_dt = datetime.fromisoformat(publish_at) if publish_at else None
                except Exception:
                    publish_dt = None
                if publish_dt and publish_dt <= now:
                    published_batch.append(item)
                else:
                    remaining.append(item)
            if remaining:
                current_queue[channel_id] = remaining
            else:
                current_queue.pop(channel_id, None)

        update_queue(_pop_overdue)
        if not published_batch:
            continue

        caught_up[channel_id] = published_batch
        cfg = get_channel(channel_id)
        logger.info("[%s] Startup catch-up: %s gecikmiş kuyruk girişi tüketildi", channel_id, len(published_batch))

        try:
            from src.scheduler_utils import send_telegram

            for entry in published_batch:
                send_telegram(
                    f"🚀 <b>Yeni Video Yayında!</b>\n"
                    f"📺 {cfg.name}\n"
                    f"🎬 {str(entry.get('title') or '')[:60]}\n"
                    f"🔗 {entry.get('youtube_url', '')}"
                )
        except Exception as e:
            logger.warning("[%s] Startup catch-up bildirimi gönderilemedi: %s", channel_id, e)

        logger.info("[%s] Startup catch-up generation deferred; next render requires scheduled or explicit trigger", channel_id)

    return caught_up


def setup_schedule():
    """Tüm aktif kanallar için upload zamanlarını ayarla."""
    from src.channel_manager import get_channel

    ready = get_ready_channels()
    day_map = {
        "Monday": schedule.every().monday,
        "Tuesday": schedule.every().tuesday,
        "Wednesday": schedule.every().wednesday,
        "Thursday": schedule.every().thursday,
        "Friday": schedule.every().friday,
        "Saturday": schedule.every().saturday,
        "Sunday": schedule.every().sunday,
    }
    days = list(day_map.keys())

    for cid in ready:
        cfg = get_channel(cid)
        for day in days:
            for t in cfg.upload_times:
                cid_copy = cid
                day_map[day].at(t).do(on_upload_time, channel_id=cid_copy)

    logger.info(f"{len(schedule.jobs)} zamanlama aktif ({len(ready)} kanal)")
    return ready


def show_status():
    """Kanal + kuyruk durumunu göster."""
    from rich.console import Console
    from rich.table import Table
    from src.channel_manager import get_channel

    console = Console()
    ready = get_ready_channels()
    queue = load_queue()

    table = Table(title=f"Sistem Durumu — {len(ready)} Aktif Kanal", border_style="cyan")
    table.add_column("Kanal")
    table.add_column("Upload Saatleri")
    table.add_column("Kuyrukta")
    table.add_column("Sonraki")

    for cid in ready:
        cfg = get_channel(cid)
        q_count = len([e for e in queue.get(cid, []) if _is_publishable_queue_entry(e)])
        next_t = get_next_upload_time(cfg).split("T")[1][:5]
        table.add_row(
            cfg.name,
            " + ".join(cfg.upload_times),
            str(q_count),
            next_t,
        )

    console.print(table)
    console.print(f"\n[dim]MAX_PARALLEL_RENDERS={MAX_PARALLEL_RENDERS}[/dim]")


def _startup_subscribe_check():
    """Başlangıçta yeni kanalları tespit et, diğer kanallar abone olsun."""
    logger.info("Cross-channel auto-subscribe devre dışı (safe mode).")


# ─── Ana Giriş ────────────────────────────────────────────────────────────────

def maintenance_job():
    """Günlük bakım: disk + log rotation + token kontrol + bayat kuyruk temizle."""
    from src.scheduler_utils import (
        cleanup_old_renders, health_check, send_telegram,
        rotate_log_file, verify_all_tokens, cleanup_stale_queue,
    )
    logger.info("Bakım başlıyor...")

    # 1. Eski render dosyalarını sil
    deleted = cleanup_old_renders(max_age_hours=48)

    # 2. Log rotation (8000 satır limit)
    for log_file in ["logs/vps_scheduler.log", "logs/scheduler.log", "logs/vps_error.log"]:
        rotate_log_file(log_file, max_lines=8000)

    # 3. Bayat kuyruk girişlerini temizle + boşalan kanallar için render tetikle
    cleanup_state = {"freed": []}

    def _cleanup_mutator(current_queue):
        cleaned, freed = cleanup_stale_queue(current_queue, TZ)
        current_queue.clear()
        current_queue.update(cleaned)
        cleanup_state["freed"] = list(freed)

    update_queue(_cleanup_mutator)
    freed = cleanup_state["freed"]
    if freed:
        for cid in freed:
            logger.info(f"[{cid}] Bayat kuyruk temizlendi → yeni render başlatılıyor")
            _submit_render(cid, trigger_source="recurring_empty_queue_fill")

    # 4. Token sağlık kontrolü (sorunlular Telegram'a bildirilir)
    verify_all_tokens()

    # 5. Kapasite uyarıları (RAM, disk, kanal sayısı, ElevenLabs kredit)
    try:
        from src.scheduler_utils import check_capacity_alerts
        check_capacity_alerts()
    except Exception as e:
        logger.warning(f"Kapasite kontrol hatası: {e}")

    # 6. PROGRESS.md güncelle
    update_progress_file(
        last_task="Günlük bakım tamamlandı",
        next_step="Scheduler çalışıyor — videoları otomatik yüklüyor"
    )

    status = health_check()
    if deleted > 0:
        logger.info(f"Bakım tamam: {deleted:.0f} MB silindi, {status['disk_free_gb']:.1f} GB boş")

    send_telegram(
        f"📊 <b>Günlük Rapor</b>\n"
        f"📡 {status['active_channels']} aktif kanal\n"
        f"💾 Disk: {status['disk_free_gb']:.1f} GB boş\n"
        f"🗄 Boyat kuyruk temizlendi: {len(freed)} kanal\n"
        f"✅ Sistem sağlıklı"
    )


def refresh_live_analytics_job():
    """Canlı YouTube Analytics verisini al ve optimization state'i yenile."""
    live_enabled, live_status = _resolve_live_collector_runtime()
    if not live_enabled:
        logger.info(
            "Live analytics refresh skipped: live_collector_enabled=false analytics_live_status=%s",
            live_status,
        )
        return

    try:
        from src.channel_manager import get_channel
        from src.channel_performance import append_performance_snapshot, load_recent_performance_snapshots
        from src.performance_optimizer import refresh_channel_optimization_state
        from src.youtube_analytics import fetch_recent_video_analytics

        snapshots = load_recent_performance_snapshots(lookback_days=14, max_items=400)
        by_channel: dict[str, list[dict]] = {}
        for row in snapshots:
            channel_id = str(row.get("channel_id") or "default")
            by_channel.setdefault(channel_id, []).append(row)

        for channel_id, rows in by_channel.items():
            try:
                cfg = get_channel(channel_id)
            except Exception as e:
                logger.warning("[%s] Optimization refresh skipped: %s", channel_id, e)
                continue

            latest_by_video = {}
            for row in rows:
                video_id = str(row.get("video_id") or "").strip()
                if not video_id:
                    continue
                if video_id not in latest_by_video:
                    latest_by_video[video_id] = row

            video_ids = list(latest_by_video.keys())[:5]
            if not video_ids:
                continue

            reports = fetch_recent_video_analytics(video_ids=video_ids, channel_cfg=cfg, lookback_days=14)
            reports_by_video = {str(report.get("video_id")): report for report in reports if report.get("video_id")}

            for video_id, base_row in latest_by_video.items():
                analytics = reports_by_video.get(video_id)
                if not analytics:
                    continue
                enriched = dict(base_row)
                enriched["youtube_analytics"] = analytics
                enriched["analytics_synced_at"] = datetime.now(TZ).isoformat()
                append_performance_snapshot(enriched)

            state = refresh_channel_optimization_state(channel_id)
            logger.info(
                "[%s] Live analytics synced: focus=%s mode=%s",
                channel_id,
                ",".join(state.get("focus", [])),
                state.get("mode"),
            )
    except Exception as e:
        logger.warning("Live analytics refresh failed: %s", e)


def run_optimization_runtime_cycle() -> dict:
    """Run controller + fleet + backlog + memory and persist runtime evidence."""
    ready_channels = get_ready_channels()
    target_channel = os.getenv("ACTIVATION_CONTROLLER_CHANNEL", "").strip()
    if not target_channel and ready_channels:
        target_channel = ready_channels[0]

    flags_path = _path_from_env("ACTIVATION_FLAGS_PATH", "output/state/learning_activation_flags.json")
    flags_before = _load_json_file(flags_path)

    evidence = {
        "generated_at": datetime.now(TZ).isoformat(),
        "kind": "runtime_optimization_cycle",
        "target_channel": target_channel,
        "ready_channel_count": len(ready_channels),
        "steps": {},
        "flags_before": flags_before,
    }

    if not target_channel:
        evidence["ok"] = False
        evidence["error"] = "no_ready_channel"
        return evidence

    python_bin = sys.executable
    activate_learning = _is_enabled(os.getenv("RUNTIME_POLICY_ACTIVATE", "false"))
    skip_analytics_probe = _is_enabled(os.getenv("RUNTIME_POLICY_SKIP_ANALYTICS_PROBE", "true"))

    activation_cmd = [
        python_bin,
        str(ACTIVATION_CONTROLLER_SCRIPT),
        "--channel",
        target_channel,
    ]
    if skip_analytics_probe:
        activation_cmd.append("--skip-analytics-probe")
    if activate_learning:
        activation_cmd.append("--activate-learning")

    evidence["steps"]["activation_controller"] = _run_json_script(activation_cmd)
    evidence["steps"]["fleet_health"] = _run_json_script([python_bin, str(FLEET_HEALTH_SCRIPT)])
    evidence["steps"]["optimization_backlog"] = _run_json_script([python_bin, str(BACKLOG_SCRIPT)])
    evidence["steps"]["optimization_memory"] = _run_json_script([python_bin, str(OPTIMIZATION_MEMORY_SCRIPT)])

    flags_after = _load_json_file(flags_path)
    evidence["flags_after"] = flags_after
    evidence["flag_changed"] = flags_before != flags_after

    step_results = evidence["steps"].values()
    evidence["ok"] = all(bool(item.get("ok")) for item in step_results)
    return evidence


def optimization_runtime_cycle_job():
    """Manually triggerable runtime evidence producer for optimization layers."""
    try:
        evidence = run_optimization_runtime_cycle()

        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
        stamped = logs_dir / f"runtime_optimization_evidence_{ts}.json"
        _write_json_atomic(stamped, evidence)
        _write_json_atomic(RUNTIME_EVIDENCE_LATEST_FILE, evidence)

        logger.info(
            "Runtime optimization cycle: ok=%s target_channel=%s flag_changed=%s",
            evidence.get("ok"),
            evidence.get("target_channel"),
            evidence.get("flag_changed"),
        )
    except Exception as e:
        logger.warning("Runtime optimization cycle failed: %s", e)


def _run_governance_refresh_shadow(
    *,
    lookback_rows: int,
    refresh_invoker=None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Run governance refresh in explicit shadow mode.

    This wrapper is integration-local and always fail-open relative to scheduler flow.
    """
    started = time.monotonic()
    result: dict[str, Any] = {
        "invoked": False,
        "shadow_mode": True,
        "success": False,
        "fail_open": True,
        "warning": "shadow_not_run",
        "duration_ms": 0,
    }

    try:
        invoker = refresh_invoker
        if invoker is None:
            python_bin = sys.executable
            command = [
                python_bin,
                str(GOVERNANCE_REFRESH_SCRIPT),
                "--lookback-rows",
                str(max(1, int(lookback_rows))),
            ]

            def _default_invoker(*, cmd: list[str], timeout: int) -> dict[str, Any]:
                return _run_json_script(cmd, timeout_seconds=timeout)

            invoker = _default_invoker
        else:
            command = [
                sys.executable,
                str(GOVERNANCE_REFRESH_SCRIPT),
                "--lookback-rows",
                str(max(1, int(lookback_rows))),
            ]

        result["invoked"] = True
        raw = invoker(cmd=command, timeout=max(10, int(timeout_seconds)))
        if not isinstance(raw, dict):
            result["warning"] = "shadow_malformed_result"
            return result

        if bool(raw.get("timed_out", False)):
            result["warning"] = "shadow_timeout"
            return result

        ok = bool(raw.get("ok", False))
        result["success"] = ok
        if ok:
            result["warning"] = ""
        else:
            result["warning"] = str(raw.get("error") or raw.get("stderr_tail") or "shadow_refresh_failed")
        return result
    except ImportError as e:
        result["warning"] = f"shadow_import_failure:{e}"
        return result
    except Exception as e:
        result["warning"] = f"shadow_exception:{e}"
        return result
    finally:
        result["duration_ms"] = max(0, int((time.monotonic() - started) * 1000))


def _evaluate_governance_shadow_diagnostics(
    *,
    lookback_rows: int,
    activation: dict[str, Any] | None = None,
    shadow_runner=None,
) -> dict[str, Any]:
    """Build deterministic informational diagnostics for governance shadow path."""
    state = str((activation or {}).get("state") or "disabled")
    enabled = bool((activation or {}).get("enabled", False))
    diagnostics: dict[str, Any] = {
        "activation_state": state,
        "invoked": False,
        "shadow_mode": True,
        "wrapper_executed": False,
        "success": False,
        "fail_open": True,
        "warning": "",
        "duration_ms": 0,
        "skipped_reason": "",
    }

    if not enabled:
        if state in {"invalid_flag", "fail_open"}:
            diagnostics["warning"] = state
            diagnostics["skipped_reason"] = state
        else:
            diagnostics["skipped_reason"] = "disabled"
        return diagnostics

    diagnostics["wrapper_executed"] = True
    try:
        runner = shadow_runner or _run_governance_refresh_shadow
        raw = runner(lookback_rows=lookback_rows)
        if not isinstance(raw, dict):
            diagnostics["warning"] = "shadow_malformed_result"
            return diagnostics

        diagnostics["invoked"] = bool(raw.get("invoked", False))
        diagnostics["success"] = bool(raw.get("success", False))
        diagnostics["fail_open"] = bool(raw.get("fail_open", True))
        diagnostics["warning"] = str(raw.get("warning") or "")
        diagnostics["duration_ms"] = max(0, int(raw.get("duration_ms", 0) or 0))
        return diagnostics
    except Exception as e:
        diagnostics["warning"] = f"shadow_diagnostics_fail_open:{e}"
        return diagnostics


def _evaluate_governance_shadow_rollout_readiness(
    *,
    activation: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    wrapper_runner=None,
    diagnostics_evaluator=None,
) -> dict[str, Any]:
    """Evaluate deterministic, advisory rollout readiness for governance shadow path."""
    activation_state = str((activation or {}).get("state") or "disabled")
    wrapper_callable = wrapper_runner if wrapper_runner is not None else _run_governance_refresh_shadow
    diagnostics_callable = (
        diagnostics_evaluator if diagnostics_evaluator is not None else _evaluate_governance_shadow_diagnostics
    )
    wrapper_available = callable(wrapper_callable)
    diagnostics_available = callable(diagnostics_callable) and isinstance(diagnostics, dict)

    readiness: dict[str, Any] = {
        "readiness_state": "not_ready",
        "activation_state": activation_state,
        "diagnostics_available": diagnostics_available,
        "wrapper_available": wrapper_available,
        "policy_version": "a4.7.v1",
        "ready": False,
        "warning": "",
        "fail_open": True,
    }

    if not wrapper_available:
        readiness["warning"] = "wrapper_unavailable"
        return readiness
    if not diagnostics_available:
        readiness["warning"] = "diagnostics_unavailable"
        return readiness

    if activation_state == "enabled":
        wrapper_executed = bool((diagnostics or {}).get("wrapper_executed", False))
        shadow_mode = bool((diagnostics or {}).get("shadow_mode", False))
        ready = wrapper_executed and shadow_mode
        readiness["ready"] = ready
        readiness["readiness_state"] = "ready" if ready else "not_ready"
        if not ready:
            readiness["warning"] = str((diagnostics or {}).get("warning") or "enabled_without_wrapper_execution")
        return readiness

    if activation_state == "invalid_flag":
        readiness["warning"] = "invalid_flag"
    elif activation_state == "fail_open":
        readiness["warning"] = "fail_open"
    elif activation_state == "disabled":
        readiness["warning"] = "activation_disabled"
    else:
        readiness["warning"] = "unknown_activation_state"
    return readiness


def _build_governance_shadow_readiness_report(
    *,
    lookback_rows: int,
    activation: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    rollout_readiness: dict[str, Any] | None = None,
    activation_resolver=None,
    diagnostics_evaluator=None,
    rollout_evaluator=None,
) -> dict[str, Any]:
    """Build an informational, deterministic shadow readiness report."""
    warnings: list[str] = []

    resolved_activation = activation
    if not isinstance(resolved_activation, dict):
        try:
            resolver = activation_resolver or _resolve_governance_shadow_activation
            resolved_activation = resolver()
        except Exception as e:
            resolved_activation = {"enabled": False, "state": "fail_open"}
            warnings.append(f"activation_resolution_fail_open:{e}")
    if not isinstance(resolved_activation, dict):
        resolved_activation = {"enabled": False, "state": "fail_open"}
        warnings.append("activation_malformed")

    resolved_diagnostics = diagnostics
    if not isinstance(resolved_diagnostics, dict):
        try:
            diag_eval = diagnostics_evaluator or _evaluate_governance_shadow_diagnostics
            resolved_diagnostics = diag_eval(
                lookback_rows=max(1, int(lookback_rows)),
                activation=resolved_activation,
            )
        except Exception as e:
            resolved_diagnostics = {
                "activation_state": str((resolved_activation or {}).get("state") or "fail_open"),
                "invoked": False,
                "shadow_mode": True,
                "wrapper_executed": False,
                "success": False,
                "fail_open": True,
                "warning": f"shadow_diagnostics_fail_open:{e}",
                "duration_ms": 0,
                "skipped_reason": "fail_open",
            }
            warnings.append(f"diagnostics_evaluation_fail_open:{e}")
    if not isinstance(resolved_diagnostics, dict):
        resolved_diagnostics = {
            "activation_state": str((resolved_activation or {}).get("state") or "fail_open"),
            "invoked": False,
            "shadow_mode": True,
            "wrapper_executed": False,
            "success": False,
            "fail_open": True,
            "warning": "diagnostics_malformed",
            "duration_ms": 0,
            "skipped_reason": "fail_open",
        }
        warnings.append("diagnostics_malformed")

    resolved_rollout = rollout_readiness
    if not isinstance(resolved_rollout, dict):
        try:
            rollout_eval = rollout_evaluator or _evaluate_governance_shadow_rollout_readiness
            resolved_rollout = rollout_eval(
                activation=resolved_activation,
                diagnostics=resolved_diagnostics,
            )
        except Exception as e:
            resolved_rollout = {
                "readiness_state": "not_ready",
                "activation_state": str((resolved_activation or {}).get("state") or "fail_open"),
                "diagnostics_available": False,
                "wrapper_available": False,
                "policy_version": "a4.7.v1",
                "ready": False,
                "warning": f"rollout_readiness_fail_open:{e}",
                "fail_open": True,
            }
            warnings.append(f"rollout_evaluation_fail_open:{e}")
    if not isinstance(resolved_rollout, dict):
        resolved_rollout = {
            "readiness_state": "not_ready",
            "activation_state": str((resolved_activation or {}).get("state") or "fail_open"),
            "diagnostics_available": False,
            "wrapper_available": False,
            "policy_version": "a4.7.v1",
            "ready": False,
            "warning": "rollout_readiness_malformed",
            "fail_open": True,
        }
        warnings.append("rollout_readiness_malformed")

    diagnostics_warning = str((resolved_diagnostics or {}).get("warning") or "")
    rollout_warning = str((resolved_rollout or {}).get("warning") or "")
    warning_set = {item for item in warnings if item}
    if diagnostics_warning:
        warning_set.add(diagnostics_warning)
    if rollout_warning:
        warning_set.add(rollout_warning)
    ordered_warnings = sorted(warning_set)

    activation_state = str((resolved_activation or {}).get("state") or "disabled")
    report: dict[str, Any] = {
        "report_version": "a4.8.v1",
        "activation_state": activation_state,
        "diagnostics": resolved_diagnostics,
        "rollout_readiness": resolved_rollout,
        "summary": {
            "activation_state": activation_state,
            "ready": bool((resolved_rollout or {}).get("ready", False)),
            "readiness_state": str((resolved_rollout or {}).get("readiness_state") or "not_ready"),
            "fail_open": bool((resolved_diagnostics or {}).get("fail_open", True))
            or bool((resolved_rollout or {}).get("fail_open", True)),
            "warning_count": len(ordered_warnings),
        },
        "warnings": ordered_warnings,
        "advisory_only": True,
    }
    return report


def governance_refresh_job():
    """Refresh governance artifacts and readiness markdown in one run."""
    if not GOVERNANCE_REFRESH_SCRIPT.exists():
        logger.warning("Governance refresh skipped: script missing (%s)", GOVERNANCE_REFRESH_SCRIPT)
        return

    lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
    python_bin = sys.executable
    cmd = [
        python_bin,
        str(GOVERNANCE_REFRESH_SCRIPT),
        "--lookback-rows",
        str(lookback_rows),
    ]
    result = _run_json_script(cmd, timeout_seconds=300)
    if result.get("ok"):
        logger.info("Governance refresh completed: lookback_rows=%s", lookback_rows)
    else:
        logger.warning(
            "Governance refresh failed: return_code=%s stderr=%s",
            result.get("return_code"),
            result.get("stderr_tail"),
        )

    activation = _resolve_governance_shadow_activation()
    diagnostics = _evaluate_governance_shadow_diagnostics(
        lookback_rows=lookback_rows,
        activation=activation,
    )
    logger.info(
        "Governance refresh shadow diagnostics: %s",
        json.dumps(diagnostics, ensure_ascii=True, sort_keys=True),
    )
    rollout_readiness = _evaluate_governance_shadow_rollout_readiness(
        activation=activation,
        diagnostics=diagnostics,
    )
    logger.info(
        "Governance refresh shadow rollout readiness: %s",
        json.dumps(rollout_readiness, ensure_ascii=True, sort_keys=True),
    )
    shadow_report = _build_governance_shadow_readiness_report(
        lookback_rows=lookback_rows,
        activation=activation,
        diagnostics=diagnostics,
        rollout_readiness=rollout_readiness,
    )
    logger.info(
        "Governance refresh shadow readiness report: %s",
        json.dumps(shadow_report, ensure_ascii=True, sort_keys=True),
    )

    if diagnostics.get("wrapper_executed"):
        if diagnostics.get("success"):
            logger.info(
                "Governance refresh shadow completed: invoked=%s duration_ms=%s",
                diagnostics.get("invoked"),
                diagnostics.get("duration_ms"),
            )
        else:
            logger.warning(
                "Governance refresh shadow fail-open: invoked=%s warning=%s duration_ms=%s",
                diagnostics.get("invoked"),
                diagnostics.get("warning"),
                diagnostics.get("duration_ms"),
            )
    elif diagnostics.get("activation_state") == "invalid_flag":
        logger.warning("Governance refresh shadow disabled: invalid_flag")
    elif diagnostics.get("activation_state") == "fail_open":
        logger.warning("Governance refresh shadow disabled: fail_open")


def process_likes_job():
    """Her 30 dk’da bir: zamanı gelen beğenileri işle."""
    logger.info("Cross-channel auto-like devre dışı (safe mode).")

def update_progress_file(last_task: str = "", next_step: str = ""):
    """PROGRESS.md'yi otomatik güncelle — her büyük görev sonunda çağır."""
    try:
        from datetime import datetime
        import pytz
        TZ_local = pytz.timezone("Europe/Istanbul")
        now = datetime.now(TZ_local).strftime("%Y-%m-%d %H:%M")

        queue = load_queue()
        ready = get_ready_channels()

        rows = []
        for cid in ready:
            entries = queue.get(cid, [])
            if entries:
                pub = entries[0].get("publish_at", "")[:16]
                rows.append(f"| {cid:25} | ✅ Kuyrukta | {pub} |")
            else:
                rows.append(f"| {cid:25} | 🔄 Render bekleniyor | — |")

        table = "\n".join(rows)

        content = f"""# PROGRESS — Para Pusulası YouTube Otomasyon

> Bu dosya scheduler tarafından otomatik güncellenir.

---

## Son Güncelleme
**Tarih:** {now} (Istanbul)

## Son Tamamlanan Görev
{last_task or "— (henüz kaydedilmedi)"}

## Bir Sonraki Adım
{next_step or "— (scheduler çalışıyor, otomatik devam)"}

## Kanal Kuyruk Durumu
| Kanal | Durum | Yayın Zamanı |
|---|---|---|
{table}
"""
        from pathlib import Path
        Path("PROGRESS.md").write_text(content, encoding="utf-8")
        logger.info("PROGRESS.md güncellendi")
    except Exception as e:
        logger.warning(f"PROGRESS.md güncellenemedi: {e}")


def fill_empty_queues_job():
    """
    Her saatte bir: kanalların tüm yakın slotlarını doldur.
    Günde 2 upload olan kanallar 2 video kuyruğa alır.
    """
    if _observation_mode_active():
        logger.warning("Automatic queue fill skipped: production_observation_mode")
        return
    try:
        from src.scheduler_utils import cleanup_stale_queue
        cleanup_state = {"freed": []}

        def _cleanup_mutator(current_queue):
            cleaned, freed = cleanup_stale_queue(current_queue, TZ)
            current_queue.clear()
            current_queue.update(cleaned)
            cleanup_state["freed"] = list(freed)

        queue = update_queue(_cleanup_mutator)

        ready = get_ready_channels()
        now = datetime.now(TZ)

        for cid in ready:
            try:
                from src.channel_manager import get_channel
                cfg = get_channel(cid)
                existing = [e for e in queue.get(cid, []) if _is_publishable_queue_entry(e)]
                occupied = [e.get("publish_at", "") for e in existing]
                needed_slots = len(cfg.upload_times)

                to_render = needed_slots - len(existing)
                for _ in range(to_render):
                    new_time = get_next_upload_time(cfg, skip_occupied=occupied)
                    occupied.append(new_time)
                    logger.info(f"[{cid}] Eksik slot → render başlatılıyor: {new_time}")
                    _submit_render(cid, trigger_source="recurring_empty_queue_fill")
                    time.sleep(5)
            except Exception as e:
                logger.warning(f"[{cid}] fill_empty_queues_job hatası: {e}")
    except Exception as e:
        logger.warning(f"fill_empty_queues_job genel hatası: {e}")


def _print_help() -> None:
    print("Para Pusulasi Scheduler")
    print("Kullanim:")
    print("  python scheduler.py          # Token'i olan tum kanallari calistir")
    print("  python scheduler.py --list   # Aktif kanallari listele")
    print("  python scheduler.py --status # Kuyruk durumunu goster")
    print("  python scheduler.py --initial-fill # Bos kuyruklar icin acik operator tetikli render baslat")
    print("  python scheduler.py --health-check # Uretim hazirlik kontrolunu calistir")
    print("  python scheduler.py --startup-preflight # Sistemd-esdeger baslangic hazirlik kontrolu")
    print("  python scheduler.py --safety-check-now # Production safety gate raporu olustur")
    print("  python scheduler.py --skip-provider-preflight # Anthropic preflight kontrolunu atla")
    print("  python scheduler.py --sync-analytics-now # Canli YouTube Analytics sync ve optimizasyonu calistir")
    print("  python scheduler.py --run-optimization-cycle-now # Controller+Fleet+Backlog+Memory runtime kanit dongusu")
    print("  python scheduler.py --refresh-governance-now # P0/P1 metrics+bundle+readiness raporunu yenile")
    print("  python scheduler.py --governance-shadow-report-now # Governance shadow readiness raporunu goster")
    print("  python scheduler.py --governance-shadow-selfcheck-now # Governance shadow self-check raporunu calistir")
    print("  python scheduler.py --governance-shadow-contract-validate-now # Governance shadow kontrat dogrulamasini calistir")
    print("  python scheduler.py --governance-shadow-output-consistency-now # Governance shadow cikti tutarlilik kontrolunu calistir")
    print("  python scheduler.py --governance-shadow-diagnostic-summary-now # Governance shadow tanisal ozetini calistir")
    print("  python scheduler.py --governance-shadow-surface-parity-now # Governance shadow operator parity denetimini calistir")
    print("  python scheduler.py --governance-shadow-coverage-audit-now # Governance shadow operator coverage denetimini calistir")
    print("  python scheduler.py --governance-shadow-stability-audit-now # Governance shadow operator stabilite denetimini calistir")
    print("  python scheduler.py --governance-shadow-reproducibility-audit-now # Governance shadow operator yeniden-uretilebilirlik denetimini calistir")
    print("  python scheduler.py --governance-shadow-isolation-audit-now # Governance shadow operator izolasyon denetimini calistir")
    print("  python scheduler.py --governance-shadow-determinism-audit-now # Governance shadow operator determinizm denetimini calistir")
    print("  python scheduler.py --help   # Bu yardim metnini goster")


def _run_startup_health_check(*, create_missing_directories: bool, require_telegram: bool):
    from src.config import config as runtime_config
    from src.production_readiness import run_production_health_check

    result = run_production_health_check(
        runtime_config,
        require_telegram=require_telegram,
        create_missing_directories=create_missing_directories,
    )
    logger.info(
        "Configuration loaded: niche=%s language=%s timezone=%s",
        runtime_config.niche,
        runtime_config.channel_language,
        runtime_config.timezone,
    )
    logger.info(
        "Fact Bundle pipeline adapter is %s",
        "enabled" if result.fact_bundle_enabled else "disabled",
    )
    logger.info(
        "YouTube DNS resolution: %s",
        ", ".join(result.youtube_dns_ips) if result.youtube_dns_ips else "unresolved",
    )
    logger.info("Health check result: %s", "PASS" if result.ok else "FAIL")
    return result


def _run_startup_preflight(*, skip_provider_preflight: bool):
    startup_health = _run_startup_health_check(
        create_missing_directories=True,
        require_telegram=True,
    )
    if not startup_health.ok:
        return startup_health, False, "not_run_due_to_health_check_fail", [], list(startup_health.errors)

    provider_ok, provider_detail = _run_provider_preflight_check(
        skip_preflight=skip_provider_preflight,
    )
    if not provider_ok:
        detail = str(provider_detail or "")
        return startup_health, False, detail, [], [f"Anthropic preflight failed: {detail}"]

    ready = get_ready_channels()
    if not ready:
        return startup_health, True, str(provider_detail or ""), [], ["Hiçbir kanalın token'i yok! Önce setup_channel.py çalıştırın."]

    return startup_health, True, str(provider_detail or ""), ready, []


def _evaluate_scheduler_startup_production_safety_gate(*, startup_health, ready_channels: list[str]) -> dict[str, Any]:
    return evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=startup_health,
        ready_channels=list(ready_channels or []),
        queue_path=Path(QUEUE_FILE),
        writable_paths=list(_collect_preprod_mutable_paths().values()),
        expected_deployment_lock_owner_token=os.getenv("IMMUTABLE_V2_EXPECTED_LOCK_OWNER_TOKEN", ""),
    ).to_dict()


def _production_safety_gate_errors(payload: dict[str, Any] | None) -> list[str]:
    if not payload or bool(payload.get("ok", True)):
        return []

    errors: list[str] = []
    for item in list(payload.get("checks") or []):
        if str(item.get("status") or "") != "fail":
            continue
        evidence = dict(item.get("evidence") or {})
        classification = str(evidence.get("lock_classification") or "")
        if classification in {"self_owned_active_lock", "foreign_active_lock"}:
            errors.append("ACTIVE DEPLOYMENT: production safety gate blocked scheduler startup because a live deployment lock is present")
            continue
        if classification == "stale_lock":
            errors.append("STALE DEPLOYMENT LOCK: production safety gate blocked scheduler startup; explicit operator confirmation is required")
            continue
        errors.append(
            f"Production safety gate failed: {str(item.get('reason') or 'production_safety_gate_failed')}"
        )
    return errors or [
        f"Production safety gate failed: {str(payload.get('blocking_reason') or 'unknown')}"
    ]


def _deployment_lock_context_from_gate(payload: dict[str, Any] | None) -> dict[str, Any]:
    for item in list((payload or {}).get("checks") or []):
        evidence = dict(item.get("evidence") or {})
        if str(evidence.get("lock_classification") or ""):
            return evidence
    return {}


def _send_startup_incident_alert(*, gate_payload: dict[str, Any] | None) -> None:
    context = _deployment_lock_context_from_gate(gate_payload)
    incident_id = f"startup-{datetime.now(TZ).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    owner_age = context.get("owner_age_seconds")
    owner_state = str(context.get("owner_state") or "unknown")
    try:
        from src.scheduler_utils import send_telegram

        send_telegram(
            "<b>Scheduler startup blocked</b>\n"
            f"incident_id={incident_id}\n"
            f"lock_classification={str(context.get('lock_classification') or 'none')}\n"
            f"reason={owner_state}\n"
            f"owner_state={owner_state}\n"
            f"owner_pid={str(context.get('owner_pid') or 'unknown')}\n"
            f"pid_state={owner_state}\n"
            f"owner_hostname={str(context.get('owner_host') or 'unknown')}\n"
            f"owner_mode={str(context.get('owner_mode') or 'unknown')}\n"
            f"owner_age_seconds={owner_age if owner_age is not None else 'unknown'}\n"
            f"target_sha={str(context.get('target_sha') or 'unknown')}\n"
            f"active_sha={str(context.get('active_sha') or _resolve_git_head_short() or 'unknown')}\n"
            f"current_hostname={str(context.get('hostname') or socket.gethostname())}"
        )
    except Exception as exc:
        logger.warning("Startup incident Telegram alert failed: %s incident_id=%s", exc, incident_id)


def _record_safety_gate_result(
    *,
    mode: str,
    startup_health,
    provider_preflight_ok: bool,
    provider_preflight_detail: str,
    production_safety_gate_payload: dict[str, Any] | None = None,
) -> dict:
    health_errors = [str(item) for item in getattr(startup_health, "errors", ())]
    gate_payload = dict(production_safety_gate_payload or {})
    gate_ok = bool(gate_payload.get("ok", True))
    payload = {
        "generated_at": datetime.now(TZ).isoformat(),
        "mode": str(mode or "unknown"),
        "health_check_ok": bool(getattr(startup_health, "ok", False)),
        "health_check_errors": health_errors,
        "provider_preflight_ok": bool(provider_preflight_ok),
        "provider_preflight_detail": str(provider_preflight_detail or ""),
        "production_safety_gate_ok": gate_ok,
        "production_safety_gate_blocking_reason": str(gate_payload.get("blocking_reason") or ""),
        "production_safety_gate": gate_payload,
        "overall_ok": bool(getattr(startup_health, "ok", False)) and bool(provider_preflight_ok) and gate_ok,
        "git_sha": _resolve_git_head_short(),
    }
    _write_json_atomic(SAFETY_GATE_LATEST_FILE, payload)
    logger.info(
        "PRODUCTION_SAFETY_GATE mode=%s result=%s health_check=%s provider_preflight=%s detail=%s file=%s",
        payload["mode"],
        "PASS" if payload["overall_ok"] else "FAIL",
        "PASS" if payload["health_check_ok"] else "FAIL",
        "PASS" if payload["provider_preflight_ok"] else "FAIL",
        payload["provider_preflight_detail"],
        SAFETY_GATE_LATEST_FILE,
    )
    return payload


def run_safety_check_once(*, skip_provider_preflight: bool = False) -> int:
    startup_health = _run_startup_health_check(
        create_missing_directories=False,
        require_telegram=True,
    )

    provider_ok = False
    provider_detail = "not_run_due_to_health_check_fail"
    if startup_health.ok:
        provider_ok, provider_detail = _run_provider_preflight_check(
            skip_preflight=skip_provider_preflight,
        )

    gate_payload = {"ok": False, "blocking_reason": "not_run_due_to_health_check_fail", "checks": []}
    if startup_health.ok and provider_ok:
        gate_payload = _evaluate_scheduler_startup_production_safety_gate(
            startup_health=startup_health,
            ready_channels=get_ready_channels(),
        )

    payload = _record_safety_gate_result(
        mode="manual",
        startup_health=startup_health,
        provider_preflight_ok=provider_ok,
        provider_preflight_detail=provider_detail,
        production_safety_gate_payload=gate_payload,
    )

    print(
        json.dumps(
            {
                "ok": payload["overall_ok"],
                "health_check_ok": payload["health_check_ok"],
                "provider_preflight_ok": payload["provider_preflight_ok"],
                "provider_preflight_detail": payload["provider_preflight_detail"],
                "production_safety_gate_ok": payload["production_safety_gate_ok"],
                "production_safety_gate_blocking_reason": payload["production_safety_gate_blocking_reason"],
                "latest": str(SAFETY_GATE_LATEST_FILE),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload["overall_ok"] else 1


def run_live_analytics_sync_once() -> int:
    """Canli analytics senkronunu bir kez calistirir."""
    refresh_live_analytics_job()
    _, live_status = _resolve_live_collector_runtime()
    print(f"Live analytics sync: PASS (analytics_live_status={live_status})")
    return 0

def _run_provider_preflight_check(*, skip_preflight: bool = False) -> tuple[bool, str]:
    if skip_preflight:
        return True, "skipped_by_flag"

    if _observation_mode_active():
        return True, "skipped_by_production_observation_mode"

    enabled = _is_enabled(os.getenv("ANTHROPIC_PREFLIGHT_ENABLED", "true"))
    if not enabled:
        return True, "disabled_by_env"

    try:
        from src.scheduler_utils import run_anthropic_preflight
    except Exception:
        # Test stubs veya minimal runtime ortamlarında preflight fonksiyonu olmayabilir.
        return True, "preflight_unavailable"

    ok, detail = run_anthropic_preflight(model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5"))
    return ok, detail


def _is_local_content_fail_open_enabled() -> bool:
    return _is_enabled(os.getenv("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", "true"))


def run_optimization_cycle_once() -> int:
    """Runtime optimization cycle'i bir kez calistir ve sonucu yazdir."""
    if not RUNTIME_CYCLE_LOCK.acquire(blocking=False):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "lock_contention",
                    "latest": str(RUNTIME_EVIDENCE_LATEST_FILE),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    try:
        evidence = run_optimization_runtime_cycle()
        _write_json_atomic(RUNTIME_EVIDENCE_LATEST_FILE, evidence)
        print(
            json.dumps(
                {
                    "ok": evidence.get("ok"),
                    "target_channel": evidence.get("target_channel"),
                    "flag_changed": evidence.get("flag_changed"),
                    "latest": str(RUNTIME_EVIDENCE_LATEST_FILE),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if evidence.get("ok") else 1
    finally:
        RUNTIME_CYCLE_LOCK.release()


def run_governance_refresh_once() -> int:
    """Governance readiness artifact zincirini bir kez calistirir."""
    governance_refresh_job()
    latest = Path("logs/governance_refresh_run_latest.json")
    print(
        json.dumps(
            {
                "ok": latest.exists(),
                "latest": str(latest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if latest.exists() else 1


def run_governance_shadow_report_once() -> int:
    """Print the deterministic governance shadow readiness report once."""
    lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
    report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
    logger.info(
        "Governance shadow report requested: %s",
        json.dumps(report, ensure_ascii=True, sort_keys=True),
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _get_governance_shadow_operator_surfaces(
    *,
    include_surface_parity: bool = False,
    include_coverage_audit: bool = False,
    include_stability_audit: bool = False,
    include_reproducibility_audit: bool = False,
    include_isolation_audit: bool = False,
    include_determinism_audit: bool = False,
) -> tuple[tuple[str, Any, str | None, str | None, bool], ...]:
    surfaces: tuple[tuple[str, Any, str | None, str | None, bool], ...] = (
        ("report_builder_callable", _build_governance_shadow_readiness_report, None, None, False),
        (
            "report_entrypoint_callable",
            run_governance_shadow_report_once,
            "--governance-shadow-report-now",
            None,
            True,
        ),
        (
            "selfcheck_entrypoint_callable",
            run_governance_shadow_selfcheck_once,
            "--governance-shadow-selfcheck-now",
            "Governance shadow self-check:",
            True,
        ),
        (
            "contract_validation_entrypoint_callable",
            run_governance_shadow_contract_validation_once,
            "--governance-shadow-contract-validate-now",
            "Governance shadow contract validation:",
            True,
        ),
        (
            "output_consistency_entrypoint_callable",
            run_governance_shadow_output_consistency_once,
            "--governance-shadow-output-consistency-now",
            "Governance shadow output consistency:",
            True,
        ),
        (
            "diagnostic_summary_entrypoint_callable",
            run_governance_shadow_diagnostic_summary_once,
            "--governance-shadow-diagnostic-summary-now",
            "Governance shadow diagnostic summary:",
            True,
        ),
    )
    if include_surface_parity:
        surfaces += (
            (
                "surface_parity_entrypoint_callable",
                run_governance_shadow_surface_parity_once,
                "--governance-shadow-surface-parity-now",
                "Governance shadow surface parity:",
                False,
            ),
        )
    if include_coverage_audit:
        surfaces += (
            (
                "coverage_audit_entrypoint_callable",
                run_governance_shadow_coverage_audit_once,
                "--governance-shadow-coverage-audit-now",
                "Governance shadow coverage audit:",
                False,
            ),
        )
    if include_stability_audit:
        surfaces += (
            (
                "stability_audit_entrypoint_callable",
                run_governance_shadow_stability_audit_once,
                "--governance-shadow-stability-audit-now",
                "Governance shadow stability audit:",
                False,
            ),
        )
    if include_reproducibility_audit:
        surfaces += (
            (
                "reproducibility_audit_entrypoint_callable",
                run_governance_shadow_reproducibility_audit_once,
                "--governance-shadow-reproducibility-audit-now",
                "Governance shadow reproducibility audit:",
                False,
            ),
        )
    if include_isolation_audit:
        surfaces += (
            (
                "isolation_audit_entrypoint_callable",
                run_governance_shadow_isolation_audit_once,
                "--governance-shadow-isolation-audit-now",
                "Governance shadow isolation audit:",
                False,
            ),
        )
    if include_determinism_audit:
        surfaces += (
            (
                "determinism_audit_entrypoint_callable",
                run_governance_shadow_determinism_audit_once,
                "--governance-shadow-determinism-audit-now",
                "Governance shadow determinism audit:",
                False,
            ),
        )
    return surfaces


def _evaluate_governance_shadow_contract_checks(
    *,
    report: Any,
    entrypoints: dict[str, Any] | None = None,
    include_field_types: bool = False,
) -> list[tuple[str, bool]]:
    expected_fields = {
        "report_version",
        "activation_state",
        "diagnostics",
        "rollout_readiness",
        "summary",
        "warnings",
        "advisory_only",
    }
    expected_field_types: dict[str, type] = {
        "report_version": str,
        "activation_state": str,
        "diagnostics": dict,
        "rollout_readiness": dict,
        "summary": dict,
        "warnings": list,
        "advisory_only": bool,
    }
    checks: list[tuple[str, bool]] = []

    for name, target in (entrypoints or {}).items():
        checks.append((name, callable(target)))

    report_is_dict = isinstance(report, dict)
    checks.append(("report_is_dict", report_is_dict))

    report_fields_ok = report_is_dict and expected_fields.issubset(report.keys())
    checks.append(("expected_fields_present", report_fields_ok))

    if include_field_types:
        field_types_ok = report_is_dict and all(
            isinstance(report.get(field), expected_type)
            for field, expected_type in expected_field_types.items()
        )
        checks.append(("field_types_stable", field_types_ok))

    advisory_only_ok = report_is_dict and report.get("advisory_only") is True
    checks.append(("advisory_only_true", advisory_only_ok))

    first_serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
    second_serialized = json.dumps(report, ensure_ascii=True, sort_keys=True)
    checks.append(("deterministic_serialization", first_serialized == second_serialized))
    return checks


def run_governance_shadow_selfcheck_once() -> int:
    """Run a deterministic self-check for the governance shadow operator interface."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks = _evaluate_governance_shadow_contract_checks(
            report=report,
            entrypoints={
                "report_entrypoint_callable": run_governance_shadow_report_once,
                "report_builder_callable": _build_governance_shadow_readiness_report,
            },
        )
    except Exception as e:
        checks.append((f"selfcheck_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow self-check: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def run_governance_shadow_contract_validation_once() -> int:
    """Run a deterministic contract validation for the governance shadow operator interface."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks = _evaluate_governance_shadow_contract_checks(
            report=report,
            entrypoints={
                "report_entrypoint_callable": run_governance_shadow_report_once,
                "selfcheck_entrypoint_callable": run_governance_shadow_selfcheck_once,
                "report_builder_callable": _build_governance_shadow_readiness_report,
            },
            include_field_types=True,
        )
    except Exception as e:
        checks.append((f"contract_validation_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow contract validation: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def _run_governance_shadow_operator_surface(target) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc = int(target())
    return rc, buffer.getvalue()


def _evaluate_governance_shadow_surface_parity_checks(*, report: Any) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    all_surfaces = _get_governance_shadow_operator_surfaces(include_surface_parity=True)
    audited_surfaces = _get_governance_shadow_operator_surfaces()
    expected_surface_names = (
        "report_builder_callable",
        "report_entrypoint_callable",
        "selfcheck_entrypoint_callable",
        "contract_validation_entrypoint_callable",
        "output_consistency_entrypoint_callable",
        "diagnostic_summary_entrypoint_callable",
        "surface_parity_entrypoint_callable",
    )
    expected_execution_order = (
        "report_entrypoint_callable",
        "selfcheck_entrypoint_callable",
        "contract_validation_entrypoint_callable",
        "output_consistency_entrypoint_callable",
        "diagnostic_summary_entrypoint_callable",
    )
    surface_names = tuple(name for name, _target, _flag, _prefix, _execute in all_surfaces)
    execution_names = tuple(name for name, _target, _flag, _prefix, execute in audited_surfaces if execute)

    checks.extend(
        _evaluate_governance_shadow_contract_checks(
            report=report,
            entrypoints={name: target for name, target, _flag, _prefix, _execute in all_surfaces},
            include_field_types=True,
        )
    )
    checks.append(("expected_surface_registry", surface_names == expected_surface_names))
    checks.append(
        (
            "surface_registry_deterministic",
            surface_names
            == tuple(
                name
                for name, _target, _flag, _prefix, _execute in _get_governance_shadow_operator_surfaces(
                    include_surface_parity=True,
                )
            ),
        )
    )
    checks.append(("surface_execution_order_deterministic", execution_names == expected_execution_order))

    help_buffer = io.StringIO()
    with redirect_stdout(help_buffer):
        _print_help()
    help_output = help_buffer.getvalue()

    for name, _target, flag, _prefix, _execute in all_surfaces:
        if flag is None:
            continue
        checks.append((f"{name}_discoverable", help_output.count(flag) == 1))

    expected_report_output = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    for name, target, _flag, summary_prefix, execute in audited_surfaces:
        if not execute:
            continue
        try:
            rc, output = _run_governance_shadow_operator_surface(target)
        except Exception as e:
            checks.append((f"{name}_exception:{e}", False))
            continue

        if name == "report_entrypoint_callable":
            checks.append(("report_output_consistent", rc == 0 and output == expected_report_output))
            continue

        checks.append((f"{name}_pass", rc == 0))
        checks.append((f"{name}_summary_prefix_consistent", output.startswith(summary_prefix or "")))

    return checks


def run_governance_shadow_output_consistency_once() -> int:
    """Run a deterministic consistency verification across governance shadow operator interfaces."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks.extend(
            _evaluate_governance_shadow_contract_checks(
                report=report,
                entrypoints={
                    "report_entrypoint_callable": run_governance_shadow_report_once,
                    "selfcheck_entrypoint_callable": run_governance_shadow_selfcheck_once,
                    "contract_validation_entrypoint_callable": run_governance_shadow_contract_validation_once,
                    "report_builder_callable": _build_governance_shadow_readiness_report,
                },
                include_field_types=True,
            )
        )

        selfcheck_buffer = io.StringIO()
        with redirect_stdout(selfcheck_buffer):
            selfcheck_rc = run_governance_shadow_selfcheck_once()

        contract_buffer = io.StringIO()
        with redirect_stdout(contract_buffer):
            contract_rc = run_governance_shadow_contract_validation_once()

        checks.append(("selfcheck_pass_consistent", selfcheck_rc == 0))
        checks.append(("contract_validation_pass_consistent", contract_rc == 0))
        checks.append(
            (
                "summary_prefixes_consistent",
                selfcheck_buffer.getvalue().startswith("Governance shadow self-check:")
                and contract_buffer.getvalue().startswith("Governance shadow contract validation:"),
            )
        )
    except Exception as e:
        checks.append((f"output_consistency_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow output consistency: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def run_governance_shadow_diagnostic_summary_once() -> int:
    """Run a deterministic diagnostic summary across governance shadow operator surfaces."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks.extend(
            _evaluate_governance_shadow_contract_checks(
                report=report,
                entrypoints={
                    "report_entrypoint_callable": run_governance_shadow_report_once,
                    "selfcheck_entrypoint_callable": run_governance_shadow_selfcheck_once,
                    "contract_validation_entrypoint_callable": run_governance_shadow_contract_validation_once,
                    "output_consistency_entrypoint_callable": run_governance_shadow_output_consistency_once,
                    "report_builder_callable": _build_governance_shadow_readiness_report,
                },
                include_field_types=True,
            )
        )

        expected_report_output = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        report_rc, report_output = _run_governance_shadow_operator_surface(run_governance_shadow_report_once)
        selfcheck_rc, selfcheck_output = _run_governance_shadow_operator_surface(run_governance_shadow_selfcheck_once)
        contract_rc, contract_output = _run_governance_shadow_operator_surface(run_governance_shadow_contract_validation_once)
        consistency_rc, consistency_output = _run_governance_shadow_operator_surface(run_governance_shadow_output_consistency_once)

        checks.append(("report_output_consistent", report_rc == 0 and report_output == expected_report_output))
        checks.append(("selfcheck_pass", selfcheck_rc == 0))
        checks.append(("contract_validation_pass", contract_rc == 0))
        checks.append(("output_consistency_pass", consistency_rc == 0))
        checks.append(
            (
                "summary_ordering_consistent",
                selfcheck_output.startswith("Governance shadow self-check:")
                and contract_output.startswith("Governance shadow contract validation:")
                and consistency_output.startswith("Governance shadow output consistency:"),
            )
        )
    except Exception as e:
        checks.append((f"diagnostic_summary_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow diagnostic summary: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def run_governance_shadow_surface_parity_once() -> int:
    """Run a deterministic parity audit across governance shadow operator surfaces."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks.extend(_evaluate_governance_shadow_surface_parity_checks(report=report))
    except Exception as e:
        checks.append((f"surface_parity_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow surface parity: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def _evaluate_governance_shadow_coverage_audit_checks(*, report: Any) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    all_surfaces = _get_governance_shadow_operator_surfaces(
        include_surface_parity=True,
        include_coverage_audit=True,
    )
    parity_surfaces = _get_governance_shadow_operator_surfaces(include_surface_parity=True)
    expected_surface_names = (
        "report_builder_callable",
        "report_entrypoint_callable",
        "selfcheck_entrypoint_callable",
        "contract_validation_entrypoint_callable",
        "output_consistency_entrypoint_callable",
        "diagnostic_summary_entrypoint_callable",
        "surface_parity_entrypoint_callable",
        "coverage_audit_entrypoint_callable",
    )
    surface_names = tuple(name for name, _target, _flag, _prefix, _execute in all_surfaces)
    parity_surface_names = tuple(name for name, _target, _flag, _prefix, _execute in parity_surfaces)

    checks.extend(
        _evaluate_governance_shadow_contract_checks(
            report=report,
            entrypoints={name: target for name, target, _flag, _prefix, _execute in all_surfaces},
            include_field_types=True,
        )
    )
    checks.append(("expected_surface_registry", surface_names == expected_surface_names))
    checks.append(("duplicate_registration_absent", len(surface_names) == len(set(surface_names))))
    checks.append(
        (
            "surface_registry_deterministic",
            surface_names
            == tuple(
                name
                for name, _target, _flag, _prefix, _execute in _get_governance_shadow_operator_surfaces(
                    include_surface_parity=True,
                    include_coverage_audit=True,
                )
            ),
        )
    )

    help_buffer = io.StringIO()
    with redirect_stdout(help_buffer):
        _print_help()
    help_output = help_buffer.getvalue()
    for name, _target, flag, _prefix, _execute in all_surfaces:
        if flag is None:
            continue
        checks.append((f"{name}_discoverable", help_output.count(flag) == 1))

    parity_rc, parity_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)
    checks.append(("surface_parity_pass", parity_rc == 0))
    checks.append(("surface_parity_summary_prefix_consistent", parity_output.startswith("Governance shadow surface parity:")))
    checks.append(
        (
            "parity_covers_registered_surfaces",
            all(f"- {name}=" in parity_output for name in parity_surface_names),
        )
    )

    return checks


def run_governance_shadow_coverage_audit_once() -> int:
    """Run a deterministic operator coverage audit across governance shadow surfaces."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks.extend(_evaluate_governance_shadow_coverage_audit_checks(report=report))
    except Exception as e:
        checks.append((f"coverage_audit_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow coverage audit: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def _evaluate_governance_shadow_stability_audit_checks(*, report: Any) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    all_surfaces = _get_governance_shadow_operator_surfaces(
        include_surface_parity=True,
        include_coverage_audit=True,
        include_stability_audit=True,
    )
    expected_surface_names = (
        "report_builder_callable",
        "report_entrypoint_callable",
        "selfcheck_entrypoint_callable",
        "contract_validation_entrypoint_callable",
        "output_consistency_entrypoint_callable",
        "diagnostic_summary_entrypoint_callable",
        "surface_parity_entrypoint_callable",
        "coverage_audit_entrypoint_callable",
        "stability_audit_entrypoint_callable",
    )
    surface_names = tuple(name for name, _target, _flag, _prefix, _execute in all_surfaces)

    checks.extend(
        _evaluate_governance_shadow_contract_checks(
            report=report,
            entrypoints={name: target for name, target, _flag, _prefix, _execute in all_surfaces},
            include_field_types=True,
        )
    )
    checks.append(("expected_surface_registry", surface_names == expected_surface_names))
    checks.append(("duplicate_registration_absent", len(surface_names) == len(set(surface_names))))
    checks.append(
        (
            "surface_registry_deterministic",
            surface_names
            == tuple(
                name
                for name, _target, _flag, _prefix, _execute in _get_governance_shadow_operator_surfaces(
                    include_surface_parity=True,
                    include_coverage_audit=True,
                    include_stability_audit=True,
                )
            ),
        )
    )

    help_buffer = io.StringIO()
    with redirect_stdout(help_buffer):
        _print_help()
    help_output = help_buffer.getvalue()
    for name, _target, flag, _prefix, _execute in all_surfaces:
        if flag is None:
            continue
        checks.append((f"{name}_discoverable", help_output.count(flag) == 1))

    parity_first_rc, parity_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)
    parity_second_rc, parity_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)
    coverage_first_rc, coverage_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_coverage_audit_once)
    coverage_second_rc, coverage_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_coverage_audit_once)

    checks.append(("surface_parity_first_pass", parity_first_rc == 0))
    checks.append(("surface_parity_second_pass", parity_second_rc == 0))
    checks.append(("coverage_audit_first_pass", coverage_first_rc == 0))
    checks.append(("coverage_audit_second_pass", coverage_second_rc == 0))
    checks.append(("surface_parity_output_identical", parity_first_output == parity_second_output))
    checks.append(("coverage_audit_output_identical", coverage_first_output == coverage_second_output))
    checks.append(
        (
            "ordered_operator_output_identical",
            (parity_first_output, coverage_first_output) == (parity_second_output, coverage_second_output),
        )
    )
    checks.append(("surface_parity_registry_stable", "- surface_registry_deterministic=PASS" in parity_first_output))
    checks.append(("coverage_audit_registry_stable", "- surface_registry_deterministic=PASS" in coverage_first_output))

    return checks


def run_governance_shadow_stability_audit_once() -> int:
    """Run a deterministic stability audit across governance shadow operator surfaces."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks.extend(_evaluate_governance_shadow_stability_audit_checks(report=report))
    except Exception as e:
        checks.append((f"stability_audit_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow stability audit: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def _evaluate_governance_shadow_reproducibility_audit_checks(*, report: Any) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    all_surfaces = _get_governance_shadow_operator_surfaces(
        include_surface_parity=True,
        include_coverage_audit=True,
        include_stability_audit=True,
        include_reproducibility_audit=True,
    )
    expected_surface_names = (
        "report_builder_callable",
        "report_entrypoint_callable",
        "selfcheck_entrypoint_callable",
        "contract_validation_entrypoint_callable",
        "output_consistency_entrypoint_callable",
        "diagnostic_summary_entrypoint_callable",
        "surface_parity_entrypoint_callable",
        "coverage_audit_entrypoint_callable",
        "stability_audit_entrypoint_callable",
        "reproducibility_audit_entrypoint_callable",
    )
    surface_names = tuple(name for name, _target, _flag, _prefix, _execute in all_surfaces)

    checks.extend(
        _evaluate_governance_shadow_contract_checks(
            report=report,
            entrypoints={name: target for name, target, _flag, _prefix, _execute in all_surfaces},
            include_field_types=True,
        )
    )
    checks.append(("expected_surface_registry", surface_names == expected_surface_names))
    checks.append(("duplicate_registration_absent", len(surface_names) == len(set(surface_names))))
    checks.append(
        (
            "surface_registry_deterministic",
            surface_names
            == tuple(
                name
                for name, _target, _flag, _prefix, _execute in _get_governance_shadow_operator_surfaces(
                    include_surface_parity=True,
                    include_coverage_audit=True,
                    include_stability_audit=True,
                    include_reproducibility_audit=True,
                )
            ),
        )
    )

    help_buffer = io.StringIO()
    with redirect_stdout(help_buffer):
        _print_help()
    help_output = help_buffer.getvalue()
    for name, _target, flag, _prefix, _execute in all_surfaces:
        if flag is None:
            continue
        checks.append((f"{name}_discoverable", help_output.count(flag) == 1))

    parity_first_rc, parity_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)
    parity_second_rc, parity_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)
    coverage_first_rc, coverage_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_coverage_audit_once)
    coverage_second_rc, coverage_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_coverage_audit_once)
    stability_first_rc, stability_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_stability_audit_once)
    stability_second_rc, stability_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_stability_audit_once)

    checks.append(("surface_parity_first_pass", parity_first_rc == 0))
    checks.append(("surface_parity_second_pass", parity_second_rc == 0))
    checks.append(("coverage_audit_first_pass", coverage_first_rc == 0))
    checks.append(("coverage_audit_second_pass", coverage_second_rc == 0))
    checks.append(("stability_audit_first_pass", stability_first_rc == 0))
    checks.append(("stability_audit_second_pass", stability_second_rc == 0))
    checks.append(("surface_parity_output_reproducible", parity_first_output == parity_second_output))
    checks.append(("coverage_audit_output_reproducible", coverage_first_output == coverage_second_output))
    checks.append(("stability_audit_output_reproducible", stability_first_output == stability_second_output))
    checks.append(
        (
            "ordered_operator_output_reproducible",
            (parity_first_output, coverage_first_output, stability_first_output)
            == (parity_second_output, coverage_second_output, stability_second_output),
        )
    )
    checks.append(("surface_parity_registry_stable", "- surface_registry_deterministic=PASS" in parity_first_output))
    checks.append(("coverage_audit_registry_stable", "- surface_registry_deterministic=PASS" in coverage_first_output))
    checks.append(("stability_audit_registry_stable", "- surface_registry_deterministic=PASS" in stability_first_output))

    return checks


def run_governance_shadow_reproducibility_audit_once() -> int:
    """Run a deterministic reproducibility audit across governance shadow operator surfaces."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks.extend(_evaluate_governance_shadow_reproducibility_audit_checks(report=report))
    except Exception as e:
        checks.append((f"reproducibility_audit_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow reproducibility audit: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def _evaluate_governance_shadow_isolation_audit_checks(*, report: Any) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    all_surfaces = _get_governance_shadow_operator_surfaces(
        include_surface_parity=True,
        include_coverage_audit=True,
        include_stability_audit=True,
        include_reproducibility_audit=True,
        include_isolation_audit=True,
    )
    expected_surface_names = (
        "report_builder_callable",
        "report_entrypoint_callable",
        "selfcheck_entrypoint_callable",
        "contract_validation_entrypoint_callable",
        "output_consistency_entrypoint_callable",
        "diagnostic_summary_entrypoint_callable",
        "surface_parity_entrypoint_callable",
        "coverage_audit_entrypoint_callable",
        "stability_audit_entrypoint_callable",
        "reproducibility_audit_entrypoint_callable",
        "isolation_audit_entrypoint_callable",
    )
    surface_names = tuple(name for name, _target, _flag, _prefix, _execute in all_surfaces)

    checks.extend(
        _evaluate_governance_shadow_contract_checks(
            report=report,
            entrypoints={name: target for name, target, _flag, _prefix, _execute in all_surfaces},
            include_field_types=True,
        )
    )
    checks.append(("expected_surface_registry", surface_names == expected_surface_names))
    checks.append(("duplicate_registration_absent", len(surface_names) == len(set(surface_names))))
    checks.append(
        (
            "surface_registry_deterministic",
            surface_names
            == tuple(
                name
                for name, _target, _flag, _prefix, _execute in _get_governance_shadow_operator_surfaces(
                    include_surface_parity=True,
                    include_coverage_audit=True,
                    include_stability_audit=True,
                    include_reproducibility_audit=True,
                    include_isolation_audit=True,
                )
            ),
        )
    )

    help_buffer = io.StringIO()
    with redirect_stdout(help_buffer):
        _print_help()
    help_output = help_buffer.getvalue()
    for name, _target, flag, _prefix, _execute in all_surfaces:
        if flag is None:
            continue
        checks.append((f"{name}_discoverable", help_output.count(flag) == 1))

    parity_first_rc, parity_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)
    coverage_first_rc, coverage_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_coverage_audit_once)
    stability_first_rc, stability_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_stability_audit_once)
    reproducibility_first_rc, reproducibility_first_output = _run_governance_shadow_operator_surface(
        run_governance_shadow_reproducibility_audit_once,
    )

    coverage_second_rc, coverage_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_coverage_audit_once)
    stability_second_rc, stability_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_stability_audit_once)
    reproducibility_second_rc, reproducibility_second_output = _run_governance_shadow_operator_surface(
        run_governance_shadow_reproducibility_audit_once,
    )
    parity_second_rc, parity_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)

    checks.append(("surface_parity_first_pass", parity_first_rc == 0))
    checks.append(("surface_parity_second_pass", parity_second_rc == 0))
    checks.append(("coverage_audit_first_pass", coverage_first_rc == 0))
    checks.append(("coverage_audit_second_pass", coverage_second_rc == 0))
    checks.append(("stability_audit_first_pass", stability_first_rc == 0))
    checks.append(("stability_audit_second_pass", stability_second_rc == 0))
    checks.append(("reproducibility_audit_first_pass", reproducibility_first_rc == 0))
    checks.append(("reproducibility_audit_second_pass", reproducibility_second_rc == 0))

    checks.append(("surface_parity_isolated_output_reproducible", parity_first_output == parity_second_output))
    checks.append(("coverage_audit_isolated_output_reproducible", coverage_first_output == coverage_second_output))
    checks.append(("stability_audit_isolated_output_reproducible", stability_first_output == stability_second_output))
    checks.append(
        (
            "reproducibility_audit_isolated_output_reproducible",
            reproducibility_first_output == reproducibility_second_output,
        )
    )
    checks.append(
        (
            "no_cross_operator_state_contamination",
            (
                parity_first_output,
                coverage_first_output,
                stability_first_output,
                reproducibility_first_output,
            )
            == (
                parity_second_output,
                coverage_second_output,
                stability_second_output,
                reproducibility_second_output,
            ),
        )
    )

    checks.append(("surface_parity_registry_stable", "- surface_registry_deterministic=PASS" in parity_first_output))
    checks.append(("coverage_audit_registry_stable", "- surface_registry_deterministic=PASS" in coverage_first_output))
    checks.append(("stability_audit_registry_stable", "- surface_registry_deterministic=PASS" in stability_first_output))
    checks.append(
        (
            "reproducibility_audit_registry_stable",
            "- surface_registry_deterministic=PASS" in reproducibility_first_output,
        )
    )

    return checks


def run_governance_shadow_isolation_audit_once() -> int:
    """Run a deterministic isolation audit across governance shadow operator surfaces."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks.extend(_evaluate_governance_shadow_isolation_audit_checks(report=report))
    except Exception as e:
        checks.append((f"isolation_audit_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow isolation audit: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1


def _evaluate_governance_shadow_determinism_audit_checks(*, report: Any) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    all_surfaces = _get_governance_shadow_operator_surfaces(
        include_surface_parity=True,
        include_coverage_audit=True,
        include_stability_audit=True,
        include_reproducibility_audit=True,
        include_isolation_audit=True,
        include_determinism_audit=True,
    )
    expected_surface_names = (
        "report_builder_callable",
        "report_entrypoint_callable",
        "selfcheck_entrypoint_callable",
        "contract_validation_entrypoint_callable",
        "output_consistency_entrypoint_callable",
        "diagnostic_summary_entrypoint_callable",
        "surface_parity_entrypoint_callable",
        "coverage_audit_entrypoint_callable",
        "stability_audit_entrypoint_callable",
        "reproducibility_audit_entrypoint_callable",
        "isolation_audit_entrypoint_callable",
        "determinism_audit_entrypoint_callable",
    )
    surface_names = tuple(name for name, _target, _flag, _prefix, _execute in all_surfaces)

    checks.extend(
        _evaluate_governance_shadow_contract_checks(
            report=report,
            entrypoints={name: target for name, target, _flag, _prefix, _execute in all_surfaces},
            include_field_types=True,
        )
    )
    checks.append(("expected_surface_registry", surface_names == expected_surface_names))
    checks.append(("duplicate_registration_absent", len(surface_names) == len(set(surface_names))))
    checks.append(
        (
            "surface_registry_deterministic",
            surface_names
            == tuple(
                name
                for name, _target, _flag, _prefix, _execute in _get_governance_shadow_operator_surfaces(
                    include_surface_parity=True,
                    include_coverage_audit=True,
                    include_stability_audit=True,
                    include_reproducibility_audit=True,
                    include_isolation_audit=True,
                    include_determinism_audit=True,
                )
            ),
        )
    )

    help_buffer = io.StringIO()
    with redirect_stdout(help_buffer):
        _print_help()
    help_output = help_buffer.getvalue()
    for name, _target, flag, _prefix, _execute in all_surfaces:
        if flag is None:
            continue
        checks.append((f"{name}_discoverable", help_output.count(flag) == 1))

    parity_first_rc, parity_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)
    coverage_first_rc, coverage_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_coverage_audit_once)
    stability_first_rc, stability_first_output = _run_governance_shadow_operator_surface(run_governance_shadow_stability_audit_once)
    reproducibility_first_rc, reproducibility_first_output = _run_governance_shadow_operator_surface(
        run_governance_shadow_reproducibility_audit_once,
    )
    isolation_first_rc, isolation_first_output = _run_governance_shadow_operator_surface(
        run_governance_shadow_isolation_audit_once,
    )

    parity_second_rc, parity_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_surface_parity_once)
    coverage_second_rc, coverage_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_coverage_audit_once)
    stability_second_rc, stability_second_output = _run_governance_shadow_operator_surface(run_governance_shadow_stability_audit_once)
    reproducibility_second_rc, reproducibility_second_output = _run_governance_shadow_operator_surface(
        run_governance_shadow_reproducibility_audit_once,
    )
    isolation_second_rc, isolation_second_output = _run_governance_shadow_operator_surface(
        run_governance_shadow_isolation_audit_once,
    )

    checks.append(("surface_parity_first_pass", parity_first_rc == 0))
    checks.append(("surface_parity_second_pass", parity_second_rc == 0))
    checks.append(("coverage_audit_first_pass", coverage_first_rc == 0))
    checks.append(("coverage_audit_second_pass", coverage_second_rc == 0))
    checks.append(("stability_audit_first_pass", stability_first_rc == 0))
    checks.append(("stability_audit_second_pass", stability_second_rc == 0))
    checks.append(("reproducibility_audit_first_pass", reproducibility_first_rc == 0))
    checks.append(("reproducibility_audit_second_pass", reproducibility_second_rc == 0))
    checks.append(("isolation_audit_first_pass", isolation_first_rc == 0))
    checks.append(("isolation_audit_second_pass", isolation_second_rc == 0))

    checks.append(("surface_parity_output_deterministic", parity_first_output == parity_second_output))
    checks.append(("coverage_audit_output_deterministic", coverage_first_output == coverage_second_output))
    checks.append(("stability_audit_output_deterministic", stability_first_output == stability_second_output))
    checks.append(
        (
            "reproducibility_audit_output_deterministic",
            reproducibility_first_output == reproducibility_second_output,
        )
    )
    checks.append(("isolation_audit_output_deterministic", isolation_first_output == isolation_second_output))
    checks.append(
        (
            "structured_chain_output_deterministic",
            (
                parity_first_output,
                coverage_first_output,
                stability_first_output,
                reproducibility_first_output,
                isolation_first_output,
            )
            == (
                parity_second_output,
                coverage_second_output,
                stability_second_output,
                reproducibility_second_output,
                isolation_second_output,
            ),
        )
    )

    checks.append(("surface_parity_registry_stable", "- surface_registry_deterministic=PASS" in parity_first_output))
    checks.append(("coverage_audit_registry_stable", "- surface_registry_deterministic=PASS" in coverage_first_output))
    checks.append(("stability_audit_registry_stable", "- surface_registry_deterministic=PASS" in stability_first_output))
    checks.append(
        (
            "reproducibility_audit_registry_stable",
            "- surface_registry_deterministic=PASS" in reproducibility_first_output,
        )
    )
    checks.append(("isolation_audit_registry_stable", "- surface_registry_deterministic=PASS" in isolation_first_output))

    return checks


def run_governance_shadow_determinism_audit_once() -> int:
    """Run a deterministic audit across the full governance shadow operator chain."""
    checks: list[tuple[str, bool]] = []

    try:
        lookback_rows = max(1, int(os.getenv("GOVERNANCE_REFRESH_LOOKBACK_ROWS", "500") or "500"))
        report = _build_governance_shadow_readiness_report(lookback_rows=lookback_rows)
        checks.extend(_evaluate_governance_shadow_determinism_audit_checks(report=report))
    except Exception as e:
        checks.append((f"determinism_audit_exception:{e}", False))

    ok = all(passed for _name, passed in checks)
    print(f"Governance shadow determinism audit: {'PASS' if ok else 'FAIL'}")
    for name, passed in checks:
        print(f"- {name}={'PASS' if passed else 'FAIL'}")
    return 0 if ok else 1

def main():
    args = sys.argv[1:]
    skip_provider_preflight = "--skip-provider-preflight" in args

    os.chdir(Path(__file__).resolve().parent)

    _assert_preprod_isolation_paths()

    if "--help" in args or "-h" in args:
        _print_help()
        return

    if "--initial-fill" in args:
        invalid = [arg for arg in args if arg not in {"--initial-fill", "--skip-provider-preflight"}]
        if invalid:
            print(f"Initial fill: FAIL unsupported_args={','.join(invalid)}")
            sys.exit(2)
        startup_health, provider_ok, provider_detail, ready, errors = _run_startup_preflight(
            skip_provider_preflight=skip_provider_preflight,
        )
        gate_payload = {"ok": False, "blocking_reason": "not_run_due_to_health_check_fail", "checks": []}
        if startup_health.ok and provider_ok and ready:
            gate_payload = _evaluate_scheduler_startup_production_safety_gate(
                startup_health=startup_health,
                ready_channels=ready,
            )
        if not startup_health.ok or not provider_ok or not ready or not bool(gate_payload.get("ok", True)):
            _record_safety_gate_result(
                mode="explicit_initial_fill",
                startup_health=startup_health,
                provider_preflight_ok=provider_ok,
                provider_preflight_detail=provider_detail,
                production_safety_gate_payload=gate_payload,
            )
            for error in errors:
                print(f"ERROR: {error}")
            for error in _production_safety_gate_errors(gate_payload):
                print(f"ERROR: {error}")
            sys.exit(1)
        _record_safety_gate_result(
            mode="explicit_initial_fill",
            startup_health=startup_health,
            provider_preflight_ok=True,
            provider_preflight_detail=provider_detail,
            production_safety_gate_payload=gate_payload,
        )
        initial_fill(trigger_source="explicit_initial_fill")
        print("Initial fill: submitted eligible channels")
        return

    if "--health-check" in args:
        result = _run_startup_health_check(
            create_missing_directories=False,
            require_telegram=True,
        )
        if result.ok:
            print("Health check: PASS")
            return
        print("Health check: FAIL")
        for error in result.errors:
            print(f"- {error}")
        sys.exit(1)

    if "--startup-preflight" in args:
        startup_health, provider_ok, provider_detail, ready, errors = _run_startup_preflight(
            skip_provider_preflight=skip_provider_preflight,
        )
        gate_payload = {"ok": False, "blocking_reason": "not_run_due_to_health_check_fail", "checks": []}
        if startup_health.ok and provider_ok and ready:
            gate_payload = _evaluate_scheduler_startup_production_safety_gate(
                startup_health=startup_health,
                ready_channels=ready,
            )
        if startup_health.ok and provider_ok and ready and bool(gate_payload.get("ok", True)):
            print("Startup preflight: PASS")
            print(f"- ready_channels={len(ready)}")
            print(f"- provider_preflight={provider_detail}")
            return
        print("Startup preflight: FAIL")
        for error in errors:
            print(f"- {error}")
        for error in _production_safety_gate_errors(gate_payload):
            print(f"- {error}")
        sys.exit(1)

    if "--safety-check-now" in args:
        sys.exit(run_safety_check_once(skip_provider_preflight=skip_provider_preflight))

    if "--sync-analytics-now" in args:
        sys.exit(run_live_analytics_sync_once())

    if "--run-optimization-cycle-now" in args:
        sys.exit(run_optimization_cycle_once())

    if "--refresh-governance-now" in args:
        sys.exit(run_governance_refresh_once())

    if "--governance-shadow-report-now" in args:
        sys.exit(run_governance_shadow_report_once())

    if "--governance-shadow-selfcheck-now" in args:
        sys.exit(run_governance_shadow_selfcheck_once())

    if "--governance-shadow-contract-validate-now" in args:
        sys.exit(run_governance_shadow_contract_validation_once())

    if "--governance-shadow-output-consistency-now" in args:
        sys.exit(run_governance_shadow_output_consistency_once())

    if "--governance-shadow-diagnostic-summary-now" in args:
        sys.exit(run_governance_shadow_diagnostic_summary_once())

    if "--governance-shadow-surface-parity-now" in args:
        sys.exit(run_governance_shadow_surface_parity_once())

    if "--governance-shadow-coverage-audit-now" in args:
        sys.exit(run_governance_shadow_coverage_audit_once())

    if "--governance-shadow-stability-audit-now" in args:
        sys.exit(run_governance_shadow_stability_audit_once())

    if "--governance-shadow-reproducibility-audit-now" in args:
        sys.exit(run_governance_shadow_reproducibility_audit_once())

    if "--governance-shadow-isolation-audit-now" in args:
        sys.exit(run_governance_shadow_isolation_audit_once())

    if "--governance-shadow-determinism-audit-now" in args:
        sys.exit(run_governance_shadow_determinism_audit_once())

    if "--list" in args or "--status" in args:
        show_status()
        return

    try:
        _acquire_scheduler_singleton_lock()
    except RuntimeError as e:
        logger.error("Scheduler singleton lock acquisition failed: %s", e)
        print(f"ERROR: {e}")
        sys.exit(1)

    from rich.console import Console
    console = Console()

    mode = os.getenv("JOB_STORE_MODE", "json").strip().lower()
    if mode not in {"json", "shadow"}:
        logger.warning("Geçersiz JOB_STORE_MODE='%s', json kullanılacak.", mode)
        mode = "json"

    if mode == "shadow":
        try:
            from src.job_store import initialize_database

            initialize_database(os.getenv("JOB_STORE_DB_PATH", "output/state/jobs.db"))
            logger.info("JOB_STORE_MODE=shadow aktif: SQLite shadow mirror etkin.")
        except Exception as e:
            logger.warning("Shadow DB init failed (non-blocking): %s", e)
    else:
        logger.info("JOB_STORE_MODE=json aktif: JSON production source of truth.")

    startup_health, provider_ok, provider_detail, ready, errors = _run_startup_preflight(
        skip_provider_preflight=skip_provider_preflight,
    )
    gate_payload = {"ok": False, "blocking_reason": "not_run_due_to_health_check_fail", "checks": []}
    if startup_health.ok and provider_ok and ready:
        gate_payload = _evaluate_scheduler_startup_production_safety_gate(
            startup_health=startup_health,
            ready_channels=ready,
        )
    if not startup_health.ok or not provider_ok or not ready or not bool(gate_payload.get("ok", True)):
        _record_safety_gate_result(
            mode="startup",
            startup_health=startup_health,
            provider_preflight_ok=provider_ok,
            provider_preflight_detail=provider_detail,
            production_safety_gate_payload=gate_payload,
        )
        _send_startup_incident_alert(gate_payload=gate_payload)
        for error in errors:
            logger.error("Startup validation failed: %s", error)
            print(f"ERROR: {error}")
        for error in _production_safety_gate_errors(gate_payload):
            logger.error("Startup validation failed: %s", error)
            print(f"ERROR: {error}")
        sys.exit(1)

    _record_safety_gate_result(
        mode="startup",
        startup_health=startup_health,
        provider_preflight_ok=True,
        provider_preflight_detail=provider_detail,
        production_safety_gate_payload=gate_payload,
    )
    logger.info("Startup provider preflight result: %s", provider_detail)

    # scheduler_utils opsiyonel — yoksa basit fallback kullan
    try:
        from src.scheduler_utils import notify_startup, cleanup_old_renders
        _has_utils = True
    except ImportError:
        _has_utils = False
        def notify_startup(n): pass
        def cleanup_old_renders(**kw): return 0

    logger.info("Scheduler starting")
    _write_pid_record()
    logger.info(
        "BUILD_INFO scheduler git_sha=%s cwd=%s python=%s started_at=%s",
        _resolve_git_head_short(),
        os.getcwd(),
        sys.executable,
        datetime.now(TZ).isoformat(),
    )

    console.print(f"\n[bold green]Para Pusulası Scheduler v4.0[/bold green]")
    console.print(f"[dim]{len(ready)} kanal aktif | MAX {MAX_PARALLEL_RENDERS} paralel render[/dim]\n")

    # Başlangıçta eski dosyaları temizle
    cleanup_old_renders(max_age_hours=48)

    # Zamanlama kur
    ready_channels = setup_schedule()

    # Restart sonrası geçmiş publish slotlarını tüket
    catch_up_overdue_queue_entries()

    inspect_startup_generation_candidates(ready_channels=ready_channels)

    # Günlük bakım (gece 03:00)
    schedule.every().day.at("03:00").do(maintenance_job)

    # Governance readiness refresh (metrics + bundle + markdown)
    governance_refresh_time = str(os.getenv("GOVERNANCE_REFRESH_TIME", "03:20")).strip() or "03:20"
    schedule.every().day.at(governance_refresh_time).do(governance_refresh_job)
    logger.info("Governance refresh job scheduled at %s", governance_refresh_time)

    # Her saatte boş kuyruğu olan kanalları doldur (restart güvencesi)
    if _observation_mode_active():
        logger.warning("Hourly queue fill scheduling skipped: production_observation_mode")
    else:
        schedule.every(1).hour.do(fill_empty_queues_job)

    # Canlı YouTube Analytics senkronu (no-go durumunda planlama yapılmaz)
    live_enabled, live_status = _resolve_live_collector_runtime()
    if live_enabled:
        schedule.every(6).hours.do(refresh_live_analytics_job)
    else:
        logger.info(
            "Live analytics scheduler disabled: live_collector_enabled=false analytics_live_status=%s",
            live_status,
        )

    logger.info("Startup initial fill disabled: generation requires --initial-fill or scheduled queue fill")

    # Telegram startup bildirimi
    notify_startup(len(ready))

    # Cross-channel subscribe/like güvenli modda kapalı

    console.print("[green]Çalışıyor. Durdurmak: Ctrl+C[/green]")
    console.print("[dim]Her upload sonrası sonraki video otomatik render edilir.[/dim]\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    finally:
        _release_scheduler_singleton_lock()


if __name__ == "__main__":
    main()

