from __future__ import annotations

from types import SimpleNamespace

import pytest


class StopSchedulerLoop(RuntimeError):
    pass


class FakeJob:
    def __init__(self, jobs, label):
        self.jobs = jobs
        self.label = label

    def at(self, value):
        return self

    def do(self, func, **kwargs):
        self.jobs.append((self.label, func, kwargs))
        return self


class FakeEvery:
    def __init__(self, jobs, label):
        self.jobs = jobs
        self.label = label
        self.monday = FakeJob(jobs, "monday")
        self.tuesday = FakeJob(jobs, "tuesday")
        self.wednesday = FakeJob(jobs, "wednesday")
        self.thursday = FakeJob(jobs, "thursday")
        self.friday = FakeJob(jobs, "friday")
        self.saturday = FakeJob(jobs, "saturday")
        self.sunday = FakeJob(jobs, "sunday")

    @property
    def hour(self):
        return FakeJob(self.jobs, "hour")

    @property
    def hours(self):
        return FakeJob(self.jobs, "hours")

    @property
    def day(self):
        return FakeJob(self.jobs, "day")


class FakeSchedule:
    def __init__(self):
        self.jobs = []
        self.run_pending_calls = 0

    def every(self, *_args):
        label = "interval" if _args else "every"
        return FakeEvery(self.jobs, label)

    def run_pending(self):
        self.run_pending_calls += 1
        raise StopSchedulerLoop


def _cfg(channel_id: str):
    return SimpleNamespace(channel_id=channel_id, name=channel_id, upload_times=["08:00", "20:00"])


def _patch_common_startup(monkeypatch, tmp_path, scheduler, *, ready=("demo",), queue=None):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(scheduler, "_assert_preprod_isolation_paths", lambda: None)
    monkeypatch.setattr(scheduler, "_acquire_scheduler_singleton_lock", lambda: None)
    monkeypatch.setattr(scheduler, "_release_scheduler_singleton_lock", lambda: None)
    monkeypatch.setattr(scheduler, "_write_pid_record", lambda: None)
    monkeypatch.setattr(scheduler, "_run_startup_preflight", lambda **_kw: (SimpleNamespace(ok=True, errors=[]), True, "ok", list(ready), []))
    monkeypatch.setattr(scheduler, "_evaluate_scheduler_startup_production_safety_gate", lambda **_kw: {"ok": True})
    monkeypatch.setattr(scheduler, "_record_safety_gate_result", lambda **_kw: {})
    monkeypatch.setattr(scheduler, "_resolve_live_collector_runtime", lambda: (False, "no_go_api_not_enabled"))
    monkeypatch.setattr(scheduler, "notify_startup", lambda *_args, **_kw: None, raising=False)
    monkeypatch.setattr(scheduler, "cleanup_old_renders", lambda **_kw: 0, raising=False)
    monkeypatch.setattr(scheduler, "_observation_mode_active", lambda: False)
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: list(ready))
    monkeypatch.setattr(scheduler, "load_queue", lambda: dict(queue or {}))
    monkeypatch.setattr(scheduler, "update_queue", lambda mutator: dict(queue or {}))
    monkeypatch.setattr("src.channel_manager.get_channel", lambda cid: _cfg(cid))
    monkeypatch.setattr(scheduler.time, "sleep", lambda *_args, **_kw: None)
    fake_schedule = FakeSchedule()
    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    return fake_schedule


def test_main_does_not_call_initial_fill_by_default(monkeypatch, tmp_path):
    import scheduler

    _patch_common_startup(monkeypatch, tmp_path, scheduler)
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    monkeypatch.setattr(scheduler, "initial_fill", lambda **_kw: (_ for _ in ()).throw(AssertionError("initial_fill called")))

    with pytest.raises(StopSchedulerLoop):
        scheduler.main()


def test_main_does_not_create_initial_fill_thread(monkeypatch, tmp_path):
    import scheduler

    _patch_common_startup(monkeypatch, tmp_path, scheduler)
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])

    def fake_thread(*_args, **kwargs):
        if kwargs.get("name") == "initial-fill":
            raise AssertionError("initial-fill thread created")
        return SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(scheduler.threading, "Thread", fake_thread)

    with pytest.raises(StopSchedulerLoop):
        scheduler.main()


def test_startup_inspection_empty_queue_submits_zero(monkeypatch):
    import scheduler

    submissions = []
    events = []
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["a"])
    monkeypatch.setattr(scheduler, "load_queue", lambda: {})
    monkeypatch.setattr(scheduler, "record_production_event", lambda event: events.append(dict(event)))
    monkeypatch.setattr(scheduler, "_resolve_git_head_short", lambda: "abc123")
    monkeypatch.setattr(scheduler, "_submit_render", lambda *args, **kwargs: submissions.append((args, kwargs)))

    decision = scheduler.inspect_startup_generation_candidates()

    assert decision["generation_allowed"] is False
    assert decision["submitted_channels"] == []
    assert decision["eligible_channels"] == ["a"]
    assert submissions == []
    assert events[-1]["event_type"] == "startup_content_generation_decision"


