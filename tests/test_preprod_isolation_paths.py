from __future__ import annotations

import json
import importlib
import os
from pathlib import Path

import pytest


def test_scheduler_preprod_isolation_blocks_missing_state_root(monkeypatch):
    import scheduler

    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.delenv("PREPROD_STATE_ROOT", raising=False)

    with pytest.raises(RuntimeError, match="PREPROD_STATE_ROOT missing"):
        scheduler._assert_preprod_isolation_paths()


def test_scheduler_preprod_isolation_blocks_missing_required_latest_writer_envs(monkeypatch, tmp_path):
    import scheduler

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", str(state_root))
    monkeypatch.setattr(scheduler.os, "getcwd", lambda: str(repo_root))
    monkeypatch.delenv("PRODUCTION_DASHBOARD_MD_PATH", raising=False)
    monkeypatch.delenv("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", raising=False)

    with pytest.raises(RuntimeError, match="required mutable path env missing"):
        scheduler._assert_preprod_isolation_paths()


def test_scheduler_preprod_isolation_blocks_repo_mutable_path(monkeypatch, tmp_path):
    import scheduler

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", str(state_root))
    monkeypatch.setenv("PRODUCTION_DASHBOARD_MD_PATH", str(state_root / "state" / "dashboard.md"))
    monkeypatch.setenv("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", str(state_root / "state" / "activation_reports"))
    monkeypatch.setattr(scheduler, "_SCHEDULER_LOG_FILE_PATH", repo_root / "logs" / "scheduler.log")
    monkeypatch.setattr(scheduler.os, "getcwd", lambda: str(repo_root))

    with pytest.raises(RuntimeError, match="preprod_isolation_violation"):
        scheduler._assert_preprod_isolation_paths()


def test_scheduler_preprod_isolation_passes_for_isolated_paths(monkeypatch, tmp_path):
    import scheduler

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)

    isolated_scheduler = scheduler
    try:
        with monkeypatch.context() as scoped:
            scoped.setenv("PREPROD_ISOLATION_MODE", "true")
            scoped.setenv("PREPROD_STATE_ROOT", str(state_root))
            scoped.setenv("SCHEDULER_QUEUE_FILE", str(state_root / "state" / "queue.json"))
            scoped.setenv("SCHEDULER_PID_FILE", str(state_root / "state" / "pid"))
            scoped.setenv("SCHEDULER_SINGLETON_LOCK_FILE", str(state_root / "state" / "singleton.lock"))
            scoped.setenv("SCHEDULER_SINGLETON_META_FILE", str(state_root / "state" / "singleton_meta.json"))
            scoped.setenv("RUNTIME_EVIDENCE_LATEST_FILE", str(state_root / "telemetry" / "runtime.json"))
            scoped.setenv("SAFETY_GATE_LATEST_FILE", str(state_root / "telemetry" / "safety.json"))
            scoped.setenv("ACTIVATION_CONTROLLER_REPORT_PATH", str(state_root / "telemetry" / "activation.json"))
            scoped.setenv("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", str(state_root / "state" / "activation_reports"))
            scoped.setenv("ACTIVATION_FLAGS_PATH", str(state_root / "state" / "flags.json"))
            scoped.setenv("GOVERNANCE_REFRESH_LATEST_PATH", str(state_root / "state" / "gov_latest.json"))
            scoped.setenv("GOVERNANCE_READINESS_MD_PATH", str(state_root / "state" / "governance.md"))
            scoped.setenv("PRODUCTION_DASHBOARD_JSON_PATH", str(state_root / "telemetry" / "dashboard.json"))
            scoped.setenv("PRODUCTION_DASHBOARD_MD_PATH", str(state_root / "state" / "dashboard.md"))
            scoped.setenv("PRODUCTION_EVENTS_PATH", str(state_root / "telemetry" / "events.jsonl"))
            scoped.setenv("PRODUCTION_OBSERVABILITY_LATEST_PATH", str(state_root / "telemetry" / "observability.json"))
            scoped.setenv("SCHEDULER_LOG_FILE", str(state_root / "logs" / "scheduler.log"))
            scheduler._close_scheduler_logging_handlers()
            isolated_scheduler = importlib.reload(scheduler)
            scoped.setattr(isolated_scheduler, "_SCHEDULER_LOG_FILE_PATH", state_root / "logs" / "scheduler.log")
            scoped.setattr(isolated_scheduler.os, "getcwd", lambda: str(repo_root))

            isolated_scheduler._assert_preprod_isolation_paths()
    finally:
        isolated_scheduler._close_scheduler_logging_handlers()
        importlib.reload(isolated_scheduler)


