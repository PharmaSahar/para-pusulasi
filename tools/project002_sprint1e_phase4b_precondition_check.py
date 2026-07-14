from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.studio_analytics_learning_bridge import validate_canonical_record


PHASE4B_ASSESSMENT_SUMMARY_PATH = Path(
    "artifacts/latest/project002_sprint1e_phase4b_studio_export_learning/assessment_summary.json"
)
PHASE4B_SOURCE_PATH = Path("logs/channel_performance.jsonl")
PHASE4B_CANONICAL_STORE_PATH = Path("logs/canonical_content_analytics.jsonl")
PHASE4B_LOCAL_PROVIDER = "ExistingLocalAnalyticsProvider"


class GateState(str, Enum):
    NOT_PREPARED = "ENVIRONMENT_NOT_PREPARED"
    INCONSISTENT = "ENVIRONMENT_INCONSISTENT"
    READY = "ENVIRONMENT_READY"


@dataclass(frozen=True)
class Problem:
    code: str
    message: str


@dataclass(frozen=True)
class CheckResult:
    state: GateState
    problems: list[Problem]


@dataclass(frozen=True)
class BaselineContract:
    imported_rows: int
    linked_rows: int
    unresolved_rows: int
    ambiguous_rows: int
    invalid_rows: int
    source_file_hash: str


def _is_safe_relative(path: Path) -> bool:
    text = str(path)
    return not path.is_absolute() and ".." not in path.parts and text != ""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            malformed += 1
            continue
        if not isinstance(payload, dict):
            malformed += 1
            continue
        rows.append(payload)
    return rows, malformed


def _extract_baseline_contract(summary: dict[str, Any]) -> tuple[BaselineContract | None, list[Problem]]:
    problems: list[Problem] = []

    if not isinstance(summary, dict):
        return None, [Problem("summary_not_object", "assessment_summary.json must be a JSON object")]

    coverage = summary.get("coverage")
    imports = summary.get("imports")

    if not isinstance(coverage, dict):
        problems.append(Problem("summary_missing_coverage", "assessment_summary.coverage is missing or invalid"))
    if not isinstance(imports, list):
        problems.append(Problem("summary_missing_imports", "assessment_summary.imports is missing or invalid"))

    imported_rows = summary.get("canonical_rows")
    if not isinstance(imported_rows, int):
        problems.append(Problem("summary_missing_canonical_rows", "assessment_summary.canonical_rows must be an integer"))

    linked_rows = None
    unresolved_rows = None
    ambiguous_rows = None
    invalid_rows = None
    if isinstance(coverage, dict):
        linked_rows = coverage.get("content_linked_rows")
        unresolved_rows = coverage.get("unresolved_rows")
        ambiguous_rows = coverage.get("ambiguous_rows")
        invalid_rows = coverage.get("invalid_rows")
        for field_name, field_value in (
            ("content_linked_rows", linked_rows),
            ("unresolved_rows", unresolved_rows),
            ("ambiguous_rows", ambiguous_rows),
            ("invalid_rows", invalid_rows),
        ):
            if not isinstance(field_value, int):
                problems.append(
                    Problem(
                        f"summary_missing_{field_name}",
                        f"assessment_summary.coverage.{field_name} must be an integer",
                    )
                )

    source_hash = ""
    if isinstance(imports, list):
        local_import = next(
            (
                item
                for item in imports
                if isinstance(item, dict) and str(item.get("provider") or "") == PHASE4B_LOCAL_PROVIDER
            ),
            None,
        )
        if local_import is None:
            problems.append(
                Problem(
                    "summary_missing_local_import",
                    "assessment_summary.imports must include ExistingLocalAnalyticsProvider",
                )
            )
        else:
            source_hash = str(local_import.get("source_file_hash") or "").strip()
            if not source_hash:
                problems.append(
                    Problem(
                        "summary_missing_source_hash",
                        "assessment_summary.imports ExistingLocalAnalyticsProvider must include source_file_hash",
                    )
                )

    if problems:
        return None, problems

    assert isinstance(imported_rows, int)
    assert isinstance(linked_rows, int)
    assert isinstance(unresolved_rows, int)
    assert isinstance(ambiguous_rows, int)
    assert isinstance(invalid_rows, int)
    return (
        BaselineContract(
            imported_rows=imported_rows,
            linked_rows=linked_rows,
            unresolved_rows=unresolved_rows,
            ambiguous_rows=ambiguous_rows,
            invalid_rows=invalid_rows,
            source_file_hash=source_hash,
        ),
        [],
    )


