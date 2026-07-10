#!/usr/bin/env python3
"""Queue quarantine admin CLI.

Capabilities:
- list quarantined entries
- restore one entry by channel_id + queue_entry_id

Safety:
- append-only decision trail is written by scheduler_utils.restore_quarantined_entry
- queue writes are atomic
- no scheduler lifecycle action is performed
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.scheduler_utils import restore_quarantined_entry

QUEUE_PATH = Path("output/queue/channel_queue.json")
DEFAULT_REPORT_PATH = Path("logs/queue_quarantine_admin_latest.json")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _iter_quarantined_entries(queue: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for channel_id, entries in (queue or {}).items():
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status") or "active").strip().lower()
            if status != "quarantined":
                continue
            rows.append(
                {
                    "channel_id": str(channel_id),
                    "queue_entry_id": str(entry.get("queue_entry_id") or ""),
                    "title": str(entry.get("title") or ""),
                    "publish_at": entry.get("publish_at"),
                    "quarantine_reason": str(entry.get("quarantine_reason") or ""),
                    "guard_reason_codes": list(entry.get("guard_reason_codes") or []),
                    "recoverable": bool(entry.get("recoverable", True)),
                    "review_status": str(entry.get("review_status") or "pending"),
                    "quarantined_at": entry.get("quarantined_at"),
                }
            )
    rows.sort(key=lambda row: (row.get("channel_id") or "", row.get("quarantined_at") or ""))
    return rows


def _build_report(*, action: str, ok: bool, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "ok": bool(ok),
        "detail": detail,
    }


def _list_action(queue_path: Path, report_path: Path) -> int:
    queue = _read_json(queue_path)
    rows = _iter_quarantined_entries(queue)
    report = _build_report(
        action="list",
        ok=True,
        detail={
            "queue_path": str(queue_path),
            "quarantined_count": len(rows),
            "items": rows,
        },
    )
    _write_json_atomic(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _restore_action(
    *,
    queue_path: Path,
    report_path: Path,
    channel_id: str,
    queue_entry_id: str,
    reviewer: str,
    review_note: str,
    dry_run: bool,
) -> int:
    queue = _read_json(queue_path)

    if dry_run:
        eligible = False
        for row in _iter_quarantined_entries(queue):
            if row["channel_id"] == channel_id and row["queue_entry_id"] == queue_entry_id:
                eligible = True
                break
        report = _build_report(
            action="restore_dry_run",
            ok=eligible,
            detail={
                "queue_path": str(queue_path),
                "channel_id": channel_id,
                "queue_entry_id": queue_entry_id,
                "reviewer": reviewer,
                "eligible": eligible,
                "applied": False,
            },
        )
        _write_json_atomic(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if eligible else 2

    changed = restore_quarantined_entry(
        queue,
        channel_id=channel_id,
        queue_entry_id=queue_entry_id,
        reviewer=reviewer,
        review_note=review_note,
    )

    if changed:
        _write_json_atomic(queue_path, queue)

    report = _build_report(
        action="restore",
        ok=bool(changed),
        detail={
            "queue_path": str(queue_path),
            "channel_id": channel_id,
            "queue_entry_id": queue_entry_id,
            "reviewer": reviewer,
            "review_note": review_note,
            "applied": bool(changed),
        },
    )
    _write_json_atomic(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if changed else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Queue quarantine admin")
    parser.add_argument("--queue", default=str(QUEUE_PATH), help="Queue JSON path")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="Admin action report output path")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List quarantined queue entries")

    restore = sub.add_parser("restore", help="Restore a quarantined entry")
    restore.add_argument("--channel", required=True, help="Channel id")
    restore.add_argument("--queue-entry-id", required=True, help="Queue entry id")
    restore.add_argument("--reviewer", default="manual", help="Reviewer id")
    restore.add_argument("--note", default="", help="Review note")
    restore.add_argument("--dry-run", action="store_true", help="Validate without mutating queue")

    args = parser.parse_args(argv)

    queue_path = Path(args.queue)
    report_path = Path(args.report)

    if args.command == "list":
        return _list_action(queue_path, report_path)

    return _restore_action(
        queue_path=queue_path,
        report_path=report_path,
        channel_id=str(args.channel),
        queue_entry_id=str(args.queue_entry_id),
        reviewer=str(args.reviewer),
        review_note=str(args.note),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
