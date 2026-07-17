from __future__ import annotations

import json
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


def _expected_report_output(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def test_shadow_surface_parity_success(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-surface-parity-now"])
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "Governance shadow surface parity: PASS" in out


def test_shadow_surface_parity_fail_open(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-surface-parity-now"])
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: {"advisory_only": True})

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "Governance shadow surface parity: FAIL" in out
    assert "expected_fields_present=FAIL" in out


def test_shadow_surface_parity_deterministic_repeated_execution(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    first = scheduler.run_governance_shadow_surface_parity_once()
    first_out = capsys.readouterr().out
    second = scheduler.run_governance_shadow_surface_parity_once()
    second_out = capsys.readouterr().out

    assert first == 0
    assert second == 0
    assert first_out == second_out


def test_shadow_surface_parity_entrypoints_callable_and_ordered(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    report = _valid_report()
    call_order: list[str] = []

    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: report)

    def _report_entrypoint() -> int:
        call_order.append("report")
        print(_expected_report_output(report), end="")
        return 0

    def _selfcheck_entrypoint() -> int:
        call_order.append("selfcheck")
        print("Governance shadow self-check: PASS")
        return 0

    def _contract_validation_entrypoint() -> int:
        call_order.append("contract")
        print("Governance shadow contract validation: PASS")
        return 0

    def _output_consistency_entrypoint() -> int:
        call_order.append("output")
        print("Governance shadow output consistency: PASS")
        return 0

    def _diagnostic_summary_entrypoint() -> int:
        call_order.append("diagnostic")
        print("Governance shadow diagnostic summary: PASS")
        return 0

    monkeypatch.setattr(scheduler, "run_governance_shadow_report_once", _report_entrypoint)
    monkeypatch.setattr(scheduler, "run_governance_shadow_selfcheck_once", _selfcheck_entrypoint)
    monkeypatch.setattr(scheduler, "run_governance_shadow_contract_validation_once", _contract_validation_entrypoint)
    monkeypatch.setattr(scheduler, "run_governance_shadow_output_consistency_once", _output_consistency_entrypoint)
    monkeypatch.setattr(scheduler, "run_governance_shadow_diagnostic_summary_once", _diagnostic_summary_entrypoint)

    rc = scheduler.run_governance_shadow_surface_parity_once()
    out = capsys.readouterr().out

    assert rc == 0
    assert call_order == ["report", "selfcheck", "contract", "output", "diagnostic"]
    assert "report_builder_callable=PASS" in out
    assert "report_entrypoint_callable=PASS" in out
    assert "selfcheck_entrypoint_callable=PASS" in out
    assert "contract_validation_entrypoint_callable=PASS" in out
    assert "output_consistency_entrypoint_callable=PASS" in out
    assert "diagnostic_summary_entrypoint_callable=PASS" in out
    assert "surface_parity_entrypoint_callable=PASS" in out
    assert "surface_execution_order_deterministic=PASS" in out


def test_shadow_surface_parity_scheduler_startup_not_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--governance-shadow-surface-parity-now"])
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


def test_shadow_surface_parity_output_is_pass_fail_only(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_surface_parity_once()
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]

    assert rc == 0
    assert lines[0] == "Governance shadow surface parity: PASS"
    for line in lines[1:]:
        assert line.startswith("- ")
        assert line.endswith("=PASS") or line.endswith("=FAIL")


def test_shadow_surface_parity_orchestration_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("operational_path_not_allowed")

    monkeypatch.setattr(scheduler, "render_and_schedule", _forbidden)
    monkeypatch.setattr(scheduler, "on_upload_time", _forbidden)
    monkeypatch.setattr(scheduler, "_build_governance_shadow_readiness_report", lambda **_kwargs: _valid_report())

    rc = scheduler.run_governance_shadow_surface_parity_once()
    assert rc == 0


def test_shadow_surface_parity_help_discoverability(capsys) -> None:
    scheduler._print_help()
    out = capsys.readouterr().out

    assert out.count("--governance-shadow-report-now") == 1
    assert out.count("--governance-shadow-selfcheck-now") == 1
    assert out.count("--governance-shadow-contract-validate-now") == 1
    assert out.count("--governance-shadow-output-consistency-now") == 1
    assert out.count("--governance-shadow-diagnostic-summary-now") == 1
    assert out.count("--governance-shadow-surface-parity-now") == 1