def test_startup_inspection_multiple_eligible_channels_submits_zero(monkeypatch):
    import scheduler

    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["a", "b"])
    monkeypatch.setattr(scheduler, "load_queue", lambda: {"a": [], "b": [{"status": "quarantined"}]})
    monkeypatch.setattr(scheduler, "record_production_event", lambda _event: None)
    decision = scheduler.inspect_startup_generation_candidates()

    assert decision["eligible_channels"] == ["a", "b"]
    assert decision["submitted_channels"] == []


def test_restart_simulation_produces_zero_render_submissions(monkeypatch, tmp_path):
    import scheduler

    _patch_common_startup(monkeypatch, tmp_path, scheduler, ready=("a", "b"), queue={})
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    submissions = []
    monkeypatch.setattr(scheduler, "_submit_render", lambda *args, **kwargs: submissions.append((args, kwargs)))

    with pytest.raises(StopSchedulerLoop):
        scheduler.main()

    assert submissions == []


def test_initial_fill_explicit_trigger_submits_eligible_channels(monkeypatch):
    import scheduler

    submissions = []
    monkeypatch.setattr(scheduler, "_observation_mode_active", lambda: False)
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["a", "b"])
    monkeypatch.setattr(scheduler, "load_queue", lambda: {"b": [{"status": "active"}]})
    monkeypatch.setattr(scheduler, "update_queue", lambda mutator: {"b": [{"status": "active"}]})
    monkeypatch.setattr(scheduler, "_submit_render", lambda cid, *, trigger_source: submissions.append((cid, trigger_source)))
    monkeypatch.setattr(scheduler, "record_production_event", lambda _event: None)
    monkeypatch.setattr(scheduler.time, "sleep", lambda *_args, **_kw: None)

    scheduler.initial_fill(trigger_source="explicit_initial_fill")

    assert submissions == [("a", "explicit_initial_fill")]


def test_initial_fill_observation_mode_still_blocks(monkeypatch):
    import scheduler

    monkeypatch.setattr(scheduler, "_observation_mode_active", lambda: True)
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: (_ for _ in ()).throw(AssertionError("enumerated channels")))

    assert scheduler.initial_fill(trigger_source="explicit_initial_fill") is None


def test_initial_fill_invalid_trigger_fails_closed():
    import scheduler

    with pytest.raises(ValueError, match="initial_fill_requires_explicit_trigger"):
        scheduler.initial_fill(trigger_source="scheduled_slot")


def test_missing_trigger_source_fails_closed():
    import scheduler

    with pytest.raises(ValueError, match="invalid_render_trigger_source:<missing>"):
        scheduler._submit_render("a", trigger_source="")


def test_invalid_trigger_source_fails_closed():
    import scheduler

    with pytest.raises(ValueError, match="invalid_render_trigger_source"):
        scheduler._submit_render("a", trigger_source="unknown")


def test_render_and_schedule_propagates_trigger_source_to_pipeline(monkeypatch):
    import scheduler

    captured = {}
    lock = SimpleNamespace(acquire=lambda blocking=False: True, release=lambda: None)
    monkeypatch.setattr(scheduler, "_get_channel_render_lock", lambda _cid: lock)
    monkeypatch.setattr(scheduler, "canary_gate_decision", lambda _cid: {"allow": True})
    monkeypatch.setattr("src.scheduler_utils.check_disk_space", lambda **_kw: True)
    monkeypatch.setattr("src.scheduler_utils.get_global_overload_pause_status", lambda: {"is_open": False})
    monkeypatch.setattr("src.scheduler_utils.get_provider_circuit_status", lambda _provider: {"is_open": False})
    monkeypatch.setattr("src.scheduler_utils.record_provider_success", lambda *_args, **_kw: None)
    monkeypatch.setattr("src.scheduler_utils.save_used_topic", lambda *_args, **_kw: None)
    monkeypatch.setattr("src.scheduler_utils.notify_upload", lambda *_args, **_kw: None)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda cid: _cfg(cid))
    monkeypatch.setattr(scheduler, "load_queue", lambda: {})
    monkeypatch.setattr(scheduler, "update_queue", lambda mutator: {})
    monkeypatch.setattr(scheduler, "get_next_upload_time", lambda *_args, **_kw: "2026-07-18T20:00:00+03:00")

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {"video_id": None, "upload_error": "blocked in test", "upload_metadata": {}}

    monkeypatch.setattr("src.pipeline.run_full_pipeline", fake_pipeline)

    scheduler.render_and_schedule("a", trigger_source="recurring_empty_queue_fill")

    assert captured["trigger_source"] == "recurring_empty_queue_fill"