def test_scheduler_preprod_reload_does_not_leak_module_constants(monkeypatch, tmp_path):
    import scheduler

    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)

    with monkeypatch.context() as scoped:
        scoped.setenv("PREPROD_ISOLATION_MODE", "true")
        scoped.setenv("PREPROD_STATE_ROOT", str(state_root))
        scoped.setenv("SCHEDULER_LOG_FILE", str(state_root / "logs" / "scheduler.log"))
        scoped.setenv("SCHEDULER_QUEUE_FILE", str(state_root / "state" / "queue.json"))
        scheduler._close_scheduler_logging_handlers()
        isolated = importlib.reload(scheduler)
        assert str(state_root) in str(isolated._SCHEDULER_LOG_FILE_PATH)
        assert str(state_root) in str(isolated.QUEUE_FILE)

    isolated._close_scheduler_logging_handlers()
    restored = importlib.reload(isolated)
    assert str(state_root) not in str(restored._SCHEDULER_LOG_FILE_PATH)
    assert str(state_root) not in str(restored.QUEUE_FILE)


def test_production_quality_dashboard_path_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCTION_DASHBOARD_JSON_PATH", str(tmp_path / "dash.json"))
    monkeypatch.setenv("PRODUCTION_DASHBOARD_MD_PATH", str(tmp_path / "dash.md"))

    import src.production_quality_platform as pqp

    pqp = importlib.reload(pqp)
    payload = pqp.update_production_dashboard(
        scheduler_status="RUNNING",
        build_sha="abc1234",
        scheduler_pid=111,
    )

    assert payload["build_sha"] == "abc1234"
    assert (tmp_path / "dash.json").exists()
    assert (tmp_path / "dash.md").exists()


def test_production_quality_dashboard_preprod_missing_md_env_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("PRODUCTION_DASHBOARD_JSON_PATH", str(tmp_path / "state" / "dash.json"))
    monkeypatch.delenv("PRODUCTION_DASHBOARD_MD_PATH", raising=False)

    import src.production_quality_platform as pqp

    pqp = importlib.reload(pqp)
    with pytest.raises(RuntimeError, match="PRODUCTION_DASHBOARD_MD_PATH missing"):
        pqp.update_production_dashboard(
            scheduler_status="RUNNING",
            build_sha="abc1234",
            scheduler_pid=111,
        )


def test_refresh_governance_readiness_markdown_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GOVERNANCE_READINESS_MD_PATH", str(tmp_path / "governance.md"))
    monkeypatch.setenv("GOVERNANCE_REFRESH_LATEST_PATH", str(tmp_path / "gov_latest.json"))
    monkeypatch.setenv("PROVEN_VALIDATED_MONITOR_PATH", str(tmp_path / "monitor.jsonl"))
    monkeypatch.setenv("GOVERNANCE_LOG_DIR", str(tmp_path / "logs"))

    from ops import refresh_governance_readiness as refresh

    refresh = importlib.reload(refresh)

    def _ok_step(command, *, required, fail_open, fallback_artifact=None):
        return {
            "name": "fake",
            "command": command,
            "exit_code": 0,
            "required": required,
            "fail_open": fail_open,
            "started_at_utc": "2026-07-11T00:00:00+00:00",
            "finished_at_utc": "2026-07-11T00:00:01+00:00",
        }

    monkeypatch.setattr(refresh, "_run_step", _ok_step)

    payload = refresh.run_refresh(lookback_rows=10)

    assert payload["ok"] is True
    assert (tmp_path / "governance.md").exists()
    assert (tmp_path / "gov_latest.json").exists()


def test_refresh_governance_preprod_missing_env_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("GOVERNANCE_READINESS_MD_PATH", raising=False)
    monkeypatch.setenv("GOVERNANCE_REFRESH_LATEST_PATH", str(tmp_path / "state" / "gov_latest.json"))
    monkeypatch.setenv("PROVEN_VALIDATED_MONITOR_PATH", str(tmp_path / "state" / "monitor.jsonl"))
    monkeypatch.setenv("GOVERNANCE_LOG_DIR", str(tmp_path / "state" / "logs"))

    from ops import refresh_governance_readiness as refresh

    refresh = importlib.reload(refresh)
    with pytest.raises(RuntimeError, match="GOVERNANCE_READINESS_MD_PATH missing"):
        refresh.run_refresh(lookback_rows=5)


