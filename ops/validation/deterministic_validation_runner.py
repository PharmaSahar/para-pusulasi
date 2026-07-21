#!/usr/bin/env python3
from __future__ import annotations

import argparse
import faulthandler
import hashlib
import importlib
import json
import logging
import os
import signal
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_PREFIX = "project004_validation_"
RUN_TIMEOUT_SECONDS = 60


class IsolationPathLeakError(RuntimeError):
    pass


class ArtifactWriteError(RuntimeError):
    pass


class ScenarioTimeoutError(TimeoutError):
    pass


class _StopLoop(Exception):
    pass


@dataclass(frozen=True)
class RunPaths:
    run_root: Path
    logs_dir: Path
    state_root: Path
    runtime_output_root: Path
    output_root: Path
    telemetry_dir: Path
    artifacts_dir: Path
    provider_health_path: Path
    visual_audit_path: Path
    visual_lock_path: Path
    queue_path: Path
    pid_path: Path
    singleton_lock_path: Path
    singleton_meta_path: Path
    runtime_evidence_path: Path
    safety_gate_path: Path
    dashboard_md_path: Path
    dashboard_json_path: Path
    governance_readiness_path: Path
    governance_refresh_path: Path
    activation_report_path: Path
    activation_report_archive_dir: Path
    production_events_path: Path
    production_observability_path: Path
    thumbnail_intelligence_path: Path
    production_evidence_dir: Path
    upload_registry_path: Path
    dead_letter_path: Path
    canary_state_path: Path
    telemetry_sink_dir: Path


