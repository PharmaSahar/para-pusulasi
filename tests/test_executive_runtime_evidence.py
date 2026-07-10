import json
from types import SimpleNamespace


def test_runtime_flag_ab_evidence_detects_change_and_rollback(tmp_path, monkeypatch):
    from ops import runtime_flag_ab_evidence as ab

    flags_path = tmp_path / "flags.json"
    cache_path = tmp_path / "thumb_cache.json"

    flags_path.write_text(json.dumps({}, ensure_ascii=True), encoding="utf-8")
    cache_path.write_text(
        json.dumps({"channels": {"para_pusulasi": {"can_upload_thumbnail": True}}}, ensure_ascii=True),
        encoding="utf-8",
    )

    monkeypatch.setattr(ab, "FLAGS_PATH", flags_path)
    monkeypatch.setattr(ab, "THUMB_CACHE_PATH", cache_path)
    monkeypatch.setattr(ab, "get_channel", lambda _cid: SimpleNamespace(thumbnail_selection_policy="first"))

    def _fake_resolver(_cfg, _channel_id):
        flags = json.loads(flags_path.read_text(encoding="utf-8"))
        on = bool(flags.get("thumbnail_learning_enabled", False))
        policy = "max_attention_score" if on else "first"
        return policy, {"thumbnail_learning_enabled": on, "effective_policy": policy}

    monkeypatch.setattr(ab, "_resolve_runtime_policy", _fake_resolver)

    report = ab.build_ab_evidence(channel_id="para_pusulasi")

    assert report["assertions"]["behavior_changed_when_on"] is True
    assert report["assertions"]["behavior_reverted_when_off"] is True
    assert report["result"]["ok"] is True


def test_executive_dashboard_aggregates_runtime_artifacts(tmp_path, monkeypatch):
    from ops import executive_dashboard_report as dash

    runtime_path = tmp_path / "runtime.json"
    fleet_path = tmp_path / "fleet.json"
    backlog_path = tmp_path / "backlog.json"
    memory_path = tmp_path / "memory.json"
    activation_path = tmp_path / "activation.json"

    runtime_path.write_text(
        json.dumps(
            {
                "ok": True,
                "target_channel": "para_pusulasi",
                "flag_changed": True,
                "steps": {
                    "activation_controller": {"ok": True},
                    "fleet_health": {"ok": True},
                },
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    fleet_path.write_text(
        json.dumps(
            {
                "fleet": {
                    "active_channels": 9,
                    "green_channels": 6,
                    "yellow_channels": 3,
                    "red_channels": 0,
                    "safe_mode_channels": 2,
                }
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    backlog_path.write_text(
        json.dumps(
            {"backlog": [{"priority": 1, "signal": "thumbnail_permission_blocked"}]},
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    memory_path.write_text(
        json.dumps(
            {
                "insights": [{"type": "title_question_pattern"}],
                "coverage": {"has_title_pattern_memory": True},
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    activation_path.write_text(
        json.dumps(
            {
                "system_status": "blocked_for_learning_activation",
                "gates": {
                    "analytics_api_probe": {"go": False},
                    "thumbnail_permission_probe": {"go": True},
                    "runtime_policy_engine": {"go": True},
                },
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(dash, "RUNTIME_EVIDENCE_PATH", runtime_path)
    monkeypatch.setattr(dash, "FLEET_PATH", fleet_path)
    monkeypatch.setattr(dash, "BACKLOG_PATH", backlog_path)
    monkeypatch.setattr(dash, "MEMORY_PATH", memory_path)
    monkeypatch.setattr(dash, "ACTIVATION_PATH", activation_path)

    report = dash.build_dashboard()

    assert report["platform_status"] == "watch"
    assert report["runtime_evidence"]["ok"] is True
    assert report["optimization_backlog"]["top_priority"] == 1
    assert report["optimization_memory"]["insight_count"] == 1
