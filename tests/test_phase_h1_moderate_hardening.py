from __future__ import annotations

import json
import threading

import pytest

import src.production_quality_platform as pqp
import src.scheduler_utils as scheduler_utils
from src.production_quality_platform import run_stage_with_recovery


def test_provider_health_concurrent_failure_success_no_lost_state(tmp_path, monkeypatch):
    state_file = tmp_path / "state" / "provider_health.json"
    lock_file = tmp_path / "state" / "provider_health.lock"
    diag_file = tmp_path / "state" / "provider_health_diagnostics.jsonl"
    corruption_file = tmp_path / "state" / "provider_health_corruption.json"

    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(state_file))
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_LOCK_FILE", str(lock_file))
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_DIAGNOSTICS_FILE", diag_file)
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_CORRUPTION_FILE", corruption_file)

    providers = [f"provider_{idx}" for idx in range(12)]

    def _worker(name: str) -> None:
        scheduler_utils.record_provider_failure(name, "timeout")
        scheduler_utils.record_provider_success(name, note="ok")

    threads = [threading.Thread(target=_worker, args=(name,)) for name in providers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    stored = payload.get("providers") or {}

    assert set(stored.keys()) == set(providers)
    for name in providers:
        row = stored[name]
        assert row.get("consecutive_failures") == 0
        assert str(row.get("last_success_at") or "").strip()


def test_provider_health_corruption_fail_closed(tmp_path, monkeypatch):
    state_file = tmp_path / "state" / "provider_health.json"
    lock_file = tmp_path / "state" / "provider_health.lock"
    diag_file = tmp_path / "state" / "provider_health_diagnostics.jsonl"
    corruption_file = tmp_path / "state" / "provider_health_corruption.json"

    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(state_file))
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_LOCK_FILE", str(lock_file))
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_DIAGNOSTICS_FILE", diag_file)
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_CORRUPTION_FILE", corruption_file)

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{broken-json", encoding="utf-8")

    circuit = scheduler_utils.get_provider_circuit_status("anthropic")
    global_pause = scheduler_utils.get_global_overload_pause_status()

    assert circuit["is_open"] is True
    assert global_pause["is_open"] is True
    assert global_pause["reason"] == "provider_health_corrupt"
    assert circuit.get("corruption", {}).get("active") is True
    assert corruption_file.exists()
    assert diag_file.exists()


def test_upload_claim_single_winner_and_single_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(pqp, "UPLOAD_REGISTRY_PATH", tmp_path / "state" / "registry.json")
    monkeypatch.setattr(pqp, "UPLOAD_REGISTRY_LOCK_PATH", tmp_path / "state" / "registry.lock")

    key = pqp.build_idempotency_key(
        channel="ch1",
        generation_id="g1",
        publish_at="2026-07-11T10:00:00+00:00",
        title="Title",
    )

    barrier = threading.Barrier(5)
    results: list[dict] = []
    write_lock = threading.Lock()

    def _claim_worker(index: int) -> None:
        barrier.wait()
        claim = pqp.claim_upload_before_side_effect(
            idempotency_key=key,
            claim_payload={"worker": index},
        )
        with write_lock:
            results.append(claim)

    threads = [threading.Thread(target=_claim_worker, args=(idx,)) for idx in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    claimed = [item for item in results if item.get("status") == "claimed"]
    already_claimed = [item for item in results if item.get("status") == "already_claimed"]

    assert len(claimed) == 1
    assert len(already_claimed) == 4

    winner = claimed[0]
    token = str(winner.get("claim_token") or "")
    assert token

    committed = pqp.commit_upload_claim(
        idempotency_key=key,
        claim_token=token,
        payload={
            "video_id": "vid123",
            "channel": "ch1",
            "title": "Title",
            "youtube_url": "https://youtube.com/watch?v=vid123",
        },
    )
    assert committed.get("status") == "committed"

    found = pqp.get_registered_upload(key)
    assert found is not None
    assert found.get("video_id") == "vid123"


def test_nested_retry_budget_shared_and_bounded(monkeypatch):
    monkeypatch.setattr(pqp.time, "sleep", lambda _seconds: None)

    inner_calls = {"count": 0}

    def _inner_once():
        inner_calls["count"] += 1
        raise RuntimeError("timeout")

    def _outer_once():
        return run_stage_with_recovery(
            stage="inner_upload",
            fn=_inner_once,
            max_attempts=4,
            base_backoff_seconds=0.0,
        )[0]

    with pytest.raises(RuntimeError, match="timeout"):
        run_stage_with_recovery(
            stage="outer_upload",
            fn=_outer_once,
            max_attempts=4,
            base_backoff_seconds=0.0,
        )

    # Shared retry budget means outer layer cannot restart inner retries indefinitely.
    assert inner_calls["count"] == 4
