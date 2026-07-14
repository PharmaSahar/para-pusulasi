from __future__ import annotations

from pathlib import Path

from src.thumbnail_metadata_lineage import (
    build_thumbnail_metadata_lineage_row,
    replay_thumbnail_metadata_lineage_state,
)


def test_replay_is_deterministic(tmp_path: Path) -> None:
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"thumb-bytes")
    rows = [
        build_thumbnail_metadata_lineage_row(
            content_id="content_1",
            run_id="run_1",
            blueprint_id="bp_1",
            planning_id="plan_1",
            thumbnail_prompt="prompt",
            thumbnail_path=str(thumb),
            metadata_version="1.0",
            creation_timestamp="2026-07-14T06:00:00+00:00",
            content_type="video",
            variant_id="var_a",
        )
    ]
    state_a, diag_a = replay_thumbnail_metadata_lineage_state(rows=rows)
    state_b, diag_b = replay_thumbnail_metadata_lineage_state(rows=rows)

    assert state_a == state_b
    assert diag_a == diag_b


def test_replay_tracks_latest_and_missing_fields(tmp_path: Path) -> None:
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"thumb-bytes")
    row = build_thumbnail_metadata_lineage_row(
        content_id="content_1",
        run_id="run_1",
        blueprint_id=None,
        planning_id=None,
        thumbnail_prompt=None,
        thumbnail_path=str(thumb),
        metadata_version="1.0",
        creation_timestamp="2026-07-14T06:00:00+00:00",
        content_type="short",
        variant_id=None,
    )
    state, _diag = replay_thumbnail_metadata_lineage_state(rows=[row])
    entry = next(iter(state.values()))
    assert entry["latest"]["content_type"] == "short"
    assert "thumbnail_prompt_hash" in entry["missing_fields"]