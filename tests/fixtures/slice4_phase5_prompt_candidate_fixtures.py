from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Any

from tests.fixtures.slice4_phase3_alignment_fixtures import build_phase3_calibration_fixtures


@dataclass(frozen=True)
class PromptCandidateFixture:
    fixture_id: str
    title: str
    channel_id: str
    content_type: str
    scenario_tags: tuple[str, ...]
    blueprint: dict[str, Any]


def _base_blueprint() -> dict[str, Any]:
    return deepcopy(build_phase3_calibration_fixtures()[0].blueprint)


def _make_fixture(
    *,
    fixture_id: str,
    title: str,
    channel_id: str,
    content_type: str,
    tags: tuple[str, ...],
) -> PromptCandidateFixture:
    blueprint = _base_blueprint()
    blueprint["channel_profile"]["channel_id"] = channel_id
    blueprint["topic_intent"]["topic_title"] = title

    if "beginner" in tags:
        blueprint["audience_profile"]["experience_level"] = "beginner"
    elif "advanced" in tags:
        blueprint["audience_profile"]["experience_level"] = "advanced"
    else:
        blueprint["audience_profile"]["experience_level"] = "intermediate"

    if "breaking" in tags:
        blueprint["topic_intent"]["topic_kind"] = "breaking_news"
        blueprint["topic_intent"]["urgency"] = "high"
    elif "evergreen" in tags:
        blueprint["topic_intent"]["topic_kind"] = "evergreen"
        blueprint["topic_intent"]["urgency"] = "low"
    else:
        blueprint["topic_intent"]["topic_kind"] = "educational"
        blueprint["topic_intent"]["urgency"] = "medium"

    return PromptCandidateFixture(
        fixture_id=fixture_id,
        title=title,
        channel_id=channel_id,
        content_type=content_type,
        scenario_tags=tags,
        blueprint=blueprint,
    )


def build_phase5_prompt_candidate_fixtures() -> list[PromptCandidateFixture]:
    scenarios = [
        ("fx01", "Emergency fund basics", "para_pusulasi", "video", ("finance", "safe_finance", "beginner", "long_form", "evergreen")),
        ("fx02", "BIST volatility reaction", "borsa_akademi", "video", ("finance", "breaking", "advanced", "retention_heavy")),
        ("fx03", "Crypto risk sizing", "kripto_gundemi", "video", ("crypto", "safe_finance", "advanced")),
        ("fx04", "Crypto hype trap", "kripto_gundemi", "short", ("crypto", "unsafe_finance", "shorts", "breaking")),
        ("fx05", "Career salary negotiation", "kariyer_okulu", "video", ("careers", "beginner", "seo_heavy")),
        ("fx06", "Career transition roadmap", "kariyer_okulu", "video", ("careers", "evergreen", "retention_heavy")),
        ("fx07", "Startup unit economics", "girisim_okulu", "video", ("entrepreneurship", "advanced", "seo_heavy")),
        ("fx08", "Startup MVP launch timeline", "girisim_okulu", "video", ("entrepreneurship", "breaking")),
        ("fx09", "Education deep work routine", "egitim_plus", "video", ("education", "evergreen", "beginner")),
        ("fx10", "Education exam myths", "egitim_plus", "short", ("education", "shorts", "myth")),
        ("fx11", "Finance duplicate A", "para_pusulasi", "video", ("finance", "duplicate_topics", "seo_heavy")),
        ("fx12", "Finance duplicate B", "para_pusulasi", "video", ("finance", "duplicate_topics", "seo_heavy")),
        ("fx13", "Safe investing principles", "para_pusulasi", "video", ("finance", "safe_finance", "evergreen")),
        ("fx14", "Unsafe pump signals", "para_pusulasi", "short", ("finance", "unsafe_finance", "shorts", "breaking")),
        ("fx15", "Beginner budgeting mistakes", "para_pusulasi", "video", ("finance", "beginner", "retention_heavy")),
        ("fx16", "Advanced options caution", "borsa_akademi", "video", ("finance", "advanced", "safe_finance")),
        ("fx17", "SEO title architecture", "egitim_plus", "video", ("seo_heavy", "education", "long_form")),
        ("fx18", "Retention hooks workshop", "egitim_plus", "video", ("retention_heavy", "education")),
        ("fx19", "Shorts productivity burst", "kariyer_okulu", "short", ("shorts", "careers", "beginner")),
        ("fx20", "Long-form career case study", "kariyer_okulu", "video", ("long_form", "careers", "advanced")),
        ("fx21", "Evergreen entrepreneurship system", "girisim_okulu", "video", ("entrepreneurship", "evergreen", "seo_heavy")),
        ("fx22", "Breaking market rumor safety", "borsa_akademi", "video", ("finance", "breaking", "safe_finance")),
        ("fx23", "Crypto evergreen custody", "kripto_gundemi", "video", ("crypto", "evergreen", "safe_finance")),
        ("fx24", "Crypto breaking liquidation", "kripto_gundemi", "short", ("crypto", "breaking", "shorts")),
        ("fx25", "Education beginner checklist", "egitim_plus", "video", ("education", "beginner", "checklist")),
        ("fx26", "Education advanced analysis", "egitim_plus", "video", ("education", "advanced", "analytical")),
        ("fx27", "Career duplicate A", "kariyer_okulu", "video", ("careers", "duplicate_topics", "seo_heavy")),
        ("fx28", "Career duplicate B", "kariyer_okulu", "video", ("careers", "duplicate_topics", "seo_heavy")),
        ("fx29", "Entrepreneurship retention challenge", "girisim_okulu", "video", ("entrepreneurship", "retention_heavy")),
        ("fx30", "Entrepreneurship SEO sprint", "girisim_okulu", "short", ("entrepreneurship", "seo_heavy", "shorts")),
        ("fx31", "Finance safe short checklist", "para_pusulasi", "short", ("finance", "shorts", "safe_finance")),
        ("fx32", "Finance unsafe certainty claims", "para_pusulasi", "video", ("finance", "unsafe_finance", "advanced")),
        ("fx33", "Crypto beginner first wallet", "kripto_gundemi", "video", ("crypto", "beginner", "evergreen")),
        ("fx34", "Crypto advanced derivatives", "kripto_gundemi", "video", ("crypto", "advanced", "retention_heavy")),
        ("fx35", "Career breaking layoffs response", "kariyer_okulu", "video", ("careers", "breaking", "beginner")),
        ("fx36", "Education long-form timeline", "egitim_plus", "video", ("education", "long_form", "evergreen")),
        ("fx37", "Entrepreneurship investigation", "girisim_okulu", "video", ("entrepreneurship", "advanced", "investigation")),
        ("fx38", "Finance SEO retention combo", "para_pusulasi", "video", ("finance", "seo_heavy", "retention_heavy")),
        ("fx39", "Shorts education recap", "egitim_plus", "short", ("education", "shorts", "retention_heavy")),
        ("fx40", "Long-form finance analytical", "borsa_akademi", "video", ("finance", "long_form", "analytical", "safe_finance")),
    ]

    fixtures: list[PromptCandidateFixture] = []
    for fixture_id, title, channel_id, content_type, tags in scenarios:
        fixtures.append(
            _make_fixture(
                fixture_id=fixture_id,
                title=title,
                channel_id=channel_id,
                content_type=content_type,
                tags=tags,
            )
        )
    return fixtures
