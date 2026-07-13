from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BLUEPRINT_ALIGNMENT_REGISTRY_VERSION = "v1"

DimensionGroup = Literal[
    "channel",
    "topic",
    "narrative",
    "hook",
    "retention",
    "thumbnail",
    "seo",
    "shorts",
    "discovery",
    "safety_quality",
]


@dataclass(frozen=True)
class BlueprintDimension:
    code: str
    group: DimensionGroup
    label: str
    blueprint_path: str
    component: str
    applicable_content_types: tuple[str, ...]


def get_blueprint_dimension_registry() -> tuple[BlueprintDimension, ...]:
    return (
        # Channel
        BlueprintDimension("channel_identity", "channel", "Channel identity", "channel_profile.channel_id", "script", ("video", "short", "mixed")),
        BlueprintDimension("channel_niche", "channel", "Channel niche", "channel_profile.niche", "script", ("video", "short", "mixed")),
        BlueprintDimension("channel_tone", "channel", "Channel tone", "channel_profile.tone", "script", ("video", "short", "mixed")),
        BlueprintDimension("channel_authority_level", "channel", "Authority level", "channel_profile.authority_level", "script", ("video", "short", "mixed")),
        BlueprintDimension("channel_audience_level", "channel", "Audience level", "audience_profile.experience_level", "script", ("video", "short", "mixed")),
        BlueprintDimension("channel_educational_depth", "channel", "Educational depth", "channel_profile.educational_depth", "script", ("video", "short", "mixed")),
        # Topic
        BlueprintDimension("topic_intent", "topic", "Topic intent", "topic_intent.topic_kind", "script", ("video", "short", "mixed")),
        BlueprintDimension("topic_urgency", "topic", "Topic urgency", "topic_intent.urgency", "script", ("video", "short", "mixed")),
        BlueprintDimension("topic_evergreen_trend", "topic", "Evergreen/trend", "topic_intent.topic_kind", "script", ("video", "short", "mixed")),
        BlueprintDimension("topic_content_objective", "topic", "Content objective", "content_goal.primary_outcome", "script", ("video", "short", "mixed")),
        BlueprintDimension("topic_risk_classification", "topic", "Risk classification", "channel_profile.risk_tolerance", "script", ("video", "short", "mixed")),
        # Narrative
        BlueprintDimension("narrative_structure", "narrative", "Narrative structure", "narrative_goal.narrative_template", "script", ("video", "short", "mixed")),
        BlueprintDimension("narrative_sequence", "narrative", "Narrative sequence", "narrative_goal.structure_notes", "script", ("video", "short", "mixed")),
        BlueprintDimension("narrative_payoff", "narrative", "Narrative payoff", "narrative_goal.expected_payoff_window_seconds", "script", ("video", "short", "mixed")),
        BlueprintDimension("narrative_evidence_structure", "narrative", "Evidence structure", "narrative_goal.psychological_strategy", "script", ("video", "short", "mixed")),
        BlueprintDimension("narrative_conclusion", "narrative", "Conclusion", "retention_goal.ending_plan", "script", ("video", "short", "mixed")),
        # Hook
        BlueprintDimension("hook_type", "hook", "Hook type", "hook_goal.hook_type", "script", ("video", "short", "mixed")),
        BlueprintDimension("hook_first_sentence_objective", "hook", "First sentence objective", "hook_goal.estimated_retention_objective", "script", ("video", "short", "mixed")),
        BlueprintDimension("hook_psychological_intent", "hook", "Psychological intent", "hook_goal.psychological_intent", "script", ("video", "short", "mixed")),
        BlueprintDimension("hook_curiosity_or_warning", "hook", "Curiosity/warning mechanism", "hook_goal.hook_type", "script", ("video", "short", "mixed")),
        # Retention
        BlueprintDimension("retention_first_30s", "retention", "First 30 seconds", "retention_goal.first_30_seconds_plan", "script", ("video", "short", "mixed")),
        BlueprintDimension("retention_refresh", "retention", "Curiosity refresh", "retention_goal.curiosity_refresh_interval_seconds", "script", ("video", "short", "mixed")),
        BlueprintDimension("retention_pacing", "retention", "Pacing", "topic_intent.expected_retention_style", "script", ("video", "short", "mixed")),
        BlueprintDimension("retention_payoff_timing", "retention", "Payoff timing", "retention_goal.payoff_timing_seconds", "script", ("video", "short", "mixed")),
        BlueprintDimension("retention_cta_timing", "retention", "CTA timing", "retention_goal.cta_timing_seconds", "script", ("video", "short", "mixed")),
        BlueprintDimension("retention_ending", "retention", "Ending", "retention_goal.ending_plan", "script", ("video", "short", "mixed")),
        # Thumbnail
        BlueprintDimension("thumbnail_emotional_emphasis", "thumbnail", "Emotional emphasis", "thumbnail_goal.emotional_emphasis", "thumbnail", ("video", "short", "mixed")),
        BlueprintDimension("thumbnail_topic_relevance", "thumbnail", "Topic relevance", "topic_intent.expected_thumbnail_style", "thumbnail", ("video", "short", "mixed")),
        BlueprintDimension("thumbnail_object_or_facial_emphasis", "thumbnail", "Object/facial emphasis", "thumbnail_goal.object_emphasis", "thumbnail", ("video", "short", "mixed")),
        BlueprintDimension("thumbnail_text_density_target", "thumbnail", "Text-density target", "thumbnail_goal.text_length_target", "thumbnail", ("video", "short", "mixed")),
        BlueprintDimension("thumbnail_trust_vs_urgency", "thumbnail", "Trust vs urgency", "thumbnail_goal.urgency_level", "thumbnail", ("video", "short", "mixed")),
        BlueprintDimension("thumbnail_misleading_claim_avoidance", "thumbnail", "Misleading-claim avoidance", "thumbnail_goal.trust_signal_level", "thumbnail", ("video", "short", "mixed")),
        # SEO
        BlueprintDimension("seo_title_objective", "seo", "Title objective", "seo_goal.title_objective", "title", ("video", "short", "mixed")),
        BlueprintDimension("seo_keyword_strategy", "seo", "Keyword strategy", "seo_goal.keyword_strategy", "description", ("video", "short", "mixed")),
        BlueprintDimension("seo_search_intent", "seo", "Search intent", "seo_goal.search_intent", "description", ("video", "short", "mixed")),
        BlueprintDimension("seo_browse_intent", "seo", "Browse intent", "seo_goal.browse_intent", "description", ("video", "short", "mixed")),
        BlueprintDimension("seo_suggested_video_intent", "seo", "Suggested-video intent", "seo_goal.suggested_traffic_objective", "description", ("video", "short", "mixed")),
        BlueprintDimension("seo_hashtag_tag_intent", "seo", "Hashtag/tag intent", "seo_goal.hashtag_strategy", "description", ("video", "short", "mixed")),
        # Shorts
        BlueprintDimension("shorts_hook", "shorts", "Short hook", "shorts_goal.hook_type", "shorts", ("short", "mixed")),
        BlueprintDimension("shorts_context", "shorts", "Short context", "shorts_goal.context_length_seconds", "shorts", ("short", "mixed")),
        BlueprintDimension("shorts_payoff", "shorts", "Short payoff", "shorts_goal.payoff_timing_seconds", "shorts", ("short", "mixed")),
        BlueprintDimension("shorts_sentence_completeness", "shorts", "Sentence completeness", "shorts_goal.clip_objective", "shorts", ("short", "mixed")),
        BlueprintDimension("shorts_ending", "shorts", "Short ending", "shorts_goal.ending_style", "shorts", ("short", "mixed")),
        BlueprintDimension("shorts_looping", "shorts", "Looping suitability", "shorts_goal.looping_suitability", "shorts", ("short", "mixed")),
        BlueprintDimension("shorts_continuation", "shorts", "Continuation suitability", "shorts_goal.continuation_suitability", "shorts", ("short", "mixed")),
        # Discovery
        BlueprintDimension("discovery_playlist_relevance", "discovery", "Playlist relevance", "discovery_goal.playlist_strategy", "discovery", ("video", "short", "mixed")),
        BlueprintDimension("discovery_cards", "discovery", "Cards", "discovery_goal.cards_strategy", "discovery", ("video", "short", "mixed")),
        BlueprintDimension("discovery_end_screen", "discovery", "End screen", "discovery_goal.end_screen_strategy", "discovery", ("video", "short", "mixed")),
        BlueprintDimension("discovery_session_continuation", "discovery", "Session continuation", "discovery_goal.end_screen_strategy", "discovery", ("video", "short", "mixed")),
        # Safety and quality
        BlueprintDimension("safety_unsupported_claim_controls", "safety_quality", "Unsupported claim controls", "hook_goal.psychological_intent", "script", ("video", "short", "mixed")),
        BlueprintDimension("safety_ticker_company_consistency", "safety_quality", "Ticker/company consistency", "topic_intent.topic_title", "script", ("video", "short", "mixed")),
        BlueprintDimension("safety_source_requirements", "safety_quality", "Source requirements", "narrative_goal.psychological_strategy", "script", ("video", "short", "mixed")),
        BlueprintDimension("safety_uncertainty_language", "safety_quality", "Uncertainty language", "channel_profile.risk_tolerance", "script", ("video", "short", "mixed")),
        BlueprintDimension("safety_duplication_avoidance", "safety_quality", "Duplication avoidance", "content_goal.primary_outcome", "script", ("video", "short", "mixed")),
        BlueprintDimension("safety_misleading_content_avoidance", "safety_quality", "Misleading content avoidance", "thumbnail_goal.trust_signal_level", "thumbnail", ("video", "short", "mixed")),
    )


