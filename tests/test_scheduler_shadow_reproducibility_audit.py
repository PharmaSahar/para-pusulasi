from __future__ import annotations

import sys

import pytest

import scheduler


@pytest.fixture(autouse=True)
def _stub_scheduler_singleton_lock(monkeypatch):
    monkeypatch.setattr(scheduler, "_acquire_scheduler_singleton_lock", lambda: None)
    monkeypatch.setattr(scheduler, "_release_scheduler_singleton_lock", lambda: None)


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


def test_shadow_reproducibility_audit_success(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-reproducibility-audit-now"])
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "Governance shadow reproducibility audit: PASS" in out


def test_shadow_reproducibility_audit_fail_open(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-reproducibility-audit-now"])
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: {"advisory_only": True})

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "Governance shadow reproducibility audit: FAIL" in out
    assert "expected_fields_present=FAIL" in out


def test_shadow_reproducibility_audit_independent_repeated_execution(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    first = scheduler.run_governance_shadow_reproducibility_audit_once()
    first_out = capsys.readouterr().out
    second = scheduler.run_governance_shadow_reproducibility_audit_once()
    second_out = capsys.readouterr().out

    assert first == 0
    assert second == 0
    assert first_out == second_out


def test_shadow_reproducibility_audit_reproducible_output_verification(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())
    calls = {"stability": 0}

    def _unstable_stability() -> int:
        calls["stability"] += 1
        print("Governance shadow stability audit: PASS")
        print("- surface_registry_deterministic=PASS")
        print(f"- unstable_call_count_{calls['stability']}=PASS")
        return 0

    monkeypatch.setattr(scheduler, "run_governance_shadow_stability_audit_once", _unstable_stability)

    rc = scheduler.run_governance_shadow_reproducibility_audit_once()
    out = capsys.readouterr().out

    assert rc == 1
    assert "stability_audit_output_reproducible=FAIL" in out


def test_shadow_reproducibility_audit_registry_ordering(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_reproducibility_audit_once()
    out = capsys.readouterr().out

    assert rc == 0
    assert "surface_registry_deterministic=PASS" in out
    assert "surface_parity_registry_stable=PASS" in out
    assert "coverage_audit_registry_stable=PASS" in out
    assert "stability_audit_registry_stable=PASS" in out


def test_shadow_reproducibility_audit_scheduler_startup_not_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-reproducibility-audit-now"])
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


def test_shadow_reproducibility_audit_output_is_pass_fail_only(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_reproducibility_audit_once()
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]

    assert rc == 0
    assert lines[0] == "Governance shadow reproducibility audit: PASS"
    for line in lines[1:]:
        assert line.startswith("- ")
        assert line.endswith("=PASS") or line.endswith("=FAIL")


def test_shadow_reproducibility_audit_orchestration_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("operational_path_not_allowed")

    monkeypatch.setattr(scheduler, "render_and_schedule", _forbidden)
    monkeypatch.setattr(scheduler, "on_upload_time", _forbidden)
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_reproducibility_audit_once()
    assert rc == 0
