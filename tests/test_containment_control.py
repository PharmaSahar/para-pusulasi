from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import containment_control as cc


SHA = "60c58ca610106e154fbddc4caeeb5c9d27b20c6a"


def _paths(tmp_path: Path) -> cc.ContainmentPaths:
    return cc.ContainmentPaths(
        provider_health_file=tmp_path / "provider_health.json",
        audit_file=tmp_path / "audit" / "visual_safety_containment_audit.jsonl",
        lock_file=tmp_path / "provider_health.lock",
        deploy_lock_dir=tmp_path / "deploy.lock",
    )


def _state(extra: dict | None = None) -> dict:
    payload = {
        "global_overload_pause_reason": cc.PROJECT003_REASON,
        "global_overload_pause_until": "2026-07-21T07:57:34.559914Z",
        "overload_events": ["2026-07-16T19:07:47.297898Z"],
        "providers": {"anthropic": {"consecutive_failures": 0, "last_error": "Overloaded"}},
        "visual_safety_incident_containment": {
            "activated_at": "2026-07-18T07:57:34.559914Z",
            "incident_id": "PROJECT003-cross-channel-visual-safety",
            "mechanism": "existing_global_overload_pause",
            "preserve_evidence": True,
        },
        "unrelated": {"keep": True},
    }
    if extra:
        payload.update(extra)
    return payload


def _write_state(paths: cc.ContainmentPaths, payload: dict | None = None) -> None:
    paths.provider_health_file.parent.mkdir(parents=True, exist_ok=True)
    paths.provider_health_file.write_text(json.dumps(payload or _state(), indent=2), encoding="utf-8")


def _evidence(tmp_path: Path, overrides: dict | None = None) -> Path:
    payload = {
        "schema_version": cc.EVIDENCE_SCHEMA_VERSION,
        "incident_id": "PROJECT003",
        "production_sha": SHA,
        "policy_version": cc.POLICY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "eligible_for_release": True,
        "mandatory": {field: True for field in cc.REQUIRED_MANDATORY_FIELDS},
        "dry_run_totals": {
            "unsafe_selections": 0,
            "unsafe_approvals": 0,
            "upload_attempts": 0,
            "quarantine_escapes": 0,
            "fail_open_paths": 0,
        },
        "critical_error_count": 0,
        "quarantine_escape_count": 0,
        "unsafe_selection_count": 0,
        "unsafe_approval_count": 0,
        "upload_attempt_count": 0,
        "verifier_version": "test-verifier.v1",
    }
    if overrides:
        payload.update(overrides)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _request(evidence: Path, **overrides) -> cc.ReleaseRequest:
    values = {
        "incident_id": "PROJECT003",
        "expected_reason": cc.PROJECT003_REASON,
        "expected_policy_version": cc.POLICY_VERSION,
        "expected_production_sha": SHA,
        "operator": "test-operator",
        "evidence_file": evidence,
        "uploads_disabled": True,
        "renders_disabled": True,
        "confirm_release": "PROJECT003",
    }
    values.update(overrides)
    return cc.ReleaseRequest(**values)


def _release(paths: cc.ContainmentPaths, request: cc.ReleaseRequest):
    return cc.release_containment(
        request,
        paths=paths,
        production_sha_resolver=lambda: SHA,
        service_health_checker=lambda: True,
    )


def _audit_records(paths: cc.ContainmentPaths) -> list[dict]:
    return [json.loads(line) for line in paths.audit_file.read_text(encoding="utf-8").splitlines()]


