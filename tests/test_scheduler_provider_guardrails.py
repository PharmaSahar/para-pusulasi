from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scheduler
from src.scheduler_utils import (
    classify_provider_preflight_degraded_mode_error,
    _classify_error_decision,
    get_global_overload_pause_status,
    get_provider_circuit_status,
    notify_error,
    record_provider_failure,
)

TEST_TRIGGER_SOURCE = "manual_operator"


@pytest.fixture(autouse=True)
def _stub_scheduler_singleton_lock(monkeypatch):
    monkeypatch.setattr(scheduler, "_acquire_scheduler_singleton_lock", lambda: None)
    monkeypatch.setattr(scheduler, "_release_scheduler_singleton_lock", lambda: None)


@pytest.fixture(autouse=True)
def _isolate_production_dashboard_paths(monkeypatch, tmp_path: Path):
    dashboard_md_path = tmp_path / "production_dashboard_latest.md"
    dashboard_json_path = tmp_path / "production_dashboard_latest.json"

    monkeypatch.setenv("PRODUCTION_DASHBOARD_MD_PATH", str(dashboard_md_path))
    monkeypatch.setenv("PRODUCTION_DASHBOARD_JSON_PATH", str(dashboard_json_path))

    # scheduler imports update_production_dashboard at module import time, so patch
    # function globals directly to avoid writes to tracked repo docs during tests.
    prod_globals = scheduler.update_production_dashboard.__globals__
    monkeypatch.setitem(prod_globals, "PRODUCTION_DASHBOARD_MD_PATH", dashboard_md_path)
    monkeypatch.setitem(prod_globals, "PRODUCTION_DASHBOARD_JSON_PATH", dashboard_json_path)


def test_main_exits_when_provider_preflight_fails(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", "0")
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


def test_main_continues_when_provider_preflight_fails_when_degraded_mode_enabled(monkeypatch, caplog):
    monkeypatch.setenv("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED", "1")
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    caplog.set_level("WARNING")

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

    import src.scheduler_utils as scheduler_utils

    calls = {"ready": 0}
    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(
        scheduler,
        "_run_provider_preflight_check",
        lambda **_kwargs: (False, "HTTP 400 credit balance is too low"),
    )
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: calls.__setitem__("ready", calls["ready"] + 1) or ["demo"])
    monkeypatch.setattr(
        scheduler,
        "_evaluate_scheduler_startup_production_safety_gate",
        lambda **_kwargs: {
            "ok": False,
            "status": "blocked",
            "blocking_reason": "provider_circuit_open",
            "checks": [
                {
                    "status": "fail",
                    "severity": "critical",
                    "reason": "provider_circuit_open",
                    "message": "Provider circuit is open",
                    "evidence": {},
                }
            ],
        },
    )
    monkeypatch.setattr(scheduler, "setup_schedule", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "catch_up_overdue_queue_entries", lambda: {})
    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    monkeypatch.setattr(scheduler.threading, "Thread", _FakeThread)
    monkeypatch.setattr(scheduler_utils, "cleanup_old_renders", lambda **kwargs: None)
    monkeypatch.setattr(scheduler_utils, "notify_startup", lambda _n: None)

    with pytest.raises(_StopLoop):
        scheduler.main()

    assert calls["ready"] == 1
    assert "STARTUP_PROVIDER_PREFLIGHT_DEGRADED" in caplog.text
    assert "STARTUP_PROVIDER_PREFLIGHT_DEGRADED_GATE_OVERRIDE" in caplog.text


def test_main_stays_fail_closed_for_unknown_provider_error_even_when_degraded_mode_enabled(monkeypatch):
    monkeypatch.setenv("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED", "1")
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])

    class _StartupResult:
        ok = True
        errors = ()

    calls = {"ready": 0}

    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "_run_provider_preflight_check", lambda **_kwargs: (False, "unexpected serialization panic"))
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: calls.__setitem__("ready", calls["ready"] + 1) or ["demo"])

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 1
    assert calls["ready"] == 0


def test_main_health_check_failure_still_exits_when_degraded_mode_enabled(monkeypatch):
    monkeypatch.setenv("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED", "1")
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])

    class _StartupResult:
        ok = False
        errors = ("missing required runtime file",)

    calls = {"provider": 0, "ready": 0}

    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(
        scheduler,
        "_run_provider_preflight_check",
        lambda **_kwargs: calls.__setitem__("provider", calls["provider"] + 1) or (True, "ok"),
    )
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: calls.__setitem__("ready", calls["ready"] + 1) or ["demo"])

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 1
    assert calls["provider"] == 0
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
    monkeypatch.setenv("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", "0")
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

    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)

    assert called["pipeline"] == 0
    assert called["notify"] == 1


