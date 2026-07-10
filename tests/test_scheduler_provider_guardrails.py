from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import scheduler


def test_main_exits_when_provider_preflight_fails(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])

    class _StartupResult:
        ok = True
        errors = ()

    calls = {"ready": 0}

    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "_run_provider_preflight_check", lambda **_kwargs: (False, "credit balance low"))
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: calls.__setitem__("ready", calls["ready"] + 1) or ["demo"])

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 1
    assert calls["ready"] == 0


def test_main_skip_provider_preflight_flag(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--skip-provider-preflight"])

    class _StartupResult:
        ok = True
        errors = ()

    class _StopLoop(Exception):
        pass

    class _FakeEvery:
        @property
        def day(self):
            return self

        def at(self, *_args, **_kwargs):
            return self

        @property
        def hours(self):
            return self

        @property
        def hour(self):
            return self

        def do(self, *_args, **_kwargs):
            return self

    fake_schedule = SimpleNamespace(
        every=lambda *args, **kwargs: _FakeEvery(),
        run_pending=lambda: (_ for _ in ()).throw(_StopLoop()),
    )

    class _FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    fake_utils = SimpleNamespace(
        cleanup_old_renders=lambda **kwargs: None,
        notify_startup=lambda _n: None,
    )

    preflight_calls = {"count": 0}
    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(
        scheduler,
        "_run_provider_preflight_check",
        lambda **kwargs: preflight_calls.__setitem__("count", preflight_calls["count"] + 1) or (True, "skipped_by_flag"),
    )
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "setup_schedule", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "catch_up_overdue_queue_entries", lambda: {})
    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    monkeypatch.setattr(scheduler.threading, "Thread", _FakeThread)
    monkeypatch.setitem(sys.modules, "src.scheduler_utils", fake_utils)

    with pytest.raises(_StopLoop):
        scheduler.main()

    assert preflight_calls["count"] == 1


def test_render_and_schedule_skips_when_provider_circuit_open(monkeypatch):
    import src.channel_manager as channel_manager
    import src.scheduler_utils as scheduler_utils
    import src.pipeline as pipeline

    channel_cfg = SimpleNamespace(name="Demo Channel", upload_times=["10:00"]) 

    monkeypatch.setattr(channel_manager, "get_channel", lambda _cid: channel_cfg)
    monkeypatch.setattr(scheduler_utils, "check_disk_space", lambda **_kwargs: True)
    monkeypatch.setattr(
        scheduler_utils,
        "get_provider_circuit_status",
        lambda _provider: {"provider": "anthropic", "is_open": True, "retry_after_seconds": 120, "state": {}},
    )

    called = {"pipeline": 0, "notify": 0}

    def _never_run_pipeline(**_kwargs):
        called["pipeline"] += 1
        raise AssertionError("pipeline should not run while circuit is open")

    monkeypatch.setattr(pipeline, "run_full_pipeline", _never_run_pipeline)
    monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: called.__setitem__("notify", called["notify"] + 1) or {})
    monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)

    scheduler.render_and_schedule("demo_channel")

    assert called["pipeline"] == 0
    assert called["notify"] == 1
