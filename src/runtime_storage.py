from __future__ import annotations

import logging
import os
from pathlib import Path


class TrackedRuntimeWriteError(RuntimeError):
    """Raised when runtime code attempts to write into tracked repository paths."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runtime_root() -> Path:
    raw = str(os.getenv("RUNTIME_OUTPUT_ROOT", "")).strip()
    if raw:
        return Path(raw)
    return repo_root() / "output" / "runtime"


def runtime_path(relative: str) -> Path:
    return runtime_root() / relative


def env_or_runtime_path(env_key: str, default_relative: str) -> Path:
    raw = str(os.getenv(env_key, "")).strip()
    if raw:
        return Path(raw)
    return runtime_path(default_relative)


def docs_dashboard_path() -> Path:
    return repo_root() / "docs" / "production_dashboard_latest.md"


def is_tracked_repo_write_target(path: Path) -> bool:
    resolved = path.resolve()
    root = repo_root().resolve()
    docs_dir = (root / "docs").resolve()

    # Runtime code must not mutate tracked documentation files.
    if resolved == docs_dir or docs_dir in resolved.parents:
        return True
    if resolved in {
        (root / "README.md").resolve(),
        (root / "CHANGELOG.md").resolve(),
        (root / "CONTRIBUTING.md").resolve(),
    }:
        return True
    return False


def _runtime_env() -> str:
    for key in ("RUNTIME_ENV", "APP_ENV", "ENV"):
        raw = str(os.getenv(key, "")).strip().lower()
        if raw:
            return raw
    return "development"


def strict_guard_mode() -> bool:
    raw = str(os.getenv("RUNTIME_TRACKED_WRITE_STRICT", "")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    if str(os.getenv("PYTEST_CURRENT_TEST", "")).strip():
        return True
    return _runtime_env() not in {"production", "prod"}


def validate_runtime_write_path(path: Path, *, purpose: str, logger: logging.Logger | None = None) -> bool:
    if not is_tracked_repo_write_target(path):
        return True

    message = f"runtime_tracked_write_blocked: purpose={purpose} target={path.resolve()}"
    if strict_guard_mode():
        raise TrackedRuntimeWriteError(message)

    if logger is not None:
        logger.error(message)
    return False
