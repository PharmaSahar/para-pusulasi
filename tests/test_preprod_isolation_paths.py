from __future__ import annotations

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

    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", str(state_root))
    monkeypatch.setenv("SCHEDULER_QUEUE_FILE", str(state_root / "state" / "queue.json"))
    monkeypatch.setenv("SCHEDULER_PID_FILE", str(state_root / "state" / "pid"))
    monkeypatch.setenv("SCHEDULER_SINGLETON_LOCK_FILE", str(state_root / "state" / "singleton.lock"))
    monkeypatch.setenv("SCHEDULER_SINGLETON_META_FILE", str(state_root / "state" / "singleton_meta.json"))
    monkeypatch.setenv("RUNTIME_EVIDENCE_LATEST_FILE", str(state_root / "telemetry" / "runtime.json"))
    monkeypatch.setenv("SAFETY_GATE_LATEST_FILE", str(state_root / "telemetry" / "safety.json"))
    monkeypatch.setenv("ACTIVATION_CONTROLLER_REPORT_PATH", str(state_root / "telemetry" / "activation.json"))
    monkeypatch.setenv("ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR", str(state_root / "state" / "activation_reports"))
    monkeypatch.setenv("ACTIVATION_FLAGS_PATH", str(state_root / "state" / "flags.json"))
    monkeypatch.setenv("GOVERNANCE_REFRESH_LATEST_PATH", str(state_root / "state" / "gov_latest.json"))
    monkeypatch.setenv("GOVERNANCE_READINESS_MD_PATH", str(state_root / "state" / "governance.md"))
    monkeypatch.setenv("PRODUCTION_DASHBOARD_JSON_PATH", str(state_root / "telemetry" / "dashboard.json"))
    monkeypatch.setenv("PRODUCTION_DASHBOARD_MD_PATH", str(state_root / "state" / "dashboard.md"))
    monkeypatch.setenv("PRODUCTION_EVENTS_PATH", str(state_root / "telemetry" / "events.jsonl"))
    monkeypatch.setenv("PRODUCTION_OBSERVABILITY_LATEST_PATH", str(state_root / "telemetry" / "observability.json"))
    monkeypatch.setenv("SCHEDULER_LOG_FILE", str(state_root / "logs" / "scheduler.log"))
    scheduler._close_scheduler_logging_handlers()
    scheduler = importlib.reload(scheduler)
    monkeypatch.setattr(scheduler, "_SCHEDULER_LOG_FILE_PATH", state_root / "logs" / "scheduler.log")
    monkeypatch.setattr(scheduler.os, "getcwd", lambda: str(repo_root))

    scheduler._assert_preprod_isolation_paths()


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

    assert str(pqp.PRODUCTION_DASHBOARD_MD_PATH).endswith("docs/production_dashboard_latest.md")
    assert str(refresh._resolve_readiness_markdown()).endswith("docs/governance_readiness_latest.md")
    assert str(ac.DEFAULT_REPORT_ARCHIVE_DIR).endswith("output/state/activation_reports")
