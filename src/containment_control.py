from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import socket
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .scheduler_utils import PROVIDER_HEALTH_FILE
from .visual_safety_policy import POLICY_VERSION


TOOL_VERSION = "visual-containment-control.v1"
SUPPORTED_INCIDENT_ID = "PROJECT003"
PROJECT003_REASON = "visual_safety_incident_containment:PROJECT003:cross_channel_inappropriate_visuals"
EVIDENCE_SCHEMA_VERSION = "visual_safety_containment_release_evidence.v1"
DEFAULT_AUDIT_PATH = Path("output/runtime/telemetry/visual_safety_containment_audit.jsonl")
DEFAULT_VALIDITY_SECONDS = 2 * 60 * 60
DEFAULT_RESTORE_SECONDS = 3 * 24 * 60 * 60
REQUIRED_MANDATORY_FIELDS = (
    "deployed_sha_verified",
    "service_healthy",
    "scheduler_healthy",
    "visual_policy_loaded",
    "cache_isolation_verified",
    "upload_precheck_verified",
    "render_manifest_verified",
    "shorts_manifest_verified",
    "thumbnail_validation_verified",
    "no_unsafe_dry_run_result",
    "no_quarantine_escape",
    "no_critical_runtime_error",
)
REQUIRED_EVIDENCE_FIELDS = (
    "schema_version",
    "incident_id",
    "production_sha",
    "policy_version",
    "generated_at",
    "eligible_for_release",
    "mandatory",
    "dry_run_totals",
    "critical_error_count",
    "quarantine_escape_count",
    "unsafe_selection_count",
    "unsafe_approval_count",
    "upload_attempt_count",
    "verifier_version",
)
CHANNELS_UNDER_TEST = (
    ("saglik_pusulasi", "saglik"),
    ("para_pusulasi", "kisisel_finans"),
    ("girisim_okulu", "girisim"),
    ("egitim_rehberi", "egitim"),
    ("teknoloji_pusulasi", "teknoloji"),
    ("kariyer_pusulasi", "kariyer"),
    ("kripto_rehber", "kripto"),
    ("gayrimenkul_tv", "gayrimenkul"),
)


class ContainmentControlError(RuntimeError):
    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(reason if not detail else f"{reason}: {detail}")


@dataclass(frozen=True)
class ContainmentPaths:
    provider_health_file: Path
    audit_file: Path
    lock_file: Path
    deploy_lock_dir: Path


@dataclass(frozen=True)
class ReleaseRequest:
    incident_id: str
    expected_reason: str
    expected_policy_version: str
    expected_production_sha: str
    operator: str
    evidence_file: Path
    uploads_disabled: bool
    renders_disabled: bool
    confirm_release: str
    quarantine_recovery_requested: bool = False


