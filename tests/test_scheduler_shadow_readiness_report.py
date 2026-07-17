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


def test_shadow_readiness_report_ready() -> None:
    report = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation={"enabled": True, "state": "enabled"},
        diagnostics={
            "activation_state": "enabled",
            "invoked": True,
            "shadow_mode": True,
            "wrapper_executed": True,
            "success": True,
            "fail_open": True,
            "warning": "",
            "duration_ms": 1,
            "skipped_reason": "",
        },
        rollout_readiness={
            "readiness_state": "ready",
            "activation_state": "enabled",
            "diagnostics_available": True,
            "wrapper_available": True,
            "policy_version": "a4.7.v1",
            "ready": True,
            "warning": "",
            "fail_open": True,
        },
    )
    assert report["report_version"] == "a4.8.v1"
    assert report["activation_state"] == "enabled"
    assert report["summary"]["ready"] is True
    assert report["summary"]["readiness_state"] == "ready"


def test_shadow_readiness_report_disabled() -> None:
    report = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation={"enabled": False, "state": "disabled"},
        diagnostics={
            "activation_state": "disabled",
            "invoked": False,
            "shadow_mode": True,
            "wrapper_executed": False,
            "success": False,
            "fail_open": True,
            "warning": "",
            "duration_ms": 0,
            "skipped_reason": "disabled",
        },
        rollout_readiness={
            "readiness_state": "not_ready",
            "activation_state": "disabled",
            "diagnostics_available": True,
            "wrapper_available": True,
            "policy_version": "a4.7.v1",
            "ready": False,
            "warning": "activation_disabled",
            "fail_open": True,
        },
    )
    assert report["activation_state"] == "disabled"
    assert report["summary"]["ready"] is False
    assert "activation_disabled" in report["warnings"]


def test_shadow_readiness_report_invalid_activation() -> None:
    report = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation={"enabled": False, "state": "invalid_flag"},
        diagnostics={
            "activation_state": "invalid_flag",
            "invoked": False,
            "shadow_mode": True,
            "wrapper_executed": False,
            "success": False,
            "fail_open": True,
            "warning": "invalid_flag",
            "duration_ms": 0,
            "skipped_reason": "invalid_flag",
        },
        rollout_readiness={
            "readiness_state": "not_ready",
            "activation_state": "invalid_flag",
            "diagnostics_available": True,
            "wrapper_available": True,
            "policy_version": "a4.7.v1",
            "ready": False,
            "warning": "invalid_flag",
            "fail_open": True,
        },
    )
    assert report["activation_state"] == "invalid_flag"
    assert report["warnings"] == ["invalid_flag"]


def test_shadow_readiness_report_fail_open() -> None:
    report = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation={"enabled": False, "state": "fail_open"},
        diagnostics={
            "activation_state": "fail_open",
            "invoked": False,
            "shadow_mode": True,
            "wrapper_executed": False,
            "success": False,
            "fail_open": True,
            "warning": "fail_open",
            "duration_ms": 0,
            "skipped_reason": "fail_open",
        },
        rollout_readiness={
            "readiness_state": "not_ready",
            "activation_state": "fail_open",
            "diagnostics_available": True,
            "wrapper_available": True,
            "policy_version": "a4.7.v1",
            "ready": False,
            "warning": "fail_open",
            "fail_open": True,
        },
    )
    assert report["summary"]["fail_open"] is True
    assert report["warnings"] == ["fail_open"]


def test_shadow_readiness_report_deterministic_repeated_output() -> None:
    activation = {"enabled": True, "state": "enabled"}
    diagnostics = {
        "activation_state": "enabled",
        "invoked": True,
        "shadow_mode": True,
        "wrapper_executed": True,
        "success": True,
        "fail_open": True,
        "warning": "",
        "duration_ms": 1,
        "skipped_reason": "",
    }
    rollout = {
        "readiness_state": "ready",
        "activation_state": "enabled",
        "diagnostics_available": True,
        "wrapper_available": True,
        "policy_version": "a4.7.v1",
        "ready": True,
        "warning": "",
        "fail_open": True,
    }
    first = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation=activation,
        diagnostics=diagnostics,
        rollout_readiness=rollout,
    )
    second = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation=activation,
        diagnostics=diagnostics,
        rollout_readiness=rollout,
    )
    assert first == second


def test_shadow_readiness_report_warning_aggregation_sorted_unique() -> None:
    report = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation={"enabled": True, "state": "enabled"},
        diagnostics={
            "activation_state": "enabled",
            "invoked": True,
            "shadow_mode": True,
            "wrapper_executed": True,
            "success": False,
            "fail_open": True,
            "warning": "z_warn",
            "duration_ms": 1,
            "skipped_reason": "",
        },
        rollout_readiness={
            "readiness_state": "not_ready",
            "activation_state": "enabled",
            "diagnostics_available": True,
            "wrapper_available": True,
            "policy_version": "a4.7.v1",
            "ready": False,
            "warning": "a_warn",
            "fail_open": True,
        },
    )
    assert report["warnings"] == ["a_warn", "z_warn"]
    assert report["summary"]["warning_count"] == 2


def test_shadow_readiness_report_advisory_only_contract() -> None:
    report = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation={"enabled": False, "state": "disabled"},
        diagnostics={
            "activation_state": "disabled",
            "invoked": False,
            "shadow_mode": True,
            "wrapper_executed": False,
            "success": False,
            "fail_open": True,
            "warning": "",
            "duration_ms": 0,
            "skipped_reason": "disabled",
        },
        rollout_readiness={
            "readiness_state": "not_ready",
            "activation_state": "disabled",
            "diagnostics_available": True,
            "wrapper_available": True,
            "policy_version": "a4.7.v1",
            "ready": False,
            "warning": "activation_disabled",
            "fail_open": True,
        },
    )
    assert report["advisory_only"] is True


def test_scheduler_success_unaffected_with_readiness_report(monkeypatch: pytest.MonkeyPatch) -> None:
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

    report = scheduler._build_governance_shadow_readiness_report(
        lookback_rows=500,
        activation={"enabled": True, "state": "enabled"},
        diagnostics={
            "activation_state": "enabled",
            "invoked": True,
            "shadow_mode": True,
            "wrapper_executed": True,
            "success": True,
            "fail_open": True,
            "warning": "",
            "duration_ms": 1,
            "skipped_reason": "",
        },
        rollout_readiness={
            "readiness_state": "ready",
            "activation_state": "enabled",
            "diagnostics_available": True,
            "wrapper_available": True,
            "policy_version": "a4.7.v1",
            "ready": True,
            "warning": "",
            "fail_open": True,
        },
    )
    assert report["summary"]["ready"] is True
