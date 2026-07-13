from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.content_quality_gap_analyzer import (
    ContentQualityGapValidationError,
    QualityAnalysisInput,
    analyze_content_quality_gaps,
    analyze_content_consistency,
    analyze_script,
    analyze_seo,
    analyze_shorts,
    analyze_thumbnail_metadata,
    analyze_title,
    append_storage_row,
    benchmark_analyzer,
    build_storage_row,
    load_storage_rows,
    replay_storage,
    run_analysis_and_store,
    run_local_calibration,
)
from tests.fixtures.project002_sprint1_quality_gap_fixtures import build_project002_sprint1_fixtures


def _input_from_payload(payload: dict) -> QualityAnalysisInput:
    return QualityAnalysisInput(
        content_id=str(payload.get("content_id") or "x"),
        channel_id=str(payload.get("channel_id") or "x"),
        content_type=str(payload.get("content_type") or "mixed"),
        niche=str(payload.get("niche") or "general"),
        topic=str(payload.get("topic") or "topic"),
        title=str(payload.get("title") or "title"),
        thumbnail_prompt=str(payload.get("thumbnail_prompt") or "thumb"),
        script=str(payload.get("script") or "script"),
        description=str(payload.get("description") or "description"),
        tags=tuple(str(x) for x in list(payload.get("tags") or [])),
        hashtags=tuple(str(x) for x in list(payload.get("hashtags") or [])),
        playlist=str(payload.get("playlist") or "unknown"),
        cards=tuple(str(x) for x in list(payload.get("cards") or [])),
        end_screens=tuple(str(x) for x in list(payload.get("end_screens") or [])),
        short_title=str(payload.get("short_title") or "short"),
        short_script=str(payload.get("short_script") or "short script"),
        review_queue=dict(payload.get("review_queue") or {}),
        analytics=dict(payload.get("analytics") or {}),
        channel_profile=dict(payload.get("channel_profile") or {}),
        audience_profile=dict(payload.get("audience_profile") or {}),
    )


def _sample_input() -> QualityAnalysisInput:
    fixture = build_project002_sprint1_fixtures()[0]
    return _input_from_payload(fixture.input_data)


def test_project002_fixture_count_is_100() -> None:
    fixtures = build_project002_sprint1_fixtures()
    assert len(fixtures) == 100


def test_analyzers_return_expected_range() -> None:
    input_data = _sample_input()

    script = analyze_script(input_data)
    title = analyze_title(input_data)
    thumbnail = analyze_thumbnail_metadata(input_data)
    shorts = analyze_shorts(input_data)
    seo = analyze_seo(input_data)
    consistency = analyze_content_consistency(input_data)

    bounded_keys = [
        (script, ["hook_quality", "opening_strength", "first_30_seconds", "narrative_structure", "pacing", "repetition", "clarity"]),
        (title, ["ctr_psychology", "search_intent", "browse_intent", "suggest_intent", "keyword_quality", "promise_accuracy"]),
        (thumbnail, ["contrast", "information_hierarchy", "text_density", "misleading_risk", "thumbnail_title_consistency"]),
        (shorts, ["hook", "beginning_completeness", "payoff", "retention_potential"]),
        (seo, ["title_keyword_strategy", "description_completeness", "tags", "hashtags", "suggested_support"]),
        (consistency, ["consistency_score"]),
    ]

    for payload, keys in bounded_keys:
        for key in keys:
            value = float(payload[key])
            assert 0.0 <= value <= 1.0


def test_analyze_content_quality_gaps_contract() -> None:
    input_data = _sample_input()

    result = analyze_content_quality_gaps(input_data=input_data, run_id="run_project002_contract")
    payload = result.to_dict()

    assert payload["schema_version"] == "v1"
    assert payload["analyzer_version"] == "v1"
    assert payload["analysis_id"].startswith("cqga_")
    assert payload["advisory_only"] is True
    assert payload["pipeline_output_changed"] is False
    assert isinstance(payload["gaps"], list)
    assert isinstance(payload["root_causes"], list)

    if payload["gaps"]:
        first = payload["gaps"][0]
        required = {
            "gap_id",
            "category",
            "severity",
            "confidence",
            "affected_component",
            "root_cause",
            "evidence",
            "expected_effect",
            "estimated_priority",
            "recommended_future_action",
            "advisory_only",
        }
        assert required.issubset(set(first.keys()))


def test_models_are_immutable() -> None:
    input_data = _sample_input()
    with pytest.raises(FrozenInstanceError):
        input_data.content_id = "mutated"  # type: ignore[misc]


def test_storage_append_load_replay(tmp_path: Path) -> None:
    output = tmp_path / "content_quality_gap_analysis.jsonl"
    input_data = _sample_input()

    payload = run_analysis_and_store(
        input_data=input_data,
        run_id="run_project002_store",
        storage_path=output,
    )

    result = analyze_content_quality_gaps(input_data=input_data, run_id="run_project002_store_2")
    row = build_storage_row(result).to_dict()
    append_storage_row(row, output_path=output)

    output.write_text(output.read_text(encoding="utf-8") + "{malformed}\n", encoding="utf-8")

    rows, malformed = load_storage_rows(input_path=output, limit=20)
    replay = replay_storage(input_path=output, limit=20)

    assert payload["results_path"].endswith("content_quality_gap_analysis.jsonl")
    assert len(rows) == 2
    assert malformed == 1
    assert replay["rows"] == 2
    assert replay["malformed_rows"] == 1


def test_storage_rejects_advisory_contract_violation() -> None:
    with pytest.raises(ContentQualityGapValidationError):
        append_storage_row(
            {
                "schema_version": "v1",
                "analysis_id": "cqga_bad",
                "run_id": "run_bad",
                "content_id": "c1",
                "channel_id": "ch",
                "content_type": "mixed",
                "topic_hash": "abc",
                "gap_count": 0,
                "high_severity_gap_count": 0,
                "root_causes": [],
                "score_summary": {},
                "advisory_only": False,
                "pipeline_output_changed": False,
                "created_at": "2026-07-13T10:00:00+00:00",
            }
        )


def test_local_calibration_stability() -> None:
    fixtures = [
        {
            "fixture_id": item.fixture_id,
            "input_data": item.input_data,
            "expected_gap_categories": list(item.expected_gap_categories),
            "expected_root_causes": list(item.expected_root_causes),
        }
        for item in build_project002_sprint1_fixtures()
    ]

    calibration = run_local_calibration(fixtures)

    assert calibration["fixture_count"] == 100
    assert 0.0 <= float(calibration["precision"]) <= 1.0
    assert 0.0 <= float(calibration["recall"]) <= 1.0
    assert 0.0 <= float(calibration["specificity"]) <= 1.0
    assert 0.0 <= float(calibration["root_cause_accuracy"]) <= 1.0
    assert calibration["score_stability"] == 1.0
    assert calibration["ranking_stability"] == 1.0


def test_benchmark_contract() -> None:
    input_data = _sample_input()
    metrics = benchmark_analyzer(input_data=input_data)

    assert float(metrics["one_analysis_ms"]) >= 0.0
    assert float(metrics["hundred_analysis_ms"]) >= 0.0
    assert float(metrics["thousand_analysis_ms"]) >= 0.0
    assert metrics["bounded_memory"] is True
    assert metrics["deterministic_runtime"] is True
