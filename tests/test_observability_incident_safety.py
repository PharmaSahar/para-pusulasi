from __future__ import annotations

import json
import threading
from contextlib import contextmanager

import src.scheduler_utils as scheduler_utils


def test_notify_error_fail_open_when_incident_write_fails(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))
    monkeypatch.setattr(scheduler_utils, "_register_incident_event", lambda **_kwargs: (_ for _ in ()).throw(OSError("read only fs")))

    result = scheduler_utils.notify_error("Demo", "Anthropic circuit open; provider is cooling down (580s)")

    assert result["decision"] == "continue_with_monitoring"
    assert result["incident_lifecycle"] == "INCIDENT_OBSERVABILITY_UNAVAILABLE"
    assert len(sent) == 1


def test_incident_jsonl_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv("INCIDENT_EVENTS_MAX_LINES", "3")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda _message: None)

    for idx in range(6):
        scheduler_utils.notify_error(
            "Demo",
            "topic_provenance_collision:/tmp/probe.json",
            context={"run_id": f"run_{idx}", "pipeline_stage": "content_generation", "retry_count": idx % 3},
        )

    lines = (tmp_path / "production_incidents.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 3
    # Ensure lines remain valid JSON after truncation.
    for row in lines:
        assert isinstance(json.loads(row), dict)


def test_concurrent_notify_error_writes_keep_state_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda _message: None)

    def _worker(worker_id: int):
        for idx in range(8):
            scheduler_utils.notify_error(
                f"Channel-{worker_id}",
                "temporary timeout while contacting provider",
                context={"run_id": f"run-{worker_id}", "retry_count": idx, "retry_limit": 8},
            )

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    payload = json.loads((tmp_path / "incident_state.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert isinstance(payload.get("incidents"), dict)
    assert isinstance(payload.get("open_by_fingerprint"), dict)


def test_notify_error_redacts_filesystem_paths_in_telegram_payload(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setenv("PRODUCTION_ALERT_DEBUG_MODE", "0")
    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    scheduler_utils.notify_error(
        "Demo",
        (
            "topic_provenance_collision: "
            "/tmp/probe.json /var/log/probe.json /opt/app/probe.json /home/user/probe.json /Users/klara/probe.json "
            "C:\\Users\\tester\\data\\probe.json \\\\server\\share\\probe.json "
            "channels/demo/item.json output/tmp/item.json logs/run/item.json artifacts/latest/evidence.json "
            "config/runtime_manifest.json src/scheduler_utils.py tests/test_observability_incident_safety.py"
        ),
        context={"run_id": "run-path", "pipeline_stage": "content_generation"},
    )

    assert len(sent) == 1
    payload = sent[0]
    assert "[path_hidden]" in payload
    assert "/tmp/" not in payload
    assert "/var/" not in payload
    assert "/opt/" not in payload
    assert "/home/" not in payload
    assert "/Users/" not in payload
    assert "C:\\" not in payload
    assert "\\\\server\\" not in payload
    assert "channels/" not in payload
    assert "output/" not in payload
    assert "logs/" not in payload
    assert "artifacts/" not in payload
    assert "config/" not in payload
    assert "src/" not in payload
    assert "tests/" not in payload


def test_corrupted_incident_state_json_is_fail_open(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    scheduler_utils.INCIDENT_STATE_FILE.write_text("{not-json", encoding="utf-8")

    result = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"run_id": "run-corrupt", "pipeline_stage": "scheduler_render", "retry_count": 2},
    )

    assert result["decision"] == "retry_then_continue"
    assert result["incident_lifecycle"] == "INCIDENT_OPEN"
    assert result["retry_count"] == 2
    assert len(sent) == 1


def test_notify_error_fail_open_when_incident_lock_fails(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    @contextmanager
    def _boom_lock():
        raise TimeoutError("lock busy")
        yield

    monkeypatch.setattr(scheduler_utils, "_incident_io_lock", _boom_lock)

    result = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"run_id": "run-lock", "pipeline_stage": "scheduler_render", "retry_count": 1},
    )

    assert result["decision"] == "retry_then_continue"
    assert result["incident_lifecycle"] == "INCIDENT_OBSERVABILITY_UNAVAILABLE"
    assert result["retry_count"] == 1
    assert len(sent) == 1


def test_notify_error_fail_open_when_alert_state_write_fails(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    original_write_text = scheduler_utils.Path.write_text

    def boom(self, *args, **kwargs):
        if str(self).endswith("alerts_sent.json"):
            raise PermissionError("read only")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(scheduler_utils.Path, "write_text", boom)

    result = scheduler_utils.notify_error("Demo", "temporary timeout while contacting provider")

    assert result["decision"] == "retry_then_continue"
    assert result["incident_lifecycle"] == "INCIDENT_OPEN"
    assert len(sent) == 1


def test_stale_incident_state_does_not_suppress_new_incident(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    stale = {
        "open_by_fingerprint": {
            "stale_fingerprint": {
                "incident_id": "stale_incident",
                "channel": "Demo",
                "opened_at": "2020-01-01T00:00:00+00:00",
                "error_type": "topic_provenance_collision",
            }
        },
        "incidents": {
            "stale_incident": {
                "incident_id": "stale_incident",
                "fingerprint": "stale_fingerprint",
                "channel": "Demo",
                "error_type": "topic_provenance_collision",
                "status": "open",
                "opened_at": "2020-01-01T00:00:00+00:00",
                "updated_at": "2020-01-01T00:00:00+00:00",
            }
        },
    }
    scheduler_utils.INCIDENT_STATE_FILE.write_text(json.dumps(stale), encoding="utf-8")

    result = scheduler_utils.notify_error(
        "Demo",
        "topic_provenance_collision:/var/tmp/fresh.json",
        context={"run_id": "run-fresh", "pipeline_stage": "content_generation"},
    )

    assert result["incident_lifecycle"] == "INCIDENT_OPEN"
    assert result["incident_id"] != "stale_incident"
    assert len(sent) == 1


def test_stale_open_incident_state_is_pruned(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    stale = {
        "open_by_fingerprint": {
            "stale_fingerprint": {
                "incident_id": "stale_incident",
                "channel": "Demo",
                "opened_at": "2020-01-01T00:00:00+00:00",
                "error_type": "topic_provenance_collision",
            }
        },
        "incidents": {
            "stale_incident": {
                "incident_id": "stale_incident",
                "fingerprint": "stale_fingerprint",
                "channel": "Demo",
                "error_type": "topic_provenance_collision",
                "status": "open",
                "opened_at": "2020-01-01T00:00:00+00:00",
                "updated_at": "2020-01-01T00:00:00+00:00",
            }
        },
    }
    scheduler_utils.INCIDENT_STATE_FILE.write_text(json.dumps(stale), encoding="utf-8")

    result = scheduler_utils.notify_error(
        "Demo",
        "topic_provenance_collision: /var/tmp/fresh.json",
        context={"incident_fingerprint": "stale_fingerprint", "run_id": "fresh-run", "content_id": "fresh-content", "pipeline_stage": "content_generation"},
    )

    state = json.loads(scheduler_utils.INCIDENT_STATE_FILE.read_text(encoding="utf-8"))
    assert result["incident_lifecycle"] == "INCIDENT_OPEN"
    assert result["incident_id"] != "stale_incident"
    assert "stale_incident" not in state.get("incidents", {})
    assert len(sent) == 1


def test_critical_event_is_not_hidden_by_warning_cooldown(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    warning = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"severity": "WARNING", "run_id": "run-severity", "pipeline_stage": "scheduler_render"},
    )
    critical = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"severity": "CRITICAL", "run_id": "run-severity", "pipeline_stage": "scheduler_render"},
    )

    assert warning["incident_lifecycle"] == "INCIDENT_OPEN"
    assert critical["incident_lifecycle"] == "INCIDENT_UPDATED"
    assert len(sent) == 2


def test_notify_error_unchanged_state_suppresses_repeated_updates(monkeypatch, tmp_path):
    sent: list[str] = []

    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: sent.append(message))

    first = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"run_id": "run-stable", "pipeline_stage": "scheduler_render", "retry_count": 0},
    )
    second = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"run_id": "run-stable", "pipeline_stage": "scheduler_render", "retry_count": 0},
    )

    assert first["incident_lifecycle"] == "INCIDENT_OPEN"
    assert second["incident_lifecycle"] == "INCIDENT_UNCHANGED"
    assert len(sent) == 1

    rows = (tmp_path / "production_incidents.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1


def test_notify_error_meaningful_delta_emits_updated_event(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda _message: None)

    first = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"run_id": "run-delta", "pipeline_stage": "scheduler_render", "retry_count": 0},
    )
    second = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"run_id": "run-delta", "pipeline_stage": "scheduler_render", "retry_count": 1},
    )

    assert first["incident_lifecycle"] == "INCIDENT_OPEN"
    assert second["incident_lifecycle"] == "INCIDENT_UPDATED"

    rows = [json.loads(line) for line in (tmp_path / "production_incidents.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[-1]["incident_lifecycle"] == "INCIDENT_UPDATED"


def test_resolve_lifecycle_happens_once_and_tracks_uploaded_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler_utils, "ALERTS_FILE", str(tmp_path / "alerts_sent.json"))
    monkeypatch.setattr(scheduler_utils, "INCIDENT_EVENTS_FILE", tmp_path / "production_incidents.jsonl")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_STATE_FILE", tmp_path / "incident_state.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_METRICS_FILE", tmp_path / "incident_metrics_latest.json")
    monkeypatch.setattr(scheduler_utils, "INCIDENT_LOCK_FILE", tmp_path / "incident_state.lock")
    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda _message: None)

    opened = scheduler_utils.notify_error(
        "Demo",
        "temporary timeout while contacting provider",
        context={"run_id": "run-resolve", "content_id": "cnt-1", "pipeline_stage": "scheduler_render"},
    )
    assert opened["incident_lifecycle"] == "INCIDENT_OPEN"

    resolved_first = scheduler_utils._resolve_open_incidents_for_channel(
        "Demo",
        run_id="run-resolve",
        pipeline_stage="upload",
        context={
            "content_id": "cnt-1",
            "uploaded_artifact_id": "video-123",
            "upload_outcome": "uploaded",
            "blocked_artifact_uploaded": False,
        },
    )
    resolved_second = scheduler_utils._resolve_open_incidents_for_channel(
        "Demo",
        run_id="run-resolve",
        pipeline_stage="upload",
        context={
            "content_id": "cnt-1",
            "uploaded_artifact_id": "video-123",
            "upload_outcome": "uploaded",
            "blocked_artifact_uploaded": False,
        },
    )

    assert len(resolved_first) == 1
    assert resolved_first[0]["lifecycle_event"] == "INCIDENT_RESOLVED"
    assert resolved_second == []

    rows = [json.loads(line) for line in (tmp_path / "production_incidents.jsonl").read_text(encoding="utf-8").splitlines()]
    resolved_rows = [row for row in rows if row.get("incident_lifecycle") == "INCIDENT_RESOLVED"]
    assert len(resolved_rows) == 1
    correlation = dict(resolved_rows[0].get("artifact_correlation") or {})
    assert correlation.get("uploaded_artifact_id") == "video-123"
    assert correlation.get("blocked_artifact_uploaded") is False
