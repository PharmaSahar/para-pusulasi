from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import src.production_safety_gate as production_safety_gate


def _make_cfg(tmp_path: Path) -> SimpleNamespace:
    channel_root = tmp_path / "channels" / "demo_channel"
    output_dir = channel_root / "output"
    scripts_dir = channel_root / "scripts"
    audio_dir = output_dir / "audio"
    videos_dir = output_dir / "videos"
    assets_dir = channel_root / "assets"
    logs_dir = tmp_path / "logs"
    for path in (output_dir, scripts_dir, audio_dir, videos_dir, assets_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)

    return SimpleNamespace(
        output_dir=str(output_dir),
        scripts_dir=str(scripts_dir),
        audio_dir=str(audio_dir),
        videos_dir=str(videos_dir),
        assets_dir=str(assets_dir),
        logs_dir=str(logs_dir),
        token_path=str(channel_root / "youtube_token.pickle"),
        client_secrets_path=str(channel_root / "client_secrets.json"),
        validate=lambda: [],
        name="Demo Channel",
    )


def _prepare_common(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PRODUCTION_SAFETY_GATE_IN_TESTS", "1")
    monkeypatch.chdir(tmp_path)
    queue_path = tmp_path / "output" / "state" / "channel_queue.json"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(production_safety_gate, "check_token_health", lambda _cfg: (True, "ok"))
    monkeypatch.setattr(production_safety_gate, "get_free_disk_gb", lambda: 9.5)
    monkeypatch.setattr(
        production_safety_gate,
        "get_global_overload_pause_status",
        lambda: {"is_open": False, "retry_after_seconds": 0, "pause_until": "", "reason": ""},
    )
    monkeypatch.setattr(
        production_safety_gate,
        "get_provider_circuit_status",
        lambda _provider: {"provider": "anthropic", "is_open": False, "retry_after_seconds": 0, "state": {}},
    )
    monkeypatch.setattr(production_safety_gate, "_resolve_git_head", lambda: "a" * 40)
    events: list[dict] = []
    monkeypatch.setattr(production_safety_gate, "record_production_event", lambda payload: events.append(dict(payload)))
    return queue_path, events


def test_production_safety_gate_all_checks_pass(monkeypatch, tmp_path: Path):
    queue_path, events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
        deployment_lock_path=tmp_path / "no-lock",
    )

    assert result.allowed is True
    assert result.status == "allowed"
    assert result.to_dict()["ok"] is True
    assert events[-1]["event_type"] == "production_safety_gate"
    assert events[-1]["final_status"] == "allowed"
    assert events[-1]["release_sha"] == "a" * 40


def test_production_safety_gate_blocks_missing_credential(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    cfg.validate = lambda: ["ANTHROPIC_API_KEY"]

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "api_credentials_missing"


def test_production_safety_gate_blocks_invalid_authentication(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr(production_safety_gate, "check_token_health", lambda _cfg: (False, "expired"))

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="upload",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "youtube_token_invalid"


def test_production_safety_gate_blocks_missing_required_environment(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    monkeypatch.setenv("PRODUCTION_SAFETY_REQUIRED_ENV_VARS", "REQUIRED_ONE")
    monkeypatch.delenv("REQUIRED_ONE", raising=False)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "required_env_missing"


def test_production_safety_gate_blocks_active_deployment_lock(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    lock_path = tmp_path / "deploy.lock"
    lock_path.mkdir(parents=True, exist_ok=True)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
        deployment_lock_path=lock_path,
    )

    assert result.ok is False
    assert result.blocking_reason == "active_deployment_lock"


def test_production_safety_gate_blocks_release_integrity_mismatch(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    metadata_path = tmp_path / ".immutable_release_metadata.json"
    metadata_path.write_text(json.dumps({"release_sha": "b" * 40}), encoding="utf-8")

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
        release_metadata_path=metadata_path,
        deployment_lock_path=tmp_path / "no-lock",
    )

    assert result.ok is False
    assert result.blocking_reason == "release_integrity_mismatch"


def test_production_safety_gate_blocks_unwritable_path(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    original_write_text = Path.write_text

    def _raise_for_probe(self, *args, **kwargs):
        if self.name.startswith(".safety_gate_probe_"):
            raise PermissionError("blocked")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _raise_for_probe)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "writable_directories_unavailable"


def test_production_safety_gate_blocks_low_disk(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr(production_safety_gate, "get_free_disk_gb", lambda: 0.25)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "disk_space_below_threshold"


def test_production_safety_gate_blocks_invalid_clock(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr(production_safety_gate, "_now_utc", lambda: datetime(1900, 1, 1, tzinfo=timezone.utc))

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "clock_sanity_failed"


def test_production_safety_gate_blocks_queue_corruption(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    queue_path.write_text("{not-json", encoding="utf-8")

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "queue_file_unreadable"


def test_production_safety_gate_returns_warning_only_result(monkeypatch, tmp_path: Path):
    queue_path, events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr(
        production_safety_gate,
        "get_provider_circuit_status",
        lambda _provider: {
            "provider": "anthropic",
            "is_open": False,
            "retry_after_seconds": 0,
            "state": {"consecutive_failures": 2},
        },
    )

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="upload",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is True
    assert result.status == "warning"
    assert any(item.status == "warn" for item in result.checks)
    assert events[-1]["severity"] == "WARNING"


def test_production_safety_gate_emits_structured_event_contents(monkeypatch, tmp_path: Path):
    queue_path, events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    lock_path = tmp_path / "deploy.lock"
    lock_path.mkdir(parents=True, exist_ok=True)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
        deployment_lock_path=lock_path,
        job_id="job-123",
    )

    event = events[-1]
    assert result.allowed is False
    assert event["event_type"] == "production_safety_gate"
    assert event["channel_id"] == "demo_channel"
    assert event["job_id"] == "job-123"
    assert event["release_sha"] == "a" * 40
    assert event["severity"] == "ERROR"
    assert event["reason"] == "active_deployment_lock"
    assert event["checks"][0]["timestamp"]


def test_production_safety_gate_blocks_duplicate_scheduler_state(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    meta_path = tmp_path / "scheduler_singleton_meta.json"
    meta_path.write_text(json.dumps({"pid": 99999}), encoding="utf-8")
    monkeypatch.setenv("SCHEDULER_SINGLETON_META_FILE", str(meta_path))
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=type("H", (), {"ok": True, "errors": (), "missing_api_keys": ()})(),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "duplicate_scheduler_state"