def test_render_and_schedule_skips_when_global_overload_pause_open(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", "0")
    import src.channel_manager as channel_manager
    import src.scheduler_utils as scheduler_utils
    import src.pipeline as pipeline

    channel_cfg = SimpleNamespace(name="Demo Channel", upload_times=["10:00"])

    monkeypatch.setattr(channel_manager, "get_channel", lambda _cid: channel_cfg)
    monkeypatch.setattr(scheduler_utils, "check_disk_space", lambda **_kwargs: True)
    monkeypatch.setattr(
        scheduler_utils,
        "get_global_overload_pause_status",
        lambda: {
            "is_open": True,
            "retry_after_seconds": 480,
            "pause_until": "2099-01-01T00:00:00Z",
            "reason": "overload_storm:3/300s",
        },
    )
    monkeypatch.setattr(
        scheduler_utils,
        "get_provider_circuit_status",
        lambda _provider: {"provider": "anthropic", "is_open": False, "retry_after_seconds": 0, "state": {}},
    )

    called = {"pipeline": 0, "notify": 0}

    def _never_run_pipeline(**_kwargs):
        called["pipeline"] += 1
        raise AssertionError("pipeline should not run while global overload pause is open")

    monkeypatch.setattr(pipeline, "run_full_pipeline", _never_run_pipeline)
    monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: called.__setitem__("notify", called["notify"] + 1) or {})
    monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)

    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)


def test_render_and_schedule_skips_when_production_safety_gate_blocks(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", "0")
    import src.channel_manager as channel_manager
    import src.scheduler_utils as scheduler_utils
    import src.pipeline as pipeline
    from src.production_safety_gate import ProductionSafetyGateBlocked, ProductionSafetyGateResult

    channel_cfg = SimpleNamespace(name="Demo Channel", upload_times=["10:00"])
    health_file = tmp_path / "provider_health.json"

    monkeypatch.setattr(channel_manager, "get_channel", lambda _cid: channel_cfg)
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(health_file))
    monkeypatch.setattr(scheduler_utils, "check_disk_space", lambda **_kwargs: True)
    monkeypatch.setattr(
        scheduler_utils,
        "get_provider_circuit_status",
        lambda _provider: {"provider": "anthropic", "is_open": False, "retry_after_seconds": 0, "state": {}},
    )
    monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)

    called = {"pipeline": 0}

    def _blocked_pipeline(**_kwargs):
        called["pipeline"] += 1
        raise ProductionSafetyGateBlocked(
            ProductionSafetyGateResult(
                operation="render",
                channel_id="demo_channel",
                job_id="run_1",
                allowed=False,
                status="blocked",
                blocking_reason="active_deployment_lock",
                timestamp="2026-07-18T00:00:00+00:00",
                release_sha="a" * 40,
                checks=(),
                evidence={},
            )
        )

    monkeypatch.setattr(pipeline, "run_full_pipeline", _blocked_pipeline)

    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)

    assert called["pipeline"] == 1


def test_render_and_schedule_quarantines_when_upload_precheck_blocked(monkeypatch, tmp_path):
    import src.channel_manager as channel_manager
    import src.scheduler_utils as scheduler_utils
    import src.pipeline as pipeline

    channel_cfg = SimpleNamespace(
        name="Demo Channel",
        upload_times=["10:00"],
        niche="teknoloji",
        topics=["yazilim", "ai"],
    )

    queue_file = tmp_path / "channel_queue.json"
    queue_file.write_text("{}", encoding="utf-8")
    trail = tmp_path / "queue_quarantine_decisions.jsonl"
    health_file = tmp_path / "provider_health.json"

    monkeypatch.setattr(scheduler, "QUEUE_FILE", str(queue_file))
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
    monkeypatch.setattr(scheduler_utils, "save_used_topic", lambda *_args, **_kwargs: None)

    monkeypatch.setattr(
        pipeline,
        "run_full_pipeline",
        lambda **_kwargs: {
            "title": "Yanlis Kanal DNA Basligi",
            "upload_precheck": {
                "status": "blocked",
                "quarantine_reason": "channel_dna_mismatch",
                "guard_reason_codes": ["channel_dna_mismatch", "upload_precheck_final_guard"],
                "recoverable": False,
            },
        },
    )

    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)

    data = json.loads(queue_file.read_text(encoding="utf-8"))
    entry = data["demo_channel"][0]
    assert entry["status"] == "quarantined"
    assert entry["quarantine_reason"] == "channel_dna_mismatch"
    assert entry["recoverable"] is False
    assert entry.get("video_id") is None


