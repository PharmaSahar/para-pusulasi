from __future__ import annotations

import json
from pathlib import Path

from src.content_intelligence_foundation import GenerationBlueprint
from src.shadow_blueprint_prompt_alignment import (
    append_alignment_row,
    build_safe_prompt_representation,
    load_alignment_rows,
    run_local_calibration,
)
from tests.fixtures.slice4_phase3_alignment_fixtures import build_phase3_calibration_fixtures


def test_calibration_fixture_count_and_titles() -> None:
    fixtures = build_phase3_calibration_fixtures()
    assert len(fixtures) >= 30

    required_titles = {
        "Fully aligned educational-finance prompt",
        "Blueprint requires a hook but prompt omits it",
        "Blueprint requires uncertainty but prompt uses certainty",
        "Beginner audience with expert-only prompt",
        "Evergreen topic with breaking-news prompt",
        "Safe finance blueprint with pump-style title instruction",
        "Correct ticker across blueprint and prompt",
        "Wrong ticker in prompt",
        "Narrative structure fully represented",
        "Narrative structure missing",
        "Retention plan fully represented",
        "Retention plan absent",
        "Thumbnail trust goal aligned",
        "Thumbnail wealth/urgency conflict",
        "Search-intent SEO alignment",
        "SEO objective missing",
        "Playlist/cards/end-screen unsupported",
        "Complete Shorts planning alignment",
        "Fixed-duration mid-content clipping conflict",
        "Prompt aligned but generated title mismatched",
        "Prompt aligned but generated script repetitive",
        "Blueprint gap causing artifact gap",
        "Prompt conflict causing artifact conflict",
        "Feature not implemented",
        "Data unavailable",
        "Analyzer exception",
        "Malformed prior storage line",
        "Unicode/Turkish finance prompt",
        "Safe negation language",
        "Dangerous financial assertion",
    }
    fixture_titles = {item.title for item in fixtures}
    assert required_titles.issubset(fixture_titles)


def test_local_calibration_metrics_pass_acceptance() -> None:
    fixtures = build_phase3_calibration_fixtures()
    metrics = run_local_calibration(fixtures=fixtures)

    assert metrics["fixture_count"] >= 30
    assert metrics["precision"] >= 0.90
    assert metrics["recall"] >= 0.90
    assert metrics["specificity"] >= 0.90


def test_turkish_and_finance_calibration_buckets_present() -> None:
    metrics = run_local_calibration(fixtures=build_phase3_calibration_fixtures())

    assert metrics["finance_specific"]["examples"] >= 1
    assert metrics["turkish_language"]["examples"] >= 1


def test_malformed_store_loading_tolerance(tmp_path: Path) -> None:
    store = tmp_path / "shadow_blueprint_prompt_alignment.jsonl"

    append_alignment_row(
        {
            "schema_version": "v1",
            "analysis_id": "align_good",
            "blueprint_id": "bp_good",
            "blueprint_hash": "hash_bp",
            "prompt_hash": "hash_prompt",
            "run_id": "run_good",
            "channel_id": "para_pusulasi",
            "content_type": "mixed",
            "prompt_type": "content_generation",
            "template_id": "fixture_content_v1",
            "analyzer_version": "v1",
            "analyzed_dimensions": 10,
            "strong_present_count": 4,
            "weak_present_count": 2,
            "missing_count": 1,
            "conflicting_count": 1,
            "unsupported_count": 1,
            "unknown_count": 1,
            "overall_coverage_score": 0.6,
            "overall_conflict_score": 0.1,
            "conflict_codes": [],
            "failure_source_summary": {"PROMPT_COVERAGE_GAP": 1},
            "advisory_only": True,
            "pipeline_output_changed": False,
            "created_at": "2026-07-13T10:00:00+00:00",
        },
        output_path=store,
    )

    store.write_text(store.read_text(encoding="utf-8") + "{broken}\n", encoding="utf-8")
    rows, malformed = load_alignment_rows(input_path=store, limit=20)

    assert len(rows) == 1
    assert malformed == 1


def test_unicode_turkish_prompt_representation() -> None:
    fixture = next(item for item in build_phase3_calibration_fixtures() if item.fixture_id == "fx28")
    blueprint = GenerationBlueprint.from_dict(fixture.blueprint)

    rep = build_safe_prompt_representation(
        prompt_text=fixture.prompt_text,
        prompt_type=fixture.prompt_type,
        template_id=fixture.template_id,
    )

    assert rep.prompt_hash
    assert rep.token_size_estimate > 0
    assert blueprint.channel_profile.channel_id == "para_pusulasi"
