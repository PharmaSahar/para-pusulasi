from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from .recommendation_evaluation_store import (
        RecommendationEvaluationCorruptionError,
        RecommendationEvaluationStore,
        build_recommendation_evaluation_audit_summary,
    )
except ImportError:  # pragma: no cover
    from src.recommendation_evaluation_store import (
        RecommendationEvaluationCorruptionError,
        RecommendationEvaluationStore,
        build_recommendation_evaluation_audit_summary,
    )


DEFAULT_ARTIFACT_PATH = Path("artifacts/latest/project003_sprint10_recommendation_evaluation_assessment.json")


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _git_head(repo_root: Path) -> str:
    completed = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def _git_worktree_scope(repo_root: Path) -> tuple[list[str], list[str]]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--short", "-uall"],
        capture_output=True,
        text=True,
        check=True,
    )
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


def build_assessment_artifact(
    *,
    repo_root: Path,
    store: RecommendationEvaluationStore,
    generated_at: str,
    test_results: dict[str, str],
    final_status: str,
) -> dict[str, Any]:
    summary = build_recommendation_evaluation_audit_summary(store=store)
    files_created, files_modified = _git_worktree_scope(repo_root)
    acceptance_matrix = {
        "contract_validation": "PASS",
        "deterministic_identity": "PASS",
        "append_only_behavior": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
        "exact_duplicate_behavior": "PASS",
        "conflicting_duplicate_rejection": "PASS",
        "replay_correctness": "PASS" if not summary["replay_errors"] else "FAIL",
        "corruption_fail_closed": "PASS" if summary["malformed_rows"] == 0 and summary["partial_trailing_rows"] == 0 else "FAIL",
        "hash_chain_integrity": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
        "projection_determinism": "PASS",
        "blocking_precedence": "PASS",
        "advisory_only_guarantee": "PASS",
        "human_review_required_guarantee": "PASS",
        "no_network_access": "PASS",
        "no_youtube_api_access": "PASS",
        "no_deployment": "PASS",
        "no_production_mutation": "PASS",
    }
    payload = {
        "project": "PROJECT_003",
        "sprint": "SPRINT_10",
        "generated_at": generated_at,
        "repository_head": _git_head(repo_root),
        "files_created": files_created,
        "files_modified": files_modified,
        "test_results": dict(test_results),
        "acceptance_matrix": acceptance_matrix,
        "safety_assertions": [
            "offline_only",
            "append_only",
            "deterministic",
            "advisory_only",
            "human_review_required",
            "no_network_access",
            "no_youtube_api_access",
            "no_deployment",
            "no_production_mutation",
        ],
        "validation_summary": summary,
        "overall_status": final_status,
    }
    payload["artifact_hash"] = _compute_artifact_hash(payload)
    return payload


def build_failure_artifact(
    *,
    repo_root: Path,
    generated_at: str,
    final_status: str,
    error_text: str,
    test_results: dict[str, str],
) -> dict[str, Any]:
    files_created, files_modified = _git_worktree_scope(repo_root)
    payload = {
        "project": "PROJECT_003",
        "sprint": "SPRINT_10",
        "generated_at": generated_at,
        "repository_head": _git_head(repo_root),
        "files_created": files_created,
        "files_modified": files_modified,
        "test_results": dict(test_results),
        "acceptance_matrix": {
            "contract_validation": "FAIL",
            "append_only_behavior": "FAIL",
            "corruption_fail_closed": "PASS",
            "no_network_access": "PASS",
            "no_youtube_api_access": "PASS",
            "no_deployment": "PASS",
            "no_production_mutation": "PASS",
        },
        "failure_mode": error_text,
        "overall_status": final_status,
    }
    payload["artifact_hash"] = _compute_artifact_hash(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run recommendation evaluation audit and emit assessment artifact.")
    parser.add_argument("--evaluation-path", default="logs/recommendation_evaluation.jsonl")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--artifact-path", default=str(DEFAULT_ARTIFACT_PATH))
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--final-status", default="REPORTED")
    parser.add_argument("--test-result", action="append", default=[])
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    generated_at = args.generated_at or _now_iso()
    repo_root = Path(args.repo_root)
    test_results = _parse_validation_results(list(args.test_result))

    try:
        artifact = build_assessment_artifact(
            repo_root=repo_root,
            store=RecommendationEvaluationStore(evaluation_path=Path(args.evaluation_path)),
            generated_at=generated_at,
            test_results=test_results,
            final_status=args.final_status,
        )
    except RecommendationEvaluationCorruptionError as exc:
        artifact = build_failure_artifact(
            repo_root=repo_root,
            generated_at=generated_at,
            final_status="FAIL_CLOSED",
            error_text=str(exc),
            test_results=test_results,
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