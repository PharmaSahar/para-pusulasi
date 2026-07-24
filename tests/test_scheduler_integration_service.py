from __future__ import annotations

from pathlib import Path

import pytest

from src.scheduler_integration_service import (
    DryRunScheduler,
    SchedulerExecutionContext,
    SchedulerIntegrationError,
    SchedulerIntegrationService,
    SchedulerJob,
    SchedulerRunResult,
)


def _context(*, dry_run: bool = True) -> SchedulerExecutionContext:
    return SchedulerExecutionContext(
        run_id="run-001",
        requested_at="2026-07-24T12:00:00+00:00",
        dry_run=dry_run,
        metadata={"source": "test"},
    )


def _job(job_id: str, *, deps: tuple[str, ...] = ()) -> SchedulerJob:
    def _handler(context: SchedulerExecutionContext):
        return {
            "job_id": job_id,
            "run_id": context.run_id,
            "dry_run": context.dry_run,
        }

    return SchedulerJob(job_id=job_id, dependencies=deps, handler=_handler)


def test_successful_dry_run() -> None:
    service = SchedulerIntegrationService(scheduler=DryRunScheduler())
    result = service.run_dry(context=_context(), jobs=(_job("sync"), _job("dashboard", deps=("sync",))))

    assert isinstance(result, SchedulerRunResult)
    assert result.execution_order == ("sync", "dashboard")
    assert all(record.payload["dry_run"] is True for record in result.records)


def test_dependency_ordering() -> None:
    service = SchedulerIntegrationService(scheduler=DryRunScheduler())
    jobs = (
        _job("dashboard", deps=("snapshot",)),
        _job("sync"),
        _job("snapshot", deps=("sync",)),
    )

    result = service.run_dry(context=_context(), jobs=jobs)
    assert result.execution_order == ("sync", "snapshot", "dashboard")


def test_lifecycle_events() -> None:
    observed: list[str] = []
    service = SchedulerIntegrationService(
        scheduler=DryRunScheduler(on_lifecycle_event=observed.append),
    )
    result = service.run_dry(context=_context(), jobs=(_job("sync"),))

    assert result.lifecycle_events == (
        "run_started",
        "job_started:sync",
        "job_finished:sync",
        "run_finished",
    )
    assert tuple(observed) == result.lifecycle_events


def test_dry_run_enforcement() -> None:
    service = SchedulerIntegrationService(scheduler=DryRunScheduler())
    with pytest.raises(SchedulerIntegrationError) as exc_info:
        service.run_dry(context=_context(dry_run=False), jobs=(_job("sync"),))
    assert exc_info.value.category == "INVALID_CONFIGURATION"


def test_invalid_configuration_rejection() -> None:
    with pytest.raises(SchedulerIntegrationError) as exc_info:
        SchedulerIntegrationService(scheduler=DryRunScheduler(), automatic_execution_enabled=True)
    assert exc_info.value.category == "INVALID_CONFIGURATION"


def test_dependency_cycle_rejected() -> None:
    service = SchedulerIntegrationService(scheduler=DryRunScheduler())
    with pytest.raises(SchedulerIntegrationError) as exc_info:
        service.run_dry(
            context=_context(),
            jobs=(
                _job("a", deps=("b",)),
                _job("b", deps=("a",)),
            ),
        )
    assert exc_info.value.category == "INVALID_CONFIGURATION"


def test_immutable_models() -> None:
    context = _context()
    job = _job("sync")
    service = SchedulerIntegrationService(scheduler=DryRunScheduler())
    result = service.run_dry(context=context, jobs=(job,))

    with pytest.raises(AttributeError):
        context.run_id = "changed"
    with pytest.raises(AttributeError):
        job.job_id = "changed"
    with pytest.raises(AttributeError):
        result.execution_order = ()


def test_no_forbidden_runtime_behaviors_in_source() -> None:
    source = Path("src/scheduler_integration_service.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "crontab",
        "systemctl",
        "service restart",
        "deploy",
        "production",
        "thread",
        "asyncio.gather",
        "time.sleep",
    ]
    for token in forbidden:
        assert token not in source
