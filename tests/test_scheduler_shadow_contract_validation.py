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


def _valid_report() -> dict[str, object]:
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


def test_shadow_contract_validation_success(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-contract-validate-now"])
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "Governance shadow contract validation: PASS" in out


def test_shadow_contract_validation_fail_open(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-contract-validate-now"])
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: {"advisory_only": True})

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "Governance shadow contract validation: FAIL" in out
    assert "expected_fields_present=FAIL" in out


def test_shadow_contract_validation_deterministic_repeated_output(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())
    first = scheduler.run_governance_shadow_contract_validation_once()
    first_out = capsys.readouterr().out
    second = scheduler.run_governance_shadow_contract_validation_once()
    second_out = capsys.readouterr().out

    assert first == 0
    assert second == 0
    assert first_out == second_out


def test_shadow_contract_validation_expected_field_type_validation(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    report = _valid_report()
    report["warnings"] = "not-a-list"
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: report)

    rc = scheduler.run_governance_shadow_contract_validation_once()
    out = capsys.readouterr().out

    assert rc == 1
    assert "field_types_stable=FAIL" in out


def test_shadow_contract_validation_report_entrypoint_callable(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_contract_validation_once()
    out = capsys.readouterr().out

    assert rc == 0
    assert "report_entrypoint_callable=PASS" in out


def test_shadow_contract_validation_selfcheck_callable(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_contract_validation_once()
    out = capsys.readouterr().out

    assert rc == 0
    assert "selfcheck_entrypoint_callable=PASS" in out


def test_shadow_contract_validation_scheduler_startup_not_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-contract-validate-now"])
    calls = {"ready": 0, "setup": 0, "thread": 0}

    def _fake_ready_channels():
        calls["ready"] += 1
        return ["demo"]

    def _fake_setup_schedule():
        calls["setup"] += 1
        return ["demo"]

    class _Thread:
        def __init__(self, *args, **kwargs):
            calls["thread"] += 1

        def start(self):
            calls["thread"] += 1

    monkeypatch.setattr(scheduler, "get_ready_channels", _fake_ready_channels)
    monkeypatch.setattr(scheduler, "setup_schedule", _fake_setup_schedule)
    monkeypatch.setattr(scheduler.threading, "Thread", _Thread)
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 0
    assert calls == {"ready": 0, "setup": 0, "thread": 0}


def test_shadow_contract_validation_no_operational_coupling(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("operational_path_not_allowed")

    monkeypatch.setattr(scheduler, "render_and_schedule", _forbidden)
    monkeypatch.setattr(scheduler, "on_upload_time", _forbidden)
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_contract_validation_once()
    assert rc == 0