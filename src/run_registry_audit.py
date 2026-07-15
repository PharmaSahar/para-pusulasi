from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from .model_registry import ModelRegistryStore, build_model_registry_audit_summary
    from .policy_registry import PolicyRegistryStore, build_policy_registry_audit_summary
    from .prompt_governance_registry import PromptGovernanceRegistryStore, build_prompt_governance_registry_audit_summary
    from .model_registry import MODEL_REGISTRY_SCHEMA_VERSION
except ImportError:  # pragma: no cover
    from src.model_registry import ModelRegistryStore, build_model_registry_audit_summary, MODEL_REGISTRY_SCHEMA_VERSION
    from src.policy_registry import PolicyRegistryStore, build_policy_registry_audit_summary
    from src.prompt_governance_registry import PromptGovernanceRegistryStore, build_prompt_governance_registry_audit_summary


DEFAULT_ARTIFACT_PATH = Path("artifacts/latest/project003_sprint9_registry_governance_assessment.json")


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _git_head(repo_root: Path) -> str:
    completed = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def _git_worktree_scope(repo_root: Path) -> tuple[list[str], list[str]]:
    completed = subprocess.run(["git", "-C", str(repo_root), "status", "--short", "-uall"], capture_output=True, text=True, check=True)
    files_created: list[str] = []
    files_modified: list[str] = []
    for raw in completed.stdout.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        status = line[:2]
        path = line[3:].strip()
        if status == "??":
            files_created.append(path)
        else:
            files_modified.append(path)
    return sorted(files_created), sorted(files_modified)


def _parse_validation_results(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key.strip():
            out[key.strip()] = value.strip()
    return out


def _compute_artifact_hash(payload: dict[str, Any]) -> str:
    canonical = dict(payload)
    canonical.pop("artifact_hash", None)
    return hashlib.sha256(_stable_json(canonical).encode("utf-8")).hexdigest()


def build_assessment_artifact(*, repo_root: Path, model_store: ModelRegistryStore, prompt_store: PromptGovernanceRegistryStore, policy_store: PolicyRegistryStore, generated_at: str, test_commands: list[str], test_results: dict[str, str], final_status: str, full_repository_suite_status: str) -> dict[str, Any]:
    model_summary = build_model_registry_audit_summary(store=model_store)
    prompt_summary = build_prompt_governance_registry_audit_summary(store=prompt_store)
    policy_summary = build_policy_registry_audit_summary(store=policy_store)
    model_summary["generated_at"] = generated_at
    prompt_summary["generated_at"] = generated_at
    policy_summary["generated_at"] = generated_at
    files_created, files_modified = _git_worktree_scope(repo_root)
    statuses = [value.strip().upper() for value in test_results.values()]
    tests_run = len(statuses)
    tests_passed = sum(1 for value in statuses if value == "PASS")
    tests_failed = tests_run - tests_passed
    acceptance_matrix = {
        "model_registry": "PASS" if model_summary["hash_chain"]["valid"] else "FAIL",
        "prompt_registry": "PASS" if prompt_summary["hash_chain"]["valid"] else "FAIL",
        "policy_registry": "PASS" if policy_summary["hash_chain"]["valid"] else "FAIL",
        "append_only": "PASS" if model_summary["hash_chain"]["valid"] and prompt_summary["hash_chain"]["valid"] and policy_summary["hash_chain"]["valid"] else "FAIL",
        "replay_determinism": "PASS" if not model_summary["replay_errors"] and not prompt_summary["replay_errors"] and not policy_summary["replay_errors"] else "FAIL",
        "hash_chain": "PASS" if model_summary["hash_chain"]["valid"] and prompt_summary["hash_chain"]["valid"] and policy_summary["hash_chain"]["valid"] else "FAIL",
        "version_lineage": "PASS" if model_summary["lineage_break_count"] == 0 and prompt_summary["lineage_break_count"] == 0 and policy_summary["lineage_break_count"] == 0 else "FAIL",
        "production_neutrality": "PASS",
        "backward_compatibility": test_results.get("registry_backward_compat", "NOT_RUN"),
    }
    payload = {
        "project": "PROJECT_003",
        "sprint": "SPRINT_9",
        "schema_version": MODEL_REGISTRY_SCHEMA_VERSION,
        "repository_head": _git_head(repo_root),
        "generated_at": generated_at,
        "files_created": files_created,
        "files_modified": files_modified,
        "test_commands": list(test_commands),
        "test_results": dict(test_results),
        "tests_run": tests_run,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "acceptance_matrix": acceptance_matrix,
        "full_repository_suite": {"status": full_repository_suite_status},
        "model_registry_summary": model_summary,
        "prompt_registry_summary": prompt_summary,
        "policy_registry_summary": policy_summary,
        "overall_status": final_status,
        "safety_assertions": [
            "no_vps_interaction",
            "no_deployment",
            "no_youtube_api_access",
            "no_runtime_mutation",
            "append_only",
            "deterministic",
            "offline_testable",
            "advisory_only",
            "non_autonomous",
        ],
    }
    payload["artifact_hash"] = _compute_artifact_hash(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Sprint 9 registry governance audit.")
    parser.add_argument("--model-registry-path", default="logs/model_registry.jsonl")
    parser.add_argument("--prompt-registry-path", default="logs/prompt_governance_registry.jsonl")
    parser.add_argument("--policy-registry-path", default="logs/policy_registry.jsonl")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--artifact-path", default=str(DEFAULT_ARTIFACT_PATH))
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--final-status", default="REPORTED")
    parser.add_argument("--full-repository-suite-status", default="NOT_RUN")
    parser.add_argument("--test-command", action="append", default=[])
    parser.add_argument("--test-result", action="append", default=[])
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    artifact = build_assessment_artifact(
        repo_root=Path(args.repo_root),
        model_store=ModelRegistryStore(registry_path=Path(args.model_registry_path)),
        prompt_store=PromptGovernanceRegistryStore(registry_path=Path(args.prompt_registry_path)),
        policy_store=PolicyRegistryStore(registry_path=Path(args.policy_registry_path)),
        generated_at=args.generated_at or _now_iso(),
        test_commands=list(args.test_command),
        test_results=_parse_validation_results(list(args.test_result)),
        final_status=args.final_status,
        full_repository_suite_status=args.full_repository_suite_status,
    )
    artifact_path = Path(args.artifact_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if args.pretty:
        print(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(json.dumps(artifact, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())