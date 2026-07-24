from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_storage import runtime_path


TOOL_VERSION = "production-observation-mode.v1"
ENV_FLAG = "PRODUCTION_OBSERVATION_MODE"
DEFAULT_STATE_PATH = runtime_path("state/production_observation_mode.json")
DEFAULT_AUDIT_PATH = runtime_path("telemetry/production_observation_mode_audit.jsonl")
DEFAULT_LOCK_PATH = runtime_path("state/.production_observation_mode.lock")


class ProductionObservationModeError(RuntimeError):
    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(reason if not detail else f"{reason}: {detail}")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_enabled_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def observation_state_path() -> Path:
    return Path(os.getenv("PRODUCTION_OBSERVATION_MODE_STATE_FILE", str(DEFAULT_STATE_PATH)))


def observation_audit_path() -> Path:
    return Path(os.getenv("PRODUCTION_OBSERVATION_MODE_AUDIT_FILE", str(DEFAULT_AUDIT_PATH)))


def observation_lock_path() -> Path:
    return Path(os.getenv("PRODUCTION_OBSERVATION_MODE_LOCK_FILE", str(DEFAULT_LOCK_PATH)))


def _resolve_production_sha(cwd: Path | None = None) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd or Path.cwd()),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _sha256_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    data = _json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _append_audit(record: dict[str, Any]) -> None:
    path = observation_audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("event_id", uuid.uuid4().hex)
    payload.setdefault("timestamp_utc", _format_utc(_now_utc()))
    payload.setdefault("hostname", socket.gethostname())
    payload.setdefault("process_id", os.getpid())
    payload.setdefault("tool_version", TOOL_VERSION)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


@contextmanager
def _locked():
    lock = observation_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_observation_state() -> dict[str, Any]:
    path = observation_state_path()
    if not path.exists():
        return {
            "schema_version": "production_observation_mode.v1",
            "enabled": _is_enabled_value(os.getenv(ENV_FLAG, "false")),
            "source": "environment_default" if ENV_FLAG in os.environ else "absent_default",
            "state_path": str(path),
            "tool_version": TOOL_VERSION,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "schema_version": "production_observation_mode.v1",
            "enabled": True,
            "source": "invalid_state_fail_closed",
            "state_path": str(path),
            "error_type": exc.__class__.__name__,
            "tool_version": TOOL_VERSION,
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": "production_observation_mode.v1",
            "enabled": True,
            "source": "non_object_state_fail_closed",
            "state_path": str(path),
            "tool_version": TOOL_VERSION,
        }
    payload = dict(payload)
    payload.setdefault("schema_version", "production_observation_mode.v1")
    payload.setdefault("state_path", str(path))
    payload.setdefault("tool_version", TOOL_VERSION)
    if ENV_FLAG in os.environ:
        payload["environment_override"] = os.getenv(ENV_FLAG, "")
        payload["enabled"] = _is_enabled_value(os.getenv(ENV_FLAG, "false"))
    else:
        payload["enabled"] = bool(payload.get("enabled"))
    return payload


def production_observation_mode_enabled() -> bool:
    return bool(read_observation_state().get("enabled"))


def set_production_observation_mode(
    *,
    enabled: bool,
    operator: str,
    reason: str,
    expected_production_sha: str,
    production_sha: str | None = None,
) -> dict[str, Any]:
    if not str(operator or "").strip():
        raise ProductionObservationModeError("operator_missing")
    if not str(reason or "").strip():
        raise ProductionObservationModeError("reason_missing")
    current_sha = production_sha if production_sha is not None else _resolve_production_sha()
    if current_sha != expected_production_sha:
        raise ProductionObservationModeError("production_sha_mismatch", current_sha)
    event_id = uuid.uuid4().hex
    with _locked():
        before = read_observation_state()
        payload = {
            "schema_version": "production_observation_mode.v1",
            "enabled": bool(enabled),
            "reason": str(reason),
            "operator": str(operator),
            "production_sha": str(expected_production_sha),
            "updated_at": _format_utc(_now_utc()),
            "updated_by_tool": TOOL_VERSION,
            "last_event_id": event_id,
        }
        _atomic_write_json(observation_state_path(), payload)
        after = read_observation_state()
        audit = {
            "event_id": event_id,
            "event_type": "production_observation_mode_enabled" if enabled else "production_observation_mode_disabled",
            "operator": str(operator),
            "reason": str(reason),
            "production_sha": str(expected_production_sha),
            "before_enabled": bool(before.get("enabled")),
            "after_enabled": bool(after.get("enabled")),
            "before_state_sha256": _sha256_payload(before),
            "after_state_sha256": _sha256_payload(after),
            "state_path": str(observation_state_path()),
            "success": True,
        }
        _append_audit(audit)
    return {
        "status": "enabled" if enabled else "disabled",
        "event_id": event_id,
        "observation_mode": after,
        "state_sha256": _sha256_payload(after),
    }