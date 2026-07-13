from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Any

from tests.fixtures.slice4_phase3_alignment_fixtures import build_phase3_calibration_fixtures


@dataclass(frozen=True)
class PromptExperimentFixture:
    fixture_id: str
    title: str
    scenario_tags: tuple[str, ...]
    content_type: str
    objective: str
    hypothesis: str
    expected_improvement: str
    prompt_text: str
    blueprint: dict[str, Any]


def _base_blueprint() -> dict[str, Any]:
    src = build_phase3_calibration_fixtures()[0].blueprint
    return deepcopy(src)


def _make_fixture(
    *,
    fixture_id: str,
    title: str,
    scenario_tags: tuple[str, ...],
    content_type: str,
    prompt_text: str,
) -> PromptExperimentFixture:
    bp = _base_blueprint()
    bp["topic_intent"]["topic_title"] = title
    bp["topic_intent"]["topic_kind"] = "educational"
    return PromptExperimentFixture(
        fixture_id=fixture_id,
        title=title,
        scenario_tags=scenario_tags,
        content_type=content_type,
        objective="improve_prompt_alignment",
        hypothesis="candidate_variants_can_improve_quality_without_runtime_changes",
        expected_improvement="better_coverage_and_safety_with_equal_or_lower_conflicts",
        prompt_text=prompt_text,
        blueprint=bp,
    )


def build_phase4_prompt_experiment_fixtures() -> list[PromptExperimentFixture]:
    scenarios = [
        ("fx01", "Educational finance foundation", ("educational_finance", "long_form"), "video", "json hook retention narrative seo thumbnail safety uncertainty source"),
        ("fx02", "Breaking finance alert", ("breaking_finance", "strong_hook"), "video", "json hook first 30 retention urgency seo thumbnail risk uncertainty"),
        ("fx03", "Evergreen education study routine", ("evergreen_education", "long_form"), "video", "json narrative structure retention checklist seo thumbnail"),
        ("fx04", "Career guidance interview prep", ("career_guidance",), "video", "json hook narrative retention seo title objective"),
        ("fx05", "Entrepreneurship customer discovery", ("entrepreneurship",), "video", "json hook narrative retention shorts seo thumbnail"),
        ("fx06", "Shorts finance risk reminder", ("shorts", "finance_safety_edge"), "short", "json shorts hook loop context safety risk uncertainty"),
        ("fx07", "Shorts productivity checklist", ("shorts",), "short", "json shorts hook loop seo thumbnail"),
        ("fx08", "Long-form retirement strategy", ("long_form", "educational_finance"), "video", "json hook narrative retention seo thumbnail safety source"),
        ("fx09", "Duplicate topic budget planning A", ("duplicate_topics",), "video", "json hook narrative retention seo thumbnail budget plan"),
        ("fx10", "Duplicate topic budget planning B", ("duplicate_topics",), "video", "json hook narrative retention seo thumbnail budget plan"),
        ("fx11", "Finance safety uncertain language", ("finance_safety_edge",), "video", "json safety uncertainty no guaranteed return risk management"),
        ("fx12", "Finance safety hard sell", ("finance_safety_edge", "weak_hook"), "video", "json hook seo thumbnail x kat garantili getiri insider"),
        ("fx13", "SEO-heavy tax planning", ("seo_heavy",), "video", "json seo keyword search intent title objective tags hashtag"),
        ("fx14", "SEO-heavy savings strategy", ("seo_heavy",), "video", "json seo keyword search intent title objective thumbnail"),
        ("fx15", "Weak hook baseline", ("weak_hook",), "video", "json narrative seo thumbnail"),
        ("fx16", "Strong hook baseline", ("strong_hook",), "video", "json hook first 30 curiosity retention narrative seo"),
        ("fx17", "Narrative mismatch scenario", ("narrative_mismatch",), "video", "json hook seo thumbnail shorts"),
        ("fx18", "Thumbnail mismatch scenario", ("thumbnail_mismatch",), "video", "json hook narrative retention seo"),
        ("fx19", "Unsupported feature marker", ("unsupported_feature",), "video", "json hook narrative runtime_replace auto_publish"),
        ("fx20", "Educational finance debt", ("educational_finance",), "video", "json hook narrative retention safety uncertainty seo"),
        ("fx21", "Breaking finance volatility", ("breaking_finance",), "video", "json hook urgency retention safety risk source"),
        ("fx22", "Evergreen education memory", ("evergreen_education",), "video", "json narrative checklist retention seo thumbnail"),
        ("fx23", "Career salary negotiation", ("career_guidance",), "video", "json hook narrative retention seo title objective"),
        ("fx24", "Entrepreneurship unit economics", ("entrepreneurship",), "video", "json hook narrative retention seo thumbnail source"),
        ("fx25", "Shorts startup pitch", ("shorts",), "short", "json shorts hook context loop seo"),
        ("fx26", "Long-form portfolio education", ("long_form",), "video", "json hook narrative retention seo thumbnail safety"),
        ("fx27", "Finance safety edge no certainty", ("finance_safety_edge",), "video", "json uncertainty risk management educational no guarantee"),
        ("fx28", "SEO-heavy entrepreneurship", ("seo_heavy", "entrepreneurship"), "video", "json seo keyword title objective search intent retention"),
        ("fx29", "Strong hook shorts finance", ("shorts", "strong_hook", "educational_finance"), "short", "json shorts hook first 30 risk safety"),
        ("fx30", "Thumbnail mismatch with weak hook", ("thumbnail_mismatch", "weak_hook"), "video", "json seo narrative"),
    ]

    fixtures: list[PromptExperimentFixture] = []
    for fixture_id, title, tags, content_type, prompt_text in scenarios:
        fixtures.append(
            _make_fixture(
                fixture_id=fixture_id,
                title=title,
                scenario_tags=tags,
                content_type=content_type,
                prompt_text=prompt_text,
            )
        )
    return fixtures
