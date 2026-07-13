from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.content_intelligence_foundation import (
    CONTENT_INTELLIGENCE_SCHEMA_VERSION,
    GENERATION_BLUEPRINT_SCHEMA_VERSION,
    AudienceProfile,
    ChannelProfile,
    ContentGoal,
    DiscoveryGoal,
    GenerationBlueprint,
    HookGoal,
    NarrativeGoal,
    PerformanceExpectation,
    RetentionGoal,
    SEOGoal,
    ShortsGoal,
    ThumbnailGoal,
    TopicIntent,
    assert_blueprint_planning_consistency,
    build_channel_profiles_from_registry,
    build_generation_blueprint,
    default_hook_templates,
    default_narrative_templates,
    evolve_blueprint_schema_v1_to_v1,
)


def _channel() -> ChannelProfile:
    return ChannelProfile(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        channel_id="borsa_akademi",
        name="Borsa Akademi",
        niche="borsa",
        audience_summary="Retail investors in Turkey",
        experience_level="mixed",
        tone="educational",
        authority_level="high",
        educational_depth="deep",
        preferred_video_length_seconds=720,
        preferred_shorts_length_seconds=55,
        preferred_cta_style="educational",
        risk_tolerance="low",
        monetization_suitability="high",
        evergreen_ratio=0.6,
        trend_ratio=0.3,
        upload_frequency_per_week=14,
        playlist_strategy="clustered_series_by_topic",
        canonical_channel_id="borsa_akademi",
    )


def _audience() -> AudienceProfile:
    return AudienceProfile(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        audience_id="tr_investing_mixed",
        primary_age_range="25-50",
        experience_level="mixed",
        primary_motivation="Build practical investing literacy",
        pain_points=["information overload", "fear of loss"],
        desired_outcomes=["better decisions", "consistent process"],
        language="tr",
    )


def _topic() -> TopicIntent:
    return TopicIntent(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        topic_id="topic_1",
        topic_title="BIST risk management",
        topic_kind="analysis",
        urgency="medium",
        expected_ctr_style="comparison",
        expected_retention_style="steady",
        expected_thumbnail_style="authority",
        recommended_narrative_structure="problem_solution",
    )


def _goal() -> ContentGoal:
    return ContentGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        goal_id="goal_1",
        primary_outcome="Increase understanding",
        success_metric="avg_percentage_viewed",
        target_surface="search",
        performance_horizon="mid_term",
    )


def _narrative() -> NarrativeGoal:
    return NarrativeGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        narrative_template="problem_solution",
        structure_notes="problem -> evidence -> solution",
        psychological_strategy="reduce uncertainty",
        expected_payoff_window_seconds=180,
    )


def _hook() -> HookGoal:
    return HookGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        hook_type="question",
        psychological_intent="activate curiosity",
        ideal_audience="mixed",
        estimated_retention_objective="improve first 30s retention",
    )


def _retention() -> RetentionGoal:
    return RetentionGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        opening_plan="Question + context",
        first_30_seconds_plan="State promise and stakes",
        curiosity_refresh_interval_seconds=40,
        payoff_timing_seconds=200,
        cta_timing_seconds=420,
        ending_plan="Summary and next-step bridge",
    )


def _thumb() -> ThumbnailGoal:
    return ThumbnailGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        emotional_emphasis="medium",
        facial_emphasis="low",
        object_emphasis="high",
        contrast_level="high",
        information_density="balanced",
        text_length_target=4,
        curiosity_level="medium",
        urgency_level="medium",
        trust_signal_level="high",
        authority_signal_level="high",
    )


def _seo() -> SEOGoal:
    return SEOGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        title_objective="clear value proposition",
        keyword_strategy="keyword cluster around bist risk strategy",
        search_intent="users searching practical risk framework",
        browse_intent="related market education content",
        suggested_traffic_objective="connect to portfolio and risk videos",
        playlist_relevance_plan="place in risk management playlist",
        tag_relevance_plan="high-intent tags only",
        hashtag_strategy="3 concise topical hashtags",
    )


def _shorts() -> ShortsGoal:
    return ShortsGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        clip_objective="tease key framework",
        hook_type="warning",
        context_length_seconds=15,
        payoff_timing_seconds=28,
        ending_style="cta_bridge",
        looping_suitability="medium",
        continuation_suitability="high",
    )


def _discovery() -> DiscoveryGoal:
    return DiscoveryGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        primary_surface="search",
        secondary_surfaces=["browse", "suggested"],
        playlist_strategy="add to thematic playlist",
        cards_strategy="point to prerequisite video",
        end_screen_strategy="next logical topic",
    )


