from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import src.production_safety_gate as production_safety_gate
import scheduler


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


def _write_owner(active_lock: Path, *, owner_id: str = "owner-123", pid: int | None = None, host: str | None = None, process_identity: str = "python", target_sha: str = "a" * 40, target_ref: str = "origin/master", mode: str = "cutover") -> None:
    active_lock.mkdir(parents=True, exist_ok=True)
    (active_lock / "owner.json").write_text(
        json.dumps(
            {
                "owner_id": owner_id,
                "pid": os.getpid() if pid is None else pid,
                "host": host or production_safety_gate.socket.gethostname(),
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "target_sha": target_sha,
                "target_ref": target_ref,
                "process_identity": process_identity,
            }
        ),
        encoding="utf-8",
    )


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


def test_observation_mode_blocks_render_and_upload_but_allows_scheduler_startup(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    monkeypatch.setenv("PRODUCTION_OBSERVATION_MODE", "true")

    render = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
        deployment_lock_path=tmp_path / "no-lock",
    )
    upload = production_safety_gate.evaluate_production_safety_gate(
        operation="upload",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
        deployment_lock_path=tmp_path / "no-lock",
    )
    startup = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        channel_id="demo_channel",
        channel_cfg=cfg,
        startup_health=SimpleNamespace(ok=True, errors=[]),
        queue_path=queue_path,
        deployment_lock_path=tmp_path / "no-lock",
    )

    assert render.allowed is False
    assert render.blocking_reason == "production_observation_mode"
    assert upload.allowed is False
    assert upload.blocking_reason == "production_observation_mode"
    assert startup.allowed is True


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
    _write_owner(lock_path / ".active_lock")

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
        deployment_lock_path=lock_path,
    )

    assert result.ok is False
    assert result.blocking_reason == "active_deployment_lock"
    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert lock_check.evidence["lock_classification"] == "foreign_active_lock"


def test_production_safety_gate_allows_self_owned_startup_deployment_lock(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    lock_path = tmp_path / "deploy.lock"
    active_lock = lock_path / ".active_lock"
    _write_owner(active_lock, owner_id="owner-123")

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=SimpleNamespace(ok=True, errors=[], missing_api_keys=[]),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
        deployment_lock_path=lock_path,
        expected_deployment_lock_owner_token="owner-123",
    )

    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert result.ok is True
    assert lock_check.reason_code == "self_owned_deployment_lock"
    assert lock_check.evidence["self_owned"] is True
    assert lock_check.evidence["lock_classification"] == "self_owned_active_lock"


def test_production_safety_gate_blocks_foreign_deployment_lock(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    lock_path = tmp_path / "deploy.lock"
    active_lock = lock_path / ".active_lock"
    _write_owner(active_lock, owner_id="foreign-owner")

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=SimpleNamespace(ok=True, errors=[], missing_api_keys=[]),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
        deployment_lock_path=lock_path,
        expected_deployment_lock_owner_token="owner-123",
    )

    assert result.ok is False
    assert result.blocking_reason == "deployment_lock_owner_mismatch"
    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert lock_check.evidence["lock_classification"] == "foreign_active_lock"


def test_production_safety_gate_rejects_self_owned_lock_with_wrong_target_sha(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    lock_path = tmp_path / "deploy.lock"
    _write_owner(lock_path / ".active_lock", owner_id="owner-123", target_sha="b" * 40)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=SimpleNamespace(ok=True, errors=[], missing_api_keys=[]),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
        deployment_lock_path=lock_path,
        expected_deployment_lock_owner_token="owner-123",
    )

    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert result.ok is False
    assert result.blocking_reason == "deployment_lock_owner_mismatch"
    assert lock_check.evidence["lock_classification"] == "foreign_active_lock"
    assert lock_check.evidence["owner_state"] == "target_sha_mismatch"


def test_production_safety_gate_blocks_stale_deployment_lock_without_expected_owner(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    lock_path = tmp_path / "deploy.lock"
    active_lock = lock_path / ".active_lock"
    monkeypatch.setenv("DEPLOYMENT_LOCK_FORENSICS_DIR", str(tmp_path / "forensics"))
    _write_owner(active_lock, owner_id="old-owner", pid=999999)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=SimpleNamespace(ok=True, errors=[], missing_api_keys=[]),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
        deployment_lock_path=lock_path,
    )

    assert result.ok is False
    assert result.blocking_reason == "stale_deployment_lock"
    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert lock_check.evidence["lock_classification"] == "stale_lock"
    assert lock_check.evidence["owner_state"] == "dead_pid"
    assert Path(lock_check.evidence["forensic_bundle_path"]).exists()