def test_overloaded_error_maps_to_backoff_decision():
    decision = _classify_error_decision("HTTP 529 - Overloaded")

    assert decision["decision"] == "continue_with_backoff"
    assert decision["retry"] is True


def test_record_provider_failure_opens_circuit_for_overloaded(tmp_path, monkeypatch):
    import src.scheduler_utils as scheduler_utils

    health_file = tmp_path / "provider_health.json"
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(health_file))

    state = record_provider_failure("anthropic", "HTTP 529 - Overloaded")
    circuit = get_provider_circuit_status("anthropic")

    assert state["last_error_type"] == "overload"
    assert circuit["is_open"] is True
    assert circuit["retry_after_seconds"] > 0


def test_record_provider_failure_opens_circuit_for_billing_rejection(tmp_path, monkeypatch):
    import src.scheduler_utils as scheduler_utils

    health_file = tmp_path / "provider_health.json"
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(health_file))

    state = record_provider_failure("anthropic", "HTTP 400 billing payment required")
    circuit = get_provider_circuit_status("anthropic")

    assert state["last_error_type"] == "billing"
    assert circuit["is_open"] is True
    assert circuit["retry_after_seconds"] > 0


def test_classify_provider_preflight_degraded_mode_error_is_fail_closed_for_unknown():
    decision = classify_provider_preflight_degraded_mode_error("unexpected binary framing mismatch")

    assert decision["eligible"] is False
    assert decision["error_type"] == "unknown"


def test_classify_provider_preflight_degraded_mode_error_marks_network_as_eligible():
    decision = classify_provider_preflight_degraded_mode_error("upstream connection timeout")

    assert decision["eligible"] is True
    assert decision["error_type"] == "network"


def test_record_provider_failure_triggers_global_overload_pause(tmp_path, monkeypatch):
    import src.scheduler_utils as scheduler_utils

    health_file = tmp_path / "provider_health.json"
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(health_file))
    monkeypatch.setenv("PROVIDER_OVERLOAD_WINDOW_SECONDS", "300")
    monkeypatch.setenv("PROVIDER_OVERLOAD_TRIGGER_COUNT", "2")
    monkeypatch.setenv("PROVIDER_OVERLOAD_GLOBAL_PAUSE_SECONDS", "600")

    record_provider_failure("anthropic", "HTTP 529 - Overloaded")
    record_provider_failure("anthropic", "HTTP 529 - Overloaded")
    pause = get_global_overload_pause_status()

    assert pause["is_open"] is True
    assert pause["retry_after_seconds"] > 0
    assert pause["reason"].startswith("overload_storm:")


def test_render_and_schedule_does_not_outer_retry_provider_handled_exception(monkeypatch, tmp_path):
    import src.channel_manager as channel_manager
    import src.pipeline as pipeline
    import src.scheduler_utils as scheduler_utils

    channel_cfg = SimpleNamespace(name="Demo Channel", upload_times=["10:00"])
    calls = {"pipeline": 0, "notify": 0}
    health_file = tmp_path / "provider_health.json"

    def _provider_handled_error(**_kwargs):
        calls["pipeline"] += 1
        exc = RuntimeError("HTTP 529 - Overloaded")
        setattr(exc, "_provider_error_text", "HTTP 529 - overloaded_error - Overloaded")
        setattr(exc, "_provider_failure_recorded", True)
        setattr(exc, "_skip_scheduler_pipeline_retry", True)
        raise exc

    monkeypatch.setattr(channel_manager, "get_channel", lambda _cid: channel_cfg)
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(health_file))
    monkeypatch.setattr(scheduler_utils, "check_disk_space", lambda **_kwargs: True)
    monkeypatch.setattr(scheduler_utils, "get_provider_circuit_status", lambda _provider: {"provider": "anthropic", "is_open": False, "retry_after_seconds": 0, "state": {}})
    monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: calls.__setitem__("notify", calls["notify"] + 1) or {})
    monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)
    monkeypatch.setattr(pipeline, "run_full_pipeline", _provider_handled_error)

    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)

    assert calls["pipeline"] == 1
    assert calls["notify"] == 1


