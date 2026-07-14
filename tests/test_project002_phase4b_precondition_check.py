from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.project002_sprint1e_phase4b_precondition_check import (
    PHASE4B_ASSESSMENT_SUMMARY_PATH,
    PHASE4B_CANONICAL_STORE_PATH,
    PHASE4B_LOCAL_PROVIDER,
    PHASE4B_SOURCE_PATH,
    GateState,
    check_phase4b_environment,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _jsonl_text(rows: list[dict]) -> str:
    return "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in rows)


def _source_rows(count: int = 3) -> list[dict]:
    return [
        {
            "channel_id": "chan-1",
            "content_id": f"cid-{idx + 1}",
            "video_id": f"vid-{idx + 1}",
            "run_id": f"run-{idx + 1}",
            "views": idx + 10,
        }
        for idx in range(count)
    ]


def _local_canonical_row(
    *,
    source_hash: str,
    source_row_number: int,
    join_outcome: str,
    record_suffix: str,
) -> dict:
    return {
        "schema_version": "v1",
        "analytics_record_id": f"car-{record_suffix}",
        "provider": PHASE4B_LOCAL_PROVIDER,
        "source_file_hash": source_hash,
        "source_row_number": source_row_number,
        "canonical_channel_id": "chan-1",
        "content_id": f"cid-{source_row_number}",
        "youtube_video_id": f"vid-{source_row_number}",
        "content_type": "LONG_FORM",
        "snapshot_start": "2026-01-01",
        "snapshot_end": "2026-01-01",
        "imported_at": "2026-01-01T00:00:00+00:00",
        "metrics_version": "v1",
        "provenance": {
            "join_outcome": join_outcome,
            "join_method": "BY_VIDEO_ID",
            "join_details": {"reason": "fixture"},
        },
        "advisory_only": True,
        "pipeline_output_changed": False,
        "metrics": {
            "views": {"state": "OBSERVED", "value": 123, "raw_name": "views"},
        },
    }


def _baseline_summary(*, source_hash: str, imported_rows: int, linked: int, unresolved: int, ambiguous: int, invalid: int) -> dict:
    return {
        "canonical_rows": imported_rows,
        "coverage": {
            "content_linked_rows": linked,
            "unresolved_rows": unresolved,
            "ambiguous_rows": ambiguous,
            "invalid_rows": invalid,
        },
        "imports": [
            {
                "provider": PHASE4B_LOCAL_PROVIDER,
                "source_file_hash": source_hash,
            }
        ],
    }


def _setup_ready_fixture(repo_root: Path) -> None:
    source_rows = _source_rows(3)
    source_text = _jsonl_text(source_rows)
    _write(repo_root / PHASE4B_SOURCE_PATH, source_text)

    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

    summary = _baseline_summary(
        source_hash=source_hash,
        imported_rows=3,
        linked=1,
        unresolved=1,
        ambiguous=1,
        invalid=0,
    )
    _write(repo_root / PHASE4B_ASSESSMENT_SUMMARY_PATH, json.dumps(summary, ensure_ascii=True, indent=2))

    canonical_rows = [
        _local_canonical_row(source_hash=source_hash, source_row_number=1, join_outcome="LINKED", record_suffix="1"),
        _local_canonical_row(source_hash=source_hash, source_row_number=2, join_outcome="UNRESOLVED", record_suffix="2"),
        _local_canonical_row(source_hash=source_hash, source_row_number=3, join_outcome="AMBIGUOUS", record_suffix="3"),
    ]
    _write(repo_root / PHASE4B_CANONICAL_STORE_PATH, _jsonl_text(canonical_rows))


def _problem_codes(result) -> set[str]:
    return {p.code for p in result.problems}


def test_missing_all_required_files_reports_not_prepared(tmp_path: Path) -> None:
    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.NOT_PREPARED
    codes = _problem_codes(result)
    assert "missing_assessment_summary" in codes
    assert "missing_channel_performance" in codes
    assert "missing_canonical_analytics" in codes


def test_ready_fixture_passes(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.READY
    assert result.problems == []


def test_assessment_summary_malformed_reports_inconsistent(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    _write(tmp_path / PHASE4B_ASSESSMENT_SUMMARY_PATH, "{not-json")

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    assert "malformed_assessment_summary" in _problem_codes(result)


def test_summary_missing_local_provider_import(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    summary_path = tmp_path / PHASE4B_ASSESSMENT_SUMMARY_PATH
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["imports"] = [{"provider": "StudioExportProvider", "source_file_hash": "abc"}]
    _write(summary_path, json.dumps(summary, ensure_ascii=True, indent=2))

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    assert "summary_missing_local_import" in _problem_codes(result)


def test_source_hash_mismatch_detected(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    summary_path = tmp_path / PHASE4B_ASSESSMENT_SUMMARY_PATH
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["imports"][0]["source_file_hash"] = "0" * 64
    _write(summary_path, json.dumps(summary, ensure_ascii=True, indent=2))

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    assert "frozen_source_hash_mismatch" in _problem_codes(result)


def test_insufficient_source_rows_detected(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    source_rows = _source_rows(2)
    source_text = _jsonl_text(source_rows)
    _write(tmp_path / PHASE4B_SOURCE_PATH, source_text)

    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    summary = _baseline_summary(
        source_hash=source_hash,
        imported_rows=3,
        linked=1,
        unresolved=1,
        ambiguous=1,
        invalid=0,
    )
    _write(tmp_path / PHASE4B_ASSESSMENT_SUMMARY_PATH, json.dumps(summary, ensure_ascii=True, indent=2))

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    assert "insufficient_frozen_source_rows" in _problem_codes(result)


def test_canonical_row_count_mismatch_detected(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    canonical_path = tmp_path / PHASE4B_CANONICAL_STORE_PATH
    rows = [json.loads(line) for line in canonical_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    _write(canonical_path, _jsonl_text(rows[:2]))

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    assert "canonical_row_count_mismatch" in _problem_codes(result)


def test_canonical_schema_validation_failures_detected(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    canonical_path = tmp_path / PHASE4B_CANONICAL_STORE_PATH
    rows = [json.loads(line) for line in canonical_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    del rows[0]["metrics"]
    _write(canonical_path, _jsonl_text(rows))

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    codes = _problem_codes(result)
    assert "canonical_row_schema_validation_failed" in codes
    assert "canonical_row_count_mismatch" in codes


def test_coverage_mismatch_unresolved_detected(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    summary_path = tmp_path / PHASE4B_ASSESSMENT_SUMMARY_PATH
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["coverage"]["unresolved_rows"] = 2
    _write(summary_path, json.dumps(summary, ensure_ascii=True, indent=2))

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    assert "coverage_unresolved_mismatch" in _problem_codes(result)


def test_source_jsonl_malformed_detected(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    source_path = tmp_path / PHASE4B_SOURCE_PATH
    _write(source_path, source_path.read_text(encoding="utf-8") + "{bad-json\n")

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    assert "channel_performance_malformed_jsonl" in _problem_codes(result)


def test_canonical_jsonl_malformed_detected(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    canonical_path = tmp_path / PHASE4B_CANONICAL_STORE_PATH
    _write(canonical_path, canonical_path.read_text(encoding="utf-8") + "not-json\n")

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.INCONSISTENT
    assert "canonical_analytics_malformed_jsonl" in _problem_codes(result)


def test_non_file_required_path_reports_not_prepared(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    summary_path = tmp_path / PHASE4B_ASSESSMENT_SUMMARY_PATH
    summary_path.unlink()
    summary_path.mkdir(parents=True, exist_ok=True)

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.NOT_PREPARED
    assert "not_file_assessment_summary" in _problem_codes(result)


def test_missing_canonical_only_reports_not_prepared(tmp_path: Path) -> None:
    _setup_ready_fixture(tmp_path)
    (tmp_path / PHASE4B_CANONICAL_STORE_PATH).unlink()

    result = check_phase4b_environment(tmp_path)
    assert result.state is GateState.NOT_PREPARED
    assert "missing_canonical_analytics" in _problem_codes(result)
