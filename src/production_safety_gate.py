from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import config as default_config
from .production_quality_platform import record_production_event
from .scheduler_utils import (
    check_token_health,
    get_free_disk_gb,
    get_global_overload_pause_status,
    get_provider_circuit_status,
)


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_env_list(name: str) -> list[str]:
    raw = str(os.getenv(name, "") or "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _resolve_git_head() -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""
    return output


def production_safety_gate_enabled() -> bool:
    if not _is_enabled(os.getenv("PRODUCTION_SAFETY_GATE_ENABLED", "true")):
        return False

    current_test = str(os.getenv("PYTEST_CURRENT_TEST") or "")
    if current_test and not _is_enabled(os.getenv("PRODUCTION_SAFETY_GATE_IN_TESTS", "false")):
        return False

    return True


@dataclass(frozen=True, slots=True)
class ProductionSafetyCheckResult:
    check_name: str
    status: str
    severity: str
    reason_code: str
    message: str
    timestamp: str
    release_sha: str
    channel_id: str
    job_id: str
    evidence: dict[str, Any]

    @property
    def allowed(self) -> bool:
        return self.status != "fail"

    @property
    def ok(self) -> bool:
        return self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "check_name": self.check_name,
            "name": self.check_name,
            "severity": self.severity,
            "reason_code": self.reason_code,
            "reason": self.reason_code,
            "message": self.message,
            "timestamp": self.timestamp,
            "release_sha": self.release_sha,
            "channel_id": self.channel_id,
            "job_id": self.job_id,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ProductionSafetyGateResult:
    operation: str
    channel_id: str
    job_id: str
    allowed: bool
    status: str
    blocking_reason: str
    timestamp: str
    release_sha: str
    checks: tuple[ProductionSafetyCheckResult, ...]
    evidence: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "channel_id": self.channel_id,
            "job_id": self.job_id,
            "allowed": self.allowed,
            "ok": self.allowed,
            "status": self.status,
            "blocking_reason": self.blocking_reason,
            "timestamp": self.timestamp,
            "release_sha": self.release_sha,
            "checks": [item.to_dict() for item in self.checks],
            "evidence": dict(self.evidence),
        }


class ProductionSafetyGateBlocked(RuntimeError):
    def __init__(self, result: ProductionSafetyGateResult):
        self.gate_result = result
        self._suppress_pipeline_stage_failed_event = True
        super().__init__(f"production_safety_gate_blocked:{result.blocking_reason or 'unknown'}")


def _build_check(
    *,
    check_name: str,
    status: str,
    severity: str,
    reason_code: str,
    message: str,
    release_sha: str,
    channel_id: str,
    job_id: str,
    evidence: dict[str, Any] | None = None,
) -> ProductionSafetyCheckResult:
    return ProductionSafetyCheckResult(
        check_name=check_name,
        status=status,
        severity=severity,
        reason_code=reason_code,
        message=message,
        timestamp=_now_utc().isoformat(),
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence=dict(evidence or {}),
    )


