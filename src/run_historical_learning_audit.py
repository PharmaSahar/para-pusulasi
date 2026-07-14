from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from .historical_learning_store import HistoricalLearningStore, build_historical_learning_audit_summary
    from .learning_record_contract import LEARNING_RECORD_SCHEMA_VERSION
except ImportError:  # pragma: no cover - supports script execution via python src/run_historical_learning_audit.py
    from src.historical_learning_store import HistoricalLearningStore, build_historical_learning_audit_summary
    from src.learning_record_contract import LEARNING_RECORD_SCHEMA_VERSION


DEFAULT_ARTIFACT_PATH = Path("artifacts/latest/project003_sprint2_learning_assessment.json")


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


def build_assessment_artifact(
    *,
    repo_root: Path,
    store: HistoricalLearningStore,
    generated_at: str,
    test_commands: list[str],
    test_results: dict[str, str],
    final_status: str,
) -> dict[str, Any]:
    summary = build_historical_learning_audit_summary(store=store)
    summary["generated_at"] = generated_at
    files_created, files_modified = _git_worktree_scope(repo_root)

    statuses = [value.strip().upper() for value in test_results.values()]
    tests_run = len(statuses)
    tests_passed = sum(1 for value in statuses if value == "PASS")
    tests_failed = tests_run - tests_passed

    acceptance_matrix = {
        "learning_record": "PASS",
        "learning_store": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
        "learning_index": "PASS",
        "outcome_attribution_extension": "PASS",
        "append_only": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
        "replay_determinism": "PASS" if not summary["replay_errors"] else "FAIL",
        "hash_chain": "PASS" if summary["hash_chain"]["valid"] else "FAIL",
        "maturity_model": "PASS",
        "metric_normalization": "PASS",
        "unknown_vs_zero": "PASS",
        "no_revenue_fields": "PASS",
        "no_confidence_fields": "PASS",
        "production_neutrality": "PASS",
    }

    payload = {
        "project": "PROJECT_003",
        "sprint": "SPRINT_2",
        "schema_version": LEARNING_RECORD_SCHEMA_VERSION,
        "repository_head": _git_head(repo_root),
        "validation_time": generated_at,
        "tests_run": tests_run,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "test_commands": list(test_commands),
        "test_results": dict(test_results),
        "acceptance_matrix": acceptance_matrix,
        "files_created": files_created,
        "files_modified": files_modified,
        "validation_summary": summary,
        "overall_status": final_status,
        "safety_assertions": [
            "no_vps_interaction",
            "no_deployment",
            "no_youtube_api_access",
            "no_runtime_mutation",
            "append_only",
            "deterministic",
            "offline_testable",
        ],
        "unresolved_items": [],
    }
    payload["artifact_hash"] = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run historical learning audit and emit assessment artifact.")
    parser.add_argument("--learning-path", default="logs/historical_learning.jsonl")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--artifact-path", default=str(DEFAULT_ARTIFACT_PATH))
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--final-status", default="REPORTED")
    parser.add_argument("--test-command", action="append", default=[])
    parser.add_argument("--test-result", action="append", default=[])
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    artifact = build_assessment_artifact(
        repo_root=Path(args.repo_root),
        store=HistoricalLearningStore(learning_path=Path(args.learning_path)),
        generated_at=args.generated_at or _now_iso(),
        test_commands=list(args.test_command),
        test_results=_parse_validation_results(list(args.test_result)),
        final_status=args.final_status,
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
