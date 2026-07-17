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


def test_shadow_coverage_audit_success(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-coverage-audit-now"])
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "Governance shadow coverage audit: PASS" in out


def test_shadow_coverage_audit_fail_open(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-coverage-audit-now"])
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: {"advisory_only": True})

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "Governance shadow coverage audit: FAIL" in out
    assert "expected_fields_present=FAIL" in out


def test_shadow_coverage_audit_deterministic_repeated_execution(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    first = scheduler.run_governance_shadow_coverage_audit_once()
    first_out = capsys.readouterr().out
    second = scheduler.run_governance_shadow_coverage_audit_once()
    second_out = capsys.readouterr().out

    assert first == 0
    assert second == 0
    assert first_out == second_out


def test_shadow_coverage_audit_registry_ordering(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_coverage_audit_once()
    out = capsys.readouterr().out

    assert rc == 0
    assert "surface_registry_deterministic=PASS" in out


def test_shadow_coverage_audit_complete_operator_coverage(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    parity_called = {"count": 0}

    def _fake_surface_parity() -> int:
        parity_called["count"] += 1
        print("Governance shadow surface parity: PASS")
        print("- report_builder_callable=PASS")
        print("- report_entrypoint_callable=PASS")
        print("- selfcheck_entrypoint_callable=PASS")
        print("- contract_validation_entrypoint_callable=PASS")
        print("- output_consistency_entrypoint_callable=PASS")
        print("- diagnostic_summary_entrypoint_callable=PASS")
        print("- surface_parity_entrypoint_callable=PASS")
        return 0

    monkeypatch.setattr(scheduler, "run_governance_shadow_surface_parity_once", _fake_surface_parity)

    rc = scheduler.run_governance_shadow_coverage_audit_once()
    out = capsys.readouterr().out

    assert rc == 0
    assert parity_called["count"] == 1
    assert "surface_parity_pass=PASS" in out
    assert "parity_covers_registered_surfaces=PASS" in out


def test_shadow_coverage_audit_duplicate_registration_detection(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())
    original = scheduler._get_governance_shadow_operator_surfaces

    def _dup_registry(*, include_surface_parity: bool = False, include_coverage_audit: bool = False):
        rows = list(
            original(
                include_surface_parity=include_surface_parity,
                include_coverage_audit=include_coverage_audit,
            )
        )
        rows.append(rows[-1])
        return tuple(rows)

    monkeypatch.setattr(scheduler, "_get_governance_shadow_operator_surfaces", _dup_registry)

    rc = scheduler.run_governance_shadow_coverage_audit_once()
    out = capsys.readouterr().out

    assert rc == 1
    assert "duplicate_registration_absent=FAIL" in out


def test_shadow_coverage_audit_scheduler_startup_not_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-coverage-audit-now"])
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


def test_shadow_coverage_audit_output_is_pass_fail_only(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_coverage_audit_once()
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]

    assert rc == 0
    assert lines[0] == "Governance shadow coverage audit: PASS"
    for line in lines[1:]:
        assert line.startswith("- ")
        assert line.endswith("=PASS") or line.endswith("=FAIL")


def test_shadow_coverage_audit_orchestration_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("operational_path_not_allowed")

    monkeypatch.setattr(scheduler, "render_and_schedule", _forbidden)
    monkeypatch.setattr(scheduler, "on_upload_time", _forbidden)
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_coverage_audit_once()
    assert rc == 0
