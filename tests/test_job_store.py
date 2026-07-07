import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.job_migrations import apply_schema
from src.job_models import JobStatus
from src.job_store import (
    admin_requeue_job,
    bootstrap_legacy_queue,
    count_jobs,
    create_job,
    initialize_database,
    list_jobs,
    open_database,
    transition_job_status,
)


def _new_connection(tmp_path):
    db_path = tmp_path / "jobs.db"
    initialize_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def test_schema_contains_required_tables_indexes_and_constraints(tmp_path):
    db_path = tmp_path / "jobs.db"
    initialize_database(db_path)
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"jobs", "job_stage_runs", "job_events", "migrations_meta"} <= tables

        jobs_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()[0]
        assert "CHECK (status IN" in jobs_sql
        assert "UNIQUE" in jobs_sql

        index_names = {
            row[1]
            for row in conn.execute("PRAGMA index_list('jobs')").fetchall()
        }
        assert "idx_jobs_status_next_run_priority" in index_names
        assert "idx_jobs_channel_status" in index_names
        assert "idx_jobs_publish_at" in index_names
    finally:
        conn.close()


@pytest.mark.parametrize(
    "current,target,allowed",
    [
        (JobStatus.QUEUED.value, JobStatus.RUNNING.value, True),
        (JobStatus.RUNNING.value, JobStatus.DONE.value, True),
        (JobStatus.RUNNING.value, JobStatus.FAILED.value, True),
        (JobStatus.FAILED.value, JobStatus.RETRYING.value, True),
        (JobStatus.RETRYING.value, JobStatus.QUEUED.value, True),
        (JobStatus.QUEUED.value, JobStatus.DONE.value, False),
        (JobStatus.DONE.value, JobStatus.RUNNING.value, False),
        (JobStatus.DEAD.value, JobStatus.QUEUED.value, False),
        (JobStatus.CANCELLED.value, JobStatus.QUEUED.value, False),
    ],
)
def test_state_transition_rules(current, target, allowed):
    from src.job_models import can_transition

    assert can_transition(current, target) is allowed


def test_idempotency_prevents_duplicate_jobs(tmp_path):
    conn = _new_connection(tmp_path)
    try:
        payload = {"title": "2026 ekonomi görünümü", "publish_at": "2026-07-07T20:00:00+03:00"}
        first = create_job(
            conn,
            channel_id="egitim_rehberi",
            workflow_type="render_schedule",
            payload=payload,
            publish_at=payload["publish_at"],
        )
        second = create_job(
            conn,
            channel_id="egitim_rehberi",
            workflow_type="render_schedule",
            payload=payload,
            publish_at=payload["publish_at"],
        )

        assert first.id == second.id
        assert count_jobs(conn) == 1
    finally:
        conn.close()


def test_admin_recovery_only_allows_dead_or_cancelled_to_queued(tmp_path):
    conn = _new_connection(tmp_path)
    try:
        dead_job = create_job(
            conn,
            channel_id="egitim_rehberi",
            workflow_type="render_schedule",
            payload={"title": "A", "publish_at": "2026-07-07T20:00:00+03:00"},
            publish_at="2026-07-07T20:00:00+03:00",
        )
        transition_job_status(conn, dead_job.id, JobStatus.RUNNING.value)
        transition_job_status(conn, dead_job.id, JobStatus.FAILED.value)
        transition_job_status(conn, dead_job.id, JobStatus.DEAD.value)
        recovered = admin_requeue_job(conn, dead_job.id, reason="manual recovery")
        assert recovered.status == JobStatus.QUEUED.value

        cancelled_job = create_job(
            conn,
            channel_id="teknoloji_pusulasi",
            workflow_type="render_schedule",
            payload={"title": "B", "publish_at": "2026-07-07T21:00:00+03:00"},
            publish_at="2026-07-07T21:00:00+03:00",
        )
        transition_job_status(conn, cancelled_job.id, JobStatus.RUNNING.value)
        transition_job_status(conn, cancelled_job.id, JobStatus.CANCELLED.value)
        recovered_two = admin_requeue_job(conn, cancelled_job.id, reason="manual recovery")
        assert recovered_two.status == JobStatus.QUEUED.value

        queued_job = create_job(
            conn,
            channel_id="kariyer_pusulasi",
            workflow_type="render_schedule",
            payload={"title": "C", "publish_at": "2026-07-07T22:00:00+03:00"},
            publish_at="2026-07-07T22:00:00+03:00",
        )
        with pytest.raises(ValueError):
            admin_requeue_job(conn, queued_job.id, reason="not allowed")
    finally:
        conn.close()


def test_legacy_queue_bootstrap_is_idempotent(tmp_path):
    conn = _new_connection(tmp_path)
    try:
        queue = {
            "egitim_rehberi": [
                {"title": "A", "publish_at": "2026-07-07T20:00:00+03:00", "youtube_url": "u1"},
                {"title": "A", "publish_at": "2026-07-07T20:00:00+03:00", "youtube_url": "u1"},
            ],
            "teknoloji_pusulasi": [
                {"title": "B", "publish_at": "2026-07-07T21:00:00+03:00", "youtube_url": "u2"},
            ],
        }
        created_first = bootstrap_legacy_queue(conn, queue)
        created_second = bootstrap_legacy_queue(conn, queue)

        assert len(created_first) == 3
        assert len(created_second) == 3
        assert count_jobs(conn) == 2

        jobs = list_jobs(conn)
        assert {job.channel_id for job in jobs} == {"egitim_rehberi", "teknoloji_pusulasi"}
        payload = json.loads(jobs[0].payload_json)
        assert "legacy_entry" in payload
    finally:
        conn.close()