def test_production_safety_gate_blocks_malformed_deployment_lock_owner(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    lock_path = tmp_path / "deploy.lock"
    active_lock = lock_path / ".active_lock"
    active_lock.mkdir(parents=True, exist_ok=True)
    (active_lock / "owner.json").write_text("{not-json", encoding="utf-8")

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=SimpleNamespace(ok=True, errors=[], missing_api_keys=[]),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
        deployment_lock_path=lock_path,
        expected_deployment_lock_owner_token="owner-123",
    )

    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert result.ok is False
    assert result.blocking_reason == "malformed_deployment_lock"
    assert lock_check.evidence["lock_classification"] == "malformed_lock"
    assert lock_check.evidence["owner_metadata_error"] == "owner_metadata_invalid_json"


def test_production_safety_gate_blocks_missing_deployment_lock_owner(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    lock_path = tmp_path / "deploy.lock"
    (lock_path / ".active_lock").mkdir(parents=True, exist_ok=True)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=SimpleNamespace(ok=True, errors=[], missing_api_keys=[]),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
        deployment_lock_path=lock_path,
        expected_deployment_lock_owner_token="owner-123",
    )

    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert result.ok is False
    assert result.blocking_reason == "malformed_deployment_lock"
    assert lock_check.evidence["lock_classification"] == "malformed_lock"
    assert lock_check.evidence["owner_metadata_error"] == "owner_metadata_missing"


def test_production_safety_gate_blocks_unreadable_deployment_lock_owner(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    lock_path = tmp_path / "deploy.lock"
    active_lock = lock_path / ".active_lock"
    _write_owner(active_lock)
    original_read_text = Path.read_text

    def _raise_for_owner(self, *args, **kwargs):
        if self == active_lock / "owner.json":
            raise PermissionError("blocked")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_for_owner)

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=SimpleNamespace(ok=True, errors=[], missing_api_keys=[]),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
        deployment_lock_path=lock_path,
        expected_deployment_lock_owner_token="owner-123",
    )

    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert result.ok is False
    assert result.blocking_reason == "unreadable_deployment_lock"
    assert lock_check.evidence["lock_classification"] == "unreadable_lock"


def test_production_safety_gate_blocks_ambiguous_deployment_lock_owner(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    lock_path = tmp_path / "deploy.lock"
    active_lock = lock_path / ".active_lock"
    _write_owner(active_lock, process_identity="definitely-not-this-process")

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=SimpleNamespace(ok=True, errors=[], missing_api_keys=[]),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
        deployment_lock_path=lock_path,
        expected_deployment_lock_owner_token="owner-123",
    )

    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert result.ok is False
    assert result.blocking_reason == "ambiguous_deployment_lock"
    assert lock_check.evidence["lock_classification"] == "ambiguous_lock"


