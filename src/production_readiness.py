"""Production readiness checks for scheduler startup and canary safety."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProductionHealthCheckResult:
    config_loaded: bool
    required_directories_ok: bool
    missing_directories: tuple[str, ...]
    required_api_keys_ok: bool
    missing_api_keys: tuple[str, ...]
    telegram_configured: bool
    fact_bundle_enabled: bool
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_fact_bundle_enabled(config) -> bool:
    cfg_value = getattr(config, "fact_bundle_pipeline_adapter_enabled", None)
    if cfg_value is not None:
        return _is_enabled(cfg_value)
    return _is_enabled(os.getenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "false"))


def _required_directories(config) -> tuple[str, ...]:
    return (
        config.output_dir,
        config.scripts_dir,
        config.audio_dir,
        config.videos_dir,
        config.assets_dir,
        config.logs_dir,
        "assets/backgrounds",
        "assets/music",
        "assets/fonts",
    )


def run_production_health_check(
    config,
    *,
    require_telegram: bool,
    create_missing_directories: bool,
) -> ProductionHealthCheckResult:
    if create_missing_directories:
        config.ensure_directories()

    required_dirs = _required_directories(config)
    missing_dirs = tuple(path for path in required_dirs if not Path(path).exists())
    missing_api_keys = tuple(config.validate())
    telegram_configured = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
    fact_bundle_enabled = resolve_fact_bundle_enabled(config)

    errors: list[str] = []
    if missing_dirs:
        errors.append(
            "Missing required directories: "
            + ", ".join(missing_dirs)
            + ". Ensure writable project paths and rerun startup."
        )
    if missing_api_keys:
        errors.append(
            "Missing required API keys: "
            + ", ".join(missing_api_keys)
            + ". Set these keys in .env before production start."
        )
    if require_telegram and not telegram_configured:
        errors.append(
            "Missing Telegram configuration. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."
        )

    return ProductionHealthCheckResult(
        config_loaded=config is not None,
        required_directories_ok=not missing_dirs,
        missing_directories=missing_dirs,
        required_api_keys_ok=not missing_api_keys,
        missing_api_keys=missing_api_keys,
        telegram_configured=telegram_configured,
        fact_bundle_enabled=fact_bundle_enabled,
        errors=tuple(errors),
    )


def format_health_check_summary(result: ProductionHealthCheckResult) -> list[str]:
    return [
        f"config_loaded={result.config_loaded}",
        f"required_directories_ok={result.required_directories_ok}",
        f"required_api_keys_ok={result.required_api_keys_ok}",
        f"telegram_configured={result.telegram_configured}",
        f"fact_bundle_enabled={result.fact_bundle_enabled}",
        f"health_check_ok={result.ok}",
    ]
