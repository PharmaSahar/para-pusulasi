from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Literal, get_args


CONTENT_INTELLIGENCE_SCHEMA_VERSION = "v1"
GENERATION_BLUEPRINT_SCHEMA_VERSION = "v1"


TopicKind = Literal[
    "educational",
    "explanatory",
    "comparison",
    "breaking_news",
    "analysis",
    "myth_busting",
    "tutorial",
    "opinion",
    "evergreen",
    "trend",
    "warning",
    "update",
]

NarrativeTemplateType = Literal[
    "curiosity_loop",
    "problem_solution",
    "myth_reality",
    "timeline",
    "checklist",
    "ranking",
    "before_after",
    "mistake_driven",
    "case_study",
    "investigation",
    "story_driven",
    "educational_lecture",
]

HookType = Literal[
    "curiosity",
    "surprise",
    "contradiction",
    "warning",
    "question",
    "data_point",
    "emotional",
    "authority",
    "visual",
    "story",
]

RetentionStyle = Literal["slow_burn", "steady", "fast_paced", "high_tension"]
ThumbnailStyle = Literal["authority", "curiosity", "warning", "comparison", "minimalist", "data_driven"]
CTRStyle = Literal["bold_claim", "question", "comparison", "result_oriented", "curiosity_gap"]
ExperienceLevel = Literal["beginner", "intermediate", "advanced", "mixed"]
AuthorityLevel = Literal["low", "medium", "high"]
RiskTolerance = Literal["low", "medium", "high"]
PerformanceHorizon = Literal["short_term", "mid_term", "long_term"]
CTAStyle = Literal["soft", "direct", "educational", "community"]

DiscoverySurface = Literal["search", "browse", "suggested", "shorts_feed", "external"]


_ALLOWED_TOPIC_KINDS = set(get_args(TopicKind))
_ALLOWED_NARRATIVE_TYPES = set(get_args(NarrativeTemplateType))
_ALLOWED_HOOK_TYPES = set(get_args(HookType))
_ALLOWED_RETENTION_STYLES = set(get_args(RetentionStyle))
_ALLOWED_THUMBNAIL_STYLES = set(get_args(ThumbnailStyle))
_ALLOWED_CTR_STYLES = set(get_args(CTRStyle))
_ALLOWED_EXPERIENCE_LEVELS = set(get_args(ExperienceLevel))
_ALLOWED_AUTHORITY_LEVELS = set(get_args(AuthorityLevel))
_ALLOWED_RISK_TOLERANCE = set(get_args(RiskTolerance))
_ALLOWED_HORIZONS = set(get_args(PerformanceHorizon))
_ALLOWED_CTA_STYLES = set(get_args(CTAStyle))
_ALLOWED_DISCOVERY_SURFACES = set(get_args(DiscoverySurface))


def _require_non_empty(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"missing_field:{name}")
    return text


