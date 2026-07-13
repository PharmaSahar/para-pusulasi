from __future__ import annotations

from pathlib import Path


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
    assert payload["artifacts"]["strict_evidence_bridge"].endswith("output/runtime/telemetry/governance_dashboard_bridge_latest.json")


def test_run_step_required_missing_script_with_fallback_artifact_fails(tmp_path):
    from ops import refresh_governance_readiness as refresh

    fallback = tmp_path / "p0_validation_metrics_latest.json"
    fallback.write_text("{}", encoding="utf-8")

    result = refresh._run_step(
        ["python", "ops/nonexistent_required_step.py"],
        required=True,
        fail_open=False,
        fallback_artifact=fallback,
    )

    assert result["exit_code"] != 0
    assert result["warning"] == "script_missing_required_hard_fail"


def test_run_step_required_missing_script_without_fallback_artifact_fails():
    from ops import refresh_governance_readiness as refresh

    result = refresh._run_step(
        ["python", "ops/nonexistent_required_step.py"],
        required=True,
        fail_open=False,
        fallback_artifact=None,
    )

    assert result["exit_code"] != 0
    assert result["warning"] == "script_missing_required_hard_fail"


def test_run_step_required_execution_failure_fails(monkeypatch):
    from ops import refresh_governance_readiness as refresh

    class _Proc:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(refresh.subprocess, "run", lambda *args, **kwargs: _Proc())

    result = refresh._run_step(
        ["python", "ops/refresh_governance_readiness.py"],
        required=True,
        fail_open=False,
        fallback_artifact=None,
    )

    assert result["exit_code"] != 0


def test_run_step_optional_fail_open_with_fallback_artifact_passes(tmp_path):
    from ops import refresh_governance_readiness as refresh

    fallback = tmp_path / "executive_dashboard.json"
    fallback.write_text("{}", encoding="utf-8")

    result = refresh._run_step(
        ["python", "ops/nonexistent_optional_step.py"],
        required=False,
        fail_open=True,
        fallback_artifact=fallback,
    )

    assert result["exit_code"] == 0
    assert result["warning"] == "script_missing_fallback_artifact_used"


def test_run_refresh_required_step_failure_forces_ok_false(tmp_path, monkeypatch):
    from ops import refresh_governance_readiness as refresh

    def _fake_run_step(command, *, required, fail_open, fallback_artifact=None):
        command_name = Path(command[1]).name if len(command) > 1 else "unknown"
        exit_code = 1 if command_name == "p0_validation_metrics_report.py" else 0
        warning = "forced_required_failure" if exit_code else None
        return {
            "name": command_name,
            "command": command,
            "exit_code": exit_code,
            "required": required,
            "fail_open": fail_open,
            "started_at_utc": "2026-07-10T00:00:00+00:00",
            "finished_at_utc": "2026-07-10T00:00:01+00:00",
            "warning": warning,
            "fallback_artifact": str(fallback_artifact) if fallback_artifact else None,
        }

    monkeypatch.setattr(refresh, "_run_step", _fake_run_step)
    monkeypatch.setattr(refresh, "_append_monitor_row", lambda _snapshot: None)
    monkeypatch.setattr(refresh, "LATEST_PATH", tmp_path / "governance_refresh_run_latest.json")

    payload = refresh.run_refresh(lookback_rows=500)

    assert payload["ok"] is False
    assert payload["required_steps_passed"] < payload["required_steps_total"]


def test_readiness_markdown_reports_fail_for_required_hard_fail():
    from ops import refresh_governance_readiness as refresh

    markdown = refresh._build_readiness_markdown(
        generated_at="2026-07-10T00:00:00+00:00",
        lookback_rows=500,
        steps=[
            {
                "name": "p0_validation_metrics",
                "required": True,
                "exit_code": 127,
                "artifact": "/tmp/p0_validation_metrics_latest.json",
                "warning": "script_missing_required_hard_fail",
            }
        ],
    )

    assert "| p0_validation_metrics | yes | FAIL |" in markdown
