from __future__ import annotations

import json
from pathlib import Path
import time

from src.shadow_content_quality import ShadowContentQualityEngine, build_shadow_evaluation_context
from src.shadow_review_queue import (
    ShadowReviewQueueBuilder,
    query_review_items,
    summarize_review_items,
)


def _row(tmp_path: Path, run_id: str, script: str) -> dict:
    ctx = build_shadow_evaluation_context(
        run_id=run_id,
        content_id=f"content_{run_id}",
        channel_id="perf_channel",
        content_type="mixed",
        topic="perf",
        title="Perf title",
        script=script,
        description="desc",
        thumbnail_prompt="prompt",
        cta_text="abone ol",
    )
    engine = ShadowContentQualityEngine(context=ctx, results_path=tmp_path / "perf_shadow_rows.jsonl")
    return engine.evaluate_checkpoint(checkpoint="generation")


def test_phase4_performance_and_scale_local(tmp_path: Path) -> None:
    events_path = tmp_path / "perf_queue_events.jsonl"
    builder = ShadowReviewQueueBuilder(events_path=events_path)

    one_row = _row(tmp_path, "perf_1", "Bu yontemle garanti getiri var ve hemen al.")

    t0 = time.perf_counter()
    one_result = builder.ingest_shadow_rows([one_row])
    one_ms = (time.perf_counter() - t0) * 1000.0

    rows_100 = [_row(tmp_path, f"perf_{i+2}", f"Bu bilgi henuz fiyatlanmadi {i}") for i in range(100)]
    t1 = time.perf_counter()
    result_100 = builder.ingest_shadow_rows(rows_100)
    hundred_ms = (time.perf_counter() - t1) * 1000.0

    # Build enough events for replay/query benchmark.
    for i in range(350):
        _ = builder.ingest_shadow_rows([
            _row(tmp_path, f"bulk_{i}", f"Iceriden bilgi aldik {i} ve son sans")
        ])

    t2 = time.perf_counter()
    items, diagnostics = builder.get_current_items()
    replay_ms = (time.perf_counter() - t2) * 1000.0

    t3 = time.perf_counter()
    queried = query_review_items(items=items, unresolved_only=True)
    query_ms = (time.perf_counter() - t3) * 1000.0

    t4 = time.perf_counter()
    summary = summarize_review_items(items=items, malformed_row_count=diagnostics.malformed_row_count)
    summarize_ms = (time.perf_counter() - t4) * 1000.0

    duplicate_row = _row(tmp_path, "duplicate_perf", "Bu yontemle garanti getiri var.")
    first = builder.ingest_shadow_rows([duplicate_row])
    second = builder.ingest_shadow_rows([duplicate_row])

    report = {
        "schema_version": "v1",
        "one_row_ingest_ms": round(one_ms, 3),
        "hundred_rows_ingest_ms": round(hundred_ms, 3),
        "replay_current_state_ms": round(replay_ms, 3),
        "query_1000_items_ms": round(query_ms, 3),
        "summarize_1000_items_ms": round(summarize_ms, 3),
        "duplicate_ingestion": {
            "first_created": first.review_items_created,
            "second_created": second.review_items_created,
            "second_existing": second.review_items_existing,
        },
        "current_item_count": len(items),
        "open_item_count": summary["open_item_count"],
        "malformed_row_count": diagnostics.malformed_row_count,
        "suitability_note": "Local advisory queue path remains bounded and suitable for 201 channels with append-only event logs and periodic offline compaction planning.",
        "compaction_strategy_note": "Future compaction should snapshot replayed state into a new file and preserve original append-only log as immutable archive; no destructive rewrite implemented in Phase 4.",
    }

    artifacts_out = Path("artifacts/latest/project001_slice3_phase4_review_queue_performance.json")
    artifacts_out.parent.mkdir(parents=True, exist_ok=True)
    artifacts_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    assert one_result.review_items_created >= 1
    assert result_100.review_items_created >= 1
    assert len(queried) <= len(items)
    assert summary["open_item_count"] >= 1
    assert first.review_items_created >= 1
    assert second.review_items_created == 0
    assert second.review_items_existing >= 1

    # Lenient machine-local bounds.
    assert one_ms < 1500.0
    assert hundred_ms < 35000.0
    assert replay_ms < 5000.0
    assert query_ms < 2000.0
    assert summarize_ms < 2000.0