def get_dimension_by_code(code: str) -> BlueprintDimension | None:
    needle = str(code or "").strip()
    for item in get_blueprint_dimension_registry():
        if item.code == needle:
            return item
    return None


def get_supported_alignment_states() -> tuple[str, ...]:
    return (
        "PRESENT_STRONG",
        "PRESENT_WEAK",
        "MISSING",
        "CONFLICTING",
        "NOT_APPLICABLE",
        "UNKNOWN",
        "UNSUPPORTED",
    )


def get_supported_failure_sources() -> tuple[str, ...]:
    return (
        "PLANNING_GAP",
        "PROMPT_COVERAGE_GAP",
        "PROMPT_CONFLICT",
        "GENERATION_NONCOMPLIANCE",
        "POST_PROCESSING_LOSS",
        "FEATURE_NOT_IMPLEMENTED",
        "DATA_UNAVAILABLE",
        "ANALYZER_FAILURE",
    )


def get_conflict_codes() -> tuple[str, ...]:
    return (
        "TONE_SENSATIONALISM_CONFLICT",
        "UNCERTAINTY_CERTAINTY_CONFLICT",
        "TRUST_URGENCY_CONFLICT",
        "AUDIENCE_LEVEL_MISMATCH",
        "EVERGREEN_BREAKING_NEWS_CONFLICT",
        "RISK_MANAGEMENT_GUARANTEED_RETURN_CONFLICT",
        "NEUTRAL_ANALYSIS_BUYSELL_PRESSURE_CONFLICT",
        "TICKER_COMPANY_MISMATCH",
        "LONGFORM_SHORTSONLY_CONFLICT",
        "SHORTS_COMPLETENESS_CLIPPING_CONFLICT",
        "THUMBNAIL_DENSITY_CONFLICT",
        "FINANCE_INSIDER_SECRET_CONFLICT",
    )
