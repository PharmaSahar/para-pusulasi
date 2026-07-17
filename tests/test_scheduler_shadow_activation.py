from __future__ import annotations

import sys
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


def test_activation_default_disabled_when_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOVERNANCE_REFRESH_SHADOW_MODE", raising=False)
    result = scheduler._resolve_governance_shadow_activation()
    assert result == {"enabled": False, "state": "disabled"}


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "on", "enabled", " yes "])
def test_activation_explicit_enable_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", raw)
    result = scheduler._resolve_governance_shadow_activation()
    assert result == {"enabled": True, "state": "enabled"}


@pytest.mark.parametrize("raw", ["0", "false", "off", "disabled", " no ", ""])
def test_activation_disabled_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", raw)
    result = scheduler._resolve_governance_shadow_activation()
    assert result == {"enabled": False, "state": "disabled"}


def test_activation_invalid_flag_treated_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "banana")
    result = scheduler._resolve_governance_shadow_activation()
    assert result == {"enabled": False, "state": "invalid_flag"}


def test_activation_parsing_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "enabled")
    first = scheduler._resolve_governance_shadow_activation()
    second = scheduler._resolve_governance_shadow_activation()
    assert first == second


def test_activation_parsing_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_key: str):
        raise RuntimeError("env_boom")

    monkeypatch.setattr(scheduler.os, "getenv", _boom)
    result = scheduler._resolve_governance_shadow_activation()
    assert result == {"enabled": False, "state": "fail_open"}


def test_wrapper_skipped_while_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "0")

    calls = {"core": 0, "shadow": 0}

    monkeypatch.setattr(scheduler, "GOVERNANCE_REFRESH_SCRIPT", scheduler.Path("scheduler.py"))
    monkeypatch.setattr(
        scheduler,
        "_run_json_script",
        lambda _cmd, *, timeout_seconds=180: calls.__setitem__("core", calls["core"] + 1) or {"ok": True, "return_code": 0, "stderr_tail": ""},
    )
    monkeypatch.setattr(
        scheduler,
        "_run_governance_refresh_shadow",
        lambda **_kwargs: calls.__setitem__("shadow", calls["shadow"] + 1) or {"success": True},
    )

    scheduler.governance_refresh_job()
    assert calls == {"core": 1, "shadow": 0}


def test_wrapper_executed_only_while_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "enabled")

    calls = {"core": 0, "shadow": 0}

    monkeypatch.setattr(scheduler, "GOVERNANCE_REFRESH_SCRIPT", scheduler.Path("scheduler.py"))
    monkeypatch.setattr(
        scheduler,
        "_run_json_script",
        lambda _cmd, *, timeout_seconds=180: calls.__setitem__("core", calls["core"] + 1) or {"ok": True, "return_code": 0, "stderr_tail": ""},
    )
    monkeypatch.setattr(
        scheduler,
        "_run_governance_refresh_shadow",
        lambda **_kwargs: calls.__setitem__("shadow", calls["shadow"] + 1) or {"success": False, "invoked": True, "warning": "shadow_exception:test", "duration_ms": 1},
    )

    scheduler.governance_refresh_job()
    assert calls == {"core": 1, "shadow": 1}


def test_scheduler_success_unaffected_after_shadow_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "enabled")

    monkeypatch.setattr(scheduler, "GOVERNANCE_REFRESH_SCRIPT", scheduler.Path("scheduler.py"))
    monkeypatch.setattr(scheduler, "_run_json_script", lambda _cmd, *, timeout_seconds=180: {"ok": True, "return_code": 0, "stderr_tail": ""})
    monkeypatch.setattr(
        scheduler,
        "_run_governance_refresh_shadow",
        lambda **_kwargs: {"success": False, "invoked": True, "warning": "shadow_exception:test", "duration_ms": 1},
    )

    scheduler.governance_refresh_job()


def test_cadence_order_and_no_duplicate_registration_with_guardrails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    monkeypatch.setenv("GOVERNANCE_REFRESH_TIME", "03:20")
    monkeypatch.setenv("GOVERNANCE_REFRESH_SHADOW_MODE", "enabled")

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
