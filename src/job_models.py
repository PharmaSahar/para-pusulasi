"""Durable job store data models and state helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import uuid


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    JobStatus.QUEUED.value: {JobStatus.RUNNING.value, JobStatus.CANCELLED.value},
    JobStatus.RUNNING.value: {JobStatus.DONE.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value},
    JobStatus.FAILED.value: {JobStatus.RETRYING.value, JobStatus.DEAD.value},
    JobStatus.RETRYING.value: {JobStatus.QUEUED.value, JobStatus.CANCELLED.value},
}

MANUAL_RECOVERY_TRANSITIONS: set[tuple[str, str]] = {
    (JobStatus.DEAD.value, JobStatus.QUEUED.value),
    (JobStatus.CANCELLED.value, JobStatus.QUEUED.value),
}

FINAL_STATUSES = {
    JobStatus.DONE.value,
    JobStatus.DEAD.value,
    JobStatus.CANCELLED.value,
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_status(status: str | JobStatus) -> str:
    value = status.value if isinstance(status, JobStatus) else str(status)
    lowered = value.strip().lower()
    if lowered not in {s.value for s in JobStatus}:
        raise ValueError(f"Unsupported job status: {status}")
    return lowered


def can_transition(current_status: str | JobStatus, target_status: str | JobStatus) -> bool:
    current = normalize_status(current_status)
    target = normalize_status(target_status)
    return target in ALLOWED_TRANSITIONS.get(current, set())


def can_admin_recover(current_status: str | JobStatus, target_status: str | JobStatus) -> bool:
    current = normalize_status(current_status)
    target = normalize_status(target_status)
    return (current, target) in MANUAL_RECOVERY_TRANSITIONS


def build_idempotency_key(channel_id: str, workflow_type: str, payload: dict) -> str:
    payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:24]
    return f"{channel_id}:{workflow_type}:{digest}"


def build_job_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class JobRecord:
    id: str
    channel_id: str
    workflow_type: str
    idempotency_key: str
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    next_run_at: str | None
    locked_by: str | None
    locked_at: str | None
    publish_at: str | None
    payload_json: str
    result_json: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None

    @classmethod
    def from_row(cls, row) -> "JobRecord":
        data = dict(row)
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)