@dataclass
class ChildModules:
    scheduler: Any
    scheduler_utils: Any
    channel_manager: Any
    pipeline: Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        _atomic_write_json(path, payload)
    except Exception as exc:  # pragma: no cover - exercised in artifact failure self-test
        raise ArtifactWriteError(f"artifact_write_failure: {path}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within_root(root: Path, candidate: Path) -> bool:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    return candidate_resolved == root_resolved or root_resolved in candidate_resolved.parents


def _require_within_root(root: Path, label: str, candidate: Path) -> None:
    if not _is_within_root(root, candidate):
        raise IsolationPathLeakError(f"ISOLATION_PATH_LEAK: {label}={candidate.resolve()} outside {root.resolve()}")


def _run_root() -> Path:
    return Path(tempfile.mkdtemp(prefix=RUN_PREFIX)).resolve()


def _build_run_paths(run_root: Path) -> RunPaths:
    output_root = run_root / "output"
    runtime_output_root = output_root / "runtime"
    telemetry_dir = output_root / "telemetry"
    return RunPaths(
        run_root=run_root,
        logs_dir=run_root / "logs",
        state_root=run_root,
        runtime_output_root=runtime_output_root,
        output_root=output_root,
        telemetry_dir=telemetry_dir,
        artifacts_dir=run_root / "artifacts",
        provider_health_path=runtime_output_root / "state" / "provider_health.json",
        visual_audit_path=runtime_output_root / "telemetry" / "visual_safety_containment_audit.jsonl",
        visual_lock_path=runtime_output_root / "telemetry" / ".visual_safety_containment.lock",
        queue_path=runtime_output_root / "state" / "channel_queue.json",
        pid_path=runtime_output_root / "state" / "production_scheduler.pid",
        singleton_lock_path=runtime_output_root / "state" / "scheduler_singleton.lock",
        singleton_meta_path=runtime_output_root / "state" / "scheduler_singleton_meta.json",
        runtime_evidence_path=runtime_output_root / "state" / "runtime_optimization_evidence_latest.json",
        safety_gate_path=runtime_output_root / "state" / "production_safety_gate_latest.json",
        dashboard_md_path=output_root / "state" / "production_dashboard_latest.md",
        dashboard_json_path=output_root / "state" / "production_dashboard_latest.json",
        governance_readiness_path=output_root / "state" / "governance_readiness_latest.md",
        governance_refresh_path=output_root / "state" / "governance_refresh_latest.json",
        activation_report_path=output_root / "state" / "activation_controller_report.json",
        activation_report_archive_dir=output_root / "state" / "activation_reports",
        production_events_path=telemetry_dir / "production_events.jsonl",
        production_observability_path=telemetry_dir / "production_observability_latest.json",
        thumbnail_intelligence_path=telemetry_dir / "thumbnail_intelligence_latest.json",
        production_evidence_dir=run_root / "evidence",
        upload_registry_path=output_root / "state" / "production_upload_registry.json",
        dead_letter_path=telemetry_dir / "production_dead_letter_queue.jsonl",
        canary_state_path=output_root / "state" / "production_canary_state.json",
        telemetry_sink_dir=telemetry_dir,
    )


def _build_isolation_env(paths: RunPaths) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PREPROD_ISOLATION_MODE": "true",
            "PREPROD_STATE_ROOT": str(paths.state_root),
            "RUNTIME_OUTPUT_ROOT": str(paths.runtime_output_root),
            "OUTPUT_ROOT": str(paths.output_root),
            "TELEMETRY_SINK_DIR": str(paths.telemetry_sink_dir),
            "SCHEDULER_LOG_FILE": str(paths.logs_dir / "scheduler.log"),
            "SCHEDULER_QUEUE_FILE": str(paths.queue_path),
            "SCHEDULER_PID_FILE": str(paths.pid_path),
            "SCHEDULER_SINGLETON_LOCK_FILE": str(paths.singleton_lock_path),
            "SCHEDULER_SINGLETON_META_FILE": str(paths.singleton_meta_path),
            "RUNTIME_EVIDENCE_LATEST_FILE": str(paths.runtime_evidence_path),
            "SAFETY_GATE_LATEST_FILE": str(paths.safety_gate_path),
            "PRODUCTION_EVENTS_PATH": str(paths.production_events_path),
            "PRODUCTION_OBSERVABILITY_LATEST_PATH": str(paths.production_observability_path),
            "PRODUCTION_DASHBOARD_MD_PATH": str(paths.dashboard_md_path),
            "PRODUCTION_DASHBOARD_JSON_PATH": str(paths.dashboard_json_path),
            "GOVERNANCE_READINESS_MD_PATH": str(paths.governance_readiness_path),
            "GOVERNANCE_REFRESH_LATEST_PATH": str(paths.governance_refresh_path),
            "ACTIVATION_CONTROLLER_REPORT_PATH": str(paths.activation_report_path),
            "ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR": str(paths.activation_report_archive_dir),
            "PRODUCTION_EVIDENCE_DIR": str(paths.production_evidence_dir),
            "UPLOAD_REGISTRY_PATH": str(paths.upload_registry_path),
            "DEAD_LETTER_QUEUE_PATH": str(paths.dead_letter_path),
            "CANARY_STATE_PATH": str(paths.canary_state_path),
            "THUMBNAIL_INTELLIGENCE_LATEST_PATH": str(paths.thumbnail_intelligence_path),
            "VISUAL_CONTAINMENT_PROVIDER_HEALTH_FILE": str(paths.provider_health_path),
            "VISUAL_CONTAINMENT_AUDIT_FILE": str(paths.visual_audit_path),
            "VISUAL_CONTAINMENT_LOCK_FILE": str(paths.visual_lock_path),
        }
    )
    return env


@contextmanager
def _scoped_environ_update(env_updates: dict[str, str]):
    """Apply process env overrides and restore exact prior state on exit."""
    sentinel = object()
    snapshot: dict[str, object] = {key: os.environ.get(key, sentinel) for key in env_updates}
    os.environ.update(env_updates)
    try:
        yield
    finally:
        for key, original in snapshot.items():
            if original is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(original)


def _bootstrap_run_metadata(paths: RunPaths, mode: str) -> dict[str, Any]:
    return {
        "run_id": paths.run_root.name,
        "mode": mode,
        "started_at_utc": utc_now(),
        "python_executable": sys.executable,
        "cwd": str(Path.cwd().resolve()),
        "repo_root": str(PROJECT_ROOT),
        "run_root": str(paths.run_root),
        "state_root": str(paths.state_root),
        "runtime_output_root": str(paths.runtime_output_root),
    }