def _require_percent(name: str, value: float) -> float:
    number = float(value)
    if number < 0.0 or number > 1.0:
        raise ValueError(f"invalid_percent:{name}")
    return number


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _serialize(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    return value


def _parse_iso(value: str) -> str:
    text = _require_non_empty("created_at", value)
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


@dataclass(frozen=True)
class ChannelProfile:
    schema_version: str
    channel_id: str
    name: str
    niche: str
    audience_summary: str
    experience_level: ExperienceLevel
    tone: str
    authority_level: AuthorityLevel
    educational_depth: Literal["light", "balanced", "deep"]
    preferred_video_length_seconds: int
    preferred_shorts_length_seconds: int
    preferred_cta_style: CTAStyle
    risk_tolerance: RiskTolerance
    monetization_suitability: Literal["low", "medium", "high"]
    evergreen_ratio: float
    trend_ratio: float
    upload_frequency_per_week: int
    playlist_strategy: str
    canonical_channel_id: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:channel_profile")
        _require_non_empty("channel_id", self.channel_id)
        _require_non_empty("name", self.name)
        _require_non_empty("niche", self.niche)
        _require_non_empty("audience_summary", self.audience_summary)
        if self.experience_level not in _ALLOWED_EXPERIENCE_LEVELS:
            raise ValueError("invalid_field:experience_level")
        if self.authority_level not in _ALLOWED_AUTHORITY_LEVELS:
            raise ValueError("invalid_field:authority_level")
        if self.educational_depth not in {"light", "balanced", "deep"}:
            raise ValueError("invalid_field:educational_depth")
        if self.preferred_video_length_seconds <= 0:
            raise ValueError("invalid_field:preferred_video_length_seconds")
        if self.preferred_shorts_length_seconds <= 0:
            raise ValueError("invalid_field:preferred_shorts_length_seconds")
        if self.preferred_cta_style not in _ALLOWED_CTA_STYLES:
            raise ValueError("invalid_field:preferred_cta_style")
        if self.risk_tolerance not in _ALLOWED_RISK_TOLERANCE:
            raise ValueError("invalid_field:risk_tolerance")
        if self.monetization_suitability not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:monetization_suitability")
        _require_percent("evergreen_ratio", self.evergreen_ratio)
        _require_percent("trend_ratio", self.trend_ratio)
        if round(self.evergreen_ratio + self.trend_ratio, 6) > 1.0:
            raise ValueError("invalid_field:content_ratio_sum")
        if self.upload_frequency_per_week <= 0:
            raise ValueError("invalid_field:upload_frequency_per_week")
        _require_non_empty("playlist_strategy", self.playlist_strategy)
        _require_non_empty("canonical_channel_id", self.canonical_channel_id)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChannelProfile":
        data = dict(payload or {})
        if "canonical_channel_id" not in data:
            data["canonical_channel_id"] = str(data.get("channel_id") or "")
        return cls(**data)


@dataclass(frozen=True)
class AudienceProfile:
    schema_version: str
    audience_id: str
    primary_age_range: str
    experience_level: ExperienceLevel
    primary_motivation: str
    pain_points: list[str]
    desired_outcomes: list[str]
    language: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:audience_profile")
        _require_non_empty("audience_id", self.audience_id)
        _require_non_empty("primary_age_range", self.primary_age_range)
        if self.experience_level not in _ALLOWED_EXPERIENCE_LEVELS:
            raise ValueError("invalid_field:experience_level")
        _require_non_empty("primary_motivation", self.primary_motivation)
        if not self.pain_points:
            raise ValueError("missing_field:pain_points")
        if not self.desired_outcomes:
            raise ValueError("missing_field:desired_outcomes")
        _require_non_empty("language", self.language)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AudienceProfile":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class TopicIntent:
    schema_version: str
    topic_id: str
    topic_title: str
    topic_kind: TopicKind
    urgency: Literal["low", "medium", "high"]
    expected_ctr_style: CTRStyle
    expected_retention_style: RetentionStyle
    expected_thumbnail_style: ThumbnailStyle
    recommended_narrative_structure: NarrativeTemplateType

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:topic_intent")
        _require_non_empty("topic_id", self.topic_id)
        _require_non_empty("topic_title", self.topic_title)
        if self.topic_kind not in _ALLOWED_TOPIC_KINDS:
            raise ValueError("invalid_field:topic_kind")
        if self.urgency not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:urgency")
        if self.expected_ctr_style not in _ALLOWED_CTR_STYLES:
            raise ValueError("invalid_field:expected_ctr_style")
        if self.expected_retention_style not in _ALLOWED_RETENTION_STYLES:
            raise ValueError("invalid_field:expected_retention_style")
        if self.expected_thumbnail_style not in _ALLOWED_THUMBNAIL_STYLES:
            raise ValueError("invalid_field:expected_thumbnail_style")
        if self.recommended_narrative_structure not in _ALLOWED_NARRATIVE_TYPES:
            raise ValueError("invalid_field:recommended_narrative_structure")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TopicIntent":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class ContentGoal:
    schema_version: str
    goal_id: str
    primary_outcome: str
    success_metric: str
    target_surface: DiscoverySurface
    performance_horizon: PerformanceHorizon

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:content_goal")
        _require_non_empty("goal_id", self.goal_id)
        _require_non_empty("primary_outcome", self.primary_outcome)
        _require_non_empty("success_metric", self.success_metric)
        if self.target_surface not in _ALLOWED_DISCOVERY_SURFACES:
            raise ValueError("invalid_field:target_surface")
        if self.performance_horizon not in _ALLOWED_HORIZONS:
            raise ValueError("invalid_field:performance_horizon")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ContentGoal":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class NarrativeGoal:
    schema_version: str
    narrative_template: NarrativeTemplateType
    structure_notes: str
    psychological_strategy: str
    expected_payoff_window_seconds: int

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:narrative_goal")
        if self.narrative_template not in _ALLOWED_NARRATIVE_TYPES:
            raise ValueError("invalid_field:narrative_template")
        _require_non_empty("structure_notes", self.structure_notes)
        _require_non_empty("psychological_strategy", self.psychological_strategy)
        if self.expected_payoff_window_seconds <= 0:
            raise ValueError("invalid_field:expected_payoff_window_seconds")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NarrativeGoal":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class HookGoal:
    schema_version: str
    hook_type: HookType
    psychological_intent: str
    ideal_audience: str
    estimated_retention_objective: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:hook_goal")
        if self.hook_type not in _ALLOWED_HOOK_TYPES:
            raise ValueError("invalid_field:hook_type")
        _require_non_empty("psychological_intent", self.psychological_intent)
        _require_non_empty("ideal_audience", self.ideal_audience)
        _require_non_empty("estimated_retention_objective", self.estimated_retention_objective)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HookGoal":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class RetentionGoal:
    schema_version: str
    opening_plan: str
    first_30_seconds_plan: str
    curiosity_refresh_interval_seconds: int
    payoff_timing_seconds: int
    cta_timing_seconds: int
    ending_plan: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:retention_goal")
        _require_non_empty("opening_plan", self.opening_plan)
        _require_non_empty("first_30_seconds_plan", self.first_30_seconds_plan)
        if self.curiosity_refresh_interval_seconds <= 0:
            raise ValueError("invalid_field:curiosity_refresh_interval_seconds")
        if self.payoff_timing_seconds <= 0:
            raise ValueError("invalid_field:payoff_timing_seconds")
        if self.cta_timing_seconds <= 0:
            raise ValueError("invalid_field:cta_timing_seconds")
        _require_non_empty("ending_plan", self.ending_plan)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RetentionGoal":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class ThumbnailGoal:
    schema_version: str
    emotional_emphasis: Literal["low", "medium", "high"]
    facial_emphasis: Literal["none", "low", "medium", "high"]
    object_emphasis: Literal["low", "medium", "high"]
    contrast_level: Literal["low", "medium", "high"]
    information_density: Literal["minimal", "balanced", "dense"]
    text_length_target: int
    curiosity_level: Literal["low", "medium", "high"]
    urgency_level: Literal["low", "medium", "high"]
    trust_signal_level: Literal["low", "medium", "high"]
    authority_signal_level: Literal["low", "medium", "high"]

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:thumbnail_goal")
        if self.emotional_emphasis not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:emotional_emphasis")
        if self.facial_emphasis not in {"none", "low", "medium", "high"}:
            raise ValueError("invalid_field:facial_emphasis")
        if self.object_emphasis not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:object_emphasis")
        if self.contrast_level not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:contrast_level")
        if self.information_density not in {"minimal", "balanced", "dense"}:
            raise ValueError("invalid_field:information_density")
        if self.text_length_target <= 0:
            raise ValueError("invalid_field:text_length_target")
        if self.curiosity_level not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:curiosity_level")
        if self.urgency_level not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:urgency_level")
        if self.trust_signal_level not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:trust_signal_level")
        if self.authority_signal_level not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:authority_signal_level")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ThumbnailGoal":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class SEOGoal:
    schema_version: str
    title_objective: str
    keyword_strategy: str
    search_intent: str
    browse_intent: str
    suggested_traffic_objective: str
    playlist_relevance_plan: str
    tag_relevance_plan: str
    hashtag_strategy: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:seo_goal")
        _require_non_empty("title_objective", self.title_objective)
        _require_non_empty("keyword_strategy", self.keyword_strategy)
        _require_non_empty("search_intent", self.search_intent)
        _require_non_empty("browse_intent", self.browse_intent)
        _require_non_empty("suggested_traffic_objective", self.suggested_traffic_objective)
        _require_non_empty("playlist_relevance_plan", self.playlist_relevance_plan)
        _require_non_empty("tag_relevance_plan", self.tag_relevance_plan)
        _require_non_empty("hashtag_strategy", self.hashtag_strategy)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SEOGoal":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class ShortsGoal:
    schema_version: str
    clip_objective: str
    hook_type: HookType
    context_length_seconds: int
    payoff_timing_seconds: int
    ending_style: Literal["closed", "open_loop", "cta_bridge"]
    looping_suitability: Literal["low", "medium", "high"]
    continuation_suitability: Literal["low", "medium", "high"]

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:shorts_goal")
        _require_non_empty("clip_objective", self.clip_objective)
        if self.hook_type not in _ALLOWED_HOOK_TYPES:
            raise ValueError("invalid_field:hook_type")
        if self.context_length_seconds <= 0:
            raise ValueError("invalid_field:context_length_seconds")
        if self.payoff_timing_seconds <= 0:
            raise ValueError("invalid_field:payoff_timing_seconds")
        if self.ending_style not in {"closed", "open_loop", "cta_bridge"}:
            raise ValueError("invalid_field:ending_style")
        if self.looping_suitability not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:looping_suitability")
        if self.continuation_suitability not in {"low", "medium", "high"}:
            raise ValueError("invalid_field:continuation_suitability")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ShortsGoal":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class DiscoveryGoal:
    schema_version: str
    primary_surface: DiscoverySurface
    secondary_surfaces: list[DiscoverySurface]
    playlist_strategy: str
    cards_strategy: str
    end_screen_strategy: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:discovery_goal")
        if self.primary_surface not in _ALLOWED_DISCOVERY_SURFACES:
            raise ValueError("invalid_field:primary_surface")
        if not self.secondary_surfaces:
            raise ValueError("missing_field:secondary_surfaces")
        for item in self.secondary_surfaces:
            if item not in _ALLOWED_DISCOVERY_SURFACES:
                raise ValueError("invalid_field:secondary_surfaces")
        _require_non_empty("playlist_strategy", self.playlist_strategy)
        _require_non_empty("cards_strategy", self.cards_strategy)
        _require_non_empty("end_screen_strategy", self.end_screen_strategy)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DiscoveryGoal":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class PerformanceExpectation:
    schema_version: str
    expected_ctr: float
    expected_average_view_duration_seconds: float
    expected_average_percentage_viewed: float
    expected_shorts_completion_rate: float
    target_kpi: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:performance_expectation")
        _require_percent("expected_ctr", self.expected_ctr)
        if self.expected_average_view_duration_seconds <= 0:
            raise ValueError("invalid_field:expected_average_view_duration_seconds")
        _require_percent("expected_average_percentage_viewed", self.expected_average_percentage_viewed)
        _require_percent("expected_shorts_completion_rate", self.expected_shorts_completion_rate)
        _require_non_empty("target_kpi", self.target_kpi)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PerformanceExpectation":
        return cls(**dict(payload or {}))


@dataclass(frozen=True)
class GenerationBlueprint:
    schema_version: str
    blueprint_id: str
    created_at: str
    channel_profile: ChannelProfile
    audience_profile: AudienceProfile
    topic_intent: TopicIntent
    content_goal: ContentGoal
    narrative_goal: NarrativeGoal
    hook_goal: HookGoal
    retention_goal: RetentionGoal
    thumbnail_goal: ThumbnailGoal
    seo_goal: SEOGoal
    shorts_goal: ShortsGoal
    discovery_goal: DiscoveryGoal
    performance_expectation: PerformanceExpectation

    def __post_init__(self) -> None:
        if self.schema_version != GENERATION_BLUEPRINT_SCHEMA_VERSION:
            raise ValueError("invalid_schema_version:generation_blueprint")
        _require_non_empty("blueprint_id", self.blueprint_id)
        _parse_iso(self.created_at)

        if self.channel_profile.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:channel_profile")
        if self.audience_profile.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:audience_profile")
        if self.topic_intent.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:topic_intent")
        if self.content_goal.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:content_goal")
        if self.narrative_goal.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:narrative_goal")
        if self.hook_goal.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:hook_goal")
        if self.retention_goal.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:retention_goal")
        if self.thumbnail_goal.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:thumbnail_goal")
        if self.seo_goal.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:seo_goal")
        if self.shorts_goal.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:shorts_goal")
        if self.discovery_goal.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:discovery_goal")
        if self.performance_expectation.schema_version != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
            raise ValueError("invalid_nested_schema:performance_expectation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "blueprint_id": self.blueprint_id,
            "created_at": self.created_at,
            "channel_profile": self.channel_profile.to_dict(),
            "audience_profile": self.audience_profile.to_dict(),
            "topic_intent": self.topic_intent.to_dict(),
            "content_goal": self.content_goal.to_dict(),
            "narrative_goal": self.narrative_goal.to_dict(),
            "hook_goal": self.hook_goal.to_dict(),
            "retention_goal": self.retention_goal.to_dict(),
            "thumbnail_goal": self.thumbnail_goal.to_dict(),
            "seo_goal": self.seo_goal.to_dict(),
            "shorts_goal": self.shorts_goal.to_dict(),
            "discovery_goal": self.discovery_goal.to_dict(),
            "performance_expectation": self.performance_expectation.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GenerationBlueprint":
        data = dict(payload or {})
        return cls(
            schema_version=str(data.get("schema_version") or GENERATION_BLUEPRINT_SCHEMA_VERSION),
            blueprint_id=str(data.get("blueprint_id") or ""),
            created_at=str(data.get("created_at") or _now_iso()),
            channel_profile=ChannelProfile.from_dict(dict(data.get("channel_profile") or {})),
            audience_profile=AudienceProfile.from_dict(dict(data.get("audience_profile") or {})),
            topic_intent=TopicIntent.from_dict(dict(data.get("topic_intent") or {})),
            content_goal=ContentGoal.from_dict(dict(data.get("content_goal") or {})),
            narrative_goal=NarrativeGoal.from_dict(dict(data.get("narrative_goal") or {})),
            hook_goal=HookGoal.from_dict(dict(data.get("hook_goal") or {})),
            retention_goal=RetentionGoal.from_dict(dict(data.get("retention_goal") or {})),
            thumbnail_goal=ThumbnailGoal.from_dict(dict(data.get("thumbnail_goal") or {})),
            seo_goal=SEOGoal.from_dict(dict(data.get("seo_goal") or {})),
            shorts_goal=ShortsGoal.from_dict(dict(data.get("shorts_goal") or {})),
            discovery_goal=DiscoveryGoal.from_dict(dict(data.get("discovery_goal") or {})),
            performance_expectation=PerformanceExpectation.from_dict(dict(data.get("performance_expectation") or {})),
        )


@dataclass(frozen=True)
class NarrativeTemplate:
    template_type: NarrativeTemplateType
    label: str
    structure_steps: list[str]
    ideal_use_cases: list[str]

    def __post_init__(self) -> None:
        if self.template_type not in _ALLOWED_NARRATIVE_TYPES:
            raise ValueError("invalid_field:template_type")
        _require_non_empty("label", self.label)
        if not self.structure_steps:
            raise ValueError("missing_field:structure_steps")
        if not self.ideal_use_cases:
            raise ValueError("missing_field:ideal_use_cases")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(frozen=True)
class HookTemplate:
    hook_type: HookType
    psychological_intent: str
    ideal_audience: str
    estimated_retention_objective: str

    def __post_init__(self) -> None:
        if self.hook_type not in _ALLOWED_HOOK_TYPES:
            raise ValueError("invalid_field:hook_type")
        _require_non_empty("psychological_intent", self.psychological_intent)
        _require_non_empty("ideal_audience", self.ideal_audience)
        _require_non_empty("estimated_retention_objective", self.estimated_retention_objective)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


def default_narrative_templates() -> list[NarrativeTemplate]:
    return [
        NarrativeTemplate("curiosity_loop", "Curiosity Loop", ["Open loop", "Delay reveal", "Resolve loop"], ["analysis", "update"]),
        NarrativeTemplate("problem_solution", "Problem to Solution", ["State problem", "Frame cost", "Offer solution"], ["tutorial", "educational"]),
        NarrativeTemplate("myth_reality", "Myth vs Reality", ["Present myth", "Show evidence", "Correct model"], ["myth_busting", "opinion"]),
        NarrativeTemplate("timeline", "Timeline", ["Set start state", "Key milestones", "Current state"], ["breaking_news", "update"]),
        NarrativeTemplate("checklist", "Checklist", ["Define criteria", "Walk steps", "Recap list"], ["tutorial", "educational"]),
        NarrativeTemplate("ranking", "Ranking", ["Rank context", "Criteria", "Count down"], ["comparison", "analysis"]),
        NarrativeTemplate("before_after", "Before and After", ["Before state", "Intervention", "After state"], ["case_study", "tutorial"]),
        NarrativeTemplate("mistake_driven", "Mistake Driven", ["Common mistakes", "Impact", "Fix patterns"], ["warning", "educational"]),
        NarrativeTemplate("case_study", "Case Study", ["Context", "Decision", "Outcome"], ["analysis", "story_driven"]),
        NarrativeTemplate("investigation", "Investigation", ["Question", "Evidence trail", "Findings"], ["analysis", "warning"]),
        NarrativeTemplate("story_driven", "Story Driven", ["Character", "Conflict", "Resolution"], ["opinion", "educational"]),
        NarrativeTemplate("educational_lecture", "Educational Lecture", ["Concept", "Examples", "Application"], ["educational", "explanatory"]),
    ]


def default_hook_templates() -> list[HookTemplate]:
    return [
        HookTemplate("curiosity", "Open information gap", "intermediate", "Increase first-30-second retention"),
        HookTemplate("surprise", "Pattern interrupt", "mixed", "Reduce early drop-off"),
        HookTemplate("contradiction", "Challenge assumptions", "advanced", "Promote watch continuation"),
        HookTemplate("warning", "Risk alert framing", "beginner", "Raise immediate attention"),
        HookTemplate("question", "Invite active thinking", "mixed", "Improve cognitive engagement"),
        HookTemplate("data_point", "Anchor with concrete figure", "intermediate", "Increase trust and watch-time"),
        HookTemplate("emotional", "Empathy and stakes", "beginner", "Strengthen emotional retention"),
        HookTemplate("authority", "Credibility lead", "intermediate", "Reduce skepticism"),
        HookTemplate("visual", "Visual contrast setup", "mixed", "Improve swipe-stop for Shorts"),
        HookTemplate("story", "Narrative entry", "mixed", "Increase completion through narrative tension"),
    ]


def build_channel_profiles_from_registry(
    *,
    registry_path: Path | str = Path("channels/channel_registry.json"),
) -> dict[str, ChannelProfile]:
    path = Path(registry_path)
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"channels": {}}
    channels = payload.get("channels") if isinstance(payload, dict) else {}
    if not isinstance(channels, dict):
        channels = {}

    out: dict[str, ChannelProfile] = {}
    for key, item in channels.items():
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("channel_id") or key)
        niche = str(item.get("niche") or "general")
        topics = item.get("topics") if isinstance(item.get("topics"), list) else []
        persona = str(item.get("persona") or item.get("tagline") or "").strip() or "general audience"

        preferred_video_length_seconds = 600
        preferred_shorts_length_seconds = 55
        educational_depth = "balanced"
        authority_level: AuthorityLevel = "medium"
        risk_tolerance: RiskTolerance = "medium"

        if niche in {"borsa", "kripto", "kisisel_finans"}:
            authority_level = "high"
            risk_tolerance = "low"
            preferred_video_length_seconds = 720
            educational_depth = "deep"
        elif niche in {"kariyer", "girisimcilik", "teknoloji"}:
            authority_level = "medium"
            preferred_video_length_seconds = 540
            educational_depth = "balanced"
        else:
            authority_level = "medium"
            preferred_video_length_seconds = 600
            educational_depth = "balanced"

        evergreen_ratio = 0.65
        trend_ratio = 0.30
        if niche in {"kripto", "teknoloji"}:
            evergreen_ratio = 0.45
            trend_ratio = 0.50

        frequency = 7
        upload_times = item.get("upload_times") if isinstance(item.get("upload_times"), list) else []
        if upload_times:
            frequency = max(1, min(14, len(upload_times) * 7))

        name = str(item.get("name") or channel_id)
        out[channel_id] = ChannelProfile(
            schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
            channel_id=channel_id,
            name=name,
            niche=niche,
            audience_summary=persona,
            experience_level="mixed",
            tone="educational and practical",
            authority_level=authority_level,
            educational_depth=educational_depth,  # type: ignore[arg-type]
            preferred_video_length_seconds=preferred_video_length_seconds,
            preferred_shorts_length_seconds=preferred_shorts_length_seconds,
            preferred_cta_style="educational",
            risk_tolerance=risk_tolerance,
            monetization_suitability="high",
            evergreen_ratio=evergreen_ratio,
            trend_ratio=trend_ratio,
            upload_frequency_per_week=frequency,
            playlist_strategy="clustered_series_by_topic",
            canonical_channel_id=channel_id,
        )

    return out


