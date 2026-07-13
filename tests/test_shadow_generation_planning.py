from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from src.content_intelligence_foundation import CONTENT_INTELLIGENCE_SCHEMA_VERSION, GENERATION_BLUEPRINT_SCHEMA_VERSION
from src.shadow_generation_planning import (
    SHADOW_GENERATION_PLANNING_SCHEMA_VERSION,
    ShadowPlanningValidationError,
    append_shadow_planning_row,
    build_blueprint_from_context,
    build_planning_context,
    build_shadow_generation_planning_artifact,
    load_shadow_planning_rows,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_build_planning_context_finance_channel() -> None:
    context = build_planning_context(
        run_id="run_test_001",
        channel_id="borsa_akademi",
        content_type="mixed",
        topic="BIST 100 risk yonetimi",
        requested_objective="engagement_growth",
        generation_timestamp=_now_iso(),
    )

    assert context.schema_version == SHADOW_GENERATION_PLANNING_SCHEMA_VERSION
    assert context.run_id == "run_test_001"
    assert context.channel_id == "borsa_akademi"
    assert context.content_type == "mixed"
    assert context.capability_profile.get("source")
    assert context.channel_profile.schema_version == CONTENT_INTELLIGENCE_SCHEMA_VERSION
    assert context.audience_profile.schema_version == CONTENT_INTELLIGENCE_SCHEMA_VERSION


def test_build_blueprint_from_context_is_deterministic() -> None:
    context = build_planning_context(
        run_id="run_test_002",
        channel_id="girisim_okulu",
        content_type="short",
        topic="Startup birim ekonomisi nasil okunur",
        requested_objective="retention_stability",
        generation_timestamp="2026-07-13T10:00:00+00:00",
    )

    first = build_blueprint_from_context(context)
    second = build_blueprint_from_context(context)

    assert first.blueprint_id == second.blueprint_id
    assert first.to_dict() == second.to_dict()
    assert first.schema_version == GENERATION_BLUEPRINT_SCHEMA_VERSION


def test_shadow_storage_append_load_and_malformed_tolerance(tmp_path: Path) -> None:
    path = tmp_path / "shadow_generation_planning.jsonl"

    row = {
        "schema_version": SHADOW_GENERATION_PLANNING_SCHEMA_VERSION,
        "run_id": "run_test_003",
        "blueprint_id": "bp_abc123",
        "blueprint_hash": "hash123",
        "channel_id": "test_channel",
        "content_type": "mixed",
        "topic_excerpt": "topic excerpt",
        "requested_objective": "engagement_growth",
        "planning_schema_version": CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        "blueprint_schema_version": GENERATION_BLUEPRINT_SCHEMA_VERSION,
        "blueprint_valid": True,
        "advisory_only": True,
        "pipeline_output_changed": False,
        "created_at": _now_iso(),
    }

    append_shadow_planning_row(row, output_path=path)
    path.write_text(path.read_text(encoding="utf-8") + "{malformed-json}\n", encoding="utf-8")

    rows, malformed = load_shadow_planning_rows(input_path=path, limit=10)

    assert len(rows) == 1
    assert malformed == 1
    assert rows[0]["run_id"] == "run_test_003"


def test_shadow_artifact_written_with_advisory_contract(tmp_path: Path) -> None:
    path = tmp_path / "artifact_rows.jsonl"

    artifact = build_shadow_generation_planning_artifact(
        run_id="run_test_004",
        channel_id="test_channel",
        content_type="video",
        topic="Uzun vadeli birikim disiplini",
        requested_objective="engagement_growth",
        generation_timestamp="2026-07-13T10:00:00+00:00",
        storage_path=path,
    )

    assert artifact["enabled"] is True
    assert artifact["mode"] == "advisory"
    assert artifact["pipeline_output_changed"] is False
    assert artifact["validation"]["valid"] is True
    assert artifact["planning_schema_version"] == CONTENT_INTELLIGENCE_SCHEMA_VERSION
    assert artifact["blueprint_schema_version"] == GENERATION_BLUEPRINT_SCHEMA_VERSION

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["run_id"] == "run_test_004"
    assert row["pipeline_output_changed"] is False


def test_secret_like_content_is_rejected() -> None:
    with pytest.raises(ShadowPlanningValidationError):
        build_planning_context(
            run_id="run_test_005",
            channel_id="test_channel",
            content_type="mixed",
            topic="api_key=SECRET this topic must fail",
            requested_objective="engagement_growth",
            generation_timestamp=_now_iso(),
        )
