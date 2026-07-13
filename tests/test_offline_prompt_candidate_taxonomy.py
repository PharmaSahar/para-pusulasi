from __future__ import annotations

from src.offline_prompt_candidate_generator import STRATEGY_IDS, get_prompt_strategy_taxonomy


def test_taxonomy_contains_required_strategies() -> None:
    taxonomy = get_prompt_strategy_taxonomy()

    assert tuple(taxonomy.keys()) == STRATEGY_IDS



def test_taxonomy_entries_have_required_properties() -> None:
    taxonomy = get_prompt_strategy_taxonomy()

    for strategy_id, strategy in taxonomy.items():
        payload = strategy.to_dict()
        assert payload["strategy_id"] == strategy_id
        assert payload["narrative_style"]
        assert payload["hook_philosophy"]
        assert payload["retention_philosophy"]
        assert payload["seo_philosophy"]
        assert payload["shorts_suitability"]
        assert payload["finance_suitability"]
        assert payload["expected_strengths"]
        assert payload["expected_weaknesses"]
