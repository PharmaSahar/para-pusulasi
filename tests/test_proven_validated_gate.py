from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import ops.proven_validated_gate as gate


def _write_monitor_rows(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def _healthy_rows(count: int, *, start_minutes_ago: int = 10, step_minutes: int = 10):
    now = datetime.now(timezone.utc)
    rows = []
    for idx in range(count):
        ts = now - timedelta(minutes=start_minutes_ago + idx * step_minutes)
        rows.append(
            {
                "ts_utc": ts.isoformat().replace("+00:00", "Z"),
                "generated_at_utc": ts.isoformat(),
                "ok": True,
                "degraded": False,
                "required_passed": 3,
                "required_total": 3,
                "optional_failed": 0,
            }
        )
    return list(reversed(rows))


def test_run_gate_emits_level_blocker_and_proven_alerts(tmp_path, monkeypatch):
    monitor = tmp_path / "proven_validated_monitor.jsonl"
    status = tmp_path / "proven_validated_status_latest.json"
    state = tmp_path / "proven_validated_notify_state.json"
    governance = tmp_path / "governance_refresh_run_latest.json"

    gate.MONITOR_PATH = monitor
    gate.STATUS_PATH = status
    gate.STATE_PATH = state
    gate.GOVERNANCE_PATH = governance

    _write_monitor_rows(monitor, _healthy_rows(6))
    governance.write_text(json.dumps({"ok": True, "degraded": False}, ensure_ascii=False), encoding="utf-8")
    state.write_text(
        json.dumps(
            {
                "maturity": "REPORTED",
                "blockers": ["latest_snapshot_unhealthy"],
                "blocker_signature": "oldsig",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    alerts: list[str] = []
    result = gate.run_gate(config=gate.GateConfig(), notifier=alerts.append)

    assert result["maturity"] == "PROVEN"
    assert any("Governance maturity changed" in msg for msg in alerts)
    assert any("Governance blockers changed" in msg for msg in alerts)
    assert any("PROVEN reached" in msg for msg in alerts)
    assert status.exists()
    assert state.exists()


def test_run_gate_emits_validated_alarm_on_transition(tmp_path):
    monitor = tmp_path / "proven_validated_monitor.jsonl"
    status = tmp_path / "proven_validated_status_latest.json"
    state = tmp_path / "proven_validated_notify_state.json"
    governance = tmp_path / "governance_refresh_run_latest.json"

    gate.MONITOR_PATH = monitor
    gate.STATUS_PATH = status
    gate.STATE_PATH = state
    gate.GOVERNANCE_PATH = governance

    _write_monitor_rows(monitor, _healthy_rows(36, start_minutes_ago=5, step_minutes=11))
    governance.write_text(json.dumps({"ok": True, "degraded": False}, ensure_ascii=False), encoding="utf-8")
    state.write_text(
        json.dumps(
            {
                "maturity": "PROVEN",
                "blockers": [],
                "blocker_signature": gate._blocker_signature([]),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    alerts: list[str] = []
    result = gate.run_gate(config=gate.GateConfig(), notifier=alerts.append)

    assert result["maturity"] == "VALIDATED"
    assert any("Governance maturity changed" in msg for msg in alerts)
    assert any("VALIDATED reached" in msg for msg in alerts)
    assert not any("Governance blockers changed" in msg for msg in alerts)


def test_run_gate_suppresses_duplicate_blocker_alerts_within_cooldown(tmp_path):
    monitor = tmp_path / "proven_validated_monitor.jsonl"
    status = tmp_path / "proven_validated_status_latest.json"
    state = tmp_path / "proven_validated_notify_state.json"
    governance = tmp_path / "governance_refresh_run_latest.json"

    gate.MONITOR_PATH = monitor
    gate.STATUS_PATH = status
    gate.STATE_PATH = state
    gate.GOVERNANCE_PATH = governance

    _write_monitor_rows(monitor, _healthy_rows(6))
    governance.write_text(json.dumps({"ok": True, "degraded": False}, ensure_ascii=False), encoding="utf-8")

    alerts_first: list[str] = []
    result_first = gate.run_gate(config=gate.GateConfig(), notifier=alerts_first.append)

    assert result_first["maturity"] == "PROVEN"
    assert any("Governance maturity changed" in msg for msg in alerts_first)

    saved_state = json.loads(state.read_text(encoding="utf-8"))
    saved_state["maturity"] = "PLANNED"
    saved_state["blockers"] = []
    saved_state["blocker_signature"] = ""
    state.write_text(json.dumps(saved_state, ensure_ascii=False), encoding="utf-8")

    alerts_second: list[str] = []
    result_second = gate.run_gate(config=gate.GateConfig(), notifier=alerts_second.append)

    assert result_second["maturity"] == "PROVEN"
    assert alerts_second == []