from __future__ import annotations

from src.config import Config
import src.production_readiness as production_readiness
from src.production_readiness import format_health_check_summary, run_production_health_check


def test_health_check_passes_with_required_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "true")

    monkeypatch.setattr(
        production_readiness.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (None, None, None, None, ("203.0.113.10", 443)),
            (None, None, None, None, ("203.0.113.11", 443)),
        ],
    )

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
    assert result.youtube_dns_ips == ("203.0.113.10", "203.0.113.11")


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

    monkeypatch.setattr(
        production_readiness.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("203.0.113.10", 443))],
    )

    cfg = Config(anthropic_api_key="a", youtube_client_id="b", youtube_client_secret="c")
    result = run_production_health_check(
        cfg,
        require_telegram=True,
        create_missing_directories=True,
    )

    lines = format_health_check_summary(result)

    assert "config_loaded=True" in lines
    assert "fact_bundle_enabled=True" in lines
    assert "youtube_dns_ips=203.0.113.10" in lines
    assert "health_check_ok=True" in lines


def test_health_check_reports_youtube_dns_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "true")

    def fake_getaddrinfo(*args, **kwargs):
        raise production_readiness.socket.gaierror(8, "nodename nor servname provided, or not known")

    monkeypatch.setattr(production_readiness.socket, "getaddrinfo", fake_getaddrinfo)

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

    assert result.ok is False
    assert result.youtube_dns_ips == ()
    assert any("Unable to resolve youtube.googleapis.com" in error for error in result.errors)
