"""SQLite schema and migration helpers for the durable job store."""
from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 1

JOB_STATUSES = ("queued", "running", "retrying", "done", "failed", "dead", "cancelled")

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS migrations_meta (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    workflow_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN {JOB_STATUSES}),
    priority INTEGER NOT NULL DEFAULT 100 CHECK (priority >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    next_run_at TEXT NULL,
    locked_by TEXT NULL,
    locked_at TEXT NULL,
    publish_at TEXT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT NULL,
    completed_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS job_stage_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    stage_status TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NULL,
    duration_ms INTEGER NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_payload_json TEXT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_next_run_priority
    ON jobs(status, next_run_at, priority);

CREATE INDEX IF NOT EXISTS idx_jobs_channel_status
    ON jobs(channel_id, status);

CREATE INDEX IF NOT EXISTS idx_jobs_publish_at
    ON jobs(publish_at);

CREATE INDEX IF NOT EXISTS idx_stage_runs_job_stage_attempt
    ON job_stage_runs(job_id, stage_name, attempt_no);

CREATE INDEX IF NOT EXISTS idx_job_events_job_created
    ON job_events(job_id, created_at);
"""


def apply_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT OR IGNORE INTO migrations_meta(version, name, applied_at) VALUES (?, ?, datetime('now'))",
        (SCHEMA_VERSION, "initial_job_store_schema"),
    )
    connection.commit()