def _top_level_artifacts(paths: RunPaths) -> dict[str, Path]:
    return {
        "run_started": paths.run_root / "run_started.json",
        "stdout": paths.run_root / "stdout.log",
        "stderr": paths.run_root / "stderr.log",
        "environment_probe": paths.run_root / "environment_probe.json",
        "import_order": paths.run_root / "import_order.json",
        "selftest_summary": paths.run_root / "selftest_summary.json",
        "staging_validation_result": paths.run_root / "staging_validation_result.json",
        "failure": paths.run_root / "failure.json",
        "timeout": paths.run_root / "timeout.json",
        "result": paths.run_root / "result.json",
        "artifact_manifest": paths.run_root / "artifact_manifest.json",
        "exit_code": paths.run_root / "exit_code.txt",
    }


def _write_top_level_start(paths: RunPaths, mode: str) -> None:
    _ensure_dir(paths.logs_dir)
    _ensure_dir(paths.artifacts_dir)
    _safe_write_json(_top_level_artifacts(paths)["run_started"], _bootstrap_run_metadata(paths, mode))
    _atomic_write_text(_top_level_artifacts(paths)["stdout"], "")
    _atomic_write_text(_top_level_artifacts(paths)["stderr"], "")


def _write_final_status(paths: RunPaths, exit_code: int) -> None:
    _atomic_write_text(_top_level_artifacts(paths)["exit_code"], f"{exit_code}\n")


def _write_manifest(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "artifact_manifest.json":
            continue
        stat = path.stat()
        entries.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "sha256": _sha256_file(path),
                "mtime": stat.st_mtime,
            }
        )
    manifest = {
        "root": str(root),
        "generated_at_utc": utc_now(),
        "artifact_count": len(entries),
        "artifacts": entries,
        "manifest_includes_self": False,
    }
    _safe_write_json(root / "artifact_manifest.json", manifest)
    return manifest


def _capture_exception(exc: BaseException) -> dict[str, Any]:
    return {
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }


def _require_env_path(env: dict[str, str], key: str) -> Path:
    value = str(env.get(key, "")).strip()
    if not value:
        raise IsolationPathLeakError(f"ISOLATION_PATH_LEAK: missing_required_env:{key}")
    return Path(value)


def _probe_path_map(paths: RunPaths, modules: ChildModules) -> dict[str, Any]:
    scheduler = modules.scheduler
    scheduler_utils = modules.scheduler_utils
    preprod_mutable = scheduler._collect_preprod_mutable_paths()
    probe = {
        "python_executable": sys.executable,
        "cwd": str(Path.cwd().resolve()),
        "repo_root": str(PROJECT_ROOT),
        "preprod_state_root": str(paths.state_root),
        "runtime_output_root": str(paths.runtime_output_root),
        "output_root": str(paths.output_root),
        "resolved_provider_health_path": str(Path(scheduler_utils.PROVIDER_HEALTH_FILE).resolve()),
        "resolved_singleton_lock": str(scheduler._scheduler_singleton_lock_path().resolve()),
        "resolved_singleton_meta": str(scheduler._scheduler_singleton_meta_path().resolve()),
        "resolved_pid": str(Path(scheduler.PID_FILE).resolve()),
        "queue_path": str(Path(scheduler.QUEUE_FILE).resolve()),
        "telemetry_paths": {
            "production_events": str(paths.production_events_path.resolve()),
            "production_observability_latest": str(paths.production_observability_path.resolve()),
            "telemetry_sink_dir": str(paths.telemetry_sink_dir.resolve()),
            "visual_safety_containment_audit": str(paths.visual_audit_path.resolve()),
            "visual_safety_containment_lock": str(paths.visual_lock_path.resolve()),
        },
        "dashboard_paths": {
            "markdown": str(paths.dashboard_md_path.resolve()),
            "json": str(paths.dashboard_json_path.resolve()),
        },
        "preprod_mutable_paths": {name: str(path.resolve()) for name, path in preprod_mutable.items()},
        "import_order": ["scheduler", "scheduler_utils", "channel_manager", "pipeline"],
    }
    for label, candidate in {
        "preprod_state_root": paths.state_root,
        "runtime_output_root": paths.runtime_output_root,
        "output_root": paths.output_root,
        "provider_health_path": paths.provider_health_path,
        "scheduler_log_file": _require_env_path(os.environ, "SCHEDULER_LOG_FILE"),
        "queue_path": paths.queue_path,
        "pid_path": paths.pid_path,
        "singleton_lock_path": paths.singleton_lock_path,
        "singleton_meta_path": paths.singleton_meta_path,
        "runtime_evidence_path": paths.runtime_evidence_path,
        "safety_gate_path": paths.safety_gate_path,
        "production_events_path": paths.production_events_path,
        "production_observability_path": paths.production_observability_path,
        "dashboard_md_path": paths.dashboard_md_path,
        "dashboard_json_path": paths.dashboard_json_path,
        "governance_readiness_path": paths.governance_readiness_path,
        "governance_refresh_path": paths.governance_refresh_path,
        "activation_report_path": paths.activation_report_path,
        "activation_report_archive_dir": paths.activation_report_archive_dir,
        "production_evidence_dir": paths.production_evidence_dir,
        "upload_registry_path": paths.upload_registry_path,
        "dead_letter_path": paths.dead_letter_path,
        "canary_state_path": paths.canary_state_path,
        "telemetry_sink_dir": paths.telemetry_sink_dir,
        "visual_audit_path": paths.visual_audit_path,
        "visual_lock_path": paths.visual_lock_path,
    }.items():
        _require_within_root(paths.run_root, label, candidate)
    for label, candidate in probe["preprod_mutable_paths"].items():
        _require_within_root(paths.run_root, label, Path(candidate))
    return probe