def _check_api_credentials(*, startup_health: Any | None, config_obj: Any, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    missing = ()
    if startup_health is not None:
        missing = tuple(getattr(startup_health, "missing_api_keys", ()) or ())
    else:
        validator = getattr(config_obj, "validate", None)
        if callable(validator):
            try:
                missing = tuple(validator())
            except Exception as exc:
                return _build_check(
                    check_name="api_credentials",
                    status="fail",
                    severity="critical",
                    reason_code="api_credentials_validation_failed",
                    message="API credential validation failed before execution.",
                    release_sha=release_sha,
                    channel_id=channel_id,
                    job_id=job_id,
                    evidence={"error_type": exc.__class__.__name__},
                )

    if missing:
        return _build_check(
            check_name="api_credentials",
            status="fail",
            severity="critical",
            reason_code="api_credentials_missing",
            message="Required API credentials are missing.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"missing_api_keys": list(missing)},
        )

    return _build_check(
        check_name="api_credentials",
        status="pass",
        severity="critical",
        reason_code="api_credentials_present",
        message="Required API credentials are present.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
    )


def _check_youtube_auth(*, channel_cfg: Any | None, ready_channels: list[str] | None, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    if channel_cfg is not None:
        ok, detail = check_token_health(channel_cfg)
        return _build_check(
            check_name="youtube_authentication",
            status="pass" if ok else "fail",
            severity="critical",
            reason_code="youtube_token_valid" if ok else "youtube_token_invalid",
            message="YouTube authentication token is valid." if ok else "YouTube authentication token is invalid.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"detail": str(detail or "")},
        )

    if ready_channels is not None:
        try:
            from .channel_manager import get_channel
        except Exception as exc:
            return _build_check(
                check_name="youtube_authentication",
                status="fail",
                severity="critical",
                reason_code="youtube_auth_probe_unavailable",
                message="The YouTube authentication probe is unavailable.",
                release_sha=release_sha,
                channel_id=channel_id,
                job_id=job_id,
                evidence={"error_type": exc.__class__.__name__},
            )

        healthy: list[str] = []
        unhealthy: list[dict[str, str]] = []
        for ready_channel_id in ready_channels:
            try:
                cfg = get_channel(ready_channel_id)
                ok, detail = check_token_health(cfg)
            except Exception as exc:
                ok = False
                detail = exc.__class__.__name__
            if ok:
                healthy.append(str(ready_channel_id))
            else:
                unhealthy.append({"channel_id": str(ready_channel_id), "detail": str(detail or "")})

        if healthy:
            return _build_check(
                check_name="youtube_authentication",
                status="pass",
                severity="critical",
                reason_code="ready_channel_token_valid",
                message="At least one ready channel has a valid YouTube token.",
                release_sha=release_sha,
                channel_id=channel_id,
                job_id=job_id,
                evidence={"healthy_channels": healthy, "unhealthy_channels": unhealthy},
            )

        return _build_check(
            check_name="youtube_authentication",
            status="fail",
            severity="critical",
            reason_code="no_ready_channel_with_valid_token",
            message="No ready channel has a valid YouTube token.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"unhealthy_channels": unhealthy},
        )

    return _build_check(
        check_name="youtube_authentication",
        status="skip",
        severity="critical",
        reason_code="not_applicable",
        message="YouTube authentication check was not applicable for this operation.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
    )


def _check_disk_space(*, release_sha: str, channel_id: str, job_id: str) -> tuple[ProductionSafetyCheckResult, ProductionSafetyCheckResult | None]:
    free_gb = float(get_free_disk_gb())
    critical_gb = float(os.getenv("PRODUCTION_SAFETY_MIN_FREE_GB", "1.5") or "1.5")
    warning_gb = float(os.getenv("PRODUCTION_SAFETY_WARN_FREE_GB", "3.0") or "3.0")
    critical = free_gb < critical_gb
    primary = _build_check(
        check_name="disk_space",
        status="fail" if critical else "pass",
        severity="critical",
        reason_code="disk_space_below_threshold" if critical else "disk_space_ok",
        message="Free disk space is below the critical threshold." if critical else "Free disk space is above the critical threshold.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"free_gb": round(free_gb, 3), "critical_gb": critical_gb, "warning_gb": warning_gb},
    )

    if critical or free_gb >= warning_gb:
        return primary, None

    warning = _build_check(
        check_name="disk_space_warning",
        status="warn",
        severity="warning",
        reason_code="disk_space_warning_threshold",
        message="Free disk space is below the warning threshold.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"free_gb": round(free_gb, 3), "warning_gb": warning_gb},
    )
    return primary, warning


def _check_writable_paths(*, config_obj: Any, writable_paths: list[str | Path] | None, artifact_paths: dict[str, str | Path | None] | None, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    probes: list[Path] = []
    for attr in ("output_dir", "scripts_dir", "audio_dir", "videos_dir", "assets_dir", "logs_dir"):
        value = getattr(config_obj, attr, None)
        if value:
            probes.append(Path(str(value)))

    for item in writable_paths or []:
        probes.append(Path(item))

    for value in (artifact_paths or {}).values():
        if value:
            probes.append(Path(value).parent)

    failures: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_path in probes:
        path = raw_path if raw_path.exists() and raw_path.is_dir() else raw_path.parent
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)

        if not path.exists():
            failures.append({"path": str(path), "reason": "missing_directory"})
            continue

        probe_file = path / f".safety_gate_probe_{os.getpid()}_{uuid.uuid4().hex}.tmp"
        try:
            probe_file.write_text("ok", encoding="utf-8")
            probe_file.unlink()
        except Exception as exc:
            failures.append({"path": str(path), "reason": exc.__class__.__name__})

    return _build_check(
        check_name="writable_directories",
        status="pass" if not failures else "fail",
        severity="critical",
        reason_code="writable_directories_ok" if not failures else "writable_directories_unavailable",
        message="All required writable paths are available." if not failures else "One or more required writable paths are unavailable.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"failures": failures},
    )


def _check_required_env_vars(*, required_env_vars: list[str] | None, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    env_names = list(required_env_vars or _parse_env_list("PRODUCTION_SAFETY_REQUIRED_ENV_VARS"))
    missing = [name for name in env_names if not str(os.getenv(name, "")).strip()]
    return _build_check(
        check_name="required_env_variables",
        status="pass" if not missing else "fail",
        severity="critical",
        reason_code="required_env_present" if not missing else "required_env_missing",
        message="All required environment variables are present." if not missing else "Required environment variables are missing.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"required_env_vars": env_names, "missing": missing},
    )


def _check_scheduler_health(*, operation: str, startup_health: Any | None, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    if operation == "scheduler_startup":
        ok = bool(getattr(startup_health, "ok", False))
        result = _build_check(
            check_name="scheduler_health",
            status="pass" if ok else "fail",
            severity="critical",
            reason_code="startup_health_ok" if ok else "startup_health_failed",
            message="Scheduler startup health checks passed." if ok else "Scheduler startup health checks failed.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"errors": list(getattr(startup_health, "errors", ()) or ())},
        )
        if not result.allowed:
            return result

        lock_path = Path(os.getenv("SCHEDULER_SINGLETON_LOCK_FILE", "output/state/scheduler_singleton.lock"))
        meta_path = Path(os.getenv("SCHEDULER_SINGLETON_META_FILE", "output/state/scheduler_singleton_meta.json"))
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            meta_pid = str((meta or {}).get("pid") or "").strip()
            if meta_pid and meta_pid != str(os.getpid()):
                return _build_check(
                    check_name="scheduler_health",
                    status="fail",
                    severity="critical",
                    reason_code="duplicate_scheduler_state",
                    message="Scheduler singleton metadata belongs to another process.",
                    release_sha=release_sha,
                    channel_id=channel_id,
                    job_id=job_id,
                    evidence={"meta_pid": meta_pid, "current_pid": os.getpid(), "lock_path": str(lock_path)},
                )
        return result

    pid_path = Path(os.getenv("SCHEDULER_PID_FILE", "output/state/production_scheduler.pid"))
    if pid_path.exists():
        raw_pid = pid_path.read_text(encoding="utf-8").strip()
        ok = raw_pid.isdigit()
        evidence = {"pid": raw_pid, "pid_file": str(pid_path)}
        return _build_check(
            check_name="scheduler_health",
            status="pass" if ok else "fail",
            severity="critical",
            reason_code="scheduler_pid_present" if ok else "scheduler_pid_invalid",
            message="Scheduler pid record is valid." if ok else "Scheduler pid record is invalid.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence=evidence,
        )

    return _build_check(
        check_name="scheduler_health",
        status="pass",
        severity="critical",
        reason_code="scheduler_pid_not_required_for_current_operation",
        message="No scheduler pid record is required for this operation.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
    )


def _load_queue_payload(path: Path) -> tuple[dict[str, Any] | None, Exception | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, exc
    return payload if isinstance(payload, dict) else None, None


def _check_queue_health(*, queue_path: str | Path | None, channel_id: str, release_sha: str, job_id: str) -> tuple[ProductionSafetyCheckResult, ProductionSafetyCheckResult | None]:
    path = Path(queue_path) if queue_path else Path(os.getenv("SCHEDULER_QUEUE_FILE", "output/state/channel_queue.json"))
    if not path.exists():
        primary = _build_check(
            check_name="queue_health",
            status="pass",
            severity="critical",
            reason_code="queue_file_absent_treated_as_empty",
            message="Queue file is absent and treated as empty.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"path": str(path)},
        )
        return primary, None

    payload, error = _load_queue_payload(path)
    if error is not None:
        primary = _build_check(
            check_name="queue_health",
            status="fail",
            severity="critical",
            reason_code="queue_file_unreadable",
            message="Queue file is unreadable or corrupted.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"path": str(path), "error_type": error.__class__.__name__},
        )
        return primary, None

    if payload is None:
        primary = _build_check(
            check_name="queue_health",
            status="fail",
            severity="critical",
            reason_code="queue_payload_not_dict",
            message="Queue payload is not a valid mapping.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"path": str(path)},
        )
        return primary, None

    if channel_id:
        entries = payload.get(channel_id, [])
        if not isinstance(entries, list):
            primary = _build_check(
                check_name="queue_health",
                status="fail",
                severity="critical",
                reason_code="queue_channel_entries_not_list",
                message="Queue entries for the channel are corrupted.",
                release_sha=release_sha,
                channel_id=channel_id,
                job_id=job_id,
                evidence={"path": str(path), "channel_id": channel_id},
            )
            return primary, None

    all_entries = 0
    for value in payload.values():
        if isinstance(value, list):
            all_entries += len(value)
    backlog_threshold = int(os.getenv("PRODUCTION_SAFETY_QUEUE_BACKLOG_WARNING", "25") or "25")

    primary = _build_check(
        check_name="queue_health",
        status="pass",
        severity="critical",
        reason_code="queue_payload_valid",
        message="Queue payload is structurally valid.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"path": str(path), "channel_id": channel_id, "entry_count": all_entries},
    )

    if all_entries <= backlog_threshold:
        return primary, None

    warning = _build_check(
        check_name="queue_backlog",
        status="warn",
        severity="warning",
        reason_code="queue_backlog_elevated",
        message="Queue backlog is above the warning threshold.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"entry_count": all_entries, "warning_threshold": backlog_threshold},
    )
    return primary, warning


def _check_release_integrity(*, release_metadata_path: str | Path | None, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    if not release_sha:
        return _build_check(
            check_name="release_integrity",
            status="fail",
            severity="critical",
            reason_code="git_head_unavailable",
            message="Release integrity cannot be verified because git HEAD is unavailable.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
        )

    meta_path = Path(release_metadata_path) if release_metadata_path else Path(".immutable_release_metadata.json")
    if not meta_path.exists():
        return _build_check(
            check_name="release_integrity",
            status="pass",
            severity="critical",
            reason_code="release_metadata_absent_non_release_worktree",
            message="No immutable release metadata is present in this non-release worktree.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"git_head": release_sha},
        )

    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _build_check(
            check_name="release_integrity",
            status="fail",
            severity="critical",
            reason_code="release_metadata_unreadable",
            message="Immutable release metadata is unreadable.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
            evidence={"path": str(meta_path), "error_type": exc.__class__.__name__},
        )

    metadata_sha = str((payload or {}).get("release_sha") or "").strip()
    ok = bool(metadata_sha) and metadata_sha == release_sha
    return _build_check(
        check_name="release_integrity",
        status="pass" if ok else "fail",
        severity="critical",
        reason_code="release_integrity_ok" if ok else "release_integrity_mismatch",
        message="Immutable release metadata matches git HEAD." if ok else "Immutable release metadata does not match git HEAD.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"path": str(meta_path), "metadata_sha": metadata_sha, "git_head": release_sha},
    )


def _check_active_deployment_lock(*, deployment_lock_path: str | Path | None, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    path = Path(deployment_lock_path) if deployment_lock_path else Path(os.getenv("IMMUTABLE_V2_LOCK_DIR", "/opt/parapusulasi/deploy.lock"))
    exists = path.exists()
    return _build_check(
        check_name="active_deployment_lock",
        status="fail" if exists else "pass",
        severity="critical",
        reason_code="active_deployment_lock" if exists else "no_active_deployment_lock",
        message="An active deployment lock is present." if exists else "No active deployment lock is present.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"path": str(path), "exists": exists},
    )


def _check_clock_sanity(*, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    now = _now_utc()
    ok = 2025 <= now.year <= 2100
    return _build_check(
        check_name="clock_sanity",
        status="pass" if ok else "fail",
        severity="critical",
        reason_code="clock_sane" if ok else "clock_sanity_failed",
        message="System clock is sane." if ok else "System clock is outside the accepted range.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"utc_now": now.isoformat()},
    )


def _check_rate_limit_status(*, operation: str, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult:
    global_pause = get_global_overload_pause_status()
    provider_circuit = get_provider_circuit_status("anthropic")
    if operation in {"scheduler_startup", "render"}:
        if bool(global_pause.get("is_open")):
            return _build_check(
                check_name="rate_limit_status",
                status="fail",
                severity="critical",
                reason_code="global_overload_pause_open",
                message="Global overload pause is open.",
                release_sha=release_sha,
                channel_id=channel_id,
                job_id=job_id,
                evidence=dict(global_pause),
            )
        if bool(provider_circuit.get("is_open")):
            return _build_check(
                check_name="rate_limit_status",
                status="fail",
                severity="critical",
                reason_code="provider_circuit_open",
                message="Provider rate-limit circuit is open.",
                release_sha=release_sha,
                channel_id=channel_id,
                job_id=job_id,
                evidence=dict(provider_circuit),
            )

    provider_state = dict(provider_circuit.get("state") or {})
    warning_threshold = int(os.getenv("PRODUCTION_SAFETY_RATE_LIMIT_WARNING_FAILURES", "1") or "1")
    consecutive_failures = int(provider_state.get("consecutive_failures", 0) or 0)
    approaching = consecutive_failures >= warning_threshold and not bool(provider_circuit.get("is_open"))
    return _build_check(
        check_name="rate_limit_status",
        status="warn" if approaching else "pass",
        severity="warning" if approaching else "critical",
        reason_code="rate_limit_approaching" if approaching else "rate_limit_clear",
        message="Provider rate limits are approaching warning thresholds." if approaching else "Provider rate limits are clear.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={
            "operation": operation,
            "global_overload_pause": dict(global_pause),
            "provider_circuit": dict(provider_circuit),
            "warning_threshold": warning_threshold,
            "consecutive_failures": consecutive_failures,
        },
    )


def _check_optional_integrations(*, release_sha: str, channel_id: str, job_id: str) -> ProductionSafetyCheckResult | None:
    optional_env_vars = _parse_env_list("PRODUCTION_SAFETY_OPTIONAL_ENV_VARS")
    if not optional_env_vars:
        return None
    missing = [name for name in optional_env_vars if not str(os.getenv(name, "")).strip()]
    if not missing:
        return None
    return _build_check(
        check_name="optional_integrations",
        status="warn",
        severity="warning",
        reason_code="optional_integration_unavailable",
        message="One or more optional integrations are unavailable.",
        release_sha=release_sha,
        channel_id=channel_id,
        job_id=job_id,
        evidence={"optional_env_vars": optional_env_vars, "missing": missing},
    )


def _aggregate_status(checks: tuple[ProductionSafetyCheckResult, ...]) -> tuple[bool, str, str]:
    blocking_reason = next((item.reason_code for item in checks if item.status == "fail" and item.severity == "critical"), "")
    if blocking_reason:
        return False, "blocked", blocking_reason
    if any(item.status == "warn" for item in checks):
        return True, "warning", ""
    if all(item.status == "skip" for item in checks):
        return True, "skipped", ""
    return True, "allowed", ""


def _emit_gate_event(result: ProductionSafetyGateResult) -> None:
    highest_severity = "INFO"
    if result.status == "blocked":
        highest_severity = "ERROR"
    elif result.status == "warning":
        highest_severity = "WARNING"

    event = {
        "timestamp": result.timestamp,
        "event_type": "production_safety_gate",
        "stage": result.operation,
        "channel": result.channel_id,
        "channel_id": result.channel_id,
        "job_id": result.job_id,
        "release_sha": result.release_sha,
        "severity": highest_severity,
        "reason": result.blocking_reason or result.status,
        "final_status": result.status,
        "allowed": result.allowed,
        "checks": [item.to_dict() for item in result.checks],
        "evidence": dict(result.evidence),
    }
    try:
        record_production_event(event)
    except Exception:
        return


def evaluate_production_safety_gate(
    *,
    operation: str,
    channel_id: str = "",
    channel_cfg: Any | None = None,
    startup_health: Any | None = None,
    ready_channels: list[str] | None = None,
    queue_path: str | Path | None = None,
    writable_paths: list[str | Path] | None = None,
    artifact_paths: dict[str, str | Path | None] | None = None,
    required_env_vars: list[str] | None = None,
    release_metadata_path: str | Path | None = None,
    deployment_lock_path: str | Path | None = None,
    job_id: str = "",
) -> ProductionSafetyGateResult:
    release_sha = _resolve_git_head()
    if not production_safety_gate_enabled():
        check = _build_check(
            check_name="production_safety_gate",
            status="skip",
            severity="critical",
            reason_code="disabled_for_current_runtime",
            message="Production safety gate is disabled for the current runtime.",
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
        )
        return ProductionSafetyGateResult(
            operation=operation,
            channel_id=channel_id,
            job_id=job_id,
            allowed=True,
            status="skipped",
            blocking_reason="",
            timestamp=_now_utc().isoformat(),
            release_sha=release_sha,
            checks=(check,),
            evidence={"critical_failures": 0, "warnings": 0},
        )

    config_obj = channel_cfg or default_config
    checks: list[ProductionSafetyCheckResult] = []
    checks.append(_check_api_credentials(startup_health=startup_health, config_obj=config_obj, release_sha=release_sha, channel_id=channel_id, job_id=job_id))
    checks.append(_check_youtube_auth(channel_cfg=channel_cfg, ready_channels=ready_channels, release_sha=release_sha, channel_id=channel_id, job_id=job_id))

    disk_primary, disk_warning = _check_disk_space(release_sha=release_sha, channel_id=channel_id, job_id=job_id)
    checks.append(disk_primary)
    if disk_warning is not None:
        checks.append(disk_warning)

    checks.append(
        _check_writable_paths(
            config_obj=config_obj,
            writable_paths=writable_paths,
            artifact_paths=artifact_paths,
            release_sha=release_sha,
            channel_id=channel_id,
            job_id=job_id,
        )
    )
    checks.append(_check_required_env_vars(required_env_vars=required_env_vars, release_sha=release_sha, channel_id=channel_id, job_id=job_id))
    checks.append(_check_scheduler_health(operation=operation, startup_health=startup_health, release_sha=release_sha, channel_id=channel_id, job_id=job_id))

    queue_primary, queue_warning = _check_queue_health(queue_path=queue_path, channel_id=channel_id, release_sha=release_sha, job_id=job_id)
    checks.append(queue_primary)
    if queue_warning is not None:
        checks.append(queue_warning)

    checks.append(_check_release_integrity(release_metadata_path=release_metadata_path, release_sha=release_sha, channel_id=channel_id, job_id=job_id))
    checks.append(_check_active_deployment_lock(deployment_lock_path=deployment_lock_path, release_sha=release_sha, channel_id=channel_id, job_id=job_id))
    checks.append(_check_clock_sanity(release_sha=release_sha, channel_id=channel_id, job_id=job_id))
    checks.append(_check_rate_limit_status(operation=operation, release_sha=release_sha, channel_id=channel_id, job_id=job_id))
    optional_check = _check_optional_integrations(release_sha=release_sha, channel_id=channel_id, job_id=job_id)
    if optional_check is not None:
        checks.append(optional_check)

    checks_tuple = tuple(checks)
    allowed, status, blocking_reason = _aggregate_status(checks_tuple)
    evidence = {
        "critical_failures": sum(1 for item in checks_tuple if item.status == "fail" and item.severity == "critical"),
        "warnings": sum(1 for item in checks_tuple if item.status == "warn"),
        "check_count": len(checks_tuple),
    }
    result = ProductionSafetyGateResult(
        operation=operation,
        channel_id=channel_id,
        job_id=job_id,
        allowed=allowed,
        status=status,
        blocking_reason=blocking_reason,
        timestamp=_now_utc().isoformat(),
        release_sha=release_sha,
        checks=checks_tuple,
        evidence=evidence,
    )
    _emit_gate_event(result)
    return result


def ensure_production_safety_gate(**kwargs: Any) -> ProductionSafetyGateResult:
    result = evaluate_production_safety_gate(**kwargs)
    if not result.allowed:
        raise ProductionSafetyGateBlocked(result)
    return result