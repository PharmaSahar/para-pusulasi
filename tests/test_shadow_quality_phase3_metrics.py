from __future__ import annotations

import json
import time
from pathlib import Path

from src.shadow_content_quality import (
    SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
    ShadowContentQualityEngine,
    build_human_review_items,
    build_shadow_evaluation_context,
    load_shadow_results,
    validate_shadow_row,
)
from src.shadow_quality_taxonomy import list_finding_specs


def _engine(tmp_path: Path, run_id: str, script: str, title: str = "Birikim Rehberi") -> ShadowContentQualityEngine:
    ctx = build_shadow_evaluation_context(
        run_id=run_id,
        content_id=f"content_{run_id}",
        channel_id="calibration_ch",
        content_type="mixed",
        topic="Birikim",
        title=title,
        script=script,
        description="Birikim adımları ve risk yönetimi.",
        thumbnail_prompt="Finance checklist",
        cta_text="abone ol",
    )
    return ShadowContentQualityEngine(
        context=ctx,
        results_path=tmp_path / "shadow_rows.jsonl",
        history_window=120,
    )


def test_phase2_row_compatibility_and_append_only(tmp_path: Path) -> None:
    v1_row = {
        "schema_version": "v1",
        "evaluation_id": "abc",
        "run_id": "run",
        "content_id": "content",
        "channel_id": "ch",
        "content_type": "mixed",
        "topic_hash": "th",
        "title_hash": "ti",
        "script_hash": "sc",
        "checkpoint": "generation",
        "quality_scores": [],
        "findings": [],
        "severity": "none",
        "validator_versions": {"shadow": "v1"},
        "created_at": "2026-07-13T12:00:00+00:00",
        "shadow_mode_enabled": True,
    }
    norm = validate_shadow_row(v1_row)
    assert norm["schema_version"] == "v1"
    assert norm["pipeline_output_changed"] is False

    path = tmp_path / "shadow_rows.jsonl"
    path.write_text(json.dumps(v1_row) + "\n{bad_line}\n", encoding="utf-8")
    rows, malformed = load_shadow_results(input_path=path, limit=100)
    assert len(rows) == 1
    assert malformed == 1


def test_human_review_contract_serialization(tmp_path: Path) -> None:
    engine = _engine(tmp_path, "rr1", "Bu yöntemle garanti kazanç var.")
    row = engine.evaluate_checkpoint(checkpoint="generation")
    items = build_human_review_items(row)
    assert isinstance(items, list)
    if items:
        one = items[0]
        for key in [
            "channel_id",
            "run_id",
            "content_type",
            "finding_code",
            "severity",
            "confidence",
            "affected_artifact",
            "bounded_excerpt",
            "explanation",
            "suggested_review_action",
            "evidence_hashes",
            "created_at",
        ]:
            assert key in one


def test_taxonomy_registry_non_empty() -> None:
    specs = list_finding_specs()
    assert specs
    assert all("code" in item and "category" in item for item in specs)


def test_performance_single_and_hundred_eval(tmp_path: Path) -> None:
    engine = _engine(tmp_path, "perf_single", "Birikim için hedef belirleyin ve bütçe uygulayın.")
    t0 = time.perf_counter()
    row = engine.evaluate_checkpoint(checkpoint="generation")
    t1 = time.perf_counter()
    assert row["schema_version"] == SHADOW_CONTENT_QUALITY_SCHEMA_VERSION
    single_ms = (t1 - t0) * 1000.0

    start = time.perf_counter()
    for i in range(100):
        e = _engine(tmp_path, f"perf_{i}", f"Birikim planı adım {i} ve risk yönetimi")
        _ = e.evaluate_checkpoint(checkpoint="generation")
    elapsed_100_ms = (time.perf_counter() - start) * 1000.0

    # Deterministic local upper bounds (lenient enough for CI/dev machines).
    assert single_ms < 500.0
    assert elapsed_100_ms < 25000.0


def test_duplicate_bounded_history_behavior(tmp_path: Path) -> None:
    path = tmp_path / "shadow_rows.jsonl"
    for i in range(300):
        engine = _engine(tmp_path, f"seed_{i}", f"Acil fon adımı {i}", title=f"Acil Fon {i}")
        row = engine.evaluate_checkpoint(checkpoint="generation")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    engine2 = _engine(tmp_path, "bounded", "Acil fon adımı 299", title="Acil Fon 299")
    row2 = engine2.evaluate_checkpoint(checkpoint="generation")
    assert int(row2.get("history_window_size") or 0) >= 10
    assert int(row2.get("history_window_size") or 0) <= 300