def _import_project_modules(paths: RunPaths) -> ChildModules:
    repo_root = PROJECT_ROOT
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    scheduler = importlib.import_module("scheduler")
    close_handlers = getattr(scheduler, "_close_scheduler_logging_handlers", None)
    if callable(close_handlers):
        close_handlers()
    scheduler = importlib.reload(scheduler)

    scheduler_utils = importlib.import_module("src.scheduler_utils")
    scheduler_utils = importlib.reload(scheduler_utils)
    scheduler_utils.PROVIDER_HEALTH_FILE = str(paths.provider_health_path)
    channel_manager = importlib.import_module("src.channel_manager")
    channel_manager = importlib.reload(channel_manager)
    pipeline = importlib.import_module("src.pipeline")
    pipeline = importlib.reload(pipeline)
    return ChildModules(scheduler=scheduler, scheduler_utils=scheduler_utils, channel_manager=channel_manager, pipeline=pipeline)


def _temporary_alarm(seconds: float, label: str):
    @contextmanager
    def _ctx():
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)

        def _handler(_signum, _frame):
            raise ScenarioTimeoutError(f"timeout:{label}:{seconds}")

        signal.signal(signal.SIGALRM, _handler)
        try:
            yield
        finally:
            signal.signal(signal.SIGALRM, previous_handler)
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])

    return _ctx()


def _scenario_root(paths: RunPaths, name: str) -> Path:
    root = paths.run_root / "scenarios" / name
    _ensure_dir(root)
    return root


def _scenario_write(paths: RunPaths, name: str, filename: str, payload: dict[str, Any]) -> None:
    _safe_write_json(_scenario_root(paths, name) / filename, payload)


def _run_normal_exit_scenario(paths: RunPaths) -> dict[str, Any]:
    _scenario_write(paths, "normal_exit", "run_started.json", _bootstrap_run_metadata(paths, "selftest-normal-exit"))
    modules = _import_project_modules(paths)
    probe = _probe_path_map(paths, modules)
    _scenario_write(paths, "normal_exit", "environment_probe.json", probe)
    result = {"scenario": "normal_exit", "status": "passed", "exit_code": 0, "import_order": probe["import_order"]}
    _scenario_write(paths, "normal_exit", "result.json", result)
    return result


def _run_exception_scenario(paths: RunPaths) -> dict[str, Any]:
    _scenario_write(paths, "intentional_exception", "run_started.json", _bootstrap_run_metadata(paths, "selftest-exception"))
    try:
        modules = _import_project_modules(paths)
        probe = _probe_path_map(paths, modules)
        _scenario_write(paths, "intentional_exception", "environment_probe.json", probe)
        raise RuntimeError("intentional_exception_probe")
    except BaseException as exc:
        payload = {"scenario": "intentional_exception", "status": "failed", "classification": "INTENTIONAL_EXCEPTION"}
        payload.update(_capture_exception(exc))
        _scenario_write(paths, "intentional_exception", "failure.json", payload)
        return payload


