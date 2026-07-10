#!/usr/bin/env python3
"""Sync pending OAuth channels to active when token files appear."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "channels/channel_registry.json"
TRACKER_PATH = ROOT / "channels/channels_tracker.csv"


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
    for channel_id, config in channels.items():
        ready = is_oauth_ready(channel_id)
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
        "summary": {
            "registry_updates": len(updated_registry),
            "tracker_updates": len(updated_tracker),
            "ready_channels": len(sorted(set(updated_registry) | set(updated_tracker))),
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
