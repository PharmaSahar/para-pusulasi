from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


class SchedulerIntegrationError(RuntimeError):
    """Structured scheduler integration error for dry-run orchestration."""

    def __init__(self, safe_message: str, *, category: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.category = category

    def to_payload(self) -> dict[str, Any]:
        return {
            "safe_message": self.safe_message,
            "category": self.category,
        }


@dataclass(frozen=True, slots=True)
class SchedulerExecutionContext:
    run_id: str
    requested_at: str
    dry_run: bool
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        run_id = str(self.run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")

        parsed = _parse_timestamp(self.requested_at)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "requested_at", parsed.isoformat())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class SchedulerJob:
    job_id: str
    dependencies: tuple[str, ...]
    handler: Callable[[SchedulerExecutionContext], Mapping[str, Any]]

    def __post_init__(self) -> None:
        job_id = str(self.job_id or "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        if not callable(self.handler):
            raise ValueError("handler must be callable")

        dependencies = tuple(sorted({str(item).strip() for item in self.dependencies if str(item).strip()}))
        if job_id in dependencies:
            raise ValueError("job cannot depend on itself")

        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "dependencies", dependencies)


@dataclass(frozen=True, slots=True)
class JobExecutionRecord:
    job_id: str
    status: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        status = str(self.status or "").strip().lower()
        if status not in {"success", "skipped"}:
            raise ValueError("status is invalid")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "payload", dict(self.payload))


@dataclass(frozen=True, slots=True)
class SchedulerRunResult:
    run_id: str
    execution_order: tuple[str, ...]
    records: tuple[JobExecutionRecord, ...]
    lifecycle_events: tuple[str, ...]

    def __post_init__(self) -> None:
        if not str(self.run_id or "").strip():
            raise ValueError("run_id is required")
        object.__setattr__(self, "execution_order", tuple(self.execution_order))
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "lifecycle_events", tuple(self.lifecycle_events))


class DryRunScheduler:
    """Deterministic scheduler adapter that executes jobs only in dry-run mode."""

    def __init__(
        self,
        *,
        on_lifecycle_event: Callable[[str], None] | None = None,
    ) -> None:
        self._on_lifecycle_event = on_lifecycle_event

    def execute(
        self,
        *,
        context: SchedulerExecutionContext,
        jobs: tuple[SchedulerJob, ...],
    ) -> SchedulerRunResult:
        if not context.dry_run:
            raise SchedulerIntegrationError("dry-run required", category="INVALID_CONFIGURATION")

        ordered_jobs = _topological_order(jobs)
        lifecycle_events: list[str] = []
        records: list[JobExecutionRecord] = []

        self._emit("run_started", lifecycle_events)
        for job in ordered_jobs:
            self._emit(f"job_started:{job.job_id}", lifecycle_events)
            payload = dict(job.handler(context))
            payload.setdefault("dry_run", True)
            records.append(JobExecutionRecord(job_id=job.job_id, status="success", payload=payload))
            self._emit(f"job_finished:{job.job_id}", lifecycle_events)
        self._emit("run_finished", lifecycle_events)

        return SchedulerRunResult(
            run_id=context.run_id,
            execution_order=tuple(job.job_id for job in ordered_jobs),
            records=tuple(records),
            lifecycle_events=tuple(lifecycle_events),
        )

    def _emit(self, event: str, events: list[str]) -> None:
        events.append(event)
        if self._on_lifecycle_event is not None:
            self._on_lifecycle_event(event)


class SchedulerIntegrationService:
    """Integration layer wiring scheduler jobs for dry-run orchestration only."""

    def __init__(
        self,
        *,
        scheduler: DryRunScheduler,
        automatic_execution_enabled: bool = False,
    ) -> None:
        if bool(automatic_execution_enabled):
            raise SchedulerIntegrationError("automatic execution is forbidden", category="INVALID_CONFIGURATION")
        self._scheduler = scheduler

    def run_dry(
        self,
        *,
        context: SchedulerExecutionContext,
        jobs: tuple[SchedulerJob, ...],
    ) -> SchedulerRunResult:
        if not context.dry_run:
            raise SchedulerIntegrationError("dry-run context required", category="INVALID_CONFIGURATION")
        return self._scheduler.execute(context=context, jobs=jobs)


def _topological_order(jobs: tuple[SchedulerJob, ...]) -> tuple[SchedulerJob, ...]:
    by_id = {job.job_id: job for job in jobs}
    if len(by_id) != len(jobs):
        raise SchedulerIntegrationError("duplicate job id", category="INVALID_CONFIGURATION")

    for job in jobs:
        for dependency in job.dependencies:
            if dependency not in by_id:
                raise SchedulerIntegrationError("missing dependency", category="INVALID_CONFIGURATION")

    temp_marks: set[str] = set()
    perm_marks: set[str] = set()
    ordered: list[SchedulerJob] = []

    def visit(job_id: str) -> None:
        if job_id in perm_marks:
            return
        if job_id in temp_marks:
            raise SchedulerIntegrationError("dependency cycle", category="INVALID_CONFIGURATION")

        temp_marks.add(job_id)
        job = by_id[job_id]
        for dependency in sorted(job.dependencies):
            visit(dependency)
        temp_marks.remove(job_id)
        perm_marks.add(job_id)
        ordered.append(job)

    for job_id in sorted(by_id.keys()):
        visit(job_id)

    return tuple(ordered)


def _parse_timestamp(raw: str) -> datetime:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("requested_at is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("requested_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "DryRunScheduler",
    "JobExecutionRecord",
    "SchedulerExecutionContext",
    "SchedulerIntegrationError",
    "SchedulerIntegrationService",
    "SchedulerJob",
    "SchedulerRunResult",
]
