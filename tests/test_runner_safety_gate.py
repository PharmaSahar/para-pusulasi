from __future__ import annotations

import pytest

import main as app_main
import run_channels
import src.pipeline as pipeline
from src.production_safety_gate import ProductionSafetyCheckResult, ProductionSafetyGateBlocked, ProductionSafetyGateResult


def _gate_block() -> ProductionSafetyGateBlocked:
    result = ProductionSafetyGateResult(
        operation="render",
        channel_id="demo_channel",
        job_id="run_1",
        allowed=False,
        status="blocked",
        blocking_reason="active_deployment_lock",
        timestamp="2026-07-18T00:00:00+00:00",
        release_sha="a" * 40,
        checks=(
            ProductionSafetyCheckResult(
                check_name="active_deployment_lock",
                status="fail",
                severity="critical",
                reason_code="active_deployment_lock",
                message="blocked",
                timestamp="2026-07-18T00:00:00+00:00",
                release_sha="a" * 40,
                channel_id="demo_channel",
                job_id="run_1",
                evidence={},
            ),
        ),
        evidence={},
    )
    return ProductionSafetyGateBlocked(result)


def test_main_once_path_propagates_pipeline_safety_block(monkeypatch):
    monkeypatch.setattr(pipeline, "run_full_pipeline", lambda **_kwargs: (_ for _ in ()).throw(_gate_block()))

    with pytest.raises(SystemExit):
        app_main._run_once(topic=None, generate_only=False, privacy="private")


def test_run_channels_pipeline_path_returns_empty_on_safety_block(monkeypatch):
    monkeypatch.setattr(pipeline, "run_full_pipeline", lambda **_kwargs: (_ for _ in ()).throw(_gate_block()))
    monkeypatch.setattr("src.channel_manager.get_channel", lambda _cid: type("Cfg", (), {"name": "Demo"})())

    result = run_channels.run_channel_pipeline("demo_channel")

    assert result == {}