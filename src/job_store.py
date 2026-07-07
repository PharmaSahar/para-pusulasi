"""Durable SQLite-backed job store with passive initialization helpers.

Module boundary: persistence only. No scheduler execution logic.
No upload/render logic here.

SQLite notes: single-writer only; enable WAL before live integration;
set a busy timeout before production use; this is a stepping stone
before PostgreSQL, not the final multi-worker state store.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Iterator

from .job_migrations import apply_schema
from .job_models import (
    FINAL_STATUSES,
    JobRecord,
    JobStatus,
    build_idempotency_key,
    build_job_id,
    can_admin_recover,
    can_transition,
    normalize_status,
    utcnow_iso,
)

DEFAULT_DB_PATH = Path("output/state/jobs.db")


@contextmanager
def open_database(db_path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


def initialize_database(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    with open_database(db_path) as connection:
        apply_schema(connection)
    return Path(db_path)


def get_job_by_id(connection: sqlite3.Connection, job_id: str) -> JobRecord | None:
    row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return JobRecord.from_row(row) if row else None


def get_job_by_idempotency_key(connection: sqlite3.Connection, idempotency_key: str) -> JobRecord | None:
    row = connection.execute(
        "SELECT * FROM jobs WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    return JobRecord.from_row(row) if row else None


def list_jobs(connection: sqlite3.Connection, status: str | None = None) -> list[JobRecord]:
    if status is None:
        rows = connection.execute("SELECT * FROM jobs ORDER BY created_at ASC, priority ASC, id ASC").fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC, priority ASC, id ASC",
            (normalize_status(status),),
        ).fetchall()
    return [JobRecord.from_row(row) for row in rows]


def count_jobs(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
    return int(row["n"] if row else 0)


def create_job(
    connection: sqlite3.Connection,
    *,
    channel_id: str,
    workflow_type: str,
    payload: dict,
    publish_at: str | None = None,
    priority: int = 100,
    max_attempts: int = 3,
    next_run_at: str | None = None,
    status: str = JobStatus.QUEUED.value,
    idempotency_key: str | None = None,
) -> JobRecord:
    normalized_status = normalize_status(status)
    if idempotency_key is None:
        idempotency_key = build_idempotency_key(channel_id, workflow_type, payload)

    existing = get_job_by_idempotency_key(connection, idempotency_key)
    if existing:
        return existing

    job_id = build_job_id()
    now = utcnow_iso()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    connection.execute(
        """
        INSERT INTO jobs (
            id, channel_id, workflow_type, idempotency_key, status, priority,
            attempt_count, max_attempts, next_run_at, locked_by, locked_at,
            publish_at, payload_json, result_json, error_code, error_message,
            created_at, updated_at, started_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            channel_id,
            workflow_type,
            idempotency_key,
            normalized_status,
            priority,
            0,
            max_attempts,
            next_run_at,
            None,
            None,
            publish_at,
            payload_json,
            None,
            None,
            None,
            now,
            now,
            None,
            None,
        ),
    )
    connection.commit()
    return get_job_by_id(connection, job_id)