def build_generation_blueprint(
    *,
    channel_profile: ChannelProfile,
    audience_profile: AudienceProfile,
    topic_intent: TopicIntent,
    content_goal: ContentGoal,
    narrative_goal: NarrativeGoal,
    hook_goal: HookGoal,
    retention_goal: RetentionGoal,
    thumbnail_goal: ThumbnailGoal,
    seo_goal: SEOGoal,
    shorts_goal: ShortsGoal,
    discovery_goal: DiscoveryGoal,
    performance_expectation: PerformanceExpectation,
    blueprint_id: str,
    created_at: str | None = None,
) -> GenerationBlueprint:
    return GenerationBlueprint(
        schema_version=GENERATION_BLUEPRINT_SCHEMA_VERSION,
        blueprint_id=_require_non_empty("blueprint_id", blueprint_id),
        created_at=str(created_at or _now_iso()),
        channel_profile=channel_profile,
        audience_profile=audience_profile,
        topic_intent=topic_intent,
        content_goal=content_goal,
        narrative_goal=narrative_goal,
        hook_goal=hook_goal,
        retention_goal=retention_goal,
        thumbnail_goal=thumbnail_goal,
        seo_goal=seo_goal,
        shorts_goal=shorts_goal,
        discovery_goal=discovery_goal,
        performance_expectation=performance_expectation,
    )


