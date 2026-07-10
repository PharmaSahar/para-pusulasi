from __future__ import annotations


def test_readiness_markdown_includes_secondary_bridge_section():
    from ops import refresh_governance_readiness as refresh

    markdown = refresh._build_readiness_markdown(
        generated_at="2026-07-10T00:00:00+00:00",
        lookback_rows=500,
        steps=[
            {
                "name": "executive_dashboard",
                "required": False,
                "exit_code": 0,
                "artifact": "/tmp/executive_dashboard.json",
                "warning": "-",
            }
        ],
    )

    assert "## Secondary Summary Layer" in markdown
    assert "logs/governance_dashboard_bridge_latest.json" in markdown


def test_run_refresh_artifacts_include_strict_evidence_bridge(tmp_path, monkeypatch):
    from ops import refresh_governance_readiness as refresh

    def _fake_run_step(command, *, required, fail_open, fallback_artifact=None):
        return {
            "name": "fake_step",
            "command": command,
            "exit_code": 0,
            "required": required,
            "fail_open": fail_open,
            "started_at_utc": "2026-07-10T00:00:00+00:00",
            "finished_at_utc": "2026-07-10T00:00:01+00:00",
            "warning": None,
            "fallback_artifact": str(fallback_artifact) if fallback_artifact else None,
        }

    monkeypatch.setattr(refresh, "_run_step", _fake_run_step)
    monkeypatch.setattr(refresh, "_append_monitor_row", lambda _snapshot: None)
    monkeypatch.setattr(refresh, "LATEST_PATH", tmp_path / "governance_refresh_run_latest.json")

    payload = refresh.run_refresh(lookback_rows=500)

    assert payload["ok"] is True
    assert "strict_evidence_bridge" in payload["artifacts"]
    assert payload["artifacts"]["strict_evidence_bridge"].endswith("logs/governance_dashboard_bridge_latest.json")
