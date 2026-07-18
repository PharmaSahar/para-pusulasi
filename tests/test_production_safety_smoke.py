from __future__ import annotations

import src.production_safety_smoke as production_safety_smoke


def test_smoke_report_schema(monkeypatch, tmp_path):
    class _Cfg:
        output_dir = str(tmp_path / "output")
        logs_dir = str(tmp_path / "logs")

    monkeypatch.setattr(production_safety_smoke, "get_channel", lambda _cid: _Cfg())
    monkeypatch.setattr(production_safety_smoke, "run_production_health_check", lambda *_args, **_kwargs: type("H", (), {"ok": True, "errors": ()})())
    monkeypatch.setattr(production_safety_smoke, "evaluate_production_safety_gate", lambda **_kwargs: type("G", (), {"allowed": True, "status": "allowed", "to_dict": lambda self: {"ok": True}})())
    monkeypatch.setattr(
        production_safety_smoke,
        "run_full_pipeline",
        lambda **_kwargs: {
            "video_path": str(tmp_path / "video.mp4"),
            "final_status": "dry_run",
            "upload_metadata": {"dry_run": True, "api_invoked": False},
            "upload_precheck": {"status": "allow", "guard_reason_codes": []},
            "performance_snapshot": {
                "performance_schema_version": "v1",
                "day": "2026-07-18",
                "created_at": "2026-07-18T10:00:00+00:00",
                "channel_id": "demo_channel",
                "content_id": "content_1",
                "run_id": "run_1",
                "title": "title",
            },
        },
    )
    monkeypatch.setattr(production_safety_smoke, "validate_performance_snapshot", lambda *_args, **_kwargs: type("A", (), {"accepted": True, "message": "ok", "reason_code": "ok", "status": "accepted", "evidence": {}, "duplicate": False})())
    monkeypatch.setattr(production_safety_smoke, "run_read_only_smoke", lambda **_kwargs: {"status": "SKIPPED_NO_GO"})
    events = []
    monkeypatch.setattr(production_safety_smoke, "record_production_event", lambda payload: events.append(payload))
    monkeypatch.setattr(production_safety_smoke, "_resolve_git_head", lambda: "a" * 40)

    report = production_safety_smoke.run_production_safety_smoke(channel_id="demo", output_path=tmp_path / "smoke.json")

    assert report["decision"] == "PASS"
    assert report["checks"]
    assert events[-1]["event_type"] == "production_safety_smoke"