def test_render_and_schedule_continues_when_provider_circuit_open_in_fail_open_mode(monkeypatch):
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

    monkeypatch.setattr(
        pipeline,
        "run_full_pipeline",
        lambda **_kwargs: called.__setitem__("pipeline", called["pipeline"] + 1) or {"video_id": "vid1", "title": "ok", "youtube_url": "https://youtube.com/watch?v=vid1"},
    )
    monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: called.__setitem__("notify", called["notify"] + 1) or {})
    monkeypatch.setattr(scheduler_utils, "notify_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)
    monkeypatch.setattr(scheduler_utils, "save_used_topic", lambda *_args, **_kwargs: None)

    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)

    assert called["pipeline"] == 0
    assert called["notify"] == 1


def test_notify_error_dedupes_anthropic_cooldown_across_channels(monkeypatch, tmp_path):
    import src.scheduler_utils as scheduler_utils

    alerts_file = tmp_path / "alerts_sent.json"
    sent = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(alerts_file))
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    notify_error("Teknoloji Pusulasi", "Anthropic circuit open; provider is cooling down (580s)")
    notify_error("Borsa Akademi", "Anthropic circuit open; provider is cooling down (595s)")

    assert len(sent) == 1


def test_notify_error_keeps_non_cooldown_alerts_channel_scoped(monkeypatch, tmp_path):
    import src.scheduler_utils as scheduler_utils

    alerts_file = tmp_path / "alerts_sent.json"
    sent = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(alerts_file))
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    notify_error("Teknoloji Pusulasi", "Disk alanı kritik seviyede!")
    notify_error("Borsa Akademi", "Disk alanı kritik seviyede!")

    assert len(sent) == 2


class _HarnessStopLoop(RuntimeError):
    pass


class _HarnessEvery:
    def __init__(self, jobs):
        self._jobs = jobs
        self.monday = self
        self.tuesday = self
        self.wednesday = self
        self.thursday = self
        self.friday = self
        self.saturday = self
        self.sunday = self

    @property
    def day(self):
        return self

    @property
    def hour(self):
        return self

    @property
    def hours(self):
        return self

    def at(self, _value):
        return self

    def do(self, func, **kwargs):
        self._jobs.append((func, dict(kwargs)))
        return self


class _HarnessSchedule:
    def __init__(self):
        self.jobs = []

    def every(self, *_args):
        return _HarnessEvery(self.jobs)

    def run_pending(self):
        raise _HarnessStopLoop()


def _install_fake_anthropic_failure(monkeypatch, error_text: str):
    class _FakeMessages:
        def create(self, **_kwargs):
            raise RuntimeError(error_text)

    class _FakeAnthropic:
        def __init__(self, **_kwargs):
            self.messages = _FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=_FakeAnthropic))


