from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import scheduler


@pytest.fixture(autouse=True)
def _stub_scheduler_singleton_lock(monkeypatch):
    monkeypatch.setattr(scheduler, "_acquire_scheduler_singleton_lock", lambda: None)
    monkeypatch.setattr(scheduler, "_release_scheduler_singleton_lock", lambda: None)


class _StopLoop(Exception):
    pass


class _FakeEvery:
    @property
    def day(self):
        return self

    @property
    def hour(self):
        return self

    def at(self, *_args, **_kwargs):
        return self

    @property
    def hours(self):
        return self

    def do(self, *_args, **_kwargs):
        return self


def test_scheduler_help_exits_successfully(monkeypatch, capsys):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--help"])

    scheduler.main()

    out = capsys.readouterr().out
    assert "Kullanim:" in out
    assert "python scheduler.py --help" in out


def test_scheduler_help_does_not_start_scheduler(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--help"])
    calls = {"ready": 0, "setup": 0, "thread": 0}

    def _fake_ready_channels():
        calls["ready"] += 1
        return ["demo"]

    def _fake_setup_schedule():
        calls["setup"] += 1
        return ["demo"]

    class _FakeThread:
        def __init__(self, *args, **kwargs):
            calls["thread"] += 1

        def start(self):
            calls["thread"] += 1

    monkeypatch.setattr(scheduler, "get_ready_channels", _fake_ready_channels)
    monkeypatch.setattr(scheduler, "setup_schedule", _fake_setup_schedule)
    monkeypatch.setattr(scheduler.threading, "Thread", _FakeThread)

    scheduler.main()

    assert calls == {"ready": 0, "setup": 0, "thread": 0}


def test_scheduler_health_check_exits_without_starting_scheduler(monkeypatch, capsys):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--health-check"])
    calls = {"startup": 0, "ready": 0}

    class _Result:
        ok = True
        errors = ()

    def _fake_startup_health(**_kwargs):
        calls["startup"] += 1
        return _Result()

    def _fake_ready_channels():
        calls["ready"] += 1
        return ["demo"]

    monkeypatch.setattr(scheduler, "_run_startup_health_check", _fake_startup_health)
    monkeypatch.setattr(scheduler, "get_ready_channels", _fake_ready_channels)

    scheduler.main()

    out = capsys.readouterr().out
    assert "Health check: PASS" in out
    assert calls == {"startup": 1, "ready": 0}


def test_scheduler_sync_analytics_now_runs_once_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--sync-analytics-now"])
    calls = {"refresh": 0}

    monkeypatch.setattr(scheduler, "refresh_live_analytics_job", lambda: calls.__setitem__("refresh", calls["refresh"] + 1))

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    out = capsys.readouterr().out
    assert "Live analytics sync: PASS" in out
    assert exc.value.code == 0
    assert calls == {"refresh": 1}


def test_scheduler_safety_check_now_runs_once_and_exits(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py", "--safety-check-now"])
    calls = {"safety": 0}

    monkeypatch.setattr(
        scheduler,
        "run_safety_check_once",
        lambda **_kwargs: calls.__setitem__("safety", calls["safety"] + 1) or 0,
    )

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 0
    assert calls == {"safety": 1}


def test_scheduler_default_startup_writes_safety_gate_result(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    calls = {"safety": 0}

    class _StartupResult:
        ok = True
        errors = ()

    class _StopLoop(Exception):
        pass

    class _FakeEvery:
        @property
        def day(self):
            return self

        @property
        def hour(self):
            return self

        @property
        def hours(self):
            return self

        def at(self, *_args, **_kwargs):
            return self

        def do(self, *_args, **_kwargs):
            return self

    class _FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    fake_schedule = SimpleNamespace(
        every=lambda *args, **kwargs: _FakeEvery(),
        run_pending=lambda: (_ for _ in ()).throw(_StopLoop()),
    )

    fake_utils = SimpleNamespace(
        cleanup_old_renders=lambda **kwargs: None,
        notify_startup=lambda _n: None,
    )

    def _fake_record(**_kwargs):
        calls["safety"] += 1
        return {"overall_ok": True}

    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "_run_provider_preflight_check", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(scheduler, "_record_safety_gate_result", _fake_record)
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "setup_schedule", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "catch_up_overdue_queue_entries", lambda: {})
    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    monkeypatch.setattr(scheduler.threading, "Thread", _FakeThread)
    monkeypatch.setitem(sys.modules, "src.scheduler_utils", fake_utils)

    with pytest.raises(_StopLoop):
        scheduler.main()

    assert calls["safety"] == 1


def test_scheduler_default_startup_path_unchanged(monkeypatch):
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    calls = {"setup": 0, "thread_start": 0, "cleanup": 0, "notify": 0}

    def _fake_ready_channels():
        return ["demo"]

    def _fake_setup_schedule():
        calls["setup"] += 1
        return ["demo"]

    class _FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            calls["thread_start"] += 1

    fake_schedule = SimpleNamespace(
        every=lambda *args, **kwargs: _FakeEvery(),
        run_pending=lambda: (_ for _ in ()).throw(_StopLoop()),
    )

    fake_utils = SimpleNamespace(
        cleanup_old_renders=lambda **kwargs: calls.__setitem__("cleanup", calls["cleanup"] + 1),
        notify_startup=lambda _n: calls.__setitem__("notify", calls["notify"] + 1),
    )

    class _StartupResult:
        ok = True
        errors = ()

    monkeypatch.setattr(
        scheduler,
        "_run_startup_health_check",
        lambda **_kwargs: _StartupResult(),
    )

    monkeypatch.setattr(scheduler, "get_ready_channels", _fake_ready_channels)
    monkeypatch.setattr(scheduler, "setup_schedule", _fake_setup_schedule)
    monkeypatch.setattr(scheduler.threading, "Thread", _FakeThread)
    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    monkeypatch.setitem(sys.modules, "src.scheduler_utils", fake_utils)

    with pytest.raises(_StopLoop):
        scheduler.main()

    assert calls["setup"] == 1
    assert calls["thread_start"] == 1
    assert calls["cleanup"] == 1
    assert calls["notify"] == 1