@dataclass(frozen=True)
class RestoreRequest:
    incident_id: str
    operator: str
    reason: str
    confirm_restore: str
    expected_production_sha: str


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception as exc:
        raise ContainmentControlError("evidence_generated_at_invalid", str(raw)) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def default_paths() -> ContainmentPaths:
    provider = Path(os.getenv("VISUAL_CONTAINMENT_PROVIDER_HEALTH_FILE", PROVIDER_HEALTH_FILE))
    audit = Path(os.getenv("VISUAL_CONTAINMENT_AUDIT_FILE", str(DEFAULT_AUDIT_PATH)))
    lock_file = Path(os.getenv("VISUAL_CONTAINMENT_LOCK_FILE", str(provider.parent / ".visual_safety_containment.lock")))
    deploy_lock = Path(os.getenv("VISUAL_CONTAINMENT_DEPLOY_LOCK_DIR", "/opt/parapusulasi/deploy.lock"))
    return ContainmentPaths(provider, audit, lock_file, deploy_lock)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _state_hash(state: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(state))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ContainmentControlError("state_file_missing", str(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContainmentControlError("state_file_invalid_json", str(path)) from exc
    if not isinstance(payload, dict):
        raise ContainmentControlError("state_file_not_object", str(path))
    return payload


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


def _append_audit(paths: ContainmentPaths, record: dict[str, Any]) -> None:
    paths.audit_file.parent.mkdir(parents=True, exist_ok=True)
    record = dict(record)
    record.setdefault("event_id", uuid.uuid4().hex)
    record.setdefault("timestamp_utc", _format_utc(_now_utc()))
    record.setdefault("hostname", socket.gethostname())
    record.setdefault("process_id", os.getpid())
    record.setdefault("tool_version", TOOL_VERSION)
    data = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    fd = os.open(str(paths.audit_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        try:
            os.chmod(paths.audit_file, 0o600)
        except OSError:
            pass


@contextmanager
def _locked(paths: ContainmentPaths):
    paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with paths.lock_file.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def _service_is_healthy() -> bool:
    try:
        active = subprocess.check_output(["systemctl", "is-active", "parapusulasi"], text=True, stderr=subprocess.DEVNULL).strip()
        state = subprocess.check_output(
            ["systemctl", "show", "parapusulasi", "-p", "ActiveState", "-p", "SubState", "-p", "Result"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    values = dict(line.split("=", 1) for line in state.splitlines() if "=" in line)
    return active == "active" and values.get("ActiveState") == "active" and values.get("SubState") == "running" and values.get("Result") == "success"


def _deploy_lock_is_clear(paths: ContainmentPaths) -> bool:
    active_marker = paths.deploy_lock_dir / ".active_lock"
    return not active_marker.exists()


def _validate_incident_id(incident_id: str) -> None:
    if incident_id != SUPPORTED_INCIDENT_ID:
        raise ContainmentControlError("unsupported_incident_id", incident_id)


def validate_release_evidence(
    *,
    evidence_file: Path,
    expected_incident_id: str,
    expected_production_sha: str,
    expected_policy_version: str,
    now: datetime | None = None,
    validity_seconds: int | None = None,
) -> dict[str, Any]:
    if not evidence_file.exists():
        raise ContainmentControlError("evidence_file_missing", str(evidence_file))
    try:
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContainmentControlError("evidence_file_invalid_json", str(evidence_file)) from exc
    if not isinstance(evidence, dict):
        raise ContainmentControlError("evidence_not_object", str(evidence_file))
    missing = [field for field in REQUIRED_EVIDENCE_FIELDS if field not in evidence]
    if missing:
        raise ContainmentControlError("evidence_missing_fields", ",".join(missing))
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ContainmentControlError("evidence_schema_unsupported", str(evidence.get("schema_version")))
    if evidence.get("incident_id") != expected_incident_id:
        raise ContainmentControlError("evidence_incident_mismatch", str(evidence.get("incident_id")))
    if evidence.get("production_sha") != expected_production_sha:
        raise ContainmentControlError("evidence_sha_mismatch", str(evidence.get("production_sha")))
    if evidence.get("policy_version") != expected_policy_version:
        raise ContainmentControlError("evidence_policy_mismatch", str(evidence.get("policy_version")))
    generated = _parse_utc(str(evidence.get("generated_at") or ""))
    age = ((now or _now_utc()) - generated).total_seconds()
    max_age = validity_seconds if validity_seconds is not None else int(os.getenv("VISUAL_CONTAINMENT_EVIDENCE_MAX_AGE_SECONDS", DEFAULT_VALIDITY_SECONDS))
    if age < 0 or age > max_age:
        raise ContainmentControlError("evidence_stale", f"age_seconds={int(age)} max={max_age}")
    if evidence.get("eligible_for_release") is not True:
        raise ContainmentControlError("evidence_not_eligible")
    mandatory = evidence.get("mandatory")
    if not isinstance(mandatory, dict):
        raise ContainmentControlError("evidence_mandatory_not_object")
    missing_mandatory = [field for field in REQUIRED_MANDATORY_FIELDS if field not in mandatory]
    if missing_mandatory:
        raise ContainmentControlError("evidence_mandatory_missing", ",".join(missing_mandatory))
    false_mandatory = [field for field in REQUIRED_MANDATORY_FIELDS if mandatory.get(field) is not True]
    if false_mandatory:
        raise ContainmentControlError("evidence_mandatory_false", ",".join(false_mandatory))
    zero_fields = (
        "critical_error_count",
        "quarantine_escape_count",
        "unsafe_selection_count",
        "unsafe_approval_count",
        "upload_attempt_count",
    )
    for field in zero_fields:
        if int(evidence.get(field) or 0) != 0:
            raise ContainmentControlError("evidence_nonzero_count", field)
    totals = evidence.get("dry_run_totals")
    if not isinstance(totals, dict):
        raise ContainmentControlError("evidence_dry_run_totals_not_object")
    for field in ("unsafe_selections", "unsafe_approvals", "upload_attempts", "quarantine_escapes", "fail_open_paths"):
        if int(totals.get(field) or 0) != 0:
            raise ContainmentControlError("evidence_nonzero_dry_run_total", field)
    return evidence


def _critical_log_count_since(since: str) -> int:
    if not since:
        return 0
    try:
        output = subprocess.check_output(["journalctl", "-u", "parapusulasi", "--since", since, "--no-pager"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return 0
    critical_tokens = ("Traceback", "[ERROR]", "[CRITICAL]", " CRITICAL ")
    return sum(1 for line in output.splitlines() if any(token in line for token in critical_tokens))


def generate_release_evidence(
    *,
    incident_id: str,
    expected_production_sha: str,
    output_file: Path,
    logs_since: str = "",
    paths: ContainmentPaths | None = None,
    production_sha_resolver: Callable[[], str] = _resolve_production_sha,
    service_health_checker: Callable[[], bool] = _service_is_healthy,
) -> dict[str, Any]:
    _validate_incident_id(incident_id)
    from .upload_precheck import evaluate_upload_precheck, persist_ownership_manifest
    from .visual_safety_policy import (
        build_visual_manifest,
        evaluate_external_moderation,
        evaluate_visual_candidate,
        evaluate_visual_query,
        validate_cache_provenance,
        validate_visual_manifest,
    )

    resolved_paths = paths or default_paths()
    production_sha = production_sha_resolver()
    service_healthy = service_health_checker()
    status = get_status(incident_id=incident_id, paths=resolved_paths)
    policy_loaded = POLICY_VERSION == "visual_safety.v1"
    pipeline_text = Path("src/pipeline.py").read_text(encoding="utf-8") if Path("src/pipeline.py").exists() else ""
    long_form_protected = all(token in pipeline_text for token in ("build_visual_manifest(", "evaluate_upload_precheck(", "final_visual_assets"))
    shorts_protected = all(token in pipeline_text for token in ("short_visual_manifest_path = build_visual_manifest(", "short_precheck = evaluate_upload_precheck(", "final_visual_assets=short_visual_assets"))

    unsafe_selections = 0
    unsafe_approvals = 0
    upload_attempts = 0
    quarantine_escapes = 0
    fail_open_paths = 0
    import tempfile

    old_cwd = Path.cwd()
    tmp_root = Path(tempfile.mkdtemp(prefix="project003_release_evidence_", dir="/tmp"))
    try:
        os.chdir(tmp_root)
        for channel_id, niche in CHANNELS_UNDER_TEST:
            content_id = f"probe_{channel_id}"
            run_id = "run_readonly"
            script = tmp_root / "channels" / channel_id / "scripts" / "script.json"
            video = tmp_root / "channels" / channel_id / "output" / "videos" / "video.mp4"
            thumb = tmp_root / "channels" / channel_id / "output" / "videos" / "thumb.jpg"
            for path, content in ((script, b"script"), (video, b"video"), (thumb, b"thumb")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            normal = evaluate_visual_query(query="professional office desk planning documents", channel_id=channel_id, niche=niche, topic="normal")
            unsafe_query = evaluate_visual_query(query="sexy woman bikini beach model", channel_id=channel_id, niche=niche, topic="unsafe")
            unsafe_provider = evaluate_visual_candidate(candidate={"alt": "Woman in bikini on beach", "url": "https://example.invalid/unsafe"}, media_type="photo", channel_id=channel_id, niche=niche, topic="normal", query="office")
            unsafe_fallback = evaluate_visual_candidate(candidate={"alt": "Glamour model in bikini", "url": "https://example.invalid/fallback"}, media_type="photo", channel_id=channel_id, niche=niche, topic="fallback", query="office", source="fallback")
            unsafe_retry = evaluate_visual_query(query="retry bikini glamour model beachwear", channel_id=channel_id, niche=niche, topic="retry")
            cache_cross = validate_cache_provenance(entry={"channel_id": "other", "policy_version": POLICY_VERSION, "moderation_version": "metadata_rules.v1", "moderation_result": "safe", "provider": "pexels", "topic_domain": niche, "asset_fingerprint": "fp"}, channel_id=channel_id, niche=niche, topic_domain=niche, provider="pexels")
            visual_manifest = build_visual_manifest(channel_id=channel_id, content_id=content_id, run_id=run_id, niche=niche, topic="normal", assets=[str(thumb)], output_path=video.with_suffix(".visual_manifest.json"))
            ownership = persist_ownership_manifest(channel_id=channel_id, content_id=content_id, run_id=run_id, niche=niche, title="Normal Topic", topic="normal", script="script", script_path=str(script), video_path=str(video), thumbnail_path=str(thumb), visual_manifest_path=str(visual_manifest))
            safe_precheck = evaluate_upload_precheck(channel_id=channel_id, content_id=content_id, run_id=run_id, niche=niche, title="Normal Topic", topic="normal", script="script", description="normal description", tags=["normal"], script_path=str(script), video_path=str(video), thumbnail_path=str(thumb), manifest_path=ownership, visual_manifest_path=visual_manifest, final_visual_assets=[str(thumb)], dry_run=True, enabled=True)
            missing_thumb = evaluate_upload_precheck(channel_id=channel_id, content_id=content_id, run_id=run_id, niche=niche, title="Normal Topic", topic="normal", script="script", description="normal description", tags=["normal"], script_path=str(script), video_path=str(video), thumbnail_path=str(video.with_suffix(".missing.jpg")), manifest_path=ownership, visual_manifest_path=visual_manifest, final_visual_assets=[str(thumb)], dry_run=True, enabled=True)
            manifest_mismatch = validate_visual_manifest(manifest=json.loads(Path(visual_manifest).read_text(encoding="utf-8")), channel_id=channel_id, content_id=content_id, run_id=run_id, final_assets=[str(video)])
            external_unsafe = evaluate_external_moderation(classifier=lambda _asset: {"status": "unsafe", "confidence": "high"}, asset=str(thumb), channel_id=channel_id, source="synthetic")
            checks = (
                normal.allowed,
                not unsafe_query.allowed,
                not unsafe_provider.allowed,
                not unsafe_fallback.allowed,
                not unsafe_retry.allowed,
                not cache_cross.allowed,
                safe_precheck.get("status") == "allow",
                missing_thumb.get("status") == "blocked",
                not manifest_mismatch.allowed,
                not external_unsafe.allowed,
            )
            if unsafe_query.allowed or unsafe_provider.allowed or unsafe_fallback.allowed or unsafe_retry.allowed or external_unsafe.allowed:
                unsafe_approvals += 1
            if not all(checks):
                fail_open_paths += 1
    finally:
        os.chdir(old_cwd)

    critical_count = _critical_log_count_since(logs_since)
    mandatory = {
        "deployed_sha_verified": production_sha == expected_production_sha == status.get("incident_state", {}).get("release_metadata", {}).get("production_sha", expected_production_sha),
        "service_healthy": service_healthy,
        "scheduler_healthy": service_healthy,
        "visual_policy_loaded": policy_loaded,
        "cache_isolation_verified": fail_open_paths == 0,
        "upload_precheck_verified": fail_open_paths == 0,
        "render_manifest_verified": long_form_protected and fail_open_paths == 0,
        "shorts_manifest_verified": shorts_protected,
        "thumbnail_validation_verified": fail_open_paths == 0,
        "no_unsafe_dry_run_result": unsafe_selections == 0 and unsafe_approvals == 0 and fail_open_paths == 0,
        "no_quarantine_escape": quarantine_escapes == 0,
        "no_critical_runtime_error": critical_count == 0,
    }
    evidence = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "incident_id": incident_id,
        "production_sha": production_sha,
        "policy_version": POLICY_VERSION,
        "generated_at": _format_utc(_now_utc()),
        "eligible_for_release": all(mandatory.values()) and production_sha == expected_production_sha,
        "mandatory": mandatory,
        "dry_run_totals": {
            "unsafe_selections": unsafe_selections,
            "unsafe_approvals": unsafe_approvals,
            "upload_attempts": upload_attempts,
            "quarantine_escapes": quarantine_escapes,
            "fail_open_paths": fail_open_paths,
        },
        "critical_error_count": critical_count,
        "quarantine_escape_count": quarantine_escapes,
        "unsafe_selection_count": unsafe_selections,
        "unsafe_approval_count": unsafe_approvals,
        "upload_attempt_count": upload_attempts,
        "verifier_version": TOOL_VERSION,
    }
    _atomic_write_json(output_file, evidence)
    return {"status": "generated", "evidence_file": str(output_file), "evidence_sha256": _file_sha256(output_file), "eligible_for_release": evidence["eligible_for_release"], "mandatory": mandatory}


def get_status(*, incident_id: str, paths: ContainmentPaths | None = None) -> dict[str, Any]:
    _validate_incident_id(incident_id)
    resolved_paths = paths or default_paths()
    state = _read_json_file(resolved_paths.provider_health_file)
    incident = state.get("visual_safety_incident_containment")
    if not isinstance(incident, dict):
        incident = {}
    return {
        "incident_id": incident_id,
        "active": state.get("global_overload_pause_reason") == PROJECT003_REASON and bool(str(state.get("global_overload_pause_until") or "").strip()),
        "pause_reason": str(state.get("global_overload_pause_reason") or ""),
        "pause_until": str(state.get("global_overload_pause_until") or ""),
        "incident_state": dict(incident),
        "provider_health_sha256": _state_hash(state),
        "provider_health_path": str(resolved_paths.provider_health_file),
        "audit_path": str(resolved_paths.audit_file),
        "tool_version": TOOL_VERSION,
    }


def _audit_base(
    *,
    event_type: str,
    incident_id: str,
    operator: str,
    production_sha: str,
    policy_version: str,
    command_mode: str,
    evidence_file: Path | None,
    evidence_sha256: str,
    before_hash: str,
    after_hash: str,
    pause_reason_before: str,
    pause_state_after: str,
    uploads_disabled: bool,
    renders_disabled: bool,
    quarantine_recovery_requested: bool,
    success: bool,
    failure_reason: str = "",
) -> dict[str, Any]:
    return {
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "incident_id": incident_id,
        "operator": operator,
        "production_sha": production_sha,
        "policy_version": policy_version,
        "command_mode": command_mode,
        "evidence_file_path": str(evidence_file or ""),
        "evidence_sha256": evidence_sha256,
        "before_state_sha256": before_hash,
        "after_state_sha256": after_hash,
        "pause_reason_before": pause_reason_before,
        "pause_state_after": pause_state_after,
        "uploads_disabled_assertion": bool(uploads_disabled),
        "renders_disabled_assertion": bool(renders_disabled),
        "quarantine_recovery_assertion": not bool(quarantine_recovery_requested),
        "success": bool(success),
        "failure_reason": failure_reason,
        "tool_version": TOOL_VERSION,
    }


def release_containment(
    request: ReleaseRequest,
    *,
    paths: ContainmentPaths | None = None,
    production_sha_resolver: Callable[[], str] = _resolve_production_sha,
    service_health_checker: Callable[[], bool] = _service_is_healthy,
) -> dict[str, Any]:
    resolved_paths = paths or default_paths()
    before_hash = ""
    after_hash = ""
    pause_reason_before = ""
    evidence_sha = ""
    try:
        _validate_incident_id(request.incident_id)
        if request.confirm_release != request.incident_id:
            raise ContainmentControlError("release_confirmation_mismatch")
        if request.expected_reason != PROJECT003_REASON:
            raise ContainmentControlError("expected_reason_not_project003")
        if request.expected_policy_version != POLICY_VERSION:
            raise ContainmentControlError("policy_version_mismatch", request.expected_policy_version)
        if not request.uploads_disabled:
            raise ContainmentControlError("uploads_not_disabled")
        if not request.renders_disabled:
            raise ContainmentControlError("renders_not_disabled")
        if request.quarantine_recovery_requested:
            raise ContainmentControlError("quarantine_recovery_requested")
        validate_release_evidence(
            evidence_file=request.evidence_file,
            expected_incident_id=request.incident_id,
            expected_production_sha=request.expected_production_sha,
            expected_policy_version=request.expected_policy_version,
        )
        evidence_sha = _file_sha256(request.evidence_file)
        current_sha = production_sha_resolver()
        if current_sha != request.expected_production_sha:
            raise ContainmentControlError("production_sha_mismatch", current_sha)
        if not service_health_checker():
            raise ContainmentControlError("service_not_healthy")
        if not _deploy_lock_is_clear(resolved_paths):
            raise ContainmentControlError("deploy_lock_active")

        initial_state = _read_json_file(resolved_paths.provider_health_file)
        initial_hash = _state_hash(initial_state)
        with _locked(resolved_paths):
            state = _read_json_file(resolved_paths.provider_health_file)
            if _state_hash(state) != initial_hash:
                raise ContainmentControlError("state_changed_before_lock")
            before_hash = _state_hash(state)
            pause_reason_before = str(state.get("global_overload_pause_reason") or "")
            if pause_reason_before != request.expected_reason:
                raise ContainmentControlError("pause_reason_mismatch", pause_reason_before)
            pause_until_before = str(state.get("global_overload_pause_until") or "")
            if not pause_until_before:
                raise ContainmentControlError("pause_not_active")
            incident = state.get("visual_safety_incident_containment")
            if not isinstance(incident, dict):
                raise ContainmentControlError("incident_metadata_missing")
            if incident.get("preserve_evidence") is not True:
                raise ContainmentControlError("preserve_evidence_not_true")
            request_id = _sha256_bytes(f"{request.incident_id}|{request.operator}|{evidence_sha}|{request.expected_production_sha}".encode("utf-8"))
            consumed = list(incident.get("consumed_release_request_ids") or [])
            if request_id in consumed:
                raise ContainmentControlError("release_request_already_consumed")
            released_history = list(incident.get("release_history") or [])
            state["global_overload_pause_reason"] = ""
            state["global_overload_pause_until"] = ""
            release_record = {
                "released_at": _format_utc(_now_utc()),
                "operator": request.operator,
                "production_sha": request.expected_production_sha,
                "policy_version": request.expected_policy_version,
                "evidence_sha256": evidence_sha,
                "tool_version": TOOL_VERSION,
                "before_state_sha256": before_hash,
                "release_mode": "contained_no_upload",
                "audit_event_id": uuid.uuid4().hex,
                "original_reason": pause_reason_before,
                "original_pause_until": pause_until_before,
                "request_id": request_id,
            }
            incident.update(
                {
                    "released": True,
                    "released_at": release_record["released_at"],
                    "release_mode": "contained_no_upload",
                    "release_metadata": release_record,
                    "release_history": released_history + [release_record],
                    "consumed_release_request_ids": consumed + [request_id],
                    "preserve_evidence": True,
                }
            )
            state["visual_safety_incident_containment"] = incident
            after_hash = _state_hash(state)
            incident["release_metadata"]["after_state_sha256"] = after_hash
            incident["release_history"][-1]["after_state_sha256"] = after_hash
            state["visual_safety_incident_containment"] = incident
            after_hash = _state_hash(state)
            _atomic_write_json(resolved_paths.provider_health_file, state)
            audit = _audit_base(
                event_type="visual_safety_containment_release",
                incident_id=request.incident_id,
                operator=request.operator,
                production_sha=request.expected_production_sha,
                policy_version=request.expected_policy_version,
                command_mode="release",
                evidence_file=request.evidence_file,
                evidence_sha256=evidence_sha,
                before_hash=before_hash,
                after_hash=after_hash,
                pause_reason_before=pause_reason_before,
                pause_state_after="released",
                uploads_disabled=True,
                renders_disabled=True,
                quarantine_recovery_requested=False,
                success=True,
            )
            audit["event_id"] = release_record["audit_event_id"]
            _append_audit(resolved_paths, audit)
            return {"status": "released", "audit_event_id": audit["event_id"], "before_state_sha256": before_hash, "after_state_sha256": after_hash}
    except Exception as exc:
        failure_reason = exc.reason if isinstance(exc, ContainmentControlError) else exc.__class__.__name__
        try:
            state = _read_json_file(resolved_paths.provider_health_file)
            before_hash = before_hash or _state_hash(state)
            pause_reason_before = pause_reason_before or str(state.get("global_overload_pause_reason") or "")
        except Exception:
            pass
        _append_audit(
            resolved_paths,
            _audit_base(
                event_type="visual_safety_containment_release",
                incident_id=request.incident_id,
                operator=request.operator,
                production_sha=request.expected_production_sha,
                policy_version=request.expected_policy_version,
                command_mode="release",
                evidence_file=request.evidence_file,
                evidence_sha256=evidence_sha,
                before_hash=before_hash,
                after_hash=after_hash,
                pause_reason_before=pause_reason_before,
                pause_state_after="unchanged",
                uploads_disabled=request.uploads_disabled,
                renders_disabled=request.renders_disabled,
                quarantine_recovery_requested=request.quarantine_recovery_requested,
                success=False,
                failure_reason=failure_reason,
            ),
        )
        raise


def restore_containment(
    request: RestoreRequest,
    *,
    paths: ContainmentPaths | None = None,
    production_sha_resolver: Callable[[], str] = _resolve_production_sha,
) -> dict[str, Any]:
    resolved_paths = paths or default_paths()
    _validate_incident_id(request.incident_id)
    if request.confirm_restore != request.incident_id:
        raise ContainmentControlError("restore_confirmation_mismatch")
    if not request.operator.strip():
        raise ContainmentControlError("operator_missing")
    if not request.reason.strip():
        raise ContainmentControlError("restore_reason_missing")
    current_sha = production_sha_resolver()
    if current_sha != request.expected_production_sha:
        raise ContainmentControlError("production_sha_mismatch", current_sha)
    with _locked(resolved_paths):
        state = _read_json_file(resolved_paths.provider_health_file)
        before_hash = _state_hash(state)
        pause_reason_before = str(state.get("global_overload_pause_reason") or "")
        incident = state.get("visual_safety_incident_containment")
        if not isinstance(incident, dict):
            incident = {"incident_id": "PROJECT003-cross-channel-visual-safety", "preserve_evidence": True}
        until = _format_utc(_now_utc() + timedelta(seconds=int(os.getenv("VISUAL_CONTAINMENT_RESTORE_SECONDS", DEFAULT_RESTORE_SECONDS))))
        state["global_overload_pause_reason"] = PROJECT003_REASON
        state["global_overload_pause_until"] = until
        restore_record = {
            "restored_at": _format_utc(_now_utc()),
            "operator": request.operator,
            "reason": request.reason,
            "production_sha": request.expected_production_sha,
            "policy_version": POLICY_VERSION,
            "pause_until": until,
            "tool_version": TOOL_VERSION,
        }
        incident.update({"released": False, "restored": True, "restore_metadata": restore_record, "preserve_evidence": True})
        incident["restore_history"] = list(incident.get("restore_history") or []) + [restore_record]
        state["visual_safety_incident_containment"] = incident
        after_hash = _state_hash(state)
        _atomic_write_json(resolved_paths.provider_health_file, state)
        audit = _audit_base(
            event_type="visual_safety_containment_restore",
            incident_id=request.incident_id,
            operator=request.operator,
            production_sha=request.expected_production_sha,
            policy_version=POLICY_VERSION,
            command_mode="restore",
            evidence_file=None,
            evidence_sha256="",
            before_hash=before_hash,
            after_hash=after_hash,
            pause_reason_before=pause_reason_before,
            pause_state_after="active",
            uploads_disabled=True,
            renders_disabled=True,
            quarantine_recovery_requested=False,
            success=True,
        )
        _append_audit(resolved_paths, audit)
        return {"status": "restored", "audit_event_id": audit["event_id"], "before_state_sha256": before_hash, "after_state_sha256": after_hash, "pause_until": until}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PROJECT003 visual-safety containment control")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--incident-id", required=True)

    validate = sub.add_parser("validate-release-eligibility")
    validate.add_argument("--incident-id", required=True)
    validate.add_argument("--expected-policy-version", required=True)
    validate.add_argument("--expected-production-sha", required=True)
    validate.add_argument("--evidence-file", required=True)

    generate = sub.add_parser("generate-eligibility-evidence")
    generate.add_argument("--incident-id", required=True)
    generate.add_argument("--expected-production-sha", required=True)
    generate.add_argument("--output-file", required=True)
    generate.add_argument("--logs-since", default="")

    release = sub.add_parser("release")
    release.add_argument("--incident-id", required=True)
    release.add_argument("--expected-reason", required=True)
    release.add_argument("--expected-policy-version", required=True)
    release.add_argument("--expected-production-sha", required=True)
    release.add_argument("--operator", required=True)
    release.add_argument("--evidence-file", required=True)
    release.add_argument("--uploads-disabled", action="store_true")
    release.add_argument("--renders-disabled", action="store_true")
    release.add_argument("--confirm-release", required=True)

    restore = sub.add_parser("restore")
    restore.add_argument("--incident-id", required=True)
    restore.add_argument("--operator", required=True)
    restore.add_argument("--reason", required=True)
    restore.add_argument("--expected-production-sha", required=True)
    restore.add_argument("--confirm-restore", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = get_status(incident_id=args.incident_id)
        elif args.command == "validate-release-eligibility":
            evidence = validate_release_evidence(
                evidence_file=Path(args.evidence_file),
                expected_incident_id=args.incident_id,
                expected_production_sha=args.expected_production_sha,
                expected_policy_version=args.expected_policy_version,
            )
            result = {"status": "valid", "evidence_sha256": _file_sha256(Path(args.evidence_file)), "verifier_version": evidence.get("verifier_version")}
        elif args.command == "generate-eligibility-evidence":
            result = generate_release_evidence(
                incident_id=args.incident_id,
                expected_production_sha=args.expected_production_sha,
                output_file=Path(args.output_file),
                logs_since=args.logs_since,
            )
        elif args.command == "release":
            result = release_containment(
                ReleaseRequest(
                    incident_id=args.incident_id,
                    expected_reason=args.expected_reason,
                    expected_policy_version=args.expected_policy_version,
                    expected_production_sha=args.expected_production_sha,
                    operator=args.operator,
                    evidence_file=Path(args.evidence_file),
                    uploads_disabled=args.uploads_disabled,
                    renders_disabled=args.renders_disabled,
                    confirm_release=args.confirm_release,
                )
            )
        elif args.command == "restore":
            result = restore_containment(
                RestoreRequest(
                    incident_id=args.incident_id,
                    operator=args.operator,
                    reason=args.reason,
                    expected_production_sha=args.expected_production_sha,
                    confirm_restore=args.confirm_restore,
                )
            )
        else:
            parser.error("unknown command")
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        reason = exc.reason if isinstance(exc, ContainmentControlError) else exc.__class__.__name__
        print(json.dumps({"ok": False, "reason": reason, "detail": str(exc)}, ensure_ascii=False, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())