def _expectation() -> PerformanceExpectation:
    return PerformanceExpectation(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        expected_ctr=0.08,
        expected_average_view_duration_seconds=240,
        expected_average_percentage_viewed=0.42,
        expected_shorts_completion_rate=0.7,
        target_kpi="avg_percentage_viewed",
    )


def _blueprint() -> GenerationBlueprint:
    return build_generation_blueprint(
        channel_profile=_channel(),
        audience_profile=_audience(),
        topic_intent=_topic(),
        content_goal=_goal(),
        narrative_goal=_narrative(),
        hook_goal=_hook(),
        retention_goal=_retention(),
        thumbnail_goal=_thumb(),
        seo_goal=_seo(),
        shorts_goal=_shorts(),
        discovery_goal=_discovery(),
        performance_expectation=_expectation(),
        blueprint_id="bp_001",
        created_at="2026-07-13T12:00:00+00:00",
    )


def test_blueprint_serialization_roundtrip() -> None:
    bp = _blueprint()
    payload = bp.to_dict()
    rebuilt = GenerationBlueprint.from_dict(payload)

    assert rebuilt.schema_version == GENERATION_BLUEPRINT_SCHEMA_VERSION
    assert rebuilt.blueprint_id == "bp_001"
    assert rebuilt.channel_profile.channel_id == "borsa_akademi"


def test_blueprint_immutability() -> None:
    bp = _blueprint()
    with pytest.raises(FrozenInstanceError):
        bp.blueprint_id = "changed"  # type: ignore[misc]


def test_channel_profile_validation() -> None:
    with pytest.raises(ValueError):
        ChannelProfile(
            schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
            channel_id="",
            name="x",
            niche="y",
            audience_summary="z",
            experience_level="mixed",
            tone="t",
            authority_level="high",
            educational_depth="deep",
            preferred_video_length_seconds=10,
            preferred_shorts_length_seconds=10,
            preferred_cta_style="educational",
            risk_tolerance="low",
            monetization_suitability="high",
            evergreen_ratio=0.8,
            trend_ratio=0.4,
            upload_frequency_per_week=1,
            playlist_strategy="p",
            canonical_channel_id="c",
        )


def test_topic_intent_validation() -> None:
    with pytest.raises(ValueError):
        TopicIntent(
            schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
            topic_id="t1",
            topic_title="title",
            topic_kind="invalid",  # type: ignore[arg-type]
            urgency="medium",
            expected_ctr_style="comparison",
            expected_retention_style="steady",
            expected_thumbnail_style="authority",
            recommended_narrative_structure="problem_solution",
        )


def test_hook_validation() -> None:
    with pytest.raises(ValueError):
        HookGoal(
            schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
            hook_type="invalid",  # type: ignore[arg-type]
            psychological_intent="x",
            ideal_audience="y",
            estimated_retention_objective="z",
        )


def test_retention_validation() -> None:
    with pytest.raises(ValueError):
        RetentionGoal(
            schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
            opening_plan="o",
            first_30_seconds_plan="f",
            curiosity_refresh_interval_seconds=0,
            payoff_timing_seconds=20,
            cta_timing_seconds=30,
            ending_plan="e",
        )


def test_schema_evolution_backward_compatibility_defaults() -> None:
    old_payload = _blueprint().to_dict()
    old_payload.pop("created_at", None)
    old_payload.pop("schema_version", None)

    evolved = evolve_blueprint_schema_v1_to_v1(old_payload)
    assert evolved["schema_version"] == GENERATION_BLUEPRINT_SCHEMA_VERSION
    assert "created_at" in evolved


def test_blueprint_planning_consistency() -> None:
    bp = _blueprint()
    assert_blueprint_planning_consistency(bp)

    inconsistent = GenerationBlueprint.from_dict(
        {
            **bp.to_dict(),
            "retention_goal": {
                **bp.retention_goal.to_dict(),
                "curiosity_refresh_interval_seconds": 90,
            },
            "topic_intent": {
                **bp.topic_intent.to_dict(),
                "expected_retention_style": "fast_paced",
            },
        }
    )

    with pytest.raises(ValueError):
        assert_blueprint_planning_consistency(inconsistent)


def test_channel_registry_profile_builder_uses_canonical_ids() -> None:
    profiles = build_channel_profiles_from_registry(
        registry_path=Path("channels/channel_registry.json"),
    )

    assert "para_pusulasi" in profiles
    assert "borsa_akademi" in profiles
    assert profiles["para_pusulasi"].canonical_channel_id == "para_pusulasi"


def test_default_template_libraries() -> None:
    narratives = default_narrative_templates()
    hooks = default_hook_templates()

    assert len(narratives) == 12
    assert len(hooks) == 10
    assert {item.template_type for item in narratives} >= {
        "curiosity_loop",
        "problem_solution",
        "myth_reality",
        "timeline",
    }