def test_production_safety_gate_blocks_runtime_paths_during_self_owned_deployment(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    lock_path = tmp_path / "deploy.lock"
    active_lock = lock_path / ".active_lock"
    _write_owner(active_lock, owner_id="owner-123")

    for operation in ("render", "upload"):
        result = production_safety_gate.evaluate_production_safety_gate(
            operation=operation,
            channel_id="demo_channel",
            channel_cfg=cfg,
            queue_path=queue_path,
            deployment_lock_path=lock_path,
            expected_deployment_lock_owner_token="owner-123",
        )

        assert result.ok is False
        assert result.blocking_reason == "active_deployment_lock"


def test_production_safety_gate_allows_empty_deployment_lock_directory(monkeypatch, tmp_path: Path):
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

    assert result.ok is True
    lock_check = next(check for check in result.checks if check.check_name == "active_deployment_lock")
    assert lock_check.reason_code == "no_active_deployment_lock"
    assert lock_check.evidence["active_marker_exists"] is False


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


def test_ordinary_overload_pause_blocks_scheduler_startup_deployment(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setenv("IMMUTABLE_CONTAINED_DEPLOYMENT", "1")
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    monkeypatch.setattr(
        production_safety_gate,
        "get_global_overload_pause_status",
        lambda: {"is_open": True, "retry_after_seconds": 300, "pause_until": "2099-01-01T00:00:00Z", "reason": "overload_storm:3/300s"},
    )

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=type("H", (), {"ok": True, "errors": (), "missing_api_keys": ()})(),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "global_overload_pause_open"


def test_visual_safety_containment_permits_scheduler_startup_without_releasing_containment(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    monkeypatch.setattr(
        production_safety_gate,
        "get_global_overload_pause_status",
        lambda: {
            "is_open": True,
            "retry_after_seconds": 600,
            "pause_until": "2099-01-01T00:00:00Z",
            "reason": "visual_safety_incident_containment:PROJECT003:cross_channel_inappropriate_visuals",
        },
    )

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=type("H", (), {"ok": True, "errors": (), "missing_api_keys": ()})(),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
    )

    assert result.allowed is True
    assert result.status == "warning"
    assert result.blocking_reason == ""
    assert any(check.reason_code == "visual_safety_containment_active_scheduler_startup" for check in result.checks)


def test_visual_safety_containment_permits_contained_deployment_startup(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setenv("IMMUTABLE_CONTAINED_DEPLOYMENT", "1")
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    monkeypatch.setattr(
        production_safety_gate,
        "get_global_overload_pause_status",
        lambda: {
            "is_open": True,
            "retry_after_seconds": 600,
            "pause_until": "2099-01-01T00:00:00Z",
            "reason": "visual_safety_incident_containment:PROJECT003:cross_channel_inappropriate_visuals",
        },
    )

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=type("H", (), {"ok": True, "errors": (), "missing_api_keys": ()})(),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
    )

    assert result.allowed is True
    assert result.status == "warning"
    assert result.blocking_reason == ""
    assert any(check.reason_code == "visual_safety_containment_active_contained_deployment" for check in result.checks)


def test_visual_safety_containment_still_blocks_render_without_releasing_containment(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    monkeypatch.setenv("IMMUTABLE_CONTAINED_DEPLOYMENT", "1")
    monkeypatch.setattr(
        production_safety_gate,
        "get_global_overload_pause_status",
        lambda: {
            "is_open": True,
            "retry_after_seconds": 600,
            "pause_until": "2099-01-01T00:00:00Z",
            "reason": "visual_safety_incident_containment:PROJECT003:cross_channel_inappropriate_visuals",
        },
    )

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="render",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "global_overload_pause_open"


def test_unknown_pause_reason_remains_fail_closed_for_contained_deployment(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    monkeypatch.setenv("IMMUTABLE_CONTAINED_DEPLOYMENT", "1")
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))
    monkeypatch.setattr(
        production_safety_gate,
        "get_global_overload_pause_status",
        lambda: {"is_open": True, "retry_after_seconds": 600, "pause_until": "2099-01-01T00:00:00Z", "reason": "manual_pause"},
    )

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=type("H", (), {"ok": True, "errors": (), "missing_api_keys": ()})(),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "global_overload_pause_open"


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


def test_production_safety_gate_queue_metrics_are_additive_and_legacy_compatible(monkeypatch, tmp_path: Path):
    queue_path, events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    queue_path.write_text(
        json.dumps(
            {
                "demo_channel": [
                    {"status": "active"},
                    {"status": "restored"},
                    {"status": "quarantined"},
                ],
                "other_channel": [
                    {"status": "permanently_rejected"},
                    {"status": "quarantined"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PRODUCTION_SAFETY_QUEUE_BACKLOG_WARNING", "2")

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="upload",
        channel_id="demo_channel",
        channel_cfg=cfg,
        queue_path=queue_path,
    )

    queue_health = next(item for item in result.checks if item.check_name == "queue_health")
    queue_backlog = next(item for item in result.checks if item.check_name == "queue_backlog")

    assert result.allowed is True
    assert result.status == "warning"
    assert queue_health.evidence["entry_count"] == 5
    assert queue_health.evidence["queue_retained_total"] == 5
    assert queue_health.evidence["queue_actionable_total"] == 2
    assert queue_health.evidence["queue_terminal_by_status"] == {"quarantined": 2, "permanently_rejected": 1}
    assert queue_health.evidence["queue_source_identity"]["path"] == str(queue_path)
    assert queue_backlog.evidence["entry_count"] == 5
    assert queue_backlog.evidence["warning_threshold"] == 2
    assert queue_backlog.evidence["queue_retained_total"] == 5
    assert events[-1]["event_type"] == "production_safety_gate"
    event_queue_backlog = next(item for item in events[-1]["checks"] if item["check_name"] == "queue_backlog")
    assert event_queue_backlog["evidence"]["queue_actionable_total"] == 2


def test_production_safety_gate_emits_structured_event_contents(monkeypatch, tmp_path: Path):
    queue_path, events = _prepare_common(monkeypatch, tmp_path)
    cfg = _make_cfg(tmp_path)
    lock_path = tmp_path / "deploy.lock"
    _write_owner(lock_path / ".active_lock")

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
    assert event["checks"][-3]["evidence"]["lock_classification"] == "foreign_active_lock"
    assert event["checks"][0]["timestamp"]


def test_startup_message_distinguishes_stale_vs_active_lock():
    active = {
        "ok": False,
        "checks": [
            {
                "status": "fail",
                "reason": "active_deployment_lock",
                "evidence": {"lock_classification": "foreign_active_lock"},
            }
        ],
    }
    stale = {
        "ok": False,
        "checks": [
            {
                "status": "fail",
                "reason": "stale_deployment_lock",
                "evidence": {"lock_classification": "stale_lock"},
            }
        ],
    }

    assert scheduler._production_safety_gate_errors(active) == [
        "ACTIVE DEPLOYMENT: production safety gate blocked scheduler startup because a live deployment lock is present"
    ]
    assert scheduler._production_safety_gate_errors(stale) == [
        "STALE DEPLOYMENT LOCK: production safety gate blocked scheduler startup; explicit operator confirmation is required"
    ]


def test_startup_incident_alert_contains_lock_context(monkeypatch):
    messages: list[str] = []
    monkeypatch.setattr("src.scheduler_utils.send_telegram", lambda message: messages.append(message))

    scheduler._send_startup_incident_alert(
        gate_payload={
            "checks": [
                {
                    "status": "fail",
                    "evidence": {
                        "lock_classification": "stale_lock",
                        "owner_pid": "999999",
                        "owner_state": "dead_pid",
                        "owner_age_seconds": 123,
                        "target_sha": "b" * 40,
                        "active_sha": "a" * 40,
                        "hostname": "test-host",
                    },
                }
            ]
        }
    )

    assert len(messages) == 1
    message = messages[0]
    assert "incident_id=" in message
    assert "lock_classification=stale_lock" in message
    assert "owner_pid=999999" in message
    assert "reason=dead_pid" in message
    assert "pid_state=dead_pid" in message
    assert "owner_age_seconds=123" in message
    assert f"target_sha={'b' * 40}" in message
    assert f"active_sha={'a' * 40}" in message
    assert "current_hostname=test-host" in message


def test_production_safety_gate_blocks_duplicate_scheduler_state(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    meta_path = tmp_path / "scheduler_singleton_meta.json"
    meta_path.write_text(json.dumps({"pid": 99999}), encoding="utf-8")
    monkeypatch.setenv("SCHEDULER_SINGLETON_META_FILE", str(meta_path))
    monkeypatch.setattr(production_safety_gate, "_pid_is_running", lambda _pid: True)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=type("H", (), {"ok": True, "errors": (), "missing_api_keys": ()})(),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
    )

    assert result.allowed is False
    assert result.blocking_reason == "duplicate_scheduler_state"


def test_production_safety_gate_ignores_stale_scheduler_metadata(monkeypatch, tmp_path: Path):
    queue_path, _events = _prepare_common(monkeypatch, tmp_path)
    meta_path = tmp_path / "scheduler_singleton_meta.json"
    meta_path.write_text(json.dumps({"pid": 99999}), encoding="utf-8")
    monkeypatch.setenv("SCHEDULER_SINGLETON_META_FILE", str(meta_path))
    monkeypatch.setattr(production_safety_gate, "_pid_is_running", lambda _pid: False)
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: _make_cfg(tmp_path))

    result = production_safety_gate.evaluate_production_safety_gate(
        operation="scheduler_startup",
        startup_health=type("H", (), {"ok": True, "errors": (), "missing_api_keys": ()})(),
        ready_channels=["demo_channel"],
        queue_path=queue_path,
    )

    assert result.allowed is True
    assert result.blocking_reason == ""