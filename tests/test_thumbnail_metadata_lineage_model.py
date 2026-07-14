from __future__ import annotations

from pathlib import Path

from src.thumbnail_metadata_lineage import (
    THUMBNAIL_METADATA_LINEAGE_SCHEMA_VERSION,
    build_thumbnail_metadata_lineage_row,
    compute_thumbnail_generation_id,
    compute_thumbnail_prompt_hash,
    validate_thumbnail_metadata_lineage_row,
)


def test_build_lineage_row_is_deterministic(tmp_path: Path) -> None:
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"thumb-bytes")

    row_a = build_thumbnail_metadata_lineage_row(
        content_id="content_1",
        run_id="run_1",
        blueprint_id="bp_1",
        planning_id="plan_1",
        thumbnail_prompt="bold market chart",
        thumbnail_path=str(thumb),
        metadata_version="1.0",
        creation_timestamp="2026-07-14T06:00:00+00:00",
        content_type="video",
        variant_id="var_a",
    )
    row_b = build_thumbnail_metadata_lineage_row(
        content_id="content_1",
        run_id="run_1",
        blueprint_id="bp_1",
        planning_id="plan_1",
        thumbnail_prompt="bold market chart",
        thumbnail_path=str(thumb),
        metadata_version="1.0",
        creation_timestamp="2026-07-14T06:00:00+00:00",
        content_type="video",
        variant_id="var_a",
    )

    assert row_a == row_b
    assert row_a["schema_version"] == THUMBNAIL_METADATA_LINEAGE_SCHEMA_VERSION
    assert row_a["completeness_score"] == 1.0
    assert row_a["missing_fields"] == []
    assert row_a["pipeline_output_changed"] is False


def test_missing_optional_identity_lowers_completeness(tmp_path: Path) -> None:
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
    assert row["completeness_score"] < 1.0
    assert "thumbnail_prompt_hash" in row["missing_fields"]


def test_validate_rejects_tampered_integrity(tmp_path: Path) -> None:
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"thumb-bytes")
    row = build_thumbnail_metadata_lineage_row(
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
    row["image_hash"] = "tampered"
    try:
        validate_thumbnail_metadata_lineage_row(row)
    except ValueError as exc:
        assert "integrity_hash" in str(exc)
    else:
        raise AssertionError("tampered row should fail integrity validation")


def test_generation_id_uses_thumbnail_identity_inputs() -> None:
    gid = compute_thumbnail_generation_id(
        content_id="content_1",
        run_id="run_1",
        content_type="video",
        variant_id="var_a",
        thumbnail_prompt_hash=compute_thumbnail_prompt_hash(thumbnail_prompt="prompt"),
        image_hash="img_hash",
    )
    assert gid.startswith("tml_gen_")