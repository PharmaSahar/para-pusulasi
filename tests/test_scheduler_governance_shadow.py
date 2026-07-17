from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scheduler


@pytest.fixture(autouse=True)
def _stub_scheduler_singleton_lock(monkeypatch):
    monkeypatch.setattr(scheduler, "_acquire_scheduler_singleton_lock", lambda: None)
    monkeypatch.setattr(scheduler, "_release_scheduler_singleton_lock", lambda: None)


class _StopLoop(Exception):
    pass


class _FakeScheduleJob:
    def __init__(self, registry: list[dict[str, str]], every_args: tuple[object, ...]):
        self._registry = registry
        self._every_args = every_args
        self._period = ""
        self._at = ""

    @property
    def day(self):
        self._period = "day"
        return self

    @property
    def hour(self):
        self._period = "hour"
        return self

    @property
    def hours(self):
        self._period = "hours"
        return self

    def at(self, when: str):
        self._at = str(when)
        return self

    def do(self, fn, *args, **kwargs):
        self._registry.append(
            {
                "name": getattr(fn, "__name__", str(fn)),
                "period": self._period,
                "at": self._at,
                "every_args": repr(self._every_args),
            }
        )
        return self


class _FakeSchedule:
    def __init__(self):
        self.registry: list[dict[str, str]] = []

    def every(self, *args, **kwargs):
        return _FakeScheduleJob(self.registry, args)

    def run_pending(self):
        raise _StopLoop()


class _FakeThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def _patch_main_runtime(monkeypatch: pytest.MonkeyPatch, fake_schedule: _FakeSchedule) -> None:
    class _StartupResult:
        ok = True
        errors = ()

    fake_utils = SimpleNamespace(
        cleanup_old_renders=lambda **_kwargs: None,
        notify_startup=lambda _n: None,
    )

    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "_run_provider_preflight_check", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "setup_schedule", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "catch_up_overdue_queue_entries", lambda: {})
    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    monkeypatch.setattr(scheduler.threading, "Thread", _FakeThread)
    monkeypatch.setitem(sys.modules, "src.scheduler_utils", fake_utils)


def test_shadow_wrapper_success_and_explicit_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([100.0, 100.0])
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: next(ticks))

    called: dict[str, object] = {}

    def _invoker(*, cmd: list[str], timeout: int) -> dict:
        called["cmd"] = list(cmd)
        called["timeout"] = timeout
        return {"ok": True}

    result = scheduler._run_governance_refresh_shadow(
        lookback_rows=500,
        refresh_invoker=_invoker,
        timeout_seconds=25,
    )

    assert result == {
        "invoked": True,
        "shadow_mode": True,
        "success": True,
        "fail_open": True,
        "warning": "",
        "duration_ms": 0,
    }
    assert called["timeout"] == 25
    cmd = list(called["cmd"])
    assert "ops/refresh_governance_readiness.py" in cmd
    assert "--lookback-rows" in cmd


def test_shadow_wrapper_exception_contained() -> None:
    def _invoker(*, cmd: list[str], timeout: int) -> dict:
        raise RuntimeError("shadow_boom")

    result = scheduler._run_governance_refresh_shadow(lookback_rows=500, refresh_invoker=_invoker)
    assert result["invoked"] is True
    assert result["shadow_mode"] is True
    assert result["success"] is False
    assert result["fail_open"] is True
    assert str(result["warning"]).startswith("shadow_exception:")


def test_shadow_wrapper_malformed_result_contained() -> None:
    result = scheduler._run_governance_refresh_shadow(
        lookback_rows=500,
        refresh_invoker=lambda **_kwargs: "not-a-dict",
    )
    assert result["invoked"] is True
    assert result["success"] is False
    assert result["warning"] == "shadow_malformed_result"


def test_shadow_wrapper_import_failure_contained() -> None:
    def _invoker(*, cmd: list[str], timeout: int) -> dict:
        raise ImportError("missing_dep")

    result = scheduler._run_governance_refresh_shadow(lookback_rows=500, refresh_invoker=_invoker)
    assert result["invoked"] is True
    assert result["success"] is False
    assert result["fail_open"] is True
    assert str(result["warning"]).startswith("shadow_import_failure:")


