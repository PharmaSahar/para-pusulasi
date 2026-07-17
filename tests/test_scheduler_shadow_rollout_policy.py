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


def test_rollout_policy_ready() -> None:
    readiness = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation={"enabled": True, "state": "enabled"},
        diagnostics={"wrapper_executed": True, "shadow_mode": True, "warning": ""},
    )
    assert readiness == {
        "readiness_state": "ready",
        "activation_state": "enabled",
        "diagnostics_available": True,
        "wrapper_available": True,
        "policy_version": "a4.7.v1",
        "ready": True,
        "warning": "",
        "fail_open": True,
    }


def test_rollout_policy_not_ready() -> None:
    readiness = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation={"enabled": True, "state": "enabled"},
        diagnostics={"wrapper_executed": False, "shadow_mode": True, "warning": "diag_missing"},
    )
    assert readiness["readiness_state"] == "not_ready"
    assert readiness["ready"] is False
    assert readiness["warning"] == "diag_missing"


def test_rollout_policy_disabled_activation() -> None:
    readiness = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation={"enabled": False, "state": "disabled"},
        diagnostics={"wrapper_executed": False, "shadow_mode": True, "warning": ""},
    )
    assert readiness["readiness_state"] == "not_ready"
    assert readiness["activation_state"] == "disabled"
    assert readiness["warning"] == "activation_disabled"


def test_rollout_policy_invalid_activation() -> None:
    readiness = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation={"enabled": False, "state": "invalid_flag"},
        diagnostics={"wrapper_executed": False, "shadow_mode": True, "warning": ""},
    )
    assert readiness["activation_state"] == "invalid_flag"
    assert readiness["warning"] == "invalid_flag"


def test_rollout_policy_fail_open_activation() -> None:
    readiness = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation={"enabled": False, "state": "fail_open"},
        diagnostics={"wrapper_executed": False, "shadow_mode": True, "warning": ""},
    )
    assert readiness["activation_state"] == "fail_open"
    assert readiness["warning"] == "fail_open"
    assert readiness["fail_open"] is True


def test_rollout_policy_deterministic_repeated_evaluation() -> None:
    activation = {"enabled": True, "state": "enabled"}
    diagnostics = {"wrapper_executed": True, "shadow_mode": True, "warning": ""}
    first = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation=activation,
        diagnostics=diagnostics,
    )
    second = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation=activation,
        diagnostics=diagnostics,
    )
    assert first == second


def test_rollout_policy_wrapper_unavailable() -> None:
    readiness = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation={"enabled": True, "state": "enabled"},
        diagnostics={"wrapper_executed": True, "shadow_mode": True, "warning": ""},
        wrapper_runner=object(),
    )
    assert readiness["wrapper_available"] is False
    assert readiness["warning"] == "wrapper_unavailable"


def test_rollout_policy_diagnostics_unavailable() -> None:
    readiness = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation={"enabled": True, "state": "enabled"},
        diagnostics=None,
    )
    assert readiness["diagnostics_available"] is False
    assert readiness["warning"] == "diagnostics_unavailable"


def test_scheduler_success_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler, "GOVERNANCE_REFRESH_SCRIPT", scheduler.Path("scheduler.py"))
    monkeypatch.setattr(scheduler, "_run_json_script", lambda _cmd, *, timeout_seconds=180: {"ok": True, "return_code": 0, "stderr_tail": ""})
    monkeypatch.setattr(scheduler, "_resolve_governance_shadow_activation", lambda: {"enabled": True, "state": "enabled"})
    monkeypatch.setattr(
        scheduler,
        "_evaluate_governance_shadow_diagnostics",
        lambda **_kwargs: {
            "activation_state": "enabled",
            "invoked": True,
            "shadow_mode": True,
            "wrapper_executed": True,
            "success": False,
            "fail_open": True,
            "warning": "shadow_exception:test",
            "duration_ms": 1,
            "skipped_reason": "",
        },
    )
    monkeypatch.setattr(
        scheduler,
        "_evaluate_governance_shadow_rollout_readiness",
        lambda **_kwargs: {
            "readiness_state": "not_ready",
            "activation_state": "enabled",
            "diagnostics_available": True,
            "wrapper_available": True,
            "policy_version": "a4.7.v1",
            "ready": False,
            "warning": "shadow_exception:test",
            "fail_open": True,
        },
    )
    scheduler.governance_refresh_job()


def test_cadence_ordering_and_no_duplicate_registration_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    monkeypatch.setenv("GOVERNANCE_REFRESH_TIME", "03:20")

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


def test_no_operational_coupling(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("operational_path_not_allowed")

    monkeypatch.setattr(scheduler, "render_and_schedule", _forbidden)
    monkeypatch.setattr(scheduler, "on_upload_time", _forbidden)

    readiness = scheduler._evaluate_governance_shadow_rollout_readiness(
        activation={"enabled": True, "state": "enabled"},
        diagnostics={"wrapper_executed": True, "shadow_mode": True, "warning": ""},
    )
    assert readiness["ready"] is True
