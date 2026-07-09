from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ops.activation_controller as ac


def _write_thumb_cache(cache_path: Path, *, channel_id: str, can_upload: bool, streak: int) -> None:
    payload = {
        "channels": {
            channel_id: {
                "can_upload_thumbnail": bool(can_upload),
                "success_streak": int(streak),
                "last_reason": None,
                "updated_at": "2026-07-09T00:00:00+00:00",
                "last_probe": {},
            }
        }
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _analytics_probe_go() -> dict:
    return {
        "attempted": True,
        "ok": True,
        "error": None,
        "exit_code": 0,
        "probe_result": {
            "token_after": {"ready": True},
            "oauth": {"ok": True},
        },
        "command": ["fake"],
    }


def test_activation_controller_analytics_probe_skipped_is_blocked(monkeypatch, tmp_path):
    channel_id = "test_channel"
    cache_path = tmp_path / "thumbnail_permission_cache.json"
    report_path = tmp_path / "report.json"

    _write_thumb_cache(cache_path, channel_id=channel_id, can_upload=True, streak=3)

    monkeypatch.setattr(ac, "THUMB_CACHE_PATH", cache_path)

    code = ac.main(
        [
            "--channel",
            channel_id,
            "--skip-analytics-probe",
            "--report-path",
            str(report_path),
        ]
    )

    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["gates"]["analytics_api_probe"]["reason"] == "analytics_probe_skipped"
    assert report["gates"]["thumbnail_permission_probe"]["go"] is True
    assert report["system_status"] == "blocked_for_learning_activation"


def test_activation_controller_thumbnail_streak_below_threshold_is_blocked(monkeypatch, tmp_path):
    channel_id = "test_channel"
    cache_path = tmp_path / "thumbnail_permission_cache.json"
    report_path = tmp_path / "report.json"

    _write_thumb_cache(cache_path, channel_id=channel_id, can_upload=True, streak=2)

    monkeypatch.setattr(ac, "THUMB_CACHE_PATH", cache_path)
    monkeypatch.setattr(ac, "_run_analytics_probe", lambda **kwargs: _analytics_probe_go())

    code = ac.main(
        [
            "--channel",
            channel_id,
            "--report-path",
            str(report_path),
        ]
    )

    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["gates"]["analytics_api_probe"]["go"] is True
    assert report["gates"]["thumbnail_permission_probe"]["go"] is False
    assert report["system_status"] == "blocked_for_learning_activation"


def test_activation_controller_ready_when_analytics_go_and_thumbnail_streak_met(monkeypatch, tmp_path):
    channel_id = "test_channel"
    cache_path = tmp_path / "thumbnail_permission_cache.json"
    report_path = tmp_path / "report.json"

    _write_thumb_cache(cache_path, channel_id=channel_id, can_upload=True, streak=3)

    monkeypatch.setattr(ac, "THUMB_CACHE_PATH", cache_path)
    monkeypatch.setattr(ac, "_run_analytics_probe", lambda **kwargs: _analytics_probe_go())

    code = ac.main(
        [
            "--channel",
            channel_id,
            "--report-path",
            str(report_path),
        ]
    )

    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["flags"]["analytics_collector_enabled"] is True
    assert report["flags"]["thumbnail_learning_enabled"] is True
    assert report["flags"]["ready_for_learning_activation"] is True
    assert report["system_status"] == "ready_for_learning_activation"


def test_activation_controller_activate_learning_returns_exit_2_on_no_go(monkeypatch, tmp_path):
    channel_id = "test_channel"
    cache_path = tmp_path / "thumbnail_permission_cache.json"
    report_path = tmp_path / "report.json"
    flags_path = tmp_path / "flags.json"

    _write_thumb_cache(cache_path, channel_id=channel_id, can_upload=True, streak=3)

    monkeypatch.setattr(ac, "THUMB_CACHE_PATH", cache_path)

    code = ac.main(
        [
            "--channel",
            channel_id,
            "--skip-analytics-probe",
            "--activate-learning",
            "--report-path",
            str(report_path),
            "--flags-path",
            str(flags_path),
        ]
    )

    assert code == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["activation"]["requested"] is True
    assert report["activation"]["applied"] is False
    assert report["activation"]["reason"] == "blocked_by_no_go"
    assert not flags_path.exists()


def test_activation_controller_activate_learning_writes_flags_when_go(monkeypatch, tmp_path):
    channel_id = "test_channel"
    cache_path = tmp_path / "thumbnail_permission_cache.json"
    report_path = tmp_path / "report.json"
    flags_path = tmp_path / "flags.json"

    _write_thumb_cache(cache_path, channel_id=channel_id, can_upload=True, streak=3)

    monkeypatch.setattr(ac, "THUMB_CACHE_PATH", cache_path)
    monkeypatch.setattr(ac, "_run_analytics_probe", lambda **kwargs: _analytics_probe_go())

    code = ac.main(
        [
            "--channel",
            channel_id,
            "--activate-learning",
            "--report-path",
            str(report_path),
            "--flags-path",
            str(flags_path),
        ]
    )

    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["activation"]["applied"] is True
    assert report["activation"]["reason"] == "all_gates_go"

    flags = json.loads(flags_path.read_text(encoding="utf-8"))
    assert flags["analytics_collector_enabled"] is True
    assert flags["thumbnail_learning_enabled"] is True
    assert flags["ready_for_learning_activation"] is True
    assert "activated_at_utc" in flags


def test_activation_controller_writes_report_archive_and_latest(monkeypatch, tmp_path):
    channel_id = "test_channel"
    cache_path = tmp_path / "thumbnail_permission_cache.json"
    report_path = tmp_path / "report.json"
    archive_dir = tmp_path / "activation_reports"

    _write_thumb_cache(cache_path, channel_id=channel_id, can_upload=True, streak=3)

    monkeypatch.setattr(ac, "THUMB_CACHE_PATH", cache_path)

    code = ac.main(
        [
            "--channel",
            channel_id,
            "--skip-analytics-probe",
            "--report-path",
            str(report_path),
            "--report-archive-dir",
            str(archive_dir),
        ]
    )

    assert code == 0
    assert report_path.exists()
    latest_path = archive_dir / "latest.json"
    assert latest_path.exists()

    stamped = [p for p in archive_dir.glob("*.json") if p.name != "latest.json"]
    assert len(stamped) == 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "report_paths" in report
    assert report["report_paths"]["archive_latest"].endswith("latest.json")
    assert report["report_paths"]["archive_stamped"].endswith(stamped[0].name)


def test_activation_controller_no_report_archive_flag_disables_history(monkeypatch, tmp_path):
    channel_id = "test_channel"
    cache_path = tmp_path / "thumbnail_permission_cache.json"
    report_path = tmp_path / "report.json"
    archive_dir = tmp_path / "activation_reports"

    _write_thumb_cache(cache_path, channel_id=channel_id, can_upload=True, streak=3)

    monkeypatch.setattr(ac, "THUMB_CACHE_PATH", cache_path)

    code = ac.main(
        [
            "--channel",
            channel_id,
            "--skip-analytics-probe",
            "--report-path",
            str(report_path),
            "--report-archive-dir",
            str(archive_dir),
            "--no-report-archive",
        ]
    )

    assert code == 0
    assert report_path.exists()
    assert not archive_dir.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "report_paths" not in report