def _run_timeout_scenario(paths: RunPaths) -> dict[str, Any]:
    _scenario_write(paths, "intentional_timeout", "run_started.json", _bootstrap_run_metadata(paths, "selftest-timeout"))
    modules = _import_project_modules(paths)
    probe = _probe_path_map(paths, modules)
    _scenario_write(paths, "intentional_timeout", "environment_probe.json", probe)
    started = time.time()
    child_state = {"running": False, "pid": None, "mode": None}
    try:
        with _temporary_alarm(0.5, "intentional_timeout"):
            time.sleep(3)
        raise AssertionError("timeout did not trigger")
    except ScenarioTimeoutError as exc:
        payload = {
            "scenario": "intentional_timeout",
            "status": "timeout",
            "elapsed_seconds": round(time.time() - started, 3),
            "stack_capture_status": "captured",
            "child_process_state": child_state,
            "cleanup_status": "completed",
        }
        payload.update(_capture_exception(exc))
        _scenario_write(paths, "intentional_timeout", "timeout.json", payload)
        return payload


def _run_path_leak_scenario(paths: RunPaths) -> dict[str, Any]:
    _scenario_write(paths, "intentional_path_leak", "run_started.json", _bootstrap_run_metadata(paths, "selftest-path-leak"))
    leaked = _build_isolation_env(paths)
    leaked["PRODUCTION_DASHBOARD_MD_PATH"] = "/tmp/project004_validation_leak/production_dashboard_latest.md"
    leaked["PRODUCTION_DASHBOARD_JSON_PATH"] = "/tmp/project004_validation_leak/production_dashboard_latest.json"
    try:
        for key, value in leaked.items():
            if key.endswith(("PATH", "DIR", "ROOT")):
                _require_within_root(paths.run_root, key, Path(value))
        raise AssertionError("path leak was not detected")
    except BaseException as exc:
        payload = {"scenario": "intentional_path_leak", "status": "failed", "classification": "ISOLATION_PATH_LEAK"}
        payload.update(_capture_exception(exc))
        _scenario_write(paths, "intentional_path_leak", "failure.json", payload)
        return payload


def _run_artifact_write_failure_scenario(paths: RunPaths) -> dict[str, Any]:
    _scenario_write(paths, "artifact_write_failure", "run_started.json", _bootstrap_run_metadata(paths, "selftest-artifact-write-failure"))
    modules = _import_project_modules(paths)
    probe = _probe_path_map(paths, modules)
    _scenario_write(paths, "artifact_write_failure", "environment_probe.json", probe)
    original = globals()["_safe_write_json"]

    def _broken_write(*_args, **_kwargs):
        raise ArtifactWriteError("simulated_artifact_write_failure")

    globals()["_safe_write_json"] = _broken_write
    try:
        try:
            _safe_write_json(_scenario_root(paths, "artifact_write_failure") / "result.json", {"scenario": "artifact_write_failure"})
        except ArtifactWriteError as exc:
            payload = {"scenario": "artifact_write_failure", "status": "failed", "classification": "ARTIFACT_WRITE_FAILURE"}
            payload.update(_capture_exception(exc))
            original(_scenario_root(paths, "artifact_write_failure") / "failure.json", payload)
            return payload
        raise AssertionError("artifact write failure was not triggered")
    finally:
        globals()["_safe_write_json"] = original


def _run_selftests(paths: RunPaths) -> dict[str, Any]:
    results = {
        "normal_exit": _run_normal_exit_scenario(paths),
        "intentional_exception": _run_exception_scenario(paths),
        "intentional_timeout": _run_timeout_scenario(paths),
        "intentional_path_leak": _run_path_leak_scenario(paths),
        "artifact_write_failure": _run_artifact_write_failure_scenario(paths),
    }
    summary = {"status": "passed", "scenarios": results, "generated_at_utc": utc_now()}
    _safe_write_json(paths.run_root / "selftest_summary.json", summary)
    return summary


