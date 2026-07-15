from __future__ import annotations

import json
import socket
from pathlib import Path

from src.model_registry import ModelRegistryStore
from src.policy_registry import PolicyRegistryStore
from src.prompt_governance_registry import PromptGovernanceRegistryStore
from src.run_registry_audit import main
from tests.test_model_registry import BASE_TIME as MODEL_TIME, base_model_payload
from tests.test_policy_registry import BASE_TIME as POLICY_TIME, base_policy_payload
from tests.test_prompt_governance_registry import BASE_TIME as PROMPT_TIME, base_prompt_payload


def _seed(model_path: Path, prompt_path: Path, policy_path: Path) -> None:
    ModelRegistryStore(registry_path=model_path).append_record(base_model_payload(), created_by="tester", source_module="tests.test_registry_projection", source_version="1.0", created_at=MODEL_TIME)
    PromptGovernanceRegistryStore(registry_path=prompt_path).append_record(base_prompt_payload(), created_by="tester", source_module="tests.test_registry_projection", source_version="1.0", created_at=PROMPT_TIME)
    PolicyRegistryStore(registry_path=policy_path).append_record(base_policy_payload(), created_by="tester", source_module="tests.test_registry_projection", source_version="1.0", created_at=POLICY_TIME)


def test_registry_audit_runner_is_deterministic_and_hash_stable(tmp_path: Path) -> None:
    model_path = tmp_path / "model_registry.jsonl"
    prompt_path = tmp_path / "prompt_registry.jsonl"
    policy_path = tmp_path / "policy_registry.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(model_path, prompt_path, policy_path)

    args = [
        "--model-registry-path", str(model_path),
        "--prompt-registry-path", str(prompt_path),
        "--policy-registry-path", str(policy_path),
        "--repo-root", str(Path(__file__).resolve().parents[1]),
        "--artifact-path", str(artifact_path),
        "--generated-at", "2026-07-15T18:30:00+00:00",
        "--final-status", "VALIDATED",
        "--full-repository-suite-status", "PASS",
        "--test-result", "sprint9_targeted=PASS",
        "--test-result", "registry_backward_compat=PASS",
    ]

    assert main(args) == 0
    first_text = artifact_path.read_text(encoding="utf-8")
    assert main(args) == 0
    second_text = artifact_path.read_text(encoding="utf-8")
    assert first_text == second_text

    payload = json.loads(first_text)
    assert payload["sprint"] == "SPRINT_9"
    canonical = dict(payload)
    artifact_hash = canonical.pop("artifact_hash")
    recomputed = __import__("hashlib").sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert artifact_hash == recomputed


def test_registry_audit_runner_is_offline(tmp_path: Path, monkeypatch) -> None:
    model_path = tmp_path / "model_registry.jsonl"
    prompt_path = tmp_path / "prompt_registry.jsonl"
    policy_path = tmp_path / "policy_registry.jsonl"
    artifact_path = tmp_path / "assessment.json"
    _seed(model_path, prompt_path, policy_path)

    def _deny_socket(*_args, **_kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    assert main([
        "--model-registry-path", str(model_path),
        "--prompt-registry-path", str(prompt_path),
        "--policy-registry-path", str(policy_path),
        "--repo-root", str(Path(__file__).resolve().parents[1]),
        "--artifact-path", str(artifact_path),
    ]) == 0
    assert artifact_path.exists()
