import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_jsonl_append_writes_one_line(tmp_path):
    from src.telemetry_sink import append_event_jsonl

    cfg = {
        "enabled": True,
        "dir": str(tmp_path),
        "basename": "events",
        "max_days": 14,
    }
    event = {"event_id": "evt_1", "k": "v"}

    ok = append_event_jsonl(event, now_utc=datetime(2026, 7, 7, tzinfo=timezone.utc), cfg=cfg)
    assert ok is True

    out = tmp_path / "events-2026-07-07.jsonl"
    assert out.exists()
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == event


def test_daily_file_naming(tmp_path):
    from src.telemetry_sink import current_jsonl_path

    cfg = {
        "enabled": True,
        "dir": str(tmp_path),
        "basename": "events",
        "max_days": 14,
    }
    p = current_jsonl_path(datetime(2026, 7, 8, 1, 2, 3, tzinfo=timezone.utc), cfg=cfg)
    assert p.name == "events-2026-07-08.jsonl"


def test_rotation_removes_old_files_only(tmp_path):
    from src.telemetry_sink import rotate_old_files

    (tmp_path / "events-2026-06-20.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "events-2026-07-01.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "events-2026-07-07.jsonl").write_text("{}\n", encoding="utf-8")

    cfg = {
        "enabled": True,
        "dir": str(tmp_path),
        "basename": "events",
        "max_days": 7,
    }
    removed = rotate_old_files(now_utc=datetime(2026, 7, 8, tzinfo=timezone.utc), cfg=cfg)
    assert removed >= 1
    assert not (tmp_path / "events-2026-06-20.jsonl").exists()
    assert (tmp_path / "events-2026-07-01.jsonl").exists()
    assert (tmp_path / "events-2026-07-07.jsonl").exists()


def test_sink_is_fail_open_on_io_error(tmp_path, monkeypatch):
    from src import telemetry_sink

    cfg = {
        "enabled": True,
        "dir": str(tmp_path),
        "basename": "events",
        "max_days": 14,
    }

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(telemetry_sink, "current_jsonl_path", boom)
    ok = telemetry_sink.append_event_jsonl({"event_id": "evt_1"}, cfg=cfg)
    assert ok is False


def test_emit_event_uses_sink_without_breaking_logger_path(monkeypatch, tmp_path):
    from src import telemetry

    # Reset lazy sink state
    monkeypatch.setattr(telemetry, "_DEFAULT_SINK", None)
    monkeypatch.setattr(telemetry, "_SINK_INIT_ATTEMPTED", False)

    monkeypatch.setenv("TELEMETRY_SINK_ENABLED", "true")
    monkeypatch.setenv("TELEMETRY_SINK_DIR", str(tmp_path))
    monkeypatch.setenv("TELEMETRY_SINK_BASENAME", "events")

    class DummyLogger:
        def __init__(self):
            self.calls = 0

        def info(self, *args, **kwargs):
            self.calls += 1

    logger = DummyLogger()

    event = {
        "event_id": "evt_1",
        "content_id": "content_1",
        "run_id": "run_1",
        "stage": "x",
        "event_type": "stage_started",
        "occurred_at_utc": "2026-07-07T00:00:00+00:00",
        "channel_id": "c1",
        "payload": {},
        "experiment_id": None,
        "asset_id": None,
    }

    telemetry.emit_event(event, logger=logger)

    files = list(tmp_path.glob("events-*.jsonl"))
    assert len(files) == 1
    assert logger.calls == 1


def test_storage_overhead_basic(tmp_path):
    from src.telemetry_sink import append_event_jsonl

    cfg = {
        "enabled": True,
        "dir": str(tmp_path),
        "basename": "events",
        "max_days": 14,
    }
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)

    for i in range(100):
        assert append_event_jsonl({"event_id": f"evt_{i}", "i": i}, now_utc=now, cfg=cfg) is True

    out = tmp_path / "events-2026-07-07.jsonl"
    assert out.exists()
    assert len(out.read_text(encoding="utf-8").splitlines()) == 100
