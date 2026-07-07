"""Passive JSONL telemetry sink with daily files and best-effort rotation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path


def get_sink_config() -> dict:
    enabled_raw = (os.getenv("TELEMETRY_SINK_ENABLED", "true") or "").strip().lower()
    enabled = enabled_raw not in {"0", "false", "no", "off"}

    sink_dir = os.getenv("TELEMETRY_SINK_DIR", "output/telemetry")
    basename = os.getenv("TELEMETRY_SINK_BASENAME", "events")

    try:
        max_days = int(os.getenv("TELEMETRY_SINK_MAX_DAYS", "14"))
    except ValueError:
        max_days = 14
    if max_days < 1:
        max_days = 1

    return {
        "enabled": enabled,
        "dir": sink_dir,
        "basename": basename,
        "max_days": max_days,
    }


def current_jsonl_path(now_utc: datetime | None = None, *, cfg: dict | None = None) -> Path:
    cfg = cfg or get_sink_config()
    now = now_utc or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    return Path(cfg["dir"]) / f"{cfg['basename']}-{day}.jsonl"


def append_event_jsonl(event: dict, *, now_utc: datetime | None = None, cfg: dict | None = None) -> bool:
    cfg = cfg or get_sink_config()
    if not cfg.get("enabled", True):
        return False
    try:
        path = current_jsonl_path(now_utc, cfg=cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        return True
    except Exception:
        # Fail-open
        return False


def rotate_old_files(*, now_utc: datetime | None = None, cfg: dict | None = None) -> int:
    cfg = cfg or get_sink_config()
    if not cfg.get("enabled", True):
        return 0

    now = now_utc or datetime.now(timezone.utc)
    cutoff = now.date() - timedelta(days=int(cfg["max_days"]))
    root = Path(cfg["dir"])
    if not root.exists():
        return 0

    removed = 0
    prefix = f"{cfg['basename']}-"
    for path in root.glob(f"{cfg['basename']}-*.jsonl"):
        name = path.name
        if not name.startswith(prefix) or not name.endswith(".jsonl"):
            continue
        date_part = name[len(prefix):-6]
        try:
            file_day = datetime.strptime(date_part, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_day < cutoff:
            try:
                path.unlink()
                removed += 1
            except Exception:
                # Fail-open
                pass
    return removed


def build_jsonl_sink(*, cfg: dict | None = None):
    cfg = cfg or get_sink_config()
    state = {"last_rotation_day": None}

    def sink(event: dict) -> None:
        # Never raise to caller; fail-open.
        try:
            now = datetime.now(timezone.utc)
            append_event_jsonl(event, now_utc=now, cfg=cfg)
            day = now.date().isoformat()
            if state["last_rotation_day"] != day:
                rotate_old_files(now_utc=now, cfg=cfg)
                state["last_rotation_day"] = day
        except Exception:
            return

    return sink
