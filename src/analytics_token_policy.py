from __future__ import annotations

import os
from pathlib import Path


CANONICAL_ANALYTICS_TOKEN_ROOT = Path("/opt/parapusulasi-shared/tokens/channels")
CANONICAL_ANALYTICS_TOKEN_FILENAME = "youtube_analytics_token.pickle"
NONCANONICAL_ANALYTICS_TOKEN_PATH = "NONCANONICAL_ANALYTICS_TOKEN_PATH"
TOKEN_SOURCE_ANALYTICS_PRIMARY = "ANALYTICS_TOKEN_PRIMARY"
TOKEN_SOURCE_NONE = "NONE"


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _is_isolation_mode() -> bool:
    return bool(str(os.getenv("PYTEST_CURRENT_TEST", "")).strip()) or _is_enabled(os.getenv("PREPROD_ISOLATION_MODE", "false"))


def canonical_analytics_token_root() -> Path:
    return CANONICAL_ANALYTICS_TOKEN_ROOT


def canonical_analytics_token_path(channel_slug: str) -> Path:
    return canonical_analytics_token_root() / str(channel_slug).strip() / CANONICAL_ANALYTICS_TOKEN_FILENAME


def _is_canonical_path(path: Path, channel_slug: str) -> bool:
    try:
        return path.resolve() == canonical_analytics_token_path(channel_slug).resolve()
    except Exception:
        return False


def resolve_analytics_token_path(*, channel_slug: str, configured_path: str | None = None) -> Path:
    canonical_path = canonical_analytics_token_path(channel_slug)
    configured_text = str(configured_path or "").strip()
    env_override = str(os.getenv("YOUTUBE_ANALYTICS_TOKEN_PATH", "")).strip()
    root_override = str(os.getenv("CHANNEL_TOKENS_ROOT", "")).strip()

    if _is_isolation_mode():
        if configured_text:
            return Path(configured_text)
        if env_override:
            return Path(env_override)
        if root_override:
            return Path(root_override) / str(channel_slug).strip() / CANONICAL_ANALYTICS_TOKEN_FILENAME
        return canonical_path

    if configured_text:
        configured = Path(configured_text)
        if not _is_canonical_path(configured, channel_slug):
            raise RuntimeError(NONCANONICAL_ANALYTICS_TOKEN_PATH)
        return configured

    if env_override:
        env_path = Path(env_override)
        if not _is_canonical_path(env_path, channel_slug):
            raise RuntimeError(NONCANONICAL_ANALYTICS_TOKEN_PATH)
        return env_path

    if root_override:
        root_path = Path(root_override)
        if root_path.resolve() != canonical_analytics_token_root().resolve():
            raise RuntimeError(NONCANONICAL_ANALYTICS_TOKEN_PATH)

    return canonical_path
