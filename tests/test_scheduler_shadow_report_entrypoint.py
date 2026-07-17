from __future__ import annotations

import json
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


def test_shadow_report_entrypoint_success(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-report-now"])
    monkeypatch.setattr(
        scheduler,
        "_build_governance_shadow_readiness_report",
        lambda **_kwargs: {
            "report_version": "a4.8.v1",
            "activation_state": "enabled",
            "diagnostics": {"fail_open": True},
            "rollout_readiness": {"ready": True, "fail_open": True},
            "summary": {
                "activation_state": "enabled",
                "ready": True,
                "readiness_state": "ready",
                "fail_open": True,
                "warning_count": 0,
            },
            "warnings": [],
            "advisory_only": True,
        },
    )

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0
    assert payload["summary"]["ready"] is True
    assert payload["advisory_only"] is True


def test_shadow_report_entrypoint_fail_open(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-report-now"])
    monkeypatch.setattr(
        scheduler,
        "_build_governance_shadow_readiness_report",
        lambda **_kwargs: {
            "report_version": "a4.8.v1",
            "activation_state": "fail_open",
            "diagnostics": {"fail_open": True, "warning": "shadow_diagnostics_fail_open:test"},
            "rollout_readiness": {"ready": False, "fail_open": True, "warning": "fail_open"},
            "summary": {
                "activation_state": "fail_open",
                "ready": False,
                "readiness_state": "not_ready",
                "fail_open": True,
                "warning_count": 2,
            },
            "warnings": ["fail_open", "shadow_diagnostics_fail_open:test"],
            "advisory_only": True,
        },
    )

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0
    assert payload["summary"]["fail_open"] is True
    assert payload["advisory_only"] is True


def test_shadow_report_entrypoint_deterministic_repeated_output(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}
    expected = {
        "report_version": "a4.8.v1",
        "activation_state": "enabled",
        "diagnostics": {"fail_open": True},
        "rollout_readiness": {"ready": True, "fail_open": True},
        "summary": {
            "activation_state": "enabled",
            "ready": True,
            "readiness_state": "ready",
            "fail_open": True,
            "warning_count": 0,
        },
        "warnings": [],
        "advisory_only": True,
    }

    def _builder(**_kwargs):
        calls["count"] += 1
        return expected

    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", _builder)
    first = scheduler.run_governance_shadow_report_once()
    second = scheduler.run_governance_shadow_report_once()

    assert first == 0
    assert second == 0
    assert calls["count"] == 2


def test_shadow_report_entrypoint_builder_invoked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def _builder(**_kwargs):
        calls["count"] += 1
        return {
            "report_version": "a4.8.v1",
            "activation_state": "enabled",
            "diagnostics": {"fail_open": True},
            "rollout_readiness": {"ready": True, "fail_open": True},
            "summary": {
                "activation_state": "enabled",
                "ready": True,
                "readiness_state": "ready",
                "fail_open": True,
                "warning_count": 0,
            },
            "warnings": [],
            "advisory_only": True,
        }

    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", _builder)
    rc = scheduler.run_governance_shadow_report_once()

    assert rc == 0
    assert calls["count"] == 1


def test_shadow_report_entrypoint_no_duplicated_evaluator_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scheduler,
        "_build_governance_shadow_readiness_report",
        lambda **_kwargs: {
            "report_version": "a4.8.v1",
            "activation_state": "enabled",
            "diagnostics": {"fail_open": True},
            "rollout_readiness": {"ready": True, "fail_open": True},
            "summary": {
                "activation_state": "enabled",
                "ready": True,
                "readiness_state": "ready",
                "fail_open": True,
                "warning_count": 0,
            },
            "warnings": [],
            "advisory_only": True,
        },
    )
    monkeypatch.setattr(
        scheduler,
        "_evaluate_governance_shadow_diagnostics",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("diagnostics_should_not_run_directly")),
    )
    monkeypatch.setattr(
        scheduler,
        "_evaluate_governance_shadow_rollout_readiness",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("rollout_should_not_run_directly")),
    )

    rc = scheduler.run_governance_shadow_report_once()
    assert rc == 0


def test_scheduler_success_unaffected_with_shadow_report_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(
        scheduler,
        "_build_governance_shadow_readiness_report",
        lambda **_kwargs: {
            "report_version": "a4.8.v1",
            "activation_state": "enabled",
            "diagnostics": {"fail_open": True},
            "rollout_readiness": {"ready": False, "fail_open": True},
            "summary": {
                "activation_state": "enabled",
                "ready": False,
                "readiness_state": "not_ready",
                "fail_open": True,
                "warning_count": 1,
            },
            "warnings": ["shadow_exception:test"],
            "advisory_only": True,
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
    monkeypatch.setattr(
        scheduler,
        "_build_governance_shadow_readiness_report",
        lambda **_kwargs: {
            "report_version": "a4.8.v1",
            "activation_state": "enabled",
            "diagnostics": {"fail_open": True},
            "rollout_readiness": {"ready": True, "fail_open": True},
            "summary": {
                "activation_state": "enabled",
                "ready": True,
                "readiness_state": "ready",
                "fail_open": True,
                "warning_count": 0,
            },
            "warnings": [],
            "advisory_only": True,
        },
    )

    rc = scheduler.run_governance_shadow_report_once()
    assert rc == 0