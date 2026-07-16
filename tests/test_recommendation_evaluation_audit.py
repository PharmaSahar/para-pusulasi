from __future__ import annotations

import json
import socket
from pathlib import Path

from src.recommendation_evaluation_store import RecommendationEvaluationStore
from src.run_recommendation_evaluation_audit import main


BASE_TIME = "2026-07-16T10:00:00+00:00"


def _payload() -> dict[str, object]:
    return {
        "evaluator_version": "a3.1",
        "recommendation_id": "rcr_001",
        "recommendation_schema_version": "v1",
        "decision_id": "dec_001",
        "learning_record_id": "lr_001",
        "outcome_record_id": "otr_001",
        "confidence_id": "scid_001",
        "attribution_record_id": "car_001",
        "experiment_id": "exp_001",
        "lifecycle_id": "life_001",
        "policy_id": "policy:v2.4",
        "model_id": "model:v3.2",
        "prompt_id": "prompt:v1.7",
        "confidence_state": "STATISTICALLY_SUPPORTED",
        "attribution_state": "CAUSALLY_SUPPORTED",
        "lineage_complete": True,
        "human_review_required": True,
        "evidence_summary": {
            "recommendation_eligible": True,
            "policy_state": "ALLOW",
            "synthetic_evidence": False,
            "contamination_state": "NONE",
            "outcome_maturity_state": "mature",
            "unresolved_evidence": False,
        },
    }


def _seed(path: Path) -> None:
    store = RecommendationEvaluationStore(evaluation_path=path)
    result = store.append_evaluation_event(
        _payload(),
        created_by="tester",
        source_module="tests.test_recommendation_evaluation_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True


def test_audit_runner_is_offline(tmp_path: Path, monkeypatch) -> None:
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    assert main([
        "--evaluation-path",
        str(evaluation_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
    ]) == 0
    assert artifact_path.exists()


def test_audit_artifact_is_deterministic(tmp_path: Path) -> None:
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)
    args = [
        "--evaluation-path",
        str(evaluation_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
        "--generated-at",
        "2026-07-16T11:00:00+00:00",
        "--final-status",
        "VALIDATED",
        "--test-result",
        "targeted=PASS",
    ]
    assert main(args) == 0
    first = artifact_path.read_text(encoding="utf-8")
    assert main(args) == 0
    second = artifact_path.read_text(encoding="utf-8")
    assert first == second


def test_audit_matrix_passes_for_valid_fixture(tmp_path: Path) -> None:
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)
    assert main([
        "--evaluation-path",
        str(evaluation_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
        "--final-status",
        "VALIDATED",
    ]) == 0
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["acceptance_matrix"]["advisory_only_guarantee"] == "PASS"
    assert payload["acceptance_matrix"]["hash_chain_integrity"] == "PASS"


def test_corrupt_fixture_produces_fail_closed_assessment(tmp_path: Path) -> None:
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    evaluation_path.write_text('{"broken"\n', encoding="utf-8")
    assert main([
        "--evaluation-path",
        str(evaluation_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
    ]) == 0
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "FAIL_CLOSED"


def test_audit_asserts_no_deployment(tmp_path: Path) -> None:
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)
    main(["--evaluation-path", str(evaluation_path), "--repo-root", str(Path(__file__).resolve().parents[1]), "--artifact-path", str(artifact_path)])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["acceptance_matrix"]["no_deployment"] == "PASS"


def test_audit_asserts_no_youtube_api_access(tmp_path: Path) -> None:
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)
    main(["--evaluation-path", str(evaluation_path), "--repo-root", str(Path(__file__).resolve().parents[1]), "--artifact-path", str(artifact_path)])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["acceptance_matrix"]["no_youtube_api_access"] == "PASS"


def test_audit_asserts_human_review_required(tmp_path: Path) -> None:
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)
    main(["--evaluation-path", str(evaluation_path), "--repo-root", str(Path(__file__).resolve().parents[1]), "--artifact-path", str(artifact_path)])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["acceptance_matrix"]["human_review_required_guarantee"] == "PASS"


def test_audit_asserts_no_runtime_action_fields(tmp_path: Path) -> None:
    evaluation_path = tmp_path / "recommendation_evaluation.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(evaluation_path)
    main(["--evaluation-path", str(evaluation_path), "--repo-root", str(Path(__file__).resolve().parents[1]), "--artifact-path", str(artifact_path)])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["acceptance_matrix"]["advisory_only_guarantee"] == "PASS"