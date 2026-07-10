from __future__ import annotations

from datetime import datetime, timezone


def test_read_json_missing_artifact_returns_empty(tmp_path, monkeypatch):
    from ops import executive_dashboard_report as dash

    missing = tmp_path / "missing.json"
    payload = dash._read_json(missing)

    assert payload == {}


def test_read_json_malformed_json_returns_empty(tmp_path):
    from ops import executive_dashboard_report as dash

    bad = tmp_path / "bad.json"
    bad.write_text("{bad-json", encoding="utf-8")

    payload = dash._read_json(bad)

    assert payload == {}


def test_empty_recommendation_list_returns_empty_impact():
    from ops import executive_dashboard_report as dash

    assert dash._expected_business_impact([]) == []


def test_no_evidence_business_impact_avoids_false_precision():
    from ops import executive_dashboard_report as dash

    items = dash._expected_business_impact(
        [
            {
                "recommended_work": "Do thing",
                "expected_impact": "high",
                "estimated_risk": "low",
                "evidence_status": "no_evidence",
                "sample_count": 0,
            }
        ]
    )

    assert len(items) == 1
    assert items[0]["impact_status"] == "unknown"
    assert items[0]["estimated_kpi_gain"] is None
    assert items[0]["confidence"] == "insufficient_evidence"


def test_duplicate_blocker_signal_is_deduped():
    from ops import executive_dashboard_report as dash

    blockers = dash._top_growth_blockers(
        bundle={"summary": {}},
        fleet={"fleet": {}},
        activation={"system_status": "ready_for_learning_activation"},
        backlog_items=[
            {"signal": "thumbnail_permission_blocked", "reason": "a", "expected_impact": "high"},
            {"signal": "thumbnail_permission_blocked", "reason": "b", "expected_impact": "high"},
        ],
    )

    titles = [item["title"] for item in blockers]
    assert titles.count("Backlog signal: thumbnail_permission_blocked") == 1


def test_business_impact_includes_evidence_metadata_fields():
    from ops import executive_dashboard_report as dash

    items = dash._expected_business_impact(
        [
            {
                "recommended_work": "Resolve thumbnail permissions",
                "expected_impact": "high",
                "estimated_risk": "low",
                "evidence_status": "observed",
                "evidence_source": "logs/thumbnail_permission_cache.json",
                "sample_count": 30,
                "observation_window": "last_14_days",
                "confidence": 0.82,
            }
        ]
    )

    assert items[0]["impact_status"] == "inferred"
    assert items[0]["estimated_kpi_gain"] is not None
    assert isinstance(items[0]["confidence"], float)
    assert items[0]["evidence_source"] == "logs/thumbnail_permission_cache.json"
    assert items[0]["sample_count"] == 30
    assert items[0]["observation_window"] == "last_14_days"


def test_dashboard_output_is_deterministic_for_same_inputs(monkeypatch):
    from ops import executive_dashboard_report as dash

    fixed_now = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDateTime:
        @staticmethod
        def now(_tz=None):
            return fixed_now

    fixtures = {
        str(dash.RUNTIME_EVIDENCE_PATH): {
            "ok": True,
            "target_channel": "para_pusulasi",
            "flag_changed": False,
            "steps": {"activation_controller": {"ok": True}},
        },
        str(dash.FLEET_PATH): {
            "fleet": {
                "active_channels": 9,
                "green_channels": 4,
                "yellow_channels": 5,
                "red_channels": 0,
                "safe_mode_channels": 2,
                "channels_without_data_last_24h": 0,
            }
        },
        str(dash.BACKLOG_PATH): {
            "backlog": [
                {
                    "priority": 1,
                    "signal": "thumbnail_permission_blocked",
                    "reason": "permission",
                    "value": 2,
                    "expected_impact": "high",
                    "estimated_risk": "low",
                    "recommended_work": "fix",
                    "evidence_status": "observed",
                    "sample_count": 10,
                    "observation_window": "last_14_days",
                }
            ]
        },
        str(dash.MEMORY_PATH): {"status": "ok", "insights": []},
        str(dash.ACTIVATION_PATH): {"system_status": "blocked_for_learning_activation", "gates": {}},
        str(dash.BUNDLE_PATH): {"summary": {"streak_blocked_channels": 2, "p0a_guard_review_pending": 1, "p0b_shorts_safety_rows": 0}},
        str(dash.GOVERNANCE_RUN_PATH): {"ok": True},
    }

    monkeypatch.setattr(dash, "datetime", _FixedDateTime)
    monkeypatch.setattr(dash, "_read_json", lambda path: fixtures.get(str(path), {}))

    a = dash.build_dashboard()
    b = dash.build_dashboard()

    assert a == b