def test_shadow_wrapper_timeout_contained() -> None:
    result = scheduler._run_governance_refresh_shadow(
        lookback_rows=500,
        refresh_invoker=lambda **_kwargs: {"ok": False, "timed_out": True},
    )
    assert result["invoked"] is True
    assert result["success"] is False
    assert result["warning"] == "shadow_timeout"


def test_governance_refresh_job_non_blocking_after_shadow_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "1")
    monkeypatch.setattr(scheduler, "GOVERNANCE_REFRESH_SCRIPT", Path("scheduler.py"))

    calls = {"core": 0, "shadow": 0}

    def _core_run(_cmd, *, timeout_seconds=180):
        calls["core"] += 1
        return {"ok": True, "return_code": 0, "stderr_tail": ""}

    def _shadow_run(*, lookback_rows: int, refresh_invoker=None, timeout_seconds: int = 60):
        calls["shadow"] += 1
        return {
            "invoked": True,
            "shadow_mode": True,
            "success": False,
            "fail_open": True,
            "warning": "shadow_exception:test",
            "duration_ms": 1,
        }

    monkeypatch.setattr(scheduler, "_run_json_script", _core_run)
    monkeypatch.setattr(scheduler, "_run_governance_refresh_shadow", _shadow_run)

    scheduler.governance_refresh_job()
    assert calls == {"core": 1, "shadow": 1}


def test_scheduler_registration_order_and_cadence_unchanged_shadow_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    monkeypatch.setenv("GOVERNANCE_REFRESH_TIME", "03:20")
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "0")

    fake_schedule = _FakeSchedule()
    _patch_main_runtime(monkeypatch, fake_schedule)

    with pytest.raises(_StopLoop):
        scheduler.main()

    names = [row["name"] for row in fake_schedule.registry]
    assert names[:3] == ["maintenance_job", "governance_refresh_job", "fill_empty_queues_job"]

    governance_rows = [row for row in fake_schedule.registry if row["name"] == "governance_refresh_job"]
    assert len(governance_rows) == 1
    assert governance_rows[0]["period"] == "day"
    assert governance_rows[0]["at"] == "03:20"


def test_scheduler_registration_order_and_cadence_unchanged_shadow_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    monkeypatch.setenv("GOVERNANCE_REFRESH_TIME", "03:20")
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "1")

    fake_schedule = _FakeSchedule()
    _patch_main_runtime(monkeypatch, fake_schedule)

    with pytest.raises(_StopLoop):
        scheduler.main()

    names = [row["name"] for row in fake_schedule.registry]
    assert names[:3] == ["maintenance_job", "governance_refresh_job", "fill_empty_queues_job"]

    governance_rows = [row for row in fake_schedule.registry if row["name"] == "governance_refresh_job"]
    assert len(governance_rows) == 1
    assert governance_rows[0]["period"] == "day"
    assert governance_rows[0]["at"] == "03:20"


def test_shadow_wrapper_deterministic_informational_result(monkeypatch: pytest.MonkeyPatch) -> None:
    invoker = lambda **_kwargs: {"ok": True}

    ticks = iter([200.0, 200.0, 300.0, 300.0])
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: next(ticks))

    first = scheduler._run_governance_refresh_shadow(lookback_rows=500, refresh_invoker=invoker)
    second = scheduler._run_governance_refresh_shadow(lookback_rows=500, refresh_invoker=invoker)
    assert first == second


def test_shadow_wrapper_no_actuation_paths_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("operational_path_not_allowed")

    monkeypatch.setattr(scheduler, "render_and_schedule", _forbidden)
    monkeypatch.setattr(scheduler, "on_upload_time", _forbidden)

    called: dict[str, object] = {}

    def _invoker(*, cmd: list[str], timeout: int) -> dict:
        called["cmd"] = list(cmd)
        called["timeout"] = timeout
        return {"ok": True}

    result = scheduler._run_governance_refresh_shadow(lookback_rows=500, refresh_invoker=_invoker)

    assert result["success"] is True
    cmd = " ".join(list(called["cmd"]))
    assert "run_full_pipeline" not in cmd
    assert "run_channel_pipeline" not in cmd
    assert "upload" not in cmd
    assert "deploy" not in cmd
    assert "restart" not in cmd
    assert "recommendation" not in cmd