def test_status_is_read_only(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    before = paths.provider_health_file.read_bytes()
    status = cc.get_status(incident_id="PROJECT003", paths=paths)
    assert status["active"] is True
    assert paths.provider_health_file.read_bytes() == before
    assert not paths.audit_file.exists()


def test_valid_release_succeeds(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    result = _release(paths, _request(_evidence(tmp_path)))
    state = json.loads(paths.provider_health_file.read_text(encoding="utf-8"))
    assert result["status"] == "released"
    assert state["global_overload_pause_reason"] == ""
    assert state["global_overload_pause_until"] == ""
    assert state["providers"] == {"anthropic": {"consecutive_failures": 0, "last_error": "Overloaded"}}
    assert state["unrelated"] == {"keep": True}
    assert state["visual_safety_incident_containment"]["released"] is True


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"incident_id": "OTHER", "confirm_release": "OTHER"}, "unsupported_incident_id"),
        ({"expected_reason": "overload_storm:3/300s"}, "expected_reason_not_project003"),
        ({"expected_production_sha": "bad"}, "evidence_sha_mismatch"),
        ({"expected_policy_version": "visual_safety.v0"}, "policy_version_mismatch"),
        ({"uploads_disabled": False}, "uploads_not_disabled"),
        ({"renders_disabled": False}, "renders_not_disabled"),
        ({"confirm_release": "WRONG"}, "release_confirmation_mismatch"),
    ],
)
def test_release_request_validation_failures(tmp_path, overrides, reason):
    paths = _paths(tmp_path)
    _write_state(paths)
    with pytest.raises(cc.ContainmentControlError) as exc:
        _release(paths, _request(_evidence(tmp_path), **overrides))
    assert exc.value.reason == reason


def test_missing_evidence_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    with pytest.raises(cc.ContainmentControlError, match="evidence_file_missing"):
        _release(paths, _request(tmp_path / "missing.json"))


def test_malformed_evidence_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    evidence = tmp_path / "bad.json"
    evidence.write_text("{", encoding="utf-8")
    with pytest.raises(cc.ContainmentControlError, match="evidence_file_invalid_json"):
        _release(paths, _request(evidence))


def test_stale_evidence_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    evidence = _evidence(tmp_path, {"generated_at": "2026-01-01T00:00:00Z"})
    with pytest.raises(cc.ContainmentControlError, match="evidence_stale"):
        _release(paths, _request(evidence))


def test_false_eligibility_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    evidence = _evidence(tmp_path, {"eligible_for_release": False})
    with pytest.raises(cc.ContainmentControlError, match="evidence_not_eligible"):
        _release(paths, _request(evidence))


def test_any_false_mandatory_condition_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    mandatory = {field: True for field in cc.REQUIRED_MANDATORY_FIELDS}
    mandatory["upload_precheck_verified"] = False
    evidence = _evidence(tmp_path, {"mandatory": mandatory})
    with pytest.raises(cc.ContainmentControlError, match="evidence_mandatory_false"):
        _release(paths, _request(evidence))


@pytest.mark.parametrize(
    "field",
    ["unsafe_selection_count", "unsafe_approval_count", "upload_attempt_count", "quarantine_escape_count", "critical_error_count"],
)
def test_nonzero_top_level_counts_fail(tmp_path, field):
    paths = _paths(tmp_path)
    _write_state(paths)
    evidence = _evidence(tmp_path, {field: 1})
    with pytest.raises(cc.ContainmentControlError, match="evidence_nonzero_count"):
        _release(paths, _request(evidence))


def test_nonzero_dry_run_total_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    totals = {"unsafe_selections": 1, "unsafe_approvals": 0, "upload_attempts": 0, "quarantine_escapes": 0, "fail_open_paths": 0}
    evidence = _evidence(tmp_path, {"dry_run_totals": totals})
    with pytest.raises(cc.ContainmentControlError, match="evidence_nonzero_dry_run_total"):
        _release(paths, _request(evidence))


def test_missing_required_evidence_field_fails(tmp_path):
    evidence = _evidence(tmp_path)
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload.pop("verifier_version")
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(cc.ContainmentControlError, match="evidence_missing_fields"):
        cc.validate_release_evidence(evidence_file=evidence, expected_incident_id="PROJECT003", expected_production_sha=SHA, expected_policy_version=cc.POLICY_VERSION)


def test_wrong_evidence_policy_version_fails(tmp_path):
    evidence = _evidence(tmp_path, {"policy_version": "visual_safety.v0"})
    with pytest.raises(cc.ContainmentControlError, match="evidence_policy_mismatch"):
        cc.validate_release_evidence(evidence_file=evidence, expected_incident_id="PROJECT003", expected_production_sha=SHA, expected_policy_version=cc.POLICY_VERSION)