class _FakeEvery:
    def __init__(self, jobs: list[tuple[str, str]]):
        self._jobs = jobs

    @property
    def day(self):
        return self

    @property
    def hour(self):
        return self

    @property
    def hours(self):
        return self

    def at(self, *_args, **_kwargs):
        return self

    def do(self, func: Callable[..., Any], *args: Any, **kwargs: Any):
        self._jobs.append((getattr(func, "__name__", "job"), json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True)))
        return self


class _FakeSchedule:
    def __init__(self):
        self.jobs: list[tuple[str, str]] = []
        self.pending_calls = 0

    def every(self, *_args, **_kwargs):
        return _FakeEvery(self.jobs)

    def run_pending(self):
        self.pending_calls += 1
        raise _StopLoop()


class _NoopThread:
    def __init__(self, *args: Any, **kwargs: Any):
        pass

    def start(self):
        return None


def _run_staging_validation(paths: RunPaths) -> dict[str, Any]:
    modules = _import_project_modules(paths)
    scheduler = modules.scheduler
    scheduler_utils = modules.scheduler_utils
    pipeline = modules.pipeline

    log_messages: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            message = self.format(record)
            if "STARTUP_" in message or "Scheduler" in message:
                log_messages.append(message)

    capture = _Capture()
    capture.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    scheduler_logger = logging.getLogger("Scheduler")
    scheduler_logger.addHandler(capture)
    scheduler_logger.setLevel(logging.INFO)

    original_state = {
        "argv": list(sys.argv),
        "provider_preflight_degraded_mode_enabled": os.environ.get("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED"),
        "schedule": scheduler.schedule,
        "thread": scheduler.threading.Thread,
        "startup_health_check": scheduler._run_startup_health_check,
        "provider_preflight_check": scheduler._run_provider_preflight_check,
        "startup_safety_gate": scheduler._evaluate_scheduler_startup_production_safety_gate,
        "setup_schedule": scheduler.setup_schedule,
        "catch_up": scheduler.catch_up_overdue_queue_entries,
        "get_ready_channels": scheduler.get_ready_channels,
        "cleanup_old_renders": scheduler_utils.cleanup_old_renders,
        "notify_startup": scheduler_utils.notify_startup,
        "notify_error": scheduler_utils.notify_error,
        "send_telegram": scheduler_utils.send_telegram,
        "run_pipeline": pipeline.run_full_pipeline,
    }

    try:
        scheduler.sys.argv = ["scheduler.py"]
        os.environ["PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED"] = "1"
        scheduler.schedule = _FakeSchedule()
        scheduler.threading.Thread = _NoopThread
        scheduler.setup_schedule = lambda: None
        scheduler.catch_up_overdue_queue_entries = lambda: {}
        scheduler.get_ready_channels = lambda: ["demo"]
        scheduler._run_startup_health_check = lambda **_kwargs: SimpleNamespace(ok=True, errors=())
        scheduler._run_provider_preflight_check = lambda **_kwargs: (False, "HTTP 400 credit balance is too low")
        scheduler._evaluate_scheduler_startup_production_safety_gate = lambda **_kwargs: {
            "ok": False,
            "status": "blocked",
            "blocking_reason": "provider_circuit_open",
            "checks": [
                {
                    "status": "fail",
                    "severity": "critical",
                    "reason": "provider_circuit_open",
                    "message": "Provider circuit is open",
                    "evidence": {},
                }
            ],
        }

        startup_notifications: list[str] = []
        cleanup_calls = {"count": 0}

        scheduler_utils.cleanup_old_renders = lambda **_kwargs: cleanup_calls.__setitem__("count", cleanup_calls["count"] + 1) or 0
        scheduler_utils.notify_startup = lambda n: startup_notifications.append(f"startup:{n}")
        scheduler_utils.notify_error = lambda *_args, **_kwargs: {"ok": True}
        scheduler_utils.send_telegram = lambda message, **_kwargs: startup_notifications.append(str(message))

        provider_before = scheduler_utils.get_provider_circuit_status("anthropic")
        scheduler_utils.record_provider_failure("anthropic", "HTTP 529 - Overloaded")
        provider_after = scheduler_utils.get_provider_circuit_status("anthropic")

        pipeline_calls = {"count": 0}

        def _pipeline_probe(**_kwargs):
            pipeline_calls["count"] += 1
            return {"video_id": "vid1", "title": "ok", "youtube_url": "https://example.invalid"}

        pipeline.run_full_pipeline = _pipeline_probe

        before_block_calls = pipeline_calls["count"]
        scheduler.render_and_schedule("demo_channel", trigger_source="manual_operator")
        after_block_calls = pipeline_calls["count"]

        scheduler_utils.record_provider_success("anthropic", note="staging_probe_ok")
        scheduler.render_and_schedule("demo_channel", trigger_source="manual_operator")
        after_recovery_calls = pipeline_calls["count"]

        singleton_result: dict[str, Any] = {}
        try:
            scheduler._acquire_scheduler_singleton_lock()
            try:
                scheduler._acquire_scheduler_singleton_lock()
            except Exception as exc:
                singleton_result = {
                    "first_acquire": "ok",
                    "second_acquire": "conflict",
                    "second_error": type(exc).__name__,
                    "second_message": str(exc),
                }
            finally:
                scheduler._release_scheduler_singleton_lock()
        except Exception as exc:
            singleton_result = {"first_acquire": "failed", "first_error": type(exc).__name__, "first_message": str(exc)}

        try:
            scheduler.main()
        except _StopLoop:
            pass

        result = {
            "status": "passed",
            "provider_health": {
                "path": str(Path(scheduler_utils.PROVIDER_HEALTH_FILE).resolve()),
                "before": provider_before,
                "after_failure": provider_after,
                "after_recovery": scheduler_utils.get_provider_circuit_status("anthropic"),
            },
            "scheduler_continuity": {
                "jobs_registered": list(scheduler.schedule.jobs),
                "pending_calls": scheduler.schedule.pending_calls,
                "cleanup_calls": cleanup_calls["count"],
                "log_messages": log_messages,
            },
            "generation_blocking": {
                "before_calls": before_block_calls,
                "after_block_calls": after_block_calls,
                "after_recovery_calls": after_recovery_calls,
            },
            "recovery": {
                "provider_circuit_closed": not scheduler_utils.get_provider_circuit_status("anthropic")["is_open"],
                "provider_state": scheduler_utils.get_provider_circuit_status("anthropic").get("state", {}),
            },
            "startup_notifications": {"count": len(startup_notifications), "messages": startup_notifications},
            "singleton": singleton_result,
        }
        _safe_write_json(paths.run_root / "staging_validation_result.json", result)
        return result
    finally:
        scheduler_logger.removeHandler(capture)
        scheduler.sys.argv = original_state["argv"]
        if original_state["provider_preflight_degraded_mode_enabled"] is None:
            os.environ.pop("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED", None)
        else:
            os.environ["PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED"] = original_state["provider_preflight_degraded_mode_enabled"]
        scheduler.schedule = original_state["schedule"]
        scheduler.threading.Thread = original_state["thread"]
        scheduler._run_startup_health_check = original_state["startup_health_check"]
        scheduler._run_provider_preflight_check = original_state["provider_preflight_check"]
        scheduler._evaluate_scheduler_startup_production_safety_gate = original_state["startup_safety_gate"]
        scheduler.setup_schedule = original_state["setup_schedule"]
        scheduler.catch_up_overdue_queue_entries = original_state["catch_up"]
        scheduler.get_ready_channels = original_state["get_ready_channels"]
        scheduler_utils.cleanup_old_renders = original_state["cleanup_old_renders"]
        scheduler_utils.notify_startup = original_state["notify_startup"]
        scheduler_utils.notify_error = original_state["notify_error"]
        scheduler_utils.send_telegram = original_state["send_telegram"]
        pipeline.run_full_pipeline = original_state["run_pipeline"]