def test_refresh_governance_preprod_rejects_repo_path(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    repo_like = tmp_path / "repo"
    repo_like.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", str(state_root))
    monkeypatch.setenv("GOVERNANCE_READINESS_MD_PATH", str(repo_like / "docs" / "governance_readiness_latest.md"))
    monkeypatch.setenv("GOVERNANCE_REFRESH_LATEST_PATH", str(state_root / "gov_latest.json"))
    monkeypatch.setenv("PROVEN_VALIDATED_MONITOR_PATH", str(state_root / "monitor.jsonl"))
    monkeypatch.setenv("GOVERNANCE_LOG_DIR", str(state_root / "logs"))

    from ops import refresh_governance_readiness as refresh

    refresh = importlib.reload(refresh)
    monkeypatch.setattr(refresh, "ROOT", repo_like)
    with pytest.raises(RuntimeError, match="preprod_isolation_violation"):
        refresh.run_refresh(lookback_rows=5)


def test_activation_controller_archive_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVATION_CONTROLLER_REPORT_PATH", str(tmp_path / "report.json"))
    monkeypatch.setenv("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("ACTIVATION_FLAGS_PATH", str(tmp_path / "flags.json"))

    from ops import activation_controller as ac

    ac = importlib.reload(ac)
    payload = {"ok": True}

    out = ac._archive_report(report=payload, archive_dir=tmp_path / "archive")

    assert Path(out["latest"]).exists()
    assert Path(out["stamped"]).exists()


def test_activation_controller_archive_preprod_missing_env_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", raising=False)

    from ops import activation_controller as ac

    ac = importlib.reload(ac)
    with pytest.raises(RuntimeError, match="ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR missing"):
        ac._archive_report(report={"ok": True}, archive_dir=tmp_path / "archive")


def test_activation_controller_archive_preprod_rejects_repo_path(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    repo_like = tmp_path / "repo"
    repo_like.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", str(state_root))
    monkeypatch.setenv("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", str(repo_like / "output" / "state" / "activation_reports"))

    from ops import activation_controller as ac

    ac = importlib.reload(ac)
    monkeypatch.setattr(ac, "ROOT", repo_like)
    with pytest.raises(RuntimeError, match="preprod_isolation_violation"):
        ac._archive_report(report={"ok": True}, archive_dir=repo_like / "output" / "state" / "activation_reports")


def test_production_default_paths_unchanged_when_no_preprod_env(monkeypatch):
    monkeypatch.delenv("PREPROD_ISOLATION_MODE", raising=False)
    monkeypatch.delenv("PRODUCTION_DASHBOARD_MD_PATH", raising=False)
    monkeypatch.delenv("GOVERNANCE_READINESS_MD_PATH", raising=False)
    monkeypatch.delenv("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", raising=False)

    import src.production_quality_platform as pqp
    from ops import refresh_governance_readiness as refresh
    from ops import activation_controller as ac

    pqp = importlib.reload(pqp)
    refresh = importlib.reload(refresh)
    ac = importlib.reload(ac)

    assert str(pqp.PRODUCTION_DASHBOARD_MD_PATH).endswith("output/runtime/state/production_dashboard_latest.md")
    assert str(refresh._resolve_readiness_markdown()).endswith("output/runtime/state/governance_readiness_latest.md")
    assert str(ac.DEFAULT_REPORT_ARCHIVE_DIR).endswith("output/state/activation_reports")


def test_runtime_path_resolver_uses_shared_root(tmp_path, monkeypatch):
    shared_runtime = tmp_path / "shared" / "runtime"
    shared_runtime.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("RUNTIME_OUTPUT_ROOT", str(shared_runtime))

    import src.runtime_storage as runtime_storage

    runtime_storage = importlib.reload(runtime_storage)

    assert runtime_storage.runtime_root() == shared_runtime.resolve()
    assert runtime_storage.runtime_path("state/progress.json") == shared_runtime / "state" / "progress.json"
    assert runtime_storage.progress_state_path() == shared_runtime / "state" / "progress.json"


def test_scheduler_progress_update_writes_json_not_progress_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    progress_file = tmp_path / "shared" / "state" / "progress.json"
    monkeypatch.setenv("PROGRESS_STATE_FILE", str(progress_file))

    import scheduler

    monkeypatch.setattr(scheduler, "load_queue", lambda: {"alpha": [{"publish_at": "2026-07-24T10:00:00"}]})
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["alpha"])

    scheduler.update_progress_file(last_task="done", next_step="next")

    assert progress_file.exists()
    assert not (tmp_path / "PROGRESS.md").exists()

    payload = json.loads(progress_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "scheduler_progress_state.v1"
    assert payload["last_task"] == "done"
    assert payload["next_step"] == "next"
