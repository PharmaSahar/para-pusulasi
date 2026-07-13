from __future__ import annotations

import json
from pathlib import Path

from src.script_lineage_evidence import (
    build_legacy_import_assessment,
    classify_legacy_sample,
    run_legacy_import_dry_run,
)


def test_classification_preview_vs_ambiguous() -> None:
    preview = classify_legacy_sample(
        runtime_row={"content_id": "content_1"},
        ownership_row={"content_id": "content_1", "script_preview": "preview text" * 4},
    )
    assert preview == "preview_only"

    ambiguous = classify_legacy_sample(
        runtime_row={"content_id": "content_A"},
        ownership_row={"content_id": "content_B", "script_preview": "preview text" * 4},
    )
    assert ambiguous == "ambiguous"


def test_legacy_assessment_and_dry_run_default(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    ownership_dir = tmp_path / "ownership"
    runtime_dir.mkdir(parents=True)
    ownership_dir.mkdir(parents=True)

    (runtime_dir / "content_1.json").write_text(
        json.dumps({"generation_id": "content_1", "metadata": {"title": "t"}, "script_hash": "h"}),
        encoding="utf-8",
    )
    (runtime_dir / "content_2.json").write_text(
        json.dumps({"generation_id": "content_2", "metadata": {"title": "t2"}}),
        encoding="utf-8",
    )
    (ownership_dir / "content_1_run_r1.json").write_text(
        json.dumps({"content_id": "content_1", "run_id": "r1", "script_preview": "p" * 80}),
        encoding="utf-8",
    )

    report_path = tmp_path / "legacy_report.json"
    payload = run_legacy_import_dry_run(
        output_path=report_path,
        runtime_evidence_dir=runtime_dir,
        ownership_dir=ownership_dir,
        limit=300,
        dry_run=True,
    )

    assert payload["dry_run"] is True
    assert payload["sample_count"] == 2
    assert report_path.exists()


def test_legacy_assessment_is_non_mutating(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    ownership_dir = tmp_path / "ownership"
    runtime_dir.mkdir(parents=True)
    ownership_dir.mkdir(parents=True)

    source = runtime_dir / "content_1.json"
    source.write_text(json.dumps({"generation_id": "content_1"}), encoding="utf-8")
    before = source.read_text(encoding="utf-8")

    _ = build_legacy_import_assessment(runtime_evidence_dir=runtime_dir, ownership_dir=ownership_dir, limit=10)

    after = source.read_text(encoding="utf-8")
    assert before == after
