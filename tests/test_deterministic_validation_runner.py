from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ops.validation import deterministic_validation_runner as runner


def test_build_isolation_env_keeps_paths_under_root(tmp_path: Path) -> None:
    paths = runner._build_run_paths(tmp_path)
    env = runner._build_isolation_env(paths)

    assert env["PREPROD_STATE_ROOT"] == str(tmp_path)
    assert env["RUNTIME_OUTPUT_ROOT"].startswith(str(tmp_path))
    assert env["VISUAL_CONTAINMENT_PROVIDER_HEALTH_FILE"].startswith(str(tmp_path))


def test_probe_path_map_requires_isolated_paths(tmp_path: Path, monkeypatch) -> None:
    paths = runner._build_run_paths(tmp_path)
    monkeypatch.setenv("SCHEDULER_LOG_FILE", str(paths.logs_dir / "scheduler.log"))

    class _Scheduler:
        QUEUE_FILE = str(paths.queue_path)
        PID_FILE = paths.pid_path

        @staticmethod
        def _collect_preprod_mutable_paths():
            return {"queue": paths.queue_path}

        @staticmethod
        def _scheduler_singleton_lock_path():
            return paths.singleton_lock_path

        @staticmethod
        def _scheduler_singleton_meta_path():
            return paths.singleton_meta_path

    class _SchedulerUtils:
        PROVIDER_HEALTH_FILE = str(paths.provider_health_path)

    modules = runner.ChildModules(scheduler=_Scheduler(), scheduler_utils=_SchedulerUtils(), channel_manager=object(), pipeline=object())
    probe = runner._probe_path_map(paths, modules)

    assert probe["resolved_provider_health_path"].startswith(str(tmp_path))
    assert probe["import_order"] == ["scheduler", "scheduler_utils", "channel_manager", "pipeline"]


def test_manifest_lists_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.json").write_text("{}\n", encoding="utf-8")

    manifest = runner._write_manifest(tmp_path)

    assert manifest["artifact_count"] == 2
    assert (tmp_path / "artifact_manifest.json").exists()


def test_selftest_entrypoint_writes_artifacts(tmp_path: Path, monkeypatch) -> None:
    run_root = tmp_path / "project004_validation_test"
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda prefix: str(run_root))

    exit_code = runner.main(["selftest"])

    assert exit_code == 0
    assert (run_root / "run_started.json").exists()
    assert (run_root / "environment_probe.json").exists()
    assert (run_root / "selftest_summary.json").exists()
    summary = json.loads((run_root / "selftest_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert (run_root / "artifact_manifest.json").exists()
    assert (run_root / "exit_code.txt").read_text(encoding="utf-8").strip() == "0"


def test_scoped_environ_update_restores_existing_values(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "PROJECT004_ENV_RESTORE_EXISTING"
    monkeypatch.setenv(key, "original")

    with runner._scoped_environ_update({key: "temporary"}):
        assert os.environ[key] == "temporary"

    assert os.environ[key] == "original"


def test_scoped_environ_update_removes_absent_values(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "PROJECT004_ENV_RESTORE_ABSENT"
    monkeypatch.delenv(key, raising=False)

    with runner._scoped_environ_update({key: "temporary"}):
        assert os.environ[key] == "temporary"

    assert key not in os.environ


def test_scoped_environ_update_restores_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "PROJECT004_ENV_RESTORE_EXCEPTION"
    monkeypatch.setenv(key, "original")

    with pytest.raises(RuntimeError, match="expected_probe_failure"):
        with runner._scoped_environ_update({key: "temporary"}):
            raise RuntimeError("expected_probe_failure")

    assert os.environ[key] == "original"


def test_scoped_environ_update_repeated_invocation_no_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "PROJECT004_ENV_RESTORE_REPEAT"
    monkeypatch.delenv(key, raising=False)

    with runner._scoped_environ_update({key: "first"}):
        assert os.environ[key] == "first"
    assert key not in os.environ

    with runner._scoped_environ_update({key: "second"}):
        assert os.environ[key] == "second"
    assert key not in os.environ


def test_selftest_entrypoint_ignores_preimported_scheduler_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scheduler

    run_root = tmp_path / "project004_validation_test_preimported"
    monkeypatch.setattr(runner.tempfile, "mkdtemp", lambda prefix: str(run_root))
    monkeypatch.setenv("SCHEDULER_LOG_FILE", str(tmp_path / "outside" / "scheduler.log"))
    scheduler._close_scheduler_logging_handlers()

    # Simulate collection-time preimport with non-isolated constants.
    import importlib

    importlib.reload(scheduler)

    exit_code = runner.main(["selftest"])

    assert exit_code == 0
