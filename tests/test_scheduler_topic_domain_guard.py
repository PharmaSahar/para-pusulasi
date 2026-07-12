from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import scheduler
import pytest


def _prepare_common_domain_block_mocks(monkeypatch, tmp_path, *, queue_file=None):
    import src.channel_manager as channel_manager
    import src.scheduler_utils as scheduler_utils

    channel_cfg = SimpleNamespace(name="Demo Channel", upload_times=["10:00"], niche="saglik")

    qf = queue_file or (tmp_path / "channel_queue.json")
    if not qf.exists():
        qf.write_text("{}", encoding="utf-8")
    trail = tmp_path / "queue_quarantine_decisions.jsonl"
    health_file = tmp_path / "provider_health.json"

    monkeypatch.setattr(scheduler, "QUEUE_FILE", str(qf))
    monkeypatch.setattr(channel_manager, "get_channel", lambda _cid: channel_cfg)
    monkeypatch.setattr(scheduler_utils, "QUARANTINE_TRAIL_PATH", trail)
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(health_file))
    monkeypatch.setattr(scheduler_utils, "check_disk_space", lambda **_kwargs: True)
    monkeypatch.setattr(
        scheduler_utils,
        "get_provider_circuit_status",
        lambda _provider: {"provider": "anthropic", "is_open": False, "retry_after_seconds": 0, "state": {}},
    )
    monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(scheduler_utils, "notify_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)
    return qf, channel_cfg


def test_scheduler_quarantines_topic_domain_block(monkeypatch, tmp_path):
    import src.pipeline as pipeline
    queue_file, _ = _prepare_common_domain_block_mocks(monkeypatch, tmp_path)

    calls = {"pipeline": 0}

    def _raise_domain_block(**_kwargs):
        calls["pipeline"] += 1
        raise RuntimeError("topic_domain_blocked:no_valid_candidate niche=saglik")

    monkeypatch.setattr(pipeline, "run_full_pipeline", _raise_domain_block)

    scheduler.render_and_schedule("demo_channel")

    data = json.loads(queue_file.read_text(encoding="utf-8"))
    entry = data["demo_channel"][0]
    assert entry["status"] == "quarantined"
    assert entry["quarantine_reason"] == "topic_domain_blocked"
    assert "topic_domain_blocked" in entry.get("guard_reason_codes", [])
    assert entry.get("prevent_upload") is True
    assert entry.get("prevent_shorts_upload") is True
    assert calls["pipeline"] == 1


def test_scheduler_topic_domain_block_is_not_retried(monkeypatch):
    import src.scheduler_utils as scheduler_utils
    import src.pipeline as pipeline

    channel_cfg = SimpleNamespace(name="Demo Channel", upload_times=["10:00"], niche="saglik")
    calls = {"pipeline": 0}

    with patch("src.channel_manager.get_channel", lambda _cid: channel_cfg):
        monkeypatch.setattr(scheduler_utils, "check_disk_space", lambda **_kwargs: True)
        monkeypatch.setattr(
            scheduler_utils,
            "get_provider_circuit_status",
            lambda _provider: {"provider": "anthropic", "is_open": False, "retry_after_seconds": 0, "state": {}},
        )
        monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)

        def _raise_domain_block(**_kwargs):
            calls["pipeline"] += 1
            raise RuntimeError("topic_domain_blocked:no_valid_candidate niche=saglik")

        monkeypatch.setattr(pipeline, "run_full_pipeline", _raise_domain_block)
        scheduler.render_and_schedule("demo_channel")

    assert calls["pipeline"] == 1


def test_transient_provider_failure_remains_retryable(monkeypatch, tmp_path):
    import src.pipeline as pipeline

    queue_file, _ = _prepare_common_domain_block_mocks(monkeypatch, tmp_path)
    calls = {"pipeline": 0}

    def _transient_then_success(**_kwargs):
        calls["pipeline"] += 1
        if calls["pipeline"] < 3:
            raise RuntimeError("temporary network timeout")
        return {"video_id": "v123", "title": "ok", "youtube_url": "https://example.com/v123"}

    monkeypatch.setattr(pipeline, "run_full_pipeline", _transient_then_success)
    monkeypatch.setattr(scheduler.time, "sleep", lambda _s: None)
    scheduler.render_and_schedule("demo_channel")

    data = json.loads(queue_file.read_text(encoding="utf-8"))
    assert data["demo_channel"][0]["status"] == "active"
    assert calls["pipeline"] == 3