def transition_job_status(
    connection: sqlite3.Connection,
    job_id: str,
    target_status: str,
    *,
    actor: str = "system",
    reason: str | None = None,
    admin_recovery: bool = False,
    next_run_at: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    result_json: str | None = None,
) -> JobRecord:
    job = get_job_by_id(connection, job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")

    normalized_target = normalize_status(target_status)
    if admin_recovery:
        if not can_admin_recover(job.status, normalized_target):
            raise ValueError(f"Admin recovery not allowed: {job.status} -> {normalized_target}")
    else:
        if not can_transition(job.status, normalized_target):
            raise ValueError(f"Transition not allowed: {job.status} -> {normalized_target}")

    now = utcnow_iso()
    started_at = job.started_at
    completed_at = job.completed_at
    attempt_count = job.attempt_count
    locked_by = job.locked_by
    locked_at = job.locked_at
    target_next_run_at = next_run_at if next_run_at is not None else job.next_run_at

    if normalized_target == JobStatus.RUNNING.value and started_at is None:
        started_at = now
        locked_by = actor
        locked_at = now
    elif normalized_target == JobStatus.FAILED.value and job.status == JobStatus.RUNNING.value:
        attempt_count += 1
    elif normalized_target == JobStatus.RETRYING.value:
        target_next_run_at = next_run_at or job.next_run_at
        locked_by = None
        locked_at = None
    elif normalized_target == JobStatus.QUEUED.value:
        locked_by = None
        locked_at = None
        if admin_recovery:
            target_next_run_at = next_run_at or now
    elif normalized_target in FINAL_STATUSES:
        completed_at = now
        locked_by = None
        locked_at = None

    connection.execute(
        """
        UPDATE jobs
        SET status = ?, attempt_count = ?, next_run_at = ?, locked_by = ?, locked_at = ?,
            result_json = COALESCE(?, result_json), error_code = COALESCE(?, error_code),
            error_message = COALESCE(?, error_message), updated_at = ?, started_at = COALESCE(?, started_at),
            completed_at = COALESCE(?, completed_at)
        WHERE id = ?
        """,
        (
            normalized_target,
            attempt_count,
            target_next_run_at,
            locked_by,
            locked_at,
            result_json,
            error_code,
            error_message,
            now,
            started_at,
            completed_at,
            job_id,
        ),
    )
    event_type = "admin_requeue" if admin_recovery else "state_change"
    event_payload = {
        "actor": actor,
        "from": job.status,
        "to": normalized_target,
    }
    if reason:
        event_payload["reason"] = reason
    connection.execute(
        "INSERT INTO job_events(job_id, event_type, event_payload_json, created_at) VALUES (?, ?, ?, ?)",
        (job_id, event_type, json.dumps(event_payload, ensure_ascii=False, sort_keys=True), now),
    )
    connection.commit()
    return get_job_by_id(connection, job_id)


def admin_requeue_job(
    connection: sqlite3.Connection,
    job_id: str,
    *,
    reason: str,
    actor: str = "admin",
) -> JobRecord:
    job = get_job_by_id(connection, job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    if job.status not in {JobStatus.DEAD.value, JobStatus.CANCELLED.value}:
        raise ValueError(f"Admin recovery only allowed from dead/cancelled, got {job.status}")
    return transition_job_status(
        connection,
        job_id,
        JobStatus.QUEUED.value,
        actor=actor,
        reason=reason,
        admin_recovery=True,
        next_run_at=utcnow_iso(),
        error_code=None,
        error_message=None,
        result_json=None,
    )


def bootstrap_legacy_queue(
    connection: sqlite3.Connection,
    queue_data: dict,
    *,
    workflow_type: str = "render_schedule",
) -> list[JobRecord]:
    created: list[JobRecord] = []
    for channel_id, entries in (queue_data or {}).items():
        for entry in entries or []:
            payload = {
                "channel_id": channel_id,
                "legacy_entry": entry,
            }
            publish_at = entry.get("publish_at")
            idempotency_key = build_idempotency_key(channel_id, workflow_type, payload)
            created.append(
                create_job(
                    connection,
                    channel_id=channel_id,
                    workflow_type=workflow_type,
                    payload=payload,
                    publish_at=publish_at,
                    priority=100,
                    max_attempts=3,
                    next_run_at=publish_at,
                    status=JobStatus.QUEUED.value,
                    idempotency_key=idempotency_key,
                )
            )
    return created


def mirror_legacy_queue_snapshot(
    queue_data: dict,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    workflow_type: str = "render_schedule_shadow",
) -> dict:
    """Mirror current JSON queue entries into SQLite and report parity.

    This helper is intentionally passive for shadow mode: it never drives
    scheduler execution, only mirrors entries and returns a parity report.
    """
    initialize_database(db_path)

    expected = 0
    mirrored = 0
    missing: list[str] = []

    with open_database(db_path) as connection:
        for channel_id, entries in (queue_data or {}).items():
            for entry in entries or []:
                expected += 1
                payload = {
                    "channel_id": channel_id,
                    "legacy_entry": entry,
                }
                publish_at = entry.get("publish_at") if isinstance(entry, dict) else None
                idempotency_key = build_idempotency_key(channel_id, workflow_type, payload)
                job = create_job(
                    connection,
                    channel_id=channel_id,
                    workflow_type=workflow_type,
                    payload=payload,
                    publish_at=publish_at,
                    priority=100,
                    max_attempts=3,
                    next_run_at=publish_at,
                    status=JobStatus.QUEUED.value,
                    idempotency_key=idempotency_key,
                )
                if job is not None:
                    mirrored += 1
                if get_job_by_idempotency_key(connection, idempotency_key) is None:
                    missing.append(idempotency_key)

    return {
        "expected": expected,
        "mirrored": mirrored,
        "missing_count": len(missing),
        "missing": missing,
    }
