import json


def test_json_mode_keeps_json_flow_without_shadow_call(tmp_path, monkeypatch):
    import scheduler
    import src.job_store as job_store

    queue_file = tmp_path / "channel_queue.json"
    monkeypatch.setattr(scheduler, "QUEUE_FILE", str(queue_file))
    monkeypatch.setenv("JOB_STORE_MODE", "json")

    calls = {"count": 0}

    def fake_mirror(*args, **kwargs):
        calls["count"] += 1
        return {"expected": 0, "mirrored": 0, "missing_count": 0, "missing": []}

    monkeypatch.setattr(job_store, "mirror_legacy_queue_snapshot", fake_mirror)

    payload = {
        "test-channel": [
            {
                "video_id": "v1",
                "title": "title",
                "youtube_url": "https://youtube.com/watch?v=v1",
                "publish_at": "2026-07-07T20:00:00+03:00",
                "rendered_at": "2026-07-07T18:00:00+03:00",
            }
        ]
    }
    scheduler.save_queue(payload)

    assert queue_file.exists()
    saved = json.loads(queue_file.read_text(encoding="utf-8"))
    assert saved == payload
    assert calls["count"] == 0


def test_shadow_mode_mirrors_and_logs_parity_mismatch(tmp_path, monkeypatch, caplog):
    import scheduler
    import src.job_store as job_store

    queue_file = tmp_path / "channel_queue.json"
    monkeypatch.setattr(scheduler, "QUEUE_FILE", str(queue_file))
    monkeypatch.setenv("JOB_STORE_MODE", "shadow")
    monkeypatch.setenv("JOB_STORE_DB_PATH", str(tmp_path / "shadow.db"))

    calls = {"count": 0}

    def fake_mirror(queue_data, *, db_path, workflow_type="render_schedule_shadow"):
        calls["count"] += 1
        return {
            "expected": 1,
            "mirrored": 1,
            "missing_count": 1,
            "missing": ["missing-key"],
        }

    monkeypatch.setattr(job_store, "mirror_legacy_queue_snapshot", fake_mirror)

    caplog.clear()
    caplog.set_level("WARNING")

    def mutator(queue):
        queue.setdefault("test-channel", []).append(
            {
                "video_id": "v1",
                "title": "title",
                "youtube_url": "https://youtube.com/watch?v=v1",
                "publish_at": "2026-07-07T20:00:00+03:00",
                "rendered_at": "2026-07-07T18:00:00+03:00",
            }
        )

    scheduler.update_queue(mutator)

    saved = json.loads(queue_file.read_text(encoding="utf-8"))
    assert "test-channel" in saved
    assert calls["count"] == 1
    assert "Shadow parity mismatch" in caplog.text


def test_shadow_failure_isolation_never_blocks_json_write(tmp_path, monkeypatch, caplog):
    import scheduler
    import src.job_store as job_store

    queue_file = tmp_path / "channel_queue.json"
    monkeypatch.setattr(scheduler, "QUEUE_FILE", str(queue_file))
    monkeypatch.setenv("JOB_STORE_MODE", "shadow")
    monkeypatch.setenv("JOB_STORE_DB_PATH", str(tmp_path / "shadow.db"))

    def exploding_mirror(*args, **kwargs):
        raise RuntimeError("shadow mirror down")

    monkeypatch.setattr(job_store, "mirror_legacy_queue_snapshot", exploding_mirror)

    caplog.clear()
    caplog.set_level("WARNING")

    def mutator(queue):
        queue.setdefault("test-channel", []).append(
            {
                "video_id": "v2",
                "title": "title 2",
                "youtube_url": "https://youtube.com/watch?v=v2",
                "publish_at": "2026-07-07T21:00:00+03:00",
                "rendered_at": "2026-07-07T18:30:00+03:00",
            }
        )

    scheduler.update_queue(mutator)

    assert queue_file.exists()
    saved = json.loads(queue_file.read_text(encoding="utf-8"))
    assert saved["test-channel"][0]["video_id"] == "v2"
    assert "Shadow mirror failed (non-blocking)" in caplog.text


def test_observation_mode_blocks_scheduler_queue_writes(tmp_path, monkeypatch, caplog):
    import scheduler

    queue_file = tmp_path / "channel_queue.json"
    queue_file.write_text(json.dumps({"test-channel": [{"video_id": "existing"}]}), encoding="utf-8")
    before = queue_file.read_text(encoding="utf-8")
    monkeypatch.setattr(scheduler, "QUEUE_FILE", str(queue_file))
    monkeypatch.setenv("PRODUCTION_OBSERVATION_MODE", "true")
    caplog.set_level("WARNING")

    scheduler.save_queue({"test-channel": [{"video_id": "new"}]})
    scheduler.update_queue(lambda queue: queue.setdefault("test-channel", []).append({"video_id": "mutated"}))

    assert queue_file.read_text(encoding="utf-8") == before
    assert "production_observation_mode" in caplog.text


def test_observation_mode_skips_provider_preflight(monkeypatch):
    import scheduler

    monkeypatch.setenv("PRODUCTION_OBSERVATION_MODE", "true")

    def forbidden_preflight(*_args, **_kwargs):
        raise AssertionError("provider preflight must not run in observation mode")

    monkeypatch.setattr("src.scheduler_utils.run_anthropic_preflight", forbidden_preflight)

    ok, detail = scheduler._run_provider_preflight_check()

    assert ok is True
    assert detail == "skipped_by_production_observation_mode"


def test_observation_mode_skips_automatic_queue_fill(monkeypatch, caplog):
    import scheduler

    monkeypatch.setenv("PRODUCTION_OBSERVATION_MODE", "true")

    def forbidden_ready_channels():
        raise AssertionError("automatic fill must not enumerate channels in observation mode")

    monkeypatch.setattr(scheduler, "get_ready_channels", forbidden_ready_channels)
    caplog.set_level("WARNING")

    scheduler.initial_fill()
    scheduler.fill_empty_queues_job()

    assert "Initial fill skipped: production_observation_mode" in caplog.text
    assert "Automatic queue fill skipped: production_observation_mode" in caplog.text
