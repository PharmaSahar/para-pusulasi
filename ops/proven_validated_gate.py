#!/usr/bin/env python3
"""Evaluate runtime maturity and emit alerts on maturity/blocker transitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scheduler_utils import send_telegram

MONITOR_PATH = PROJECT_ROOT / "logs" / "proven_validated_monitor.jsonl"
GOVERNANCE_PATH = PROJECT_ROOT / "logs" / "governance_refresh_run_latest.json"
STATUS_PATH = PROJECT_ROOT / "logs" / "proven_validated_status_latest.json"
STATE_PATH = PROJECT_ROOT / "logs" / "proven_validated_notify_state.json"
ALERT_COOLDOWN_MINUTES = 30


@dataclass(frozen=True)
class GateConfig:
    freshness_max_minutes: int = 20
    proven_min_healthy_samples: int = 6
    validated_min_healthy_samples: int = 36
    validated_min_hours: float = 6.0
    rolled_out_min_healthy_samples: int = 72
    rolled_out_min_hours: float = 12.0


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_monitor_rows(path: Path, max_rows: int = 1000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    rows = rows[-max_rows:]
    rows.sort(key=lambda r: (_parse_dt(r.get("generated_at_utc")) or _parse_dt(r.get("ts_utc")) or datetime.min.replace(tzinfo=timezone.utc)))
    return rows


def _is_healthy_row(row: dict[str, Any]) -> bool:
    if row.get("ok") is not True:
        return False
    if row.get("degraded") is True:
        return False
    try:
        return int(row.get("required_passed")) == int(row.get("required_total"))
    except Exception:
        return False


def _tail_all_healthy(rows: list[dict[str, Any]], n: int) -> bool:
    if n <= 0:
        return True
    if len(rows) < n:
        return False
    return all(_is_healthy_row(row) for row in rows[-n:])


def _healthy_window_hours(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    idx = len(rows) - 1
    if not _is_healthy_row(rows[idx]):
        return 0.0
    end_ts = _parse_dt(rows[idx].get("generated_at_utc")) or _parse_dt(rows[idx].get("ts_utc"))
    if end_ts is None:
        return 0.0
    while idx >= 0 and _is_healthy_row(rows[idx]):
        idx -= 1
    start_idx = idx + 1
    start_ts = _parse_dt(rows[start_idx].get("generated_at_utc")) or _parse_dt(rows[start_idx].get("ts_utc"))
    if start_ts is None:
        return 0.0
    return max(0.0, (end_ts - start_ts).total_seconds() / 3600.0)


def _blocker_signature(blockers: list[str]) -> str:
    normalized = "|".join(sorted(str(item).strip().lower() for item in blockers if str(item).strip()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def evaluate(config: GateConfig) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = _load_monitor_rows(MONITOR_PATH)
    governance_latest = _load_json(GOVERNANCE_PATH)

    latest_row = rows[-1] if rows else {}
    latest_ts = _parse_dt(latest_row.get("generated_at_utc")) or _parse_dt(latest_row.get("ts_utc"))
    freshness_minutes = None
    latest_snapshot_fresh = False
    if latest_ts is not None:
        freshness_minutes = max(0.0, (now - latest_ts).total_seconds() / 60.0)
        latest_snapshot_fresh = freshness_minutes <= float(config.freshness_max_minutes)

    latest_snapshot_healthy = _is_healthy_row(latest_row) if latest_row else False
    healthy_window_hours = _healthy_window_hours(rows)

    planned = len(rows) == 0
    proven_ready = latest_snapshot_fresh and latest_snapshot_healthy and _tail_all_healthy(rows, config.proven_min_healthy_samples)
    validated_ready = (
        proven_ready
        and _tail_all_healthy(rows, config.validated_min_healthy_samples)
        and healthy_window_hours >= float(config.validated_min_hours)
    )
    rolled_out_ready = (
        validated_ready
        and _tail_all_healthy(rows, config.rolled_out_min_healthy_samples)
        and healthy_window_hours >= float(config.rolled_out_min_hours)
    )

    if planned:
        maturity = "PLANNED"
    elif rolled_out_ready:
        maturity = "ROLLED_OUT"
    elif validated_ready:
        maturity = "VALIDATED"
    elif proven_ready:
        maturity = "PROVEN"
    else:
        maturity = "REPORTED"

    blockers: list[str] = []
    if not rows:
        blockers.append("no_runtime_monitor_rows")
    else:
        if not latest_snapshot_fresh:
            blockers.append("latest_snapshot_stale")
        if not latest_snapshot_healthy:
            blockers.append("latest_snapshot_unhealthy")
        if not _tail_all_healthy(rows, config.proven_min_healthy_samples):
            blockers.append("insufficient_healthy_tail_for_proven")
        if proven_ready and not _tail_all_healthy(rows, config.validated_min_healthy_samples):
            blockers.append("insufficient_healthy_tail_for_validated")
        if proven_ready and healthy_window_hours < float(config.validated_min_hours):
            blockers.append("healthy_window_too_short_for_validated")

    payload = {
        "schema_version": "v1",
        "generated_at_utc": now.isoformat(),
        "maturity": maturity,
        "maturity_order": ["PLANNED", "REPORTED", "PROVEN", "VALIDATED", "ROLLED_OUT"],
        "evidence": {
            "monitor_path": str(MONITOR_PATH),
            "governance_path": str(GOVERNANCE_PATH),
            "rows_observed": len(rows),
            "latest_row": latest_row,
            "latest_snapshot_fresh": latest_snapshot_fresh,
            "latest_snapshot_age_minutes": None if freshness_minutes is None else round(freshness_minutes, 3),
            "latest_snapshot_healthy": latest_snapshot_healthy,
            "healthy_window_hours": round(healthy_window_hours, 3),
            "governance_latest_ok": governance_latest.get("ok"),
            "governance_latest_degraded": governance_latest.get("degraded"),
        },
        "thresholds": {
            "freshness_max_minutes": config.freshness_max_minutes,
            "proven_min_healthy_samples": config.proven_min_healthy_samples,
            "validated_min_healthy_samples": config.validated_min_healthy_samples,
            "validated_min_hours": config.validated_min_hours,
            "rolled_out_min_healthy_samples": config.rolled_out_min_healthy_samples,
            "rolled_out_min_hours": config.rolled_out_min_hours,
        },
        "gate_results": {
            "planned": planned,
            "proven_ready": proven_ready,
            "validated_ready": validated_ready,
            "rolled_out_ready": rolled_out_ready,
        },
        "blockers": blockers,
        "blocker_signature": _blocker_signature(blockers),
    }
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_state() -> dict[str, Any]:
    state = _load_json(STATE_PATH)
    state.setdefault("alert_history", {})
    return state


def _write_state(state: dict[str, Any]) -> None:
    _write_json(STATE_PATH, state)


def _format_blockers(blockers: list[str]) -> str:
    if not blockers:
        return "none"
    return ", ".join(blockers)


def _notify(message: str, notifier: Callable[[str], None] = send_telegram) -> None:
    try:
        notifier(message)
    except Exception:
        return


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_alert_dt(value: Any) -> datetime | None:
    return _parse_dt(value)


def _event_signature(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "maturity_change":
        return f"{payload.get('from', '')}->{payload.get('to', '')}"
    if event_type == "blocker_change":
        return str(payload.get("signature") or "")
    if event_type in {"proven_transition", "validated_transition"}:
        return str(event_type)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _cooldown_active(state: dict[str, Any], event_type: str, signature: str, cooldown_minutes: int = ALERT_COOLDOWN_MINUTES) -> bool:
    history = dict(state.get("alert_history") or {})
    item = history.get(event_type) or {}
    if not isinstance(item, dict):
        return False
    if str(item.get("signature") or "") != signature:
        return False
    last_notified = _parse_alert_dt(item.get("notified_at_utc"))
    if last_notified is None:
        return False
    return (_utc_now() - last_notified).total_seconds() < float(cooldown_minutes) * 60.0


def _record_alert(state: dict[str, Any], event_type: str, signature: str) -> None:
    history = dict(state.get("alert_history") or {})
    history[event_type] = {
        "signature": signature,
        "notified_at_utc": _utc_now().isoformat(),
    }
    state["alert_history"] = history


def maybe_notify_transitions(current: dict[str, Any], previous: dict[str, Any], *, notifier: Callable[[str], None] = send_telegram) -> list[dict[str, Any]]:
    current_maturity = str(current.get("maturity") or "PLANNED")
    previous_maturity = str(previous.get("maturity") or "PLANNED")
    current_blockers = list(current.get("blockers") or [])
    previous_blockers = list(previous.get("blockers") or [])
    current_state = dict(current.get("state") or {})
    if not current_state:
        current_state = {"alert_history": dict(previous.get("alert_history") or {})}
    current.setdefault("state", current_state)

    events: list[dict[str, Any]] = []

    if current_maturity != previous_maturity:
        payload = {"from": previous_maturity, "to": current_maturity}
        signature = _event_signature("maturity_change", payload)
        if not _cooldown_active(current_state, "maturity_change", signature):
            events.append({"type": "maturity_change", **payload})
            _notify(
                f"📡 <b>Governance maturity changed</b>\n"
                f"From: {previous_maturity}\n"
                f"To: {current_maturity}\n"
                f"Blockers: {_format_blockers(current_blockers)}",
                notifier=notifier,
            )
            _record_alert(current_state, "maturity_change", signature)

    current_signature = str(current.get("blocker_signature") or _blocker_signature(current_blockers))
    previous_signature = str(previous.get("blocker_signature") or _blocker_signature(previous_blockers))
    if current_signature != previous_signature:
        payload = {"from": previous_blockers, "to": current_blockers, "signature": current_signature}
        signature = _event_signature("blocker_change", payload)
        if not _cooldown_active(current_state, "blocker_change", signature):
            events.append({"type": "blocker_change", "from": previous_blockers, "to": current_blockers})
            _notify(
                f"⚠️ <b>Governance blockers changed</b>\n"
                f"Old: {_format_blockers(previous_blockers)}\n"
                f"New: {_format_blockers(current_blockers)}",
                notifier=notifier,
            )
            _record_alert(current_state, "blocker_change", signature)

    if previous_maturity != "PROVEN" and current_maturity == "PROVEN":
        signature = _event_signature("proven_transition", {})
        if not _cooldown_active(current_state, "proven_transition", signature):
            events.append({"type": "proven_transition"})
            _notify(
                f"✅ <b>PROVEN reached</b>\n"
                f"Fresh healthy monitor samples now satisfy the PROVEN gate.\n"
                f"Rows: {current.get('evidence', {}).get('rows_observed', 'n/a')}",
                notifier=notifier,
            )
            _record_alert(current_state, "proven_transition", signature)

    if previous_maturity != "VALIDATED" and current_maturity == "VALIDATED":
        signature = _event_signature("validated_transition", {})
        if not _cooldown_active(current_state, "validated_transition", signature):
            events.append({"type": "validated_transition"})
            _notify(
                f"🏁 <b>VALIDATED reached</b>\n"
                f"The sustained healthy runtime window now satisfies the VALIDATED gate.\n"
                f"Healthy window (h): {current.get('evidence', {}).get('healthy_window_hours', 'n/a')}",
                notifier=notifier,
            )
            _record_alert(current_state, "validated_transition", signature)

    return events


def run_gate(*, config: GateConfig, notifier: Callable[[str], None] = send_telegram) -> dict[str, Any]:
    previous_state = _load_state()
    current = evaluate(config)
    current["transition_events"] = maybe_notify_transitions(current, previous_state, notifier=notifier)
    current["previous_maturity"] = previous_state.get("maturity", "PLANNED")
    current["previous_blocker_signature"] = previous_state.get("blocker_signature", "")
    current["state"] = {
        "alert_history": dict(current.get("state", {}).get("alert_history") or previous_state.get("alert_history") or {}),
    }
    _write_json(STATUS_PATH, current)
    _write_state({
        "maturity": current.get("maturity"),
        "blockers": current.get("blockers", []),
        "blocker_signature": current.get("blocker_signature", ""),
        "generated_at_utc": current.get("generated_at_utc"),
        "alert_history": current.get("state", {}).get("alert_history", {}),
    })
    return current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate runtime maturity and emit alerts on transitions")
    parser.add_argument("--out", default=str(STATUS_PATH))
    parser.add_argument("--freshness-max-minutes", type=int, default=20)
    parser.add_argument("--proven-min-healthy-samples", type=int, default=6)
    parser.add_argument("--validated-min-healthy-samples", type=int, default=36)
    parser.add_argument("--validated-min-hours", type=float, default=6.0)
    parser.add_argument("--rolled-out-min-healthy-samples", type=int, default=72)
    parser.add_argument("--rolled-out-min-hours", type=float, default=12.0)
    args = parser.parse_args(argv)

    cfg = GateConfig(
        freshness_max_minutes=max(1, int(args.freshness_max_minutes)),
        proven_min_healthy_samples=max(1, int(args.proven_min_healthy_samples)),
        validated_min_healthy_samples=max(1, int(args.validated_min_healthy_samples)),
        validated_min_hours=max(0.1, float(args.validated_min_hours)),
        rolled_out_min_healthy_samples=max(1, int(args.rolled_out_min_healthy_samples)),
        rolled_out_min_hours=max(0.1, float(args.rolled_out_min_hours)),
    )

    current = run_gate(config=cfg)
    if Path(args.out) != STATUS_PATH:
        _write_json(Path(args.out), current)
    print(json.dumps(current, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())