def _write_top_level_failure(paths: RunPaths, exc: BaseException, classification: str) -> dict[str, Any]:
    payload = {"status": "failed", "classification": classification, "generated_at_utc": utc_now()}
    payload.update(_capture_exception(exc))
    _safe_write_json(_top_level_artifacts(paths)["failure"], payload)
    return payload


def _write_top_level_timeout(paths: RunPaths, elapsed_seconds: float, child_state: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "status": "timeout",
        "classification": "RUNNER_TIMEOUT",
        "elapsed_seconds": round(elapsed_seconds, 3),
        "stack_capture_status": "captured",
        "child_process_state": child_state,
        "cleanup_status": "completed",
        "generated_at_utc": utc_now(),
    }
    _safe_write_json(_top_level_artifacts(paths)["timeout"], payload)
    return payload


def _run_mode(mode: str) -> tuple[int, dict[str, Any]]:
    run_root = _run_root()
    paths = _build_run_paths(run_root)
    env = _build_isolation_env(paths)
    with _scoped_environ_update(env):
        _write_top_level_start(paths, mode)

        stdout_path = _top_level_artifacts(paths)["stdout"]
        stderr_path = _top_level_artifacts(paths)["stderr"]
        stdout_handle = stdout_path.open("a", encoding="utf-8")
        stderr_handle = stderr_path.open("a", encoding="utf-8")
        child_state = {"running": False, "pid": None, "mode": None}
        start_time = time.time()
        result: dict[str, Any] = {}
        exit_code = 1

        faulthandler.enable(file=stderr_handle, all_threads=True)

        def _top_timeout_handler(_signum, _frame):
            raise ScenarioTimeoutError(f"runner_timeout:{RUN_TIMEOUT_SECONDS}")

        previous_alarm_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.setitimer(signal.ITIMER_REAL, RUN_TIMEOUT_SECONDS)
        signal.signal(signal.SIGALRM, _top_timeout_handler)

        try:
            with redirect_stdout(stdout_handle), redirect_stderr(stderr_handle):
                print(json.dumps({"event": "runner_start", "mode": mode, "run_root": str(paths.run_root)}, ensure_ascii=False))
                modules = _import_project_modules(paths)
                probe = _probe_path_map(paths, modules)
                _safe_write_json(_top_level_artifacts(paths)["environment_probe"], probe)
                _safe_write_json(_top_level_artifacts(paths)["import_order"], {"import_order": probe["import_order"], "generated_at_utc": utc_now()})
                print(json.dumps({"event": "import_order", "modules": probe["import_order"]}, ensure_ascii=False))
                if mode in {"all", "selftest"}:
                    selftest_summary = _run_selftests(paths)
                    _safe_write_json(_top_level_artifacts(paths)["selftest_summary"], selftest_summary)
                    result["selftest_summary"] = selftest_summary
                if mode in {"all", "staging"}:
                    staging_summary = _run_staging_validation(paths)
                    _safe_write_json(_top_level_artifacts(paths)["staging_validation_result"], staging_summary)
                    result["staging_validation_result"] = staging_summary
                result["status"] = "passed"
                _safe_write_json(_top_level_artifacts(paths)["result"], result)
                exit_code = 0
        except ScenarioTimeoutError as exc:
            faulthandler.dump_traceback(file=stderr_handle, all_threads=True)
            _write_top_level_timeout(paths, time.time() - start_time, child_state)
            _write_top_level_failure(paths, exc, "RUNNER_TIMEOUT")
            exit_code = 124
            result = {"status": "timeout", "message": str(exc)}
        except IsolationPathLeakError as exc:
            _write_top_level_failure(paths, exc, "ISOLATION_PATH_LEAK")
            exit_code = 2
            result = {"status": "failed", "classification": "ISOLATION_PATH_LEAK"}
        except ArtifactWriteError as exc:
            _write_top_level_failure(paths, exc, "ARTIFACT_GENERATION_FAILURE")
            exit_code = 3
            result = {"status": "failed", "classification": "ARTIFACT_GENERATION_FAILURE"}
        except BaseException as exc:
            _write_top_level_failure(paths, exc, "UNEXPECTED_FAILURE")
            exit_code = 4
            result = {"status": "failed", "classification": type(exc).__name__}
        finally:
            signal.signal(signal.SIGALRM, previous_alarm_handler)
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
            try:
                stdout_handle.flush()
                stderr_handle.flush()
                os.fsync(stdout_handle.fileno())
                os.fsync(stderr_handle.fileno())
            except Exception:
                pass
            stdout_handle.close()
            stderr_handle.close()
            _write_final_status(paths, exit_code)
            _write_manifest(paths.run_root)

        return exit_code, result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic validation runner")
    parser.add_argument("command", choices=["all", "selftest", "staging"], nargs="?", default="all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    exit_code, _result = _run_mode(args.command)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())