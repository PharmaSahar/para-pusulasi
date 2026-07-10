#!/usr/bin/env python3
"""Sync pending OAuth channels to active when token files appear."""

from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from datetime import datetime
from pathlib import Path

from src.channel_manager import get_channel
from src.youtube_auth import get_authenticated_service

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "channels/channel_registry.json"
TRACKER_PATH = ROOT / "channels/channels_tracker.csv"


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_text.lower() if ch.isalnum())


def token_matches_channel(channel_id: str) -> tuple[bool, str | None, str | None]:
    cfg = get_channel(channel_id)
    try:
        svc = get_authenticated_service(channel_cfg=cfg)
        res = svc.channels().list(part="snippet,id", mine=True).execute()
    except Exception as exc:
        return False, None, f"auth_check_failed: {exc}"

    items = res.get("items") or []
    if not items:
        return False, None, "auth_check_failed: no_channel_items"

    actual_id = items[0].get("id") or ""
    actual_name = items[0].get("snippet", {}).get("title", "")
    expected_id = getattr(cfg, "youtube_channel_id", "") or ""
    if expected_id:
        return expected_id == actual_id, actual_name, actual_id
    return normalize_name(cfg.name) == normalize_name(actual_name), actual_name, actual_id


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def load_tracker() -> tuple[list[dict[str, str]], list[str]]:
    if not TRACKER_PATH.exists():
        return [], []
    with TRACKER_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def is_oauth_ready(channel_id: str) -> bool:
    base_dir = ROOT / "channels" / channel_id
    return (base_dir / "youtube_token.pickle").exists() and (base_dir / "client_secrets.json").exists()


def sync(apply: bool) -> Path:
    registry = load_registry()
    tracker_rows, tracker_fields = load_tracker()
    channels = registry.get("channels", {})

    updated_registry: list[str] = []
    updated_tracker: list[str] = []
    mismatched_tokens: list[dict[str, str]] = []
    for channel_id, config in channels.items():
        ready = is_oauth_ready(channel_id)
        matched = False
        actual_name = None
        actual_id = None
        if ready:
            matched, actual_name, actual_id = token_matches_channel(channel_id)
            if not matched:
                mismatched_tokens.append({
                    "channel": channel_id,
                    "actual_name": actual_name or "",
                    "actual_id": actual_id or "",
                })
                ready = False
        if ready and config.get("status") == "pending_oauth":
            config["status"] = "active"
            updated_registry.append(channel_id)

        for row in tracker_rows:
            if row.get("channel_id") != channel_id:
                continue
            if ready:
                changed = False
                if row.get("token_ready") != "TRUE":
                    row["token_ready"] = "TRUE"
                    changed = True
                if row.get("status") != "active":
                    row["status"] = "active"
                    changed = True
                if changed:
                    updated_tracker.append(channel_id)
            break

    if apply and updated_registry:
        REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if apply and tracker_rows and updated_tracker and tracker_fields:
        with TRACKER_PATH.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=tracker_fields)
            writer.writeheader()
            writer.writerows(tracker_rows)

    report = {
        "generated_at": datetime.now().isoformat(),
        "apply": apply,
        "updated_registry": updated_registry,
        "updated_tracker": updated_tracker,
        "ready_channels": sorted(set(updated_registry) | set(updated_tracker)),
        "mismatched_tokens": mismatched_tokens,
        "summary": {
            "registry_updates": len(updated_registry),
            "tracker_updates": len(updated_tracker),
            "ready_channels": len(sorted(set(updated_registry) | set(updated_tracker))),
            "mismatched_tokens": len(mismatched_tokens),
        },
    }
    out_path = ROOT / "logs" / f"sync_oauth_ready_channels_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync OAuth-ready channels into active status")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = sync(apply=args.apply)
    print(json.dumps({"report": str(report.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
