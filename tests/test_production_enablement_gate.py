from __future__ import annotations

from pathlib import Path

import pytest

from src.production_enablement_gate import (
    DryRunApproval,
    ProductionEnablementGate,
    ReadinessChecklist,
    ReadinessReport,
)


def _checklist(**kwargs) -> ReadinessChecklist:
    base = {
        "checklist_id": "project009-b6.9",
        "readiness_items": ("contracts", "dependencies", "configuration"),
        "required_dependencies": ("analytics_client", "snapshot_writer"),
        "required_contracts": ("scheduler_contract",),
        "configuration": {},
    }
    base.update(kwargs)
    return ReadinessChecklist(**base)


def test_ready_state() -> None:
    gate = ProductionEnablementGate()
    report = gate.evaluate(
        checklist=_checklist(),
        readiness_results={"contracts": True, "dependencies": True, "configuration": True},
        dependency_results={"analytics_client": True, "snapshot_writer": True},
        contract_results={"scheduler_contract": True},
    )

    assert report.status == "ready"
    assert report.score == 100
    assert report.approval.approved is True
    assert report.blocked_reasons == ()


def test_blocked_on_missing_dependency() -> None:
    gate = ProductionEnablementGate()
    report = gate.evaluate(
        checklist=_checklist(),
        readiness_results={"contracts": True, "dependencies": True, "configuration": True},
        dependency_results={"analytics_client": True, "snapshot_writer": False},
        contract_results={"scheduler_contract": True},
    )

    assert report.status == "partial"
    assert report.missing_dependencies == ("snapshot_writer",)
    assert "missing_dependencies" in report.blocked_reasons


def test_blocked_on_invalid_configuration() -> None:
    gate = ProductionEnablementGate()
    report = gate.evaluate(
        checklist=_checklist(configuration={"scheduler_enabled": True}),
        readiness_results={"contracts": True, "dependencies": True, "configuration": True},
        dependency_results={"analytics_client": True, "snapshot_writer": True},
        contract_results={"scheduler_contract": True},
    )

    assert report.status == "partial"
    assert report.invalid_configuration == ("scheduler_enabled",)
    assert "invalid_configuration" in report.blocked_reasons


def test_failed_readiness_item() -> None:
    gate = ProductionEnablementGate()
    report = gate.evaluate(
        checklist=_checklist(),
        readiness_results={"contracts": True, "dependencies": False, "configuration": True},
        dependency_results={"analytics_client": True, "snapshot_writer": True},
        contract_results={"scheduler_contract": True},
    )

    assert report.status == "partial"
    assert report.failed_items == ("dependencies",)
    assert "failed_readiness_items" in report.blocked_reasons


def test_deterministic_output() -> None:
    gate = ProductionEnablementGate()
    checklist = _checklist(
        readiness_items=("configuration", "contracts", "dependencies"),
        required_dependencies=("snapshot_writer", "analytics_client"),
        required_contracts=("scheduler_contract",),
    )
    report = gate.evaluate(
        checklist=checklist,
        readiness_results={"dependencies": True, "configuration": True, "contracts": True},
        dependency_results={"snapshot_writer": True, "analytics_client": True},
        contract_results={"scheduler_contract": True},
    )

    assert report.passed_items == ("configuration", "contracts", "dependencies")
    assert report.missing_dependencies == ()


def test_reject_inconsistent_report_state() -> None:
    with pytest.raises(ValueError):
        ReadinessReport(
            checklist_id="x",
            status="ready",
            score=90,
            passed_items=("a",),
            failed_items=(),
            missing_dependencies=(),
            contract_failures=(),
            invalid_configuration=(),
            blocked_reasons=(),
            approval=DryRunApproval(approved=True, reason="ok", dry_run_only=True),
        )


def test_immutable_models() -> None:
    checklist = _checklist()
    gate = ProductionEnablementGate()
    report = gate.evaluate(
        checklist=checklist,
        readiness_results={"contracts": True, "dependencies": True, "configuration": True},
        dependency_results={"analytics_client": True, "snapshot_writer": True},
        contract_results={"scheduler_contract": True},
    )

    with pytest.raises(AttributeError):
        checklist.checklist_id = "mutated"
    with pytest.raises(AttributeError):
        report.status = "blocked"


def test_no_runtime_mutation_behaviors_in_source() -> None:
    source = Path("src/production_enablement_gate.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "subprocess",
        "os.system",
        "systemctl",
        "crontab",
        "threading",
        "asyncio.create_task",
        "time.sleep",
    ]
    for token in forbidden:
        assert token not in source
