from __future__ import annotations

import json
from pathlib import Path

from src.shadow_content_quality import ShadowContentQualityEngine, build_shadow_evaluation_context
from src.shadow_review_queue import (
    ShadowReviewQueueBuilder,
    add_reviewer_note,
    apply_disposition,
    apply_status_transition,
    build_related_finding_bundles,
    load_review_queue_events,
    replay_review_queue_state,
)


def _row(
    tmp_path: Path,
    *,
    run_id: str,
    script: str,
    title: str = "Birikim Rehberi",
    description: str = "Birikim adimlari",
) -> dict:
    ctx = build_shadow_evaluation_context(
        run_id=run_id,
        content_id=f"content_{run_id}",
        channel_id="channel_q",
        content_type="mixed",
        topic="finans",
        title=title,
        script=script,
        description=description,
        thumbnail_prompt="Finance board",
        cta_text="abone ol",
    )
    engine = ShadowContentQualityEngine(context=ctx, results_path=tmp_path / "shadow_rows.jsonl")
    return engine.evaluate_checkpoint(checkpoint="generation")


def test_append_only_events_and_replay_determinism(tmp_path: Path) -> None:
    events_path = tmp_path / "queue_events.jsonl"
    builder = ShadowReviewQueueBuilder(events_path=events_path)

    row = _row(tmp_path, run_id="a1", script="Bu yontemle garanti getiri var ve hemen al.")
    result = builder.ingest_shadow_rows([row])
    assert result.review_items_created >= 1

    events1, malformed1, errors1 = load_review_queue_events(input_path=events_path)
    state1, diagnostics1 = replay_review_queue_state(events=events1)

    events2, malformed2, errors2 = load_review_queue_events(input_path=events_path)
    state2, diagnostics2 = replay_review_queue_state(events=events2)

    assert malformed1 == 0
    assert malformed2 == 0
    assert not errors1
    assert not errors2
    assert diagnostics1.replay_errors == diagnostics2.replay_errors
    assert state1 == state2


def test_malformed_line_tolerance(tmp_path: Path) -> None:
    events_path = tmp_path / "queue_events.jsonl"
    events_path.write_text("{bad json}\n", encoding="utf-8")

    builder = ShadowReviewQueueBuilder(events_path=events_path)
    row = _row(tmp_path, run_id="a2", script="Iceriden bilgi aldik, hemen al.")
    result = builder.ingest_shadow_rows([row])

    assert result.review_items_created >= 1
    events, malformed, _errors = load_review_queue_events(input_path=events_path)
    assert malformed >= 1
    assert events


def test_duplicate_ingestion_is_idempotent(tmp_path: Path) -> None:
    events_path = tmp_path / "queue_events.jsonl"
    builder = ShadowReviewQueueBuilder(events_path=events_path)

    row = _row(tmp_path, run_id="a3", script="Bu hisse icin not priced in bilgi var.")

    first = builder.ingest_shadow_rows([row])
    second = builder.ingest_shadow_rows([row])

    assert first.review_items_created >= 1
    assert second.review_items_created == 0
    assert second.review_items_existing >= 1


def test_materially_changed_finding_creates_new_item_and_supersedes_old(tmp_path: Path) -> None:
    events_path = tmp_path / "queue_events.jsonl"
    builder = ShadowReviewQueueBuilder(events_path=events_path)

    row1 = _row(tmp_path, run_id="a4", script="Bu yontemle garanti getiri var.")
    row2 = _row(tmp_path, run_id="a4", script="Bu yontemle garanti getiri var ve yuzde 300 kesin.")

    r1 = builder.ingest_shadow_rows([row1])
    r2 = builder.ingest_shadow_rows([row2])

    assert r1.review_items_created >= 1
    assert r2.review_items_created >= 1

    items, _diag = builder.get_current_items()
    superseded = [item for item in items if item["status"] == "SUPERSEDED"]
    assert superseded


def test_status_disposition_note_events_apply_without_rewrite(tmp_path: Path) -> None:
    events_path = tmp_path / "queue_events.jsonl"
    builder = ShadowReviewQueueBuilder(events_path=events_path)
    row = _row(tmp_path, run_id="a5", script="Fonlar gizlice topluyor, son sans.")
    _ = builder.ingest_shadow_rows([row])

    items, _diag = builder.get_current_items()
    item_id = items[0]["review_item_id"]

    before_lines = len(events_path.read_text(encoding="utf-8").splitlines())
    apply_status_transition(review_item_id=item_id, to_status="IN_REVIEW", events_path=events_path)
    apply_disposition(review_item_id=item_id, disposition="NEEDS_SOURCE_VERIFICATION", events_path=events_path)
    add_reviewer_note(review_item_id=item_id, note="Check source and phrasing", events_path=events_path)
    apply_status_transition(review_item_id=item_id, to_status="RESOLVED", events_path=events_path)
    after_lines = len(events_path.read_text(encoding="utf-8").splitlines())

    assert after_lines >= before_lines + 4

    events, malformed, errors = load_review_queue_events(input_path=events_path)
    assert malformed == 0
    assert not errors

    state, diagnostics = replay_review_queue_state(events=events)
    assert not diagnostics.replay_errors
    assert state[item_id]["status"] == "RESOLVED"
    assert state[item_id]["disposition"] == "NEEDS_SOURCE_VERIFICATION"
    assert state[item_id]["reviewer_note"] == "Check source and phrasing"


def test_related_bundle_creation_preserves_finding_codes(tmp_path: Path) -> None:
    events_path = tmp_path / "queue_events.jsonl"
    builder = ShadowReviewQueueBuilder(events_path=events_path)

    row = _row(
        tmp_path,
        run_id="a6",
        title="Bu Hisse Ucacak Son Sans",
        script="Bu yontemle garanti getiri var. Hemen al. Insider information var.",
    )
    _ = builder.ingest_shadow_rows([row])
    items, _diag = builder.get_current_items()
    bundles = build_related_finding_bundles(items=items)

    assert bundles
    first = bundles[0]
    assert first["finding_count"] >= first["grouped_finding_count"]
    assert first["review_item_ids"]