def check_phase4b_environment(repository_root: Path) -> CheckResult:
    problems: list[Problem] = []

    required_paths = {
        "assessment_summary": PHASE4B_ASSESSMENT_SUMMARY_PATH,
        "channel_performance": PHASE4B_SOURCE_PATH,
        "canonical_analytics": PHASE4B_CANONICAL_STORE_PATH,
    }

    for key, rel_path in required_paths.items():
        if not _is_safe_relative(rel_path):
            problems.append(
                Problem(
                    f"unsafe_required_path_{key}",
                    f"required path must be repository-relative and safe: {rel_path}",
                )
            )

    if problems:
        return CheckResult(state=GateState.INCONSISTENT, problems=problems)

    abs_paths = {key: repository_root / rel_path for key, rel_path in required_paths.items()}

    missing_or_unreadable = False
    for key, abs_path in abs_paths.items():
        if not abs_path.exists():
            missing_or_unreadable = True
            problems.append(Problem(f"missing_{key}", f"required file is missing: {abs_path.relative_to(repository_root)}"))
            continue
        if not abs_path.is_file():
            missing_or_unreadable = True
            problems.append(Problem(f"not_file_{key}", f"required path is not a file: {abs_path.relative_to(repository_root)}"))
            continue
        try:
            _ = abs_path.read_text(encoding="utf-8")
        except Exception as exc:
            missing_or_unreadable = True
            problems.append(
                Problem(
                    f"unreadable_{key}",
                    f"required file is not readable: {abs_path.relative_to(repository_root)} ({exc.__class__.__name__})",
                )
            )

    summary_payload: dict[str, Any] | None = None
    contract: BaselineContract | None = None

    summary_path = abs_paths["assessment_summary"]
    if summary_path.exists() and summary_path.is_file():
        try:
            summary_payload = _load_json(summary_path)
        except Exception as exc:
            problems.append(
                Problem(
                    "malformed_assessment_summary",
                    f"assessment_summary.json is malformed ({exc.__class__.__name__})",
                )
            )
        if summary_payload is not None:
            contract, contract_problems = _extract_baseline_contract(summary_payload)
            problems.extend(contract_problems)

    source_rows: list[dict[str, Any]] = []
    source_malformed = 0
    source_path = abs_paths["channel_performance"]
    if source_path.exists() and source_path.is_file():
        source_rows, source_malformed = _load_jsonl(source_path)
        if source_malformed > 0:
            problems.append(
                Problem(
                    "channel_performance_malformed_jsonl",
                    f"logs/channel_performance.jsonl contains malformed rows: {source_malformed}",
                )
            )

    canonical_rows: list[dict[str, Any]] = []
    canonical_malformed = 0
    canonical_path = abs_paths["canonical_analytics"]
    if canonical_path.exists() and canonical_path.is_file():
        canonical_rows, canonical_malformed = _load_jsonl(canonical_path)
        if canonical_malformed > 0:
            problems.append(
                Problem(
                    "canonical_analytics_malformed_jsonl",
                    f"logs/canonical_content_analytics.jsonl contains malformed rows: {canonical_malformed}",
                )
            )

    if contract is not None:
        raw_lines = source_path.read_text(encoding="utf-8").splitlines(True)
        if len(raw_lines) < contract.imported_rows:
            problems.append(
                Problem(
                    "insufficient_frozen_source_rows",
                    (
                        "logs/channel_performance.jsonl has fewer rows than required by "
                        f"assessment summary: {len(raw_lines)} < {contract.imported_rows}"
                    ),
                )
            )
        else:
            frozen_bytes = "".join(raw_lines[: contract.imported_rows])
            frozen_hash = hashlib.sha256(frozen_bytes.encode("utf-8")).hexdigest()
            if frozen_hash != contract.source_file_hash:
                problems.append(
                    Problem(
                        "frozen_source_hash_mismatch",
                        (
                            "frozen source hash mismatch for logs/channel_performance.jsonl first "
                            f"{contract.imported_rows} rows"
                        ),
                    )
                )

        filtered_local_provider: list[dict[str, Any]] = []
        canonical_validation_errors = 0
        for row in canonical_rows:
            try:
                normalized = validate_canonical_record(row)
            except Exception:
                canonical_validation_errors += 1
                continue
            if (
                str(normalized.get("provider") or "") == PHASE4B_LOCAL_PROVIDER
                and str(normalized.get("source_file_hash") or "") == contract.source_file_hash
            ):
                filtered_local_provider.append(normalized)

        if canonical_validation_errors > 0:
            problems.append(
                Problem(
                    "canonical_row_schema_validation_failed",
                    f"canonical analytics rows failing schema validation: {canonical_validation_errors}",
                )
            )

        if len(filtered_local_provider) != contract.imported_rows:
            problems.append(
                Problem(
                    "canonical_row_count_mismatch",
                    (
                        "canonical analytics rows for ExistingLocalAnalyticsProvider/source hash "
                        f"mismatch: {len(filtered_local_provider)} != {contract.imported_rows}"
                    ),
                )
            )

        outcome_counts = {
            "LINKED": 0,
            "UNRESOLVED": 0,
            "AMBIGUOUS": 0,
            "INVALID": 0,
        }
        for row in filtered_local_provider:
            provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
            join_outcome = str((provenance or {}).get("join_outcome") or "")
            if join_outcome in outcome_counts:
                outcome_counts[join_outcome] += 1

        if outcome_counts["LINKED"] != contract.linked_rows:
            problems.append(
                Problem(
                    "coverage_linked_mismatch",
                    (
                        "assessment coverage linked count mismatch: "
                        f"{outcome_counts['LINKED']} != {contract.linked_rows}"
                    ),
                )
            )

        if outcome_counts["UNRESOLVED"] != contract.unresolved_rows:
            problems.append(
                Problem(
                    "coverage_unresolved_mismatch",
                    (
                        "assessment coverage unresolved count mismatch: "
                        f"{outcome_counts['UNRESOLVED']} != {contract.unresolved_rows}"
                    ),
                )
            )

        if outcome_counts["AMBIGUOUS"] != contract.ambiguous_rows:
            problems.append(
                Problem(
                    "coverage_ambiguous_mismatch",
                    (
                        "assessment coverage ambiguous count mismatch: "
                        f"{outcome_counts['AMBIGUOUS']} != {contract.ambiguous_rows}"
                    ),
                )
            )

        if outcome_counts["INVALID"] != contract.invalid_rows:
            problems.append(
                Problem(
                    "coverage_invalid_mismatch",
                    (
                        "assessment coverage invalid count mismatch: "
                        f"{outcome_counts['INVALID']} != {contract.invalid_rows}"
                    ),
                )
            )

    state = GateState.READY
    if missing_or_unreadable:
        state = GateState.NOT_PREPARED
    elif problems:
        state = GateState.INCONSISTENT

    return CheckResult(state=state, problems=problems)


def _print_result(result: CheckResult) -> None:
    if result.state is GateState.READY:
        print("PHASE4B ENVIRONMENT READY")
        print(f"STATE: {result.state.value}")
        return

    print("PHASE4B ENVIRONMENT PRECONDITION FAILED")
    print(f"STATE: {result.state.value}")
    for idx, problem in enumerate(result.problems, start=1):
        print(f"{idx}. [{problem.code}] {problem.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Phase4B precondition check for Phase4C validation")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root to validate",
    )
    args = parser.parse_args()

    repository_root = args.root.resolve()
    result = check_phase4b_environment(repository_root)
    _print_result(result)
    if result.state is GateState.READY:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())