def test_strict_bridge_layer_builds_p0_thumbnail_followup_list(monkeypatch):
    from ops import executive_dashboard_report as dash

    fixtures = {
        str(dash.RUNTIME_EVIDENCE_PATH): {"ok": True, "steps": {}},
        str(dash.FLEET_PATH): {
            "fleet": {"active_channels": 2, "green_channels": 1, "yellow_channels": 1, "red_channels": 0},
            "channels": [
                {"channel_id": "para_pusulasi", "analytics_data_status": "OBSERVED"},
                {"channel_id": "egitim_rehberi", "analytics_data_status": "DATA_PENDING"},
            ],
        },
        str(dash.BACKLOG_PATH): {"backlog": []},
        str(dash.MEMORY_PATH): {"status": "ok", "insights": []},
        str(dash.ACTIVATION_PATH): {
            "system_status": "blocked_for_learning_activation",
            "gates": {"analytics_api_probe": {"go": False, "reason": "analytics_probe_skipped"}},
        },
        str(dash.BUNDLE_PATH): {
            "summary": {"streak_blocked_channels": 1},
            "artifacts": {
                "thumbnail_streak_path": {
                    "payload": {
                        "required_streak": 3,
                        "rows": [
                            {
                                "channel_id": "egitim_rehberi",
                                "state": "blocked",
                                "block_reason": "ownership_or_brand_permission",
                                "success_streak": 0,
                                "remaining_successes": 3,
                                "last_probe": {
                                    "status": 403,
                                    "authenticated_channel_id": "UC123",
                                    "authenticated_channel_title": "Egitim Rehberi",
                                },
                            }
                        ],
                    }
                },
                "trace_completeness": {
                    "payload": {
                        "trace_completeness": {"upload_runs_by_channel": {"para_pusulasi": 2}},
                        "metrics_coverage": {
                            "click_through_rate": {"percent": 0.0},
                            "watch_time_hours": {"percent": 0.0},
                            "impressions": {"percent": 0.0},
                            "average_view_duration_seconds": {"percent": 0.0},
                        },
                    }
                },
            },
        },
        str(dash.GOVERNANCE_RUN_PATH): {"ok": True, "degraded": False},
    }

    monkeypatch.setattr(dash, "_read_json", lambda path: fixtures.get(str(path), {}))
    monkeypatch.setattr(
        dash,
        "_read_text",
        lambda _path: "# Strict Evidence Report - 2026-07-10\n- Activation learning state: NO-GO\n- P1 backfill SLO: queued for validation\n",
    )

    report = dash.build_dashboard()
    bridge = report["strict_evidence_bridge_layer"]
    p0_list = bridge["p0_thumbnail_youtube_auth_followup"]["worklist"]

    assert bridge["max_claim_maturity"] == "REPORTED"
    assert len(p0_list) == 1
    assert p0_list[0]["channel_id"] == "egitim_rehberi"
    assert p0_list[0]["last_probe_status"] == 403


def test_strict_bridge_layer_p1_validation_queue_has_channel_criteria(monkeypatch):
    from ops import executive_dashboard_report as dash

    fixtures = {
        str(dash.RUNTIME_EVIDENCE_PATH): {"ok": True, "steps": {}},
        str(dash.FLEET_PATH): {
            "fleet": {"active_channels": 2, "green_channels": 0, "yellow_channels": 2, "red_channels": 0},
            "channels": [
                {"channel_id": "para_pusulasi", "analytics_data_status": "OBSERVED"},
                {"channel_id": "egitim_rehberi", "analytics_data_status": "NO_EVIDENCE"},
            ],
        },
        str(dash.BACKLOG_PATH): {"backlog": []},
        str(dash.MEMORY_PATH): {"status": "ok", "insights": []},
        str(dash.ACTIVATION_PATH): {
            "system_status": "blocked_for_learning_activation",
            "gates": {"analytics_api_probe": {"go": True, "reason": "analytics_api_enabled_and_oauth_ready"}},
        },
        str(dash.BUNDLE_PATH): {
            "summary": {"streak_blocked_channels": 0},
            "artifacts": {
                "thumbnail_streak_path": {"payload": {"required_streak": 3, "rows": []}},
                "trace_completeness": {
                    "payload": {
                        "trace_completeness": {"upload_runs_by_channel": {"para_pusulasi": 1, "egitim_rehberi": 0}},
                        "metrics_coverage": {
                            "click_through_rate": {"percent": 10.0},
                            "watch_time_hours": {"percent": 10.0},
                            "impressions": {"percent": 10.0},
                            "average_view_duration_seconds": {"percent": 10.0},
                        },
                    }
                },
            },
        },
        str(dash.GOVERNANCE_RUN_PATH): {"ok": True, "degraded": False},
    }

    monkeypatch.setattr(dash, "_read_json", lambda path: fixtures.get(str(path), {}))
    monkeypatch.setattr(dash, "_read_text", lambda _path: "")

    report = dash.build_dashboard()
    p1 = report["strict_evidence_bridge_layer"]["p1_analytics_validation_queue"]
    assert p1["status"] == "VALIDATION_QUEUE"
    assert p1["channels_total"] == 2

    first = p1["worklist"][0]
    assert "analytics_api_go" in first["criteria"]
    assert "eligible_input_seen" in first["criteria"]
    assert "rows_appended_evidence" in first["criteria"]
    assert "downstream_consumption_evidence" in first["criteria"]
