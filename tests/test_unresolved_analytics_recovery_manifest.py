from __future__ import annotations

import hashlib
from pathlib import Path

from src.unresolved_analytics_recovery import (
    build_unresolved_input_manifest,
    load_authoritative_phase4b_canonical_rows,
    load_phase4b_baseline,
    reconstruct_authoritative_source_rows,
    run_phase4c_unresolved_analytics_recovery,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_manifest_is_stable_and_represents_all_102_rows() -> None:
    baseline = load_phase4b_baseline(repository_root=REPO_ROOT)
    source_rows = reconstruct_authoritative_source_rows(repository_root=REPO_ROOT, baseline=baseline)
    canonical_rows = load_authoritative_phase4b_canonical_rows(repository_root=REPO_ROOT, baseline=baseline)

    manifest_a = build_unresolved_input_manifest(source_rows=source_rows, canonical_rows=canonical_rows, baseline=baseline)
    manifest_b = build_unresolved_input_manifest(source_rows=source_rows, canonical_rows=canonical_rows, baseline=baseline)

    assert len(manifest_a) == 102
    assert manifest_a == manifest_b
    assert len({row["unresolved_record_id"] for row in manifest_a}) == 102
    assert all(row["original_join_status"] == "UNRESOLVED" for row in manifest_a)
    assert {row["source_file_hash"] for row in manifest_a} == {baseline.source_file_hash}


def test_first_788_lines_match_phase4b_hash() -> None:
    baseline = load_phase4b_baseline(repository_root=REPO_ROOT)
    path = REPO_ROOT / "logs/channel_performance.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(True)
    digest = hashlib.sha256("".join(lines[:788]).encode("utf-8")).hexdigest()
    assert digest == baseline.source_file_hash


def test_phase4c_run_does_not_mutate_source_rows(tmp_path: Path) -> None:
    source_path = REPO_ROOT / "logs/channel_performance.jsonl"
    before = source_path.read_bytes()
    run_phase4c_unresolved_analytics_recovery(
        repository_root=REPO_ROOT,
        output_dir=tmp_path / "output",
        manifest_path=tmp_path / "manifest.jsonl",
        audit_results_path=tmp_path / "audit.jsonl",
        recovery_evidence_path=tmp_path / "recovery.jsonl",
        duplicate_disposition_path=tmp_path / "duplicates.jsonl",
    )
    after = source_path.read_bytes()
    assert before == after