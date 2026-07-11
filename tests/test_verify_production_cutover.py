from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ops.verify_production_cutover as cutover


def _configure_common_mocks(monkeypatch):
    monkeypatch.setattr(cutover, "_discover_scheduler_pids", lambda: [4242])
    monkeypatch.setattr(cutover, "_read_pid", lambda: 4242)
    monkeypatch.setattr(cutover, "_process_info", lambda _pid: {
        "command": "python scheduler.py",
        "elapsed": "00:10:00",
        "cwd": str(cutover.ROOT),
    })


def _equivalence_payload(*, head_sha: str, classification: str, generated_at_utc: str | None = None, final_decision: str = "PROVEN_EQUIVALENT") -> dict:
    return {
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
        "current_head": head_sha,
        "import_integrity": "PASS",
        "governance_tests": "PASS",
        "full_suite": "PASS",
        "classification_per_commit": {
            commit: classification for commit in cutover.APPROVED_COMMITS
        },
        "final_equivalence_decision": final_decision,
    }


def _write_payload(path: Path, payload: dict):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_cutover_returns_nonzero_when_build_sha_mismatch(monkeypatch, capsys):
    _configure_common_mocks(monkeypatch)
    monkeypatch.setattr(cutover, "_head_sha", lambda: "fb518e9")
    monkeypatch.setattr(cutover, "_last_build_info", lambda: {
        "line": "BUILD_INFO scheduler git_sha=bc9e1c2",
        "sha": "bc9e1c2",
    })
    monkeypatch.setattr(cutover, "_evaluate_governance_equivalence", lambda _head: {"ok": True})

    rc = cutover.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["checks"]["build_sha_matches_head"] is False
    assert payload["ok"] is False


def test_cutover_returns_zero_when_required_checks_pass(monkeypatch, capsys):
    _configure_common_mocks(monkeypatch)
    monkeypatch.setattr(cutover, "_head_sha", lambda: "fb518e9")
    monkeypatch.setattr(cutover, "_last_build_info", lambda: {
        "line": "BUILD_INFO scheduler git_sha=fb518e9",
        "sha": "fb518e9",
    })
    monkeypatch.setattr(cutover, "_evaluate_governance_equivalence", lambda _head: {"ok": True})

    rc = cutover.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["checks"]["build_sha_matches_head"] is True
    assert payload["ok"] is True


def test_exact_ancestry_passes_without_artifact(monkeypatch):
    monkeypatch.setattr(cutover, "_approved_commit_ancestry", lambda: {c: True for c in cutover.APPROVED_COMMITS})

    result = cutover._evaluate_governance_equivalence("469c799")

    assert result["ok"] is True
    assert result["mode"] == "exact_ancestry"


def test_matching_patch_id_classification_passes(tmp_path, monkeypatch):
    artifact = tmp_path / "approved_governance_equivalence_latest.json"
    monkeypatch.setattr(cutover, "EQUIVALENCE_ARTIFACT", artifact)
    monkeypatch.setattr(cutover, "_approved_commit_ancestry", lambda: {c: False for c in cutover.APPROVED_COMMITS})
    _write_payload(
        artifact,
        _equivalence_payload(head_sha="469c799", classification="PATCH_EQUIVALENT", final_decision="EQUIVALENT"),
    )

    result = cutover._evaluate_governance_equivalence("469c799")

    assert result["ok"] is True


def test_functionally_superseded_passes_with_complete_evidence(tmp_path, monkeypatch):
    artifact = tmp_path / "approved_governance_equivalence_latest.json"
    monkeypatch.setattr(cutover, "EQUIVALENCE_ARTIFACT", artifact)
    monkeypatch.setattr(cutover, "_approved_commit_ancestry", lambda: {c: False for c in cutover.APPROVED_COMMITS})
    _write_payload(
        artifact,
        _equivalence_payload(head_sha="469c799", classification="FUNCTIONALLY_SUPERSEDED"),
    )

    result = cutover._evaluate_governance_equivalence("469c799")

    assert result["ok"] is True


def test_full_head_in_artifact_matches_short_runtime_head(tmp_path, monkeypatch):
    artifact = tmp_path / "approved_governance_equivalence_latest.json"
    monkeypatch.setattr(cutover, "EQUIVALENCE_ARTIFACT", artifact)
    monkeypatch.setattr(cutover, "_approved_commit_ancestry", lambda: {c: False for c in cutover.APPROVED_COMMITS})
    _write_payload(
        artifact,
        _equivalence_payload(
            head_sha="469c7997ffc429fa999e1bddea9d61d1ab2285ce",
            classification="FUNCTIONALLY_SUPERSEDED",
        ),
    )

    result = cutover._evaluate_governance_equivalence("469c799")

    assert result["ok"] is True


def test_missing_capability_fails(tmp_path, monkeypatch):
    artifact = tmp_path / "approved_governance_equivalence_latest.json"
    monkeypatch.setattr(cutover, "EQUIVALENCE_ARTIFACT", artifact)
    monkeypatch.setattr(cutover, "_approved_commit_ancestry", lambda: {c: False for c in cutover.APPROVED_COMMITS})
    payload = _equivalence_payload(head_sha="469c799", classification="FUNCTIONALLY_SUPERSEDED")
    payload["classification_per_commit"][cutover.APPROVED_COMMITS[0]] = "MISSING"
    _write_payload(artifact, payload)

    result = cutover._evaluate_governance_equivalence("469c799")

    assert result["ok"] is False


def test_stale_evidence_fails(tmp_path, monkeypatch):
    artifact = tmp_path / "approved_governance_equivalence_latest.json"
    monkeypatch.setattr(cutover, "EQUIVALENCE_ARTIFACT", artifact)
    monkeypatch.setattr(cutover, "_approved_commit_ancestry", lambda: {c: False for c in cutover.APPROVED_COMMITS})
    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _write_payload(
        artifact,
        _equivalence_payload(
            head_sha="469c799",
            classification="FUNCTIONALLY_SUPERSEDED",
            generated_at_utc=stale,
        ),
    )

    result = cutover._evaluate_governance_equivalence("469c799")

    assert result["ok"] is False
    assert result["checks"]["artifact_fresh"] is False


def test_unrelated_implementation_fails(tmp_path, monkeypatch):
    artifact = tmp_path / "approved_governance_equivalence_latest.json"
    monkeypatch.setattr(cutover, "EQUIVALENCE_ARTIFACT", artifact)
    monkeypatch.setattr(cutover, "_approved_commit_ancestry", lambda: {c: False for c in cutover.APPROVED_COMMITS})
    _write_payload(
        artifact,
        _equivalence_payload(
            head_sha="469c799",
            classification="FUNCTIONALLY_SUPERSEDED",
            final_decision="NOT_EQUIVALENT",
        ),
    )

    result = cutover._evaluate_governance_equivalence("469c799")

    assert result["ok"] is False
    assert result["checks"]["final_decision_allows_equivalence"] is False