def assert_blueprint_planning_consistency(blueprint: GenerationBlueprint) -> None:
    if blueprint.topic_intent.recommended_narrative_structure != blueprint.narrative_goal.narrative_template:
        raise ValueError("planning_inconsistency:narrative_template")

    if blueprint.topic_intent.expected_retention_style == "fast_paced" and blueprint.retention_goal.curiosity_refresh_interval_seconds > 45:
        raise ValueError("planning_inconsistency:retention_refresh_too_slow")

    if blueprint.content_goal.target_surface == "shorts_feed" and blueprint.shorts_goal.context_length_seconds > 25:
        raise ValueError("planning_inconsistency:shorts_context_too_long")

    if blueprint.content_goal.target_surface == "search" and "keyword" not in blueprint.seo_goal.keyword_strategy.lower():
        raise ValueError("planning_inconsistency:search_without_keyword_strategy")

    if blueprint.channel_profile.evergreen_ratio < blueprint.channel_profile.trend_ratio and blueprint.topic_intent.topic_kind == "evergreen":
        # Allowed but should not be impossible; no error.
        return


def evolve_blueprint_schema_v1_to_v1(payload: dict[str, Any]) -> dict[str, Any]:
    # Placeholder for explicit schema-evolution entrypoint used in tests.
    data = dict(payload or {})
    if "schema_version" not in data:
        data["schema_version"] = GENERATION_BLUEPRINT_SCHEMA_VERSION
    if "created_at" not in data:
        data["created_at"] = _now_iso()
    return data
