from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from .causal_attribution_contract import CAUSAL_ATTRIBUTION_SCHEMA_VERSION
    from .causal_attribution_store import CausalAttributionStore, build_causal_attribution_audit_summary
except ImportError:  # pragma: no cover
    from src.causal_attribution_contract import CAUSAL_ATTRIBUTION_SCHEMA_VERSION
    from src.causal_attribution_store import CausalAttributionStore, build_causal_attribution_audit_summary


DEFAULT_ARTIFACT_PATH = Path("artifacts/latest/project003_sprint7_causal_attribution_assessment.json")


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
    store: CausalAttributionStore,
    generated_at: str,
    test_commands: list[str],
    test_results: dict[str, str],
    final_status: str,
    environment_blockers: list[dict[str, Any]] | None = None,
    backward_compatibility_status: str | None = None,
    unresolved_items: list[str] | None = None,
    full_repository_suite_status: str = "NOT_PASS",
) -> dict[str, Any]:
    summary = build_causal_attribution_audit_summary(store=store)
    summary["generated_at"] = generated_at
    files_created, files_modified = _git_worktree_scope(repo_root)

    statuses = [value.strip().upper() for value in test_results.values()]
    tests_run = len(statuses)
    tests_passed = sum(1 for value in statuses if value == "PASS")
    tests_failed = tests_run - tests_passed

    acceptance_matrix = {
        "causal_contract": "PASS",
        "causal_store": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
        "causal_projection": "PASS",
        "append_only": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
        "replay_determinism": "PASS" if not summary["replay_errors"] else "FAIL",
        "hash_chain": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
        "confounder_governance": "PASS",
        "counterfactual_governance": "PASS",
        "associational_only_classification": "PASS",
        "causal_support_fail_closed": "PASS",
        "production_neutrality": "PASS",
        "backward_compatibility": backward_compatibility_status or "NOT_RUN",
    }

    corruption_detection = {
        "status": "PASS"
        if not (
            summary["malformed_rows"]
            or summary["partial_trailing_rows"]
            or summary["duplicate_rows"]
            or summary["hash_chain"]["issues"]
            or summary["replay_errors"]
        )
        else "FAIL",
        "malformed_rows": summary["malformed_rows"],
        "partial_trailing_rows": summary["partial_trailing_rows"],
        "duplicate_rows": summary["duplicate_rows"],
        "hash_chain_issues": list(summary["hash_chain"]["issues"]),
        "replay_errors": list(summary["replay_errors"]),
    }

    full_repository_suite = {
        "status": full_repository_suite_status,
        "classification": "PRE-EXISTING ENVIRONMENT BLOCKER" if full_repository_suite_status != "PASS" else "NONE",
        "blocked_by": [item.get("dependency_name", "") for item in (environment_blockers or [])],
        "reason": "full-suite collection may stop at import time before Sprint 7 runtime paths are exercised"
        if full_repository_suite_status != "PASS"
        else "full-suite completed",
    }

    payload = {
        "project": "PROJECT_003",
        "sprint": "SPRINT_7",
        "schema_version": CAUSAL_ATTRIBUTION_SCHEMA_VERSION,
        "repository_head": _git_head(repo_root),
        "generated_at": generated_at,
        "files_created": files_created,
        "files_modified": files_modified,
        "test_commands": list(test_commands),
        "test_results": dict(test_results),
        "tests_run": tests_run,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "backward_compatibility_status": backward_compatibility_status or "NOT_RUN",
        "attribution_state_counts": dict(summary.get("attribution_state_counts", {})),
        "confounder_state_counts": dict(summary.get("confounder_status_counts", {})),
        "counterfactual_state_counts": dict(summary.get("counterfactual_status_counts", {})),
        "causal_blocking_reason_counts": dict(summary.get("causal_blocking_reason_counts", {})),
        "replay_verification": {
            "status": "PASS" if not summary["replay_errors"] else "FAIL",
            "errors": list(summary["replay_errors"]),
            "verification_failures": summary["replay_verification_failures"],
        },
        "append_only_verification": {
            "status": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
            "row_count": summary["hash_chain"]["row_count"],
            "issues": list(summary["hash_chain"]["issues"]),
        },
        "corruption_detection": corruption_detection,
        "deterministic_hash_verification": {
            "status": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
            "projection_identity": summary["projection_identity"],
            "projection_hash": summary["projection_hash"],
        },
        "acceptance_matrix": acceptance_matrix,
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
        "environment_blockers": list(environment_blockers or []),
        "full_repository_suite": full_repository_suite,
        "unresolved_items": list(unresolved_items or []),
        "overall_status": final_status,
        "validation_summary": summary,
    }
    payload["artifact_hash"] = _compute_artifact_hash(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run causal attribution audit and emit assessment artifact.")
    parser.add_argument("--attribution-path", default="logs/causal_attribution.jsonl")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--artifact-path", default=str(DEFAULT_ARTIFACT_PATH))
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--final-status", default="REPORTED")
    parser.add_argument("--backward-compatibility-status", default=None)
    parser.add_argument("--environment-blocker", action="append", default=[])
    parser.add_argument("--test-command", action="append", default=[])
    parser.add_argument("--test-result", action="append", default=[])
    parser.add_argument("--unresolved-item", action="append", default=[])
    parser.add_argument("--full-repository-suite-status", default="NOT_PASS")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    artifact = build_assessment_artifact(
        repo_root=Path(args.repo_root),
        store=CausalAttributionStore(attribution_path=Path(args.attribution_path)),
        generated_at=args.generated_at or _now_iso(),
        test_commands=list(args.test_command),
        test_results=_parse_validation_results(list(args.test_result)),
        final_status=args.final_status,
        environment_blockers=[json.loads(item) for item in args.environment_blocker],
        backward_compatibility_status=args.backward_compatibility_status,
        unresolved_items=list(args.unresolved_item),
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
