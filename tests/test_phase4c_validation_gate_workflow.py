from __future__ import annotations

from pathlib import Path

from tools.project002_sprint1e_phase4b_precondition_check import CheckResult, GateState, Problem

import tests.conftest as gate


def test_validator_invoked_before_phase4c(monkeypatch) -> None:
    call_order: list[str] = []

    def fake_check(_repo: Path) -> CheckResult:
        call_order.append("validator")
        return CheckResult(state=GateState.READY, problems=[])

    def phase4c_callable() -> str:
        call_order.append("phase4c")
        return "ok"

    monkeypatch.setattr(gate, "check_phase4b_environment", fake_check)
    result = gate.run_phase4c_with_precondition(Path("/synthetic"), phase4c_callable)

    assert result == "ok"
    assert call_order == ["validator", "phase4c"]


def test_failed_precondition_blocks_phase4c_entry(monkeypatch) -> None:
    entered = {"phase4c": False}

    def fake_check(_repo: Path) -> CheckResult:
        return CheckResult(
            state=GateState.NOT_PREPARED,
            problems=[Problem(code="missing_assessment_summary", message="missing summary")],
        )

    def phase4c_callable() -> str:
        entered["phase4c"] = True
        return "should-not-run"

    monkeypatch.setattr(gate, "check_phase4b_environment", fake_check)

    try:
        gate.run_phase4c_with_precondition(Path("/synthetic"), phase4c_callable)
        raise AssertionError("expected precondition failure")
    except RuntimeError as exc:
        message = str(exc)

    assert entered["phase4c"] is False
    assert "PHASE4B ENVIRONMENT PRECONDITION FAILED" in message
    assert "STATE: ENVIRONMENT_NOT_PREPARED" in message


def test_failure_diagnostic_is_deterministic(monkeypatch) -> None:
    def fake_check(_repo: Path) -> CheckResult:
        return CheckResult(
            state=GateState.INCONSISTENT,
            problems=[
                Problem(code="frozen_source_hash_mismatch", message="hash mismatch"),
                Problem(code="canonical_row_count_mismatch", message="count mismatch"),
            ],
        )

    monkeypatch.setattr(gate, "check_phase4b_environment", fake_check)

    try:
        gate.run_phase4c_with_precondition(Path("/synthetic"), lambda: "unreachable")
        raise AssertionError("expected runtime error")
    except RuntimeError as exc:
        message = str(exc)

    assert "PHASE4B ENVIRONMENT PRECONDITION FAILED" in message
    assert "STATE: ENVIRONMENT_INCONSISTENT" in message
    assert "[frozen_source_hash_mismatch] hash mismatch" in message
    assert "[canonical_row_count_mismatch] count mismatch" in message


def test_ready_precondition_preserves_execution_path(monkeypatch) -> None:
    sentinel = {"status": "unchanged"}

    def fake_check(_repo: Path) -> CheckResult:
        return CheckResult(state=GateState.READY, problems=[])

    monkeypatch.setattr(gate, "check_phase4b_environment", fake_check)
    result = gate.run_phase4c_with_precondition(Path("/synthetic"), lambda: sentinel)

    assert result is sentinel


def test_requires_phase4c_gate_detects_target_tests() -> None:
    assert gate._requires_phase4c_gate(["tests/test_unresolved_analytics_recovery_manifest.py"]) is True
    assert gate._requires_phase4c_gate(["tests/test_something_else.py"]) is False