def test_integration_degraded_startup_keeps_scheduler_alive_and_blocks_generation(monkeypatch, tmp_path, caplog):
    import src.channel_manager as channel_manager
    import src.pipeline as pipeline
    import src.scheduler_utils as scheduler_utils

    monkeypatch.setenv("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_PREFLIGHT_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-5")
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "0")
    monkeypatch.setenv("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", "0")
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    caplog.set_level("WARNING")

    health_file = tmp_path / "provider_health.json"
    sent = []
    records = []
    schedule_obj = _HarnessSchedule()
    channel_cfg = SimpleNamespace(name="Demo Channel", upload_times=["10:00", "20:00"], token_path=str(tmp_path / "token.json"))

    class _StartupResult:
        ok = True
        errors = ()

    _install_fake_anthropic_failure(monkeypatch, "HTTP 400 credit balance is too low")
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(health_file))
    monkeypatch.setattr(scheduler_utils, "_get_anthropic_key", lambda: "test-key")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(str(message)))
    monkeypatch.setattr(scheduler_utils, "cleanup_old_renders", lambda **_kwargs: 0)
    monkeypatch.setattr(scheduler_utils, "check_disk_space", lambda **_kwargs: True)
    monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)
    monkeypatch.setattr(scheduler_utils, "notify_upload", lambda *_args, **_kwargs: None)

    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["demo_channel"])
    monkeypatch.setattr(channel_manager, "list_channels", lambda: ["demo_channel"])
    monkeypatch.setattr(channel_manager, "get_channel", lambda _cid: channel_cfg)
    monkeypatch.setattr(scheduler, "_evaluate_scheduler_startup_production_safety_gate", lambda **_kwargs: {"ok": True, "checks": []})
    monkeypatch.setattr(scheduler, "_record_safety_gate_result", lambda **kwargs: records.append(dict(kwargs)) or {"overall_ok": True})
    monkeypatch.setattr(scheduler, "_send_startup_incident_alert", lambda **_kwargs: None)
    monkeypatch.setattr(scheduler, "catch_up_overdue_queue_entries", lambda: {})
    monkeypatch.setattr(scheduler, "inspect_startup_generation_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(scheduler, "_resolve_live_collector_runtime", lambda: (True, "live"))
    monkeypatch.setattr(scheduler, "schedule", schedule_obj)
    monkeypatch.setattr(scheduler.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_write_pid_record", lambda: None)

    with pytest.raises(_HarnessStopLoop):
        scheduler.main()

    startup_records = [item for item in records if item.get("mode") == "startup"]
    assert startup_records
    assert str(startup_records[-1]["provider_preflight_detail"]).startswith("degraded_mode_active:")

    circuit = get_provider_circuit_status("anthropic")
    assert circuit["is_open"] is True
    assert circuit["state"].get("last_error_type") in {"billing", "credit"}

    warning_lines = [line for line in caplog.messages if "STARTUP_PROVIDER_PREFLIGHT_DEGRADED" in line]
    assert len(warning_lines) == 1
    assert '"provider": "anthropic"' in warning_lines[0]
    assert '"error_type": "credit"' in warning_lines[0]

    startup_messages = [msg for msg in sent if "Scheduler Basladi" in msg]
    assert len(startup_messages) == 1

    registered = [entry[0] for entry in schedule_obj.jobs]
    assert scheduler.maintenance_job in registered
    assert scheduler.fill_empty_queues_job in registered
    assert scheduler.refresh_live_analytics_job in registered

    pipeline_calls = {"count": 0}
    monkeypatch.setattr(
        pipeline,
        "run_full_pipeline",
        lambda **_kwargs: pipeline_calls.__setitem__("count", pipeline_calls["count"] + 1) or {},
    )
    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)
    assert pipeline_calls["count"] == 0


def test_startup_notification_sent_once_for_one_process_and_not_per_channel(monkeypatch):
    import src.scheduler_utils as scheduler_utils

    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])

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

    sent = []
    fake_schedule = SimpleNamespace(
        every=lambda *args, **kwargs: _FakeEvery(),
        run_pending=lambda: (_ for _ in ()).throw(_StopLoop()),
    )

    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "_run_provider_preflight_check", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["a", "b", "c"])
    monkeypatch.setattr(scheduler, "setup_schedule", lambda: ["a", "b", "c"])
    monkeypatch.setattr(scheduler, "catch_up_overdue_queue_entries", lambda: {})
    monkeypatch.setattr(scheduler, "inspect_startup_generation_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(scheduler, "_resolve_live_collector_runtime", lambda: (False, "no_go_api_not_enabled"))
    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    monkeypatch.setattr(scheduler.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_write_pid_record", lambda: None)
    monkeypatch.setattr(scheduler_utils, "cleanup_old_renders", lambda **_kwargs: 0)
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(str(message)))

    with pytest.raises(_StopLoop):
        scheduler.main()

    startup_messages = [msg for msg in sent if "Scheduler Basladi" in msg]
    assert len(startup_messages) == 1


def test_second_bootstrap_attempt_in_same_process_does_not_send_second_startup_notification(monkeypatch):
    import src.scheduler_utils as scheduler_utils

    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])

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

    fake_schedule = SimpleNamespace(
        every=lambda *args, **kwargs: _FakeEvery(),
        run_pending=lambda: (_ for _ in ()).throw(_StopLoop()),
    )
    sent = []
    acquire_calls = {"count": 0}

    def _acquire_once_then_conflict():
        acquire_calls["count"] += 1
        if acquire_calls["count"] > 1:
            raise RuntimeError("scheduler_singleton_lock_conflict:already_acquired_in_process")

    monkeypatch.setattr(scheduler, "_acquire_scheduler_singleton_lock", _acquire_once_then_conflict)
    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "_run_provider_preflight_check", lambda **_kwargs: (True, "ok"))
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "setup_schedule", lambda: ["demo"])
    monkeypatch.setattr(scheduler, "catch_up_overdue_queue_entries", lambda: {})
    monkeypatch.setattr(scheduler, "inspect_startup_generation_candidates", lambda **_kwargs: {})
    monkeypatch.setattr(scheduler, "_resolve_live_collector_runtime", lambda: (False, "no_go_api_not_enabled"))
    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    monkeypatch.setattr(scheduler.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler, "_write_pid_record", lambda: None)
    monkeypatch.setattr(scheduler_utils, "cleanup_old_renders", lambda **_kwargs: 0)
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(str(message)))

    with pytest.raises(_StopLoop):
        scheduler.main()

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 1
    assert [msg for msg in sent if "Scheduler Basladi" in msg] == [msg for msg in sent if "Scheduler Basladi" in msg][:1]