def test_quarantine_entry_contains_identity_fields(monkeypatch, tmp_path):
    import src.pipeline as pipeline

    queue_file, _ = _prepare_common_domain_block_mocks(monkeypatch, tmp_path)

    def _raise_domain_block_with_identity(**_kwargs):
        exc = RuntimeError("channel_topic_domain_mismatch: finance_in_health")
        setattr(exc, "_run_id", "run_001")
        setattr(exc, "_content_id", "content_001")
        setattr(exc, "_topic", "Dolar/TL 2027 tahmini")
        setattr(exc, "_detected_domain", "finance")
        setattr(exc, "_guard_reason_codes", ["channel_topic_domain_mismatch"])
        raise exc

    monkeypatch.setattr(pipeline, "run_full_pipeline", _raise_domain_block_with_identity)
    scheduler.render_and_schedule("demo_channel")

    data = json.loads(queue_file.read_text(encoding="utf-8"))
    entry = data["demo_channel"][0]
    assert entry["channel_id"] == "demo_channel"
    assert entry["run_id"] == "run_001"
    assert entry["content_id"] == "content_001"
    assert entry["topic"] == "Dolar/TL 2027 tahmini"
    assert entry["expected_niche"] == "saglik"
    assert entry["detected_domain"] == "finance"
    assert entry["source_stage"] == "scheduler.render_and_schedule"
    assert entry["retry_count"] == 1


def test_quarantine_duplicate_handling_is_idempotent(monkeypatch, tmp_path):
    import src.pipeline as pipeline

    queue_file, _ = _prepare_common_domain_block_mocks(monkeypatch, tmp_path)

    def _raise_repeatable_domain_block(**_kwargs):
        exc = RuntimeError("cross_channel_topic_contamination")
        setattr(exc, "_run_id", "run_dup")
        setattr(exc, "_content_id", "content_dup")
        setattr(exc, "_topic", "Borsa trendleri")
        setattr(exc, "_detected_domain", "finance")
        setattr(exc, "_guard_reason_codes", ["cross_channel_topic_contamination"])
        raise exc

    monkeypatch.setattr(pipeline, "run_full_pipeline", _raise_repeatable_domain_block)
    scheduler.render_and_schedule("demo_channel")
    scheduler.render_and_schedule("demo_channel")

    data = json.loads(queue_file.read_text(encoding="utf-8"))
    entries = data["demo_channel"]
    assert len(entries) == 1
    assert entries[0]["content_id"] == "content_dup"


def test_blocked_main_content_cannot_upload_short(monkeypatch, tmp_path):
    import src.pipeline as pipeline
    import src.scheduler_utils as scheduler_utils

    _, _ = _prepare_common_domain_block_mocks(monkeypatch, tmp_path)
    calls = {"notify_upload": 0}

    def _raise_domain_block(**_kwargs):
        raise RuntimeError("domain_policy_forbidden_keyword")

    monkeypatch.setattr(pipeline, "run_full_pipeline", _raise_domain_block)
    monkeypatch.setattr(
        scheduler_utils,
        "notify_upload",
        lambda *_args, **_kwargs: calls.__setitem__("notify_upload", calls["notify_upload"] + 1),
    )

    scheduler.render_and_schedule("demo_channel")

    assert calls["notify_upload"] == 0


def test_retry_resume_cannot_bypass_terminal_domain_block(monkeypatch, tmp_path):
    import src.pipeline as pipeline

    queue_file, _ = _prepare_common_domain_block_mocks(monkeypatch, tmp_path)

    def _raise_domain_block(**_kwargs):
        raise RuntimeError("topic_provenance_collision")

    monkeypatch.setattr(pipeline, "run_full_pipeline", _raise_domain_block)
    scheduler.render_and_schedule("demo_channel")

    data = json.loads(queue_file.read_text(encoding="utf-8"))
    entry = data["demo_channel"][0]
    assert entry["status"] == "quarantined"
    assert entry.get("video_id") is None
    assert entry.get("review_status") == "pending"


def test_domain_block_does_not_consume_general_retry_budget(monkeypatch, tmp_path):
    import src.pipeline as pipeline

    _, _ = _prepare_common_domain_block_mocks(monkeypatch, tmp_path)
    calls = {"pipeline": 0}

    def _raise_domain_block(**_kwargs):
        calls["pipeline"] += 1
        raise RuntimeError("domain_policy_forbidden_keyword")

    monkeypatch.setattr(pipeline, "run_full_pipeline", _raise_domain_block)
    scheduler.render_and_schedule("demo_channel")

    assert calls["pipeline"] == 1
