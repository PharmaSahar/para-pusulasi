from __future__ import annotations

import json
import socket
from pathlib import Path

from src.recommendation_store import RecommendationStore
from src.run_recommendation_audit import main
from tests.recommendation_fixtures import BASE_TIME, base_recommendation_payload


def _seed(path: Path) -> None:
    store = RecommendationStore(recommendation_path=path)
    result = store.append_recommendation_event(
        base_recommendation_payload(),
        created_by="tester",
        source_module="tests.test_recommendation_audit",
        source_version="1.0",
        created_at=BASE_TIME,
    )
    assert result.appended is True


def test_audit_runner_is_deterministic_and_hash_stable(tmp_path: Path) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(recommendation_path)

    args = [
        "--recommendation-path",
        str(recommendation_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
        "--generated-at",
        "2026-07-15T16:30:00+00:00",
        "--final-status",
        "CONDITIONALLY_VALIDATED",
        "--backward-compatibility-status",
        "PASS",
        "--test-result",
        "sprint8_targeted=PASS",
    ]

    assert main(args) == 0
    first_text = artifact_path.read_text(encoding="utf-8")
    assert main(args) == 0
    second_text = artifact_path.read_text(encoding="utf-8")
    assert first_text == second_text

    payload = json.loads(first_text)
    assert payload["sprint"] == "SPRINT_8"
    assert payload["deterministic_hash_verification"]["status"] == "PASS"

    canonical = dict(payload)
    artifact_hash = canonical.pop("artifact_hash")
    recomputed = __import__("hashlib").sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert artifact_hash == recomputed


def test_audit_runner_is_offline(tmp_path: Path, monkeypatch) -> None:
    recommendation_path = tmp_path / "recommendation_governance.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(recommendation_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)

    assert main([
        "--recommendation-path",
        str(recommendation_path),
        "--repo-root",
        str(Path(__file__).resolve().parents[1]),
        "--artifact-path",
        str(artifact_path),
    ]) == 0
    assert artifact_path.exists()
