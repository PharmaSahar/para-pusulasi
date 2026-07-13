from __future__ import annotations

from src.content_intelligence_foundation import GenerationBlueprint
from src.offline_prompt_candidate_generator import (
    benchmark_offline_candidate_lab,
    explain_candidate_evaluations,
    evaluate_candidates,
    rank_candidate_evaluations,
    run_local_calibration,
    run_offline_prompt_candidate_lab,
)
from tests.fixtures.slice4_phase5_prompt_candidate_fixtures import build_phase5_prompt_candidate_fixtures



def _first_blueprint() -> GenerationBlueprint:
    fixture = build_phase5_prompt_candidate_fixtures()[0]
    return GenerationBlueprint.from_dict(fixture.blueprint)



def test_evaluation_dimensions_and_ranking_contract() -> None:
    result = run_offline_prompt_candidate_lab(
        blueprint=_first_blueprint(),
        run_id="run_phase5_eval",
        channel_id="para_pusulasi",
        content_type="mixed",
    )

    payload = result.to_dict()
    assert payload["advisory_only"] is True
    assert payload["pipeline_output_changed"] is False

    ranking = payload["ranking"]
    assert ranking["best_overall"]
    assert ranking["safest"]
    assert ranking["highest_retention"]
    assert ranking["best_seo"]
    assert ranking["best_shorts"]
    assert ranking["most_maintainable"]
    assert len(ranking["ordered_candidates"]) >= 12



def test_explanations_cover_required_fields() -> None:
    result = run_offline_prompt_candidate_lab(
        blueprint=_first_blueprint(),
        run_id="run_phase5_explain",
        channel_id="para_pusulasi",
        content_type="mixed",
    )

    for item in result.to_dict()["explanations"]:
        assert item["why_scored_well"]
        assert item["why_lost"]
        assert item["strongest_dimensions"]
        assert item["weakest_dimensions"]
        assert "finance_concerns" in item
        assert "blueprint_gaps" in item



def test_deterministic_ranking_and_tie_stability() -> None:
    blueprint = _first_blueprint()

    r1 = run_offline_prompt_candidate_lab(
        blueprint=blueprint,
        run_id="run_phase5_det_1",
        channel_id="para_pusulasi",
        content_type="mixed",
    ).to_dict()
    r2 = run_offline_prompt_candidate_lab(
        blueprint=blueprint,
        run_id="run_phase5_det_2",
        channel_id="para_pusulasi",
        content_type="mixed",
    ).to_dict()

    assert r1["ranking"] == r2["ranking"]



def test_calibration_report_acceptance() -> None:
    fixtures = build_phase5_prompt_candidate_fixtures()
    payloads = [
        {
            "fixture_id": fx.fixture_id,
            "channel_id": fx.channel_id,
            "content_type": fx.content_type,
            "blueprint": fx.blueprint,
        }
        for fx in fixtures
    ]
    report = run_local_calibration(payloads)

    assert report["fixture_count"] >= 40
    assert report["deterministic_repeated_runs"] is True
    assert report["nondeterministic_rankings"] == 0
    assert report["unsafe_recommendation_promotions"] == 0



def test_benchmark_runs() -> None:
    bench = benchmark_offline_candidate_lab(blueprint=_first_blueprint(), runs=10)

    assert bench["one_lab_run_ms"] >= 0.0
    assert bench["fifty_lab_run_ms"] >= 0.0
    assert bench["strategy_count"] >= 12
