from __future__ import annotations

from src.config import Config
from src.production_readiness import format_health_check_summary, run_production_health_check


def test_health_check_passes_with_required_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "true")

    cfg = Config(
        anthropic_api_key="a",
        youtube_client_id="b",
        youtube_client_secret="c",
    )

    result = run_production_health_check(
        cfg,
        require_telegram=True,
        create_missing_directories=True,
    )

    assert result.ok is True
    assert result.fact_bundle_enabled is True
    assert result.required_directories_ok is True
    assert result.required_api_keys_ok is True
    assert result.telegram_configured is True


def test_health_check_reports_actionable_failures(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "false")

    cfg = Config(anthropic_api_key="", youtube_client_id="", youtube_client_secret="")

    result = run_production_health_check(
        cfg,
        require_telegram=True,
        create_missing_directories=False,
    )

    assert result.ok is False
    assert result.required_directories_ok is False
    assert result.required_api_keys_ok is False
    assert result.telegram_configured is False
    assert result.fact_bundle_enabled is False
    assert any("Missing required directories" in error for error in result.errors)
    assert any("Missing required API keys" in error for error in result.errors)
    assert any("Missing Telegram configuration" in error for error in result.errors)


def test_health_check_summary_contains_key_signals(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "1")

    cfg = Config(anthropic_api_key="a", youtube_client_id="b", youtube_client_secret="c")
    result = run_production_health_check(
        cfg,
        require_telegram=True,
        create_missing_directories=True,
    )

    lines = format_health_check_summary(result)

    assert "config_loaded=True" in lines
    assert "fact_bundle_enabled=True" in lines
    assert "health_check_ok=True" in lines
