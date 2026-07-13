from __future__ import annotations

from src.content_intelligence_foundation import GenerationBlueprint
from src.shadow_blueprint_prompt_alignment import analyze_blueprint_prompt_alignment, build_safe_prompt_representation
from tests.fixtures.slice4_phase3_alignment_fixtures import build_phase3_calibration_fixtures


def _run_fixture(index: int):
    fixture = build_phase3_calibration_fixtures()[index]
    blueprint = GenerationBlueprint.from_dict(fixture.blueprint)
    prompt_repr = build_safe_prompt_representation(
        prompt_text=fixture.prompt_text,
        prompt_type=fixture.prompt_type,
        template_id=fixture.template_id,
        blueprint_goal_references=[],
    )
    result = analyze_blueprint_prompt_alignment(
        blueprint=blueprint,
        prompt_representation=prompt_repr,
        run_id=f"run_{fixture.fixture_id}",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
        artifacts=fixture.artifacts,
        recent_history=[],
        history_window=20,
    )
    finding_map = {item.get("dimension_code"): item for item in result.alignment_findings}
    return fixture, result, finding_map


def test_hook_missing_detected() -> None:
    fixture, _result, finding_map = _run_fixture(1)
    assert finding_map["hook_type"]["alignment_state"] == fixture.expected_states["hook_type"]


def test_uncertainty_conflict_detected() -> None:
    fixture, result, finding_map = _run_fixture(2)
    assert finding_map["safety_uncertainty_language"]["alignment_state"] == fixture.expected_states["safety_uncertainty_language"]
    for code in fixture.expected_conflict_codes:
        assert code in result.conflict_codes


def test_audience_conflict_detected() -> None:
    fixture, result, finding_map = _run_fixture(3)
    assert finding_map["channel_audience_level"]["alignment_state"] == fixture.expected_states["channel_audience_level"]
    for code in fixture.expected_conflict_codes:
        assert code in result.conflict_codes


def test_evergreen_breaking_conflict_detected() -> None:
    fixture, result, finding_map = _run_fixture(4)
    assert finding_map["topic_evergreen_trend"]["alignment_state"] == fixture.expected_states["topic_evergreen_trend"]
    for code in fixture.expected_conflict_codes:
        assert code in result.conflict_codes


def test_wrong_ticker_conflict_detected() -> None:
    fixture, result, finding_map = _run_fixture(7)
    assert finding_map["safety_ticker_company_consistency"]["alignment_state"] == fixture.expected_states["safety_ticker_company_consistency"]
    assert "TICKER_COMPANY_MISMATCH" in result.conflict_codes


def test_shorts_clipping_conflict_detected() -> None:
    fixture, result, finding_map = _run_fixture(18)
    assert finding_map["shorts_sentence_completeness"]["alignment_state"] == fixture.expected_states["shorts_sentence_completeness"]
    assert "SHORTS_COMPLETENESS_CLIPPING_CONFLICT" in result.conflict_codes


def test_feature_not_implemented_and_data_unavailable() -> None:
    fixture_u, _result_u, finding_u = _run_fixture(23)
    assert finding_u["discovery_session_continuation"]["alignment_state"] == fixture_u.expected_states["discovery_session_continuation"]

    fixture_x, _result_x, finding_x = _run_fixture(24)
    assert finding_x["safety_source_requirements"]["alignment_state"] == fixture_x.expected_states["safety_source_requirements"]


def test_safe_negation_not_flagged_as_high_severity_conflict() -> None:
    fixture, result, _finding_map = _run_fixture(28)
    for code in fixture.prohibited_findings:
        assert code not in result.conflict_codes