def test_explicit_initial_fill_cli_runs_preflight_and_fill(monkeypatch, tmp_path):
    import scheduler

    _patch_common_startup(monkeypatch, tmp_path, scheduler)
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--initial-fill"])
    calls = []
    monkeypatch.setattr(scheduler, "initial_fill", lambda *, trigger_source: calls.append(trigger_source))

    scheduler.main()

    assert calls == ["explicit_initial_fill"]


def test_recurring_fill_submits_with_recurring_trigger(monkeypatch):
    import scheduler

    submissions = []
    monkeypatch.setattr(scheduler, "_observation_mode_active", lambda: False)
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["a"])
    monkeypatch.setattr(scheduler, "update_queue", lambda mutator: {})
    monkeypatch.setattr("src.channel_manager.get_channel", lambda cid: _cfg(cid))
    monkeypatch.setattr(scheduler, "get_next_upload_time", lambda *_args, **_kw: "2026-07-18T20:00:00+03:00")
    monkeypatch.setattr(scheduler, "_submit_render", lambda cid, *, trigger_source: submissions.append((cid, trigger_source)))
    monkeypatch.setattr(scheduler.time, "sleep", lambda *_args, **_kw: None)

    scheduler.fill_empty_queues_job()

    assert submissions == [("a", "recurring_empty_queue_fill"), ("a", "recurring_empty_queue_fill")]


def test_recurring_registration_does_not_execute_generation(monkeypatch, tmp_path):
    import scheduler

    fake_schedule = _patch_common_startup(monkeypatch, tmp_path, scheduler)
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    submissions = []
    monkeypatch.setattr(scheduler, "_submit_render", lambda *args, **kwargs: submissions.append((args, kwargs)))

    with pytest.raises(StopSchedulerLoop):
        scheduler.main()

    assert any(job[1] is scheduler.fill_empty_queues_job for job in fake_schedule.jobs)
    assert submissions == []


def test_overdue_startup_catchup_does_not_create_render(monkeypatch):
    import scheduler

    submissions = []
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["a"])
    monkeypatch.setattr(scheduler, "load_queue", lambda: {"a": [{"status": "active", "publish_at": "2000-01-01T00:00:00+00:00", "title": "old"}]})
    monkeypatch.setattr(scheduler, "update_queue", lambda mutator: {})
    monkeypatch.setattr("src.channel_manager.get_channel", lambda cid: _cfg(cid))
    monkeypatch.setattr(scheduler, "_submit_render", lambda *args, **kwargs: submissions.append((args, kwargs)))

    caught_up = scheduler.catch_up_overdue_queue_entries()

    assert caught_up == {}
    assert submissions == []


def test_pipeline_stage_telemetry_includes_trigger_source(monkeypatch, tmp_path):
    import src.pipeline as pipeline

    cfg = SimpleNamespace(
        channel_id="demo",
        output_dir=str(tmp_path / "output"),
        scripts_dir=str(tmp_path / "scripts"),
        audio_dir=str(tmp_path / "audio"),
        videos_dir=str(tmp_path / "videos"),
        logs_dir=str(tmp_path / "logs"),
        niche="demo",
        pexels_query="demo",
        thumbnail_selection_policy="first",
        ensure_directories=lambda: None,
    )
    for path in (tmp_path / "output", tmp_path / "scripts", tmp_path / "audio", tmp_path / "videos", tmp_path / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    emitted = []
    monkeypatch.setattr(pipeline, "production_observation_mode_enabled", lambda: True)
    monkeypatch.setattr(pipeline, "emit_event", lambda envelope, logger=None: emitted.append(envelope))
    monkeypatch.setattr(pipeline, "record_production_event", lambda _payload: None)
    monkeypatch.setattr(pipeline, "evaluate_visual_query", lambda **_kw: SimpleNamespace(allowed=True, rewritten_query="", to_dict=lambda: {"allowed": True}))
    monkeypatch.setattr(pipeline, "build_visual_manifest", lambda **kwargs: tmp_path / "visual_manifest.json")
    monkeypatch.setattr(pipeline, "evaluate_production_safety_gate", lambda **_kw: SimpleNamespace(allowed=False, blocking_reason="production_observation_mode", to_dict=lambda: {"ok": False}))

    result = pipeline.run_full_pipeline(channel_cfg=cfg, trigger_source="explicit_initial_fill")

    assert result["trigger_source"] == "explicit_initial_fill"