def test_current_production_sha_mismatch_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    with pytest.raises(cc.ContainmentControlError, match="production_sha_mismatch"):
        cc.release_containment(
            _request(_evidence(tmp_path)),
            paths=paths,
            production_sha_resolver=lambda: "bad",
            service_health_checker=lambda: True,
        )


def test_unhealthy_service_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    with pytest.raises(cc.ContainmentControlError, match="service_not_healthy"):
        cc.release_containment(
            _request(_evidence(tmp_path)),
            paths=paths,
            production_sha_resolver=lambda: SHA,
            service_health_checker=lambda: False,
        )


def test_active_deploy_lock_fails(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    paths.deploy_lock_dir.mkdir(parents=True)
    (paths.deploy_lock_dir / ".active_lock").write_text("locked", encoding="utf-8")
    with pytest.raises(cc.ContainmentControlError, match="deploy_lock_active"):
        _release(paths, _request(_evidence(tmp_path)))


def test_unknown_pause_type_fails_and_is_not_cleared(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths, _state({"global_overload_pause_reason": "overload_storm:3/300s"}))
    with pytest.raises(cc.ContainmentControlError, match="pause_reason_mismatch"):
        _release(paths, _request(_evidence(tmp_path)))
    state = json.loads(paths.provider_health_file.read_text(encoding="utf-8"))
    assert state["global_overload_pause_reason"] == "overload_storm:3/300s"


def test_provider_rate_limit_pause_is_never_cleared(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths, _state({"global_overload_pause_reason": "rate_limit_pause:anthropic"}))
    with pytest.raises(cc.ContainmentControlError):
        _release(paths, _request(_evidence(tmp_path)))
    state = json.loads(paths.provider_health_file.read_text(encoding="utf-8"))
    assert state["global_overload_pause_reason"] == "rate_limit_pause:anthropic"


def test_project003_fields_are_cleared_only_and_unrelated_preserved(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    _release(paths, _request(_evidence(tmp_path)))
    state = json.loads(paths.provider_health_file.read_text(encoding="utf-8"))
    assert state["global_overload_pause_reason"] == ""
    assert state["global_overload_pause_until"] == ""
    assert state["overload_events"] == ["2026-07-16T19:07:47.297898Z"]
    assert state["providers"]["anthropic"]["last_error"] == "Overloaded"


def test_atomic_write_failure_preserves_original_state(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    original = _state()
    _write_state(paths, original)
    monkeypatch.setattr(cc.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        _release(paths, _request(_evidence(tmp_path)))
    assert json.loads(paths.provider_health_file.read_text(encoding="utf-8")) == original


def test_concurrent_second_release_fails_safely(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    evidence = _evidence(tmp_path)
    _release(paths, _request(evidence))
    with pytest.raises(cc.ContainmentControlError, match="pause_reason_mismatch"):
        _release(paths, _request(evidence))


def test_duplicate_request_id_cannot_be_reused(tmp_path):
    paths = _paths(tmp_path)
    state = _state()
    state["visual_safety_incident_containment"]["consumed_release_request_ids"] = []
    _write_state(paths, state)
    evidence = _evidence(tmp_path)
    request = _request(evidence)
    request_id = cc._sha256_bytes(f"PROJECT003|test-operator|{cc._file_sha256(evidence)}|{SHA}".encode("utf-8"))
    state["visual_safety_incident_containment"]["consumed_release_request_ids"] = [request_id]
    _write_state(paths, state)
    with pytest.raises(cc.ContainmentControlError, match="release_request_already_consumed"):
        _release(paths, request)


def test_audit_success_and_failure_records_are_written_without_secrets(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    _release(paths, _request(_evidence(tmp_path)))
    _write_state(paths)
    with pytest.raises(cc.ContainmentControlError):
        _release(paths, _request(_evidence(tmp_path), uploads_disabled=False))
    records = _audit_records(paths)
    assert any(record["success"] is True for record in records)
    assert any(record["success"] is False for record in records)
    serialized = json.dumps(records).lower()
    assert "token" not in serialized
    assert "secret" not in serialized


def test_restore_reapplies_containment_and_preserves_release_history(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    _release(paths, _request(_evidence(tmp_path)))
    result = cc.restore_containment(
        cc.RestoreRequest("PROJECT003", "test-operator", "observation failed", "PROJECT003", SHA),
        paths=paths,
        production_sha_resolver=lambda: SHA,
    )
    state = json.loads(paths.provider_health_file.read_text(encoding="utf-8"))
    assert result["status"] == "restored"
    assert state["global_overload_pause_reason"] == cc.PROJECT003_REASON
    assert state["visual_safety_incident_containment"]["release_history"]
    assert state["providers"]["anthropic"]["last_error"] == "Overloaded"


def test_restore_requires_confirmation_and_sha(tmp_path):
    paths = _paths(tmp_path)
    _write_state(paths)
    with pytest.raises(cc.ContainmentControlError, match="restore_confirmation_mismatch"):
        cc.restore_containment(cc.RestoreRequest("PROJECT003", "op", "reason", "NO", SHA), paths=paths, production_sha_resolver=lambda: SHA)
    with pytest.raises(cc.ContainmentControlError, match="production_sha_mismatch"):
        cc.restore_containment(cc.RestoreRequest("PROJECT003", "op", "reason", "PROJECT003", SHA), paths=paths, production_sha_resolver=lambda: "bad")


def test_quarantine_files_are_untouched(tmp_path):
    paths = _paths(tmp_path)
    queue = tmp_path / "channel_queue.json"
    queue.write_text(json.dumps({"channel": [{"status": "quarantined"}]}), encoding="utf-8")
    before = queue.read_bytes()
    _write_state(paths)
    _release(paths, _request(_evidence(tmp_path)))
    assert queue.read_bytes() == before


def test_cli_status_outputs_read_only_json(tmp_path, monkeypatch, capsys):
    paths = _paths(tmp_path)
    _write_state(paths)
    before = paths.provider_health_file.read_bytes()
    monkeypatch.setenv("VISUAL_CONTAINMENT_PROVIDER_HEALTH_FILE", str(paths.provider_health_file))
    monkeypatch.setenv("VISUAL_CONTAINMENT_AUDIT_FILE", str(paths.audit_file))
    rc = cc.main(["status", "--incident-id", "PROJECT003"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["result"]["active"] is True
    assert paths.provider_health_file.read_bytes() == before
    assert not paths.audit_file.exists()


def test_cli_validate_release_eligibility_outputs_hash(tmp_path, capsys):
    evidence = _evidence(tmp_path)
    rc = cc.main([
        "validate-release-eligibility",
        "--incident-id", "PROJECT003",
        "--expected-policy-version", cc.POLICY_VERSION,
        "--expected-production-sha", SHA,
        "--evidence-file", str(evidence),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["result"]["status"] == "valid"
    assert out["result"]["evidence_sha256"] == cc._file_sha256(evidence)


def test_generate_release_evidence_writes_strict_schema(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _write_state(paths)
    pipeline = tmp_path / "src" / "pipeline.py"
    pipeline.parent.mkdir()
    pipeline.write_text(
        "build_visual_manifest(\nevaluate_upload_precheck(\nfinal_visual_assets\n"
        "short_visual_manifest_path = build_visual_manifest(\nshort_precheck = evaluate_upload_precheck(\nfinal_visual_assets=short_visual_assets\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cc, "_critical_log_count_since", lambda _since: 0)
    output = tmp_path / "evidence.generated.json"
    result = cc.generate_release_evidence(
        incident_id="PROJECT003",
        expected_production_sha=SHA,
        output_file=output,
        paths=paths,
        production_sha_resolver=lambda: SHA,
        service_health_checker=lambda: True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result["eligible_for_release"] is True
    assert payload["schema_version"] == cc.EVIDENCE_SCHEMA_VERSION
    assert payload["mandatory"]["shorts_manifest_verified"] is True
    assert payload["dry_run_totals"]["unsafe_approvals"] == 0