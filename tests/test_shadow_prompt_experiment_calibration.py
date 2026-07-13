from __future__ import annotations

from src.content_intelligence_foundation import GenerationBlueprint
from src.shadow_blueprint_prompt_alignment import build_safe_prompt_representation
from src.shadow_prompt_experiment_framework import run_prompt_experiment
from tests.fixtures.slice4_phase4_prompt_experiment_fixtures import build_phase4_prompt_experiment_fixtures



def test_phase4_fixture_count_and_coverage_tags() -> None:
    fixtures = build_phase4_prompt_experiment_fixtures()
    assert len(fixtures) >= 30

    tags = {tag for fixture in fixtures for tag in fixture.scenario_tags}
    required_tags = {
        "educational_finance",
        "breaking_finance",
        "evergreen_education",
        "career_guidance",
        "entrepreneurship",
        "shorts",
        "long_form",
        "duplicate_topics",
        "finance_safety_edge",
        "seo_heavy",
        "weak_hook",
        "strong_hook",
        "narrative_mismatch",
        "thumbnail_mismatch",
        "unsupported_feature",
    }
    assert required_tags.issubset(tags)



def test_local_experiment_recommendation_distribution_is_deterministic() -> None:
    fixtures = build_phase4_prompt_experiment_fixtures()

    rec_counts: dict[str, int] = {}
    for item in fixtures:
        blueprint = GenerationBlueprint.from_dict(item.blueprint)
        prompt_repr = build_safe_prompt_representation(
            prompt_text=item.prompt_text,
            prompt_type="content_generation",
            template_id="content_generator_v2_json",
        )
        result = run_prompt_experiment(
            blueprint=blueprint,
            prompt_representation=prompt_repr,
            run_id=f"run_{item.fixture_id}",
            channel_id=blueprint.channel_profile.channel_id,
            content_type=item.content_type,
            objective=item.objective,
            hypothesis=item.hypothesis,
            expected_improvement=item.expected_improvement,
        )

        recommendations = list(result.to_dict().get("recommendations") or [])
        for rec in recommendations:
            key = str(rec.get("recommendation") or "")
            rec_counts[key] = int(rec_counts.get(key, 0)) + 1

    assert rec_counts.get("KEEP_CURRENT", 0) >= 30
    assert rec_counts.get("UNSUPPORTED", 0) >= 1



def test_aggregate_metrics_are_in_range() -> None:
    fixture = build_phase4_prompt_experiment_fixtures()[0]
    blueprint = GenerationBlueprint.from_dict(fixture.blueprint)
    prompt_repr = build_safe_prompt_representation(
        prompt_text=fixture.prompt_text,
        prompt_type="content_generation",
        template_id="content_generator_v2_json",
    )
    result = run_prompt_experiment(
        blueprint=blueprint,
        prompt_representation=prompt_repr,
        run_id="run_phase4_metrics",
        channel_id=blueprint.channel_profile.channel_id,
        content_type="mixed",
    )

    metrics = result.to_dict().get("evaluation_metrics") or {}
    for key in ("coverage", "conflicts", "clarity", "safety", "repetition", "alignment", "maintainability"):
        assert 0.0 <= float(metrics.get(key, 0.0)) <= 1.0