def test_singleton_conflict_exits_without_startup_notification(monkeypatch):
    import src.scheduler_utils as scheduler_utils

    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])
    sent = []
    monkeypatch.setattr(scheduler, "_acquire_scheduler_singleton_lock", lambda: (_ for _ in ()).throw(RuntimeError("scheduler_singleton_lock_conflict:test")))
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(str(message)))

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 1
    assert not any("Scheduler Basladi" in msg for msg in sent)


@pytest.mark.parametrize("flag_value", [None, "false"])
def test_fail_closed_credit_failure_when_degraded_mode_not_enabled(monkeypatch, flag_value):
    import src.scheduler_utils as scheduler_utils

    if flag_value is None:
        monkeypatch.delenv("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED", flag_value)
    monkeypatch.setenv("ANTHROPIC_PREFLIGHT_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "0")
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])

    class _StartupResult:
        ok = True
        errors = ()

    sent = []
    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "_send_startup_incident_alert", lambda **_kwargs: None)
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["demo"])
    monkeypatch.setattr(scheduler_utils, "_get_anthropic_key", lambda: "test-key")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(str(message)))
    _install_fake_anthropic_failure(monkeypatch, "HTTP 400 credit balance is too low")

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 1
    assert not any("Scheduler Basladi" in msg for msg in sent)


def test_fail_closed_auth_failure_even_when_degraded_mode_enabled(monkeypatch):
    import src.scheduler_utils as scheduler_utils

    monkeypatch.setenv("PROVIDER_PREFLIGHT_DEGRADED_MODE_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_PREFLIGHT_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "0")
    monkeypatch.setattr(scheduler.sys, "argv", ["scheduler.py"])

    class _StartupResult:
        ok = True
        errors = ()

    sent = []
    monkeypatch.setattr(scheduler, "_run_startup_health_check", lambda **_kwargs: _StartupResult())
    monkeypatch.setattr(scheduler, "_send_startup_incident_alert", lambda **_kwargs: None)
    monkeypatch.setattr(scheduler, "get_ready_channels", lambda: ["demo"])
    monkeypatch.setattr(scheduler_utils, "_get_anthropic_key", lambda: "test-key")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(str(message)))
    _install_fake_anthropic_failure(monkeypatch, "HTTP 401 invalid api key")

    with pytest.raises(SystemExit) as exc:
        scheduler.main()

    assert exc.value.code == 1
    assert not any("Scheduler Basladi" in msg for msg in sent)


def test_provider_recovery_reenables_generation_after_recorded_success(monkeypatch, tmp_path):
    import src.channel_manager as channel_manager
    import src.pipeline as pipeline
    import src.scheduler_utils as scheduler_utils

    health_file = tmp_path / "provider_health.json"
    channel_cfg = SimpleNamespace(name="Demo Channel", upload_times=["10:00"], token_path=str(tmp_path / "token.json"))
    calls = {"pipeline": 0}

    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(health_file))
    monkeypatch.setattr(channel_manager, "get_channel", lambda _cid: channel_cfg)
    monkeypatch.setattr(scheduler_utils, "check_disk_space", lambda **_kwargs: True)
    monkeypatch.setattr(scheduler_utils, "notify_error", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(scheduler_utils, "notify_upload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scheduler_utils, "force_cleanup", lambda: None)
    monkeypatch.setattr(scheduler_utils, "save_used_topic", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "run_full_pipeline",
        lambda **_kwargs: calls.__setitem__("pipeline", calls["pipeline"] + 1) or {"video_id": "vid", "title": "ok", "youtube_url": "https://youtube.com/watch?v=vid"},
    )

    record_provider_failure("anthropic", "HTTP 400 billing payment required")
    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)
    assert calls["pipeline"] == 0

    from src.scheduler_utils import record_provider_success

    record_provider_success("anthropic", note="manual_probe_ok")
    scheduler.render_and_schedule("demo_channel", trigger_source=TEST_TRIGGER_SOURCE)
    assert calls["pipeline"] == 1
