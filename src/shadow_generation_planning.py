from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

from .channel_capabilities import get_default_channel_capability_resolver
from .content_intelligence_foundation import (
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
)


SHADOW_GENERATION_PLANNING_SCHEMA_VERSION = "v1"
SHADOW_GENERATION_PLANNING_RESULTS_PATH = Path("logs/shadow_generation_planning.jsonl")

_CONTENT_TYPE = Literal["video", "short", "mixed"]

_SECRET_PATTERN = re.compile(
    r"(oauth|token|api[_-]?key|client[_-]?secret|refresh[_-]?token|access[_-]?token|cookie|password)",
    re.IGNORECASE,
)


class ShadowPlanningValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ShadowPlanningValidationError(f"missing_field:{name}")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise ShadowPlanningValidationError(f"invalid_datetime:{name}") from exc
    return text


def _bounded(value: str | None, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if _SECRET_PATTERN.search(text):
        raise ShadowPlanningValidationError("secret_like_content_detected")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _json_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _topic_kind_from_text(topic: str) -> str:
    text = str(topic or "").lower()
    if any(token in text for token in ["neden", "niye", "myth", "efsane", "dogru mu"]):
        return "myth_busting"
    if any(token in text for token in ["karsilastir", "vs", "mi", "fark"]):
        return "comparison"
    if any(token in text for token in ["acil", "uyari", "risk", "tehlike"]):
        return "warning"
    if any(token in text for token in ["guncel", "son", "breaking", "bugun"]):
        return "update"
    if any(token in text for token in ["rehber", "adim", "nasil", "tutorial"]):
        return "tutorial"
    if any(token in text for token in ["analiz", "degerlendirme"]):
        return "analysis"
    return "educational"


def _urgency_from_topic_kind(kind: str) -> str:
    if kind in {"breaking_news", "warning", "update", "trend"}:
        return "high"
    if kind in {"analysis", "comparison"}:
        return "medium"
    return "low"


def _retention_style_from_topic_kind(kind: str) -> str:
    if kind in {"breaking_news", "trend", "warning"}:
        return "fast_paced"
    if kind in {"analysis", "comparison"}:
        return "steady"
    return "slow_burn"


def _thumbnail_style_from_topic_kind(kind: str) -> str:
    if kind in {"warning", "breaking_news"}:
        return "warning"
    if kind in {"comparison"}:
        return "comparison"
    if kind in {"analysis"}:
        return "data_driven"
    return "authority"


def _narrative_template_from_topic_kind(kind: str) -> str:
    mapping = {
        "educational": "educational_lecture",
        "explanatory": "problem_solution",
        "comparison": "ranking",
        "breaking_news": "timeline",
        "analysis": "investigation",
        "myth_busting": "myth_reality",
        "tutorial": "checklist",
        "opinion": "story_driven",
        "evergreen": "problem_solution",
        "trend": "curiosity_loop",
        "warning": "mistake_driven",
        "update": "timeline",
    }
    return mapping.get(kind, "educational_lecture")


@dataclass(frozen=True)
class PlanningContext:
    schema_version: str
    run_id: str
    channel_id: str
    content_type: _CONTENT_TYPE
    topic: str
    requested_objective: str
    generation_timestamp: str
    capability_profile: dict[str, Any]
    channel_profile: ChannelProfile
    audience_profile: AudienceProfile

    def __post_init__(self) -> None:
        if self.schema_version != SHADOW_GENERATION_PLANNING_SCHEMA_VERSION:
            raise ShadowPlanningValidationError("invalid_field:schema_version")
        if not str(self.run_id or "").strip():
            raise ShadowPlanningValidationError("missing_field:run_id")
        if not str(self.channel_id or "").strip():
            raise ShadowPlanningValidationError("missing_field:channel_id")
        if self.content_type not in {"video", "short", "mixed"}:
            raise ShadowPlanningValidationError("invalid_field:content_type")
        _bounded(self.topic, limit=220)
        if not str(self.requested_objective or "").strip():
            raise ShadowPlanningValidationError("missing_field:requested_objective")
        _parse_iso("generation_timestamp", self.generation_timestamp)
        if not isinstance(self.capability_profile, dict):
            raise ShadowPlanningValidationError("invalid_field:capability_profile")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "channel_id": self.channel_id,
            "content_type": self.content_type,
            "topic": _bounded(self.topic, limit=220),
            "requested_objective": self.requested_objective,
            "generation_timestamp": self.generation_timestamp,
            "capability_profile": dict(self.capability_profile),
            "channel_profile": self.channel_profile.to_dict(),
            "audience_profile": self.audience_profile.to_dict(),
        }


@dataclass(frozen=True)
class ShadowPlanningStorageRow:
    schema_version: str
    run_id: str
    blueprint_id: str
    blueprint_hash: str
    channel_id: str
    content_type: str
    topic_excerpt: str
    requested_objective: str
    planning_schema_version: str
    blueprint_schema_version: str
    blueprint_valid: bool
    advisory_only: bool
    pipeline_output_changed: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_shadow_planning_storage_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ShadowPlanningValidationError("invalid_payload")

    required = [
        "schema_version",
        "run_id",
        "blueprint_id",
        "blueprint_hash",
        "channel_id",
        "content_type",
        "topic_excerpt",
        "requested_objective",
        "planning_schema_version",
        "blueprint_schema_version",
        "blueprint_valid",
        "advisory_only",
        "pipeline_output_changed",
        "created_at",
    ]
    for key in required:
        if key not in row:
            raise ShadowPlanningValidationError(f"missing_field:{key}")

    if str(row.get("schema_version") or "") != SHADOW_GENERATION_PLANNING_SCHEMA_VERSION:
        raise ShadowPlanningValidationError("invalid_field:schema_version")
    if str(row.get("planning_schema_version") or "") != CONTENT_INTELLIGENCE_SCHEMA_VERSION:
        raise ShadowPlanningValidationError("invalid_field:planning_schema_version")
    if str(row.get("blueprint_schema_version") or "") != GENERATION_BLUEPRINT_SCHEMA_VERSION:
        raise ShadowPlanningValidationError("invalid_field:blueprint_schema_version")

    _parse_iso("created_at", str(row.get("created_at") or ""))
    excerpt = _bounded(str(row.get("topic_excerpt") or ""), limit=140)

    normalized = dict(row)
    normalized["topic_excerpt"] = excerpt
    normalized["blueprint_valid"] = bool(normalized.get("blueprint_valid"))
    normalized["advisory_only"] = bool(normalized.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(normalized.get("pipeline_output_changed"))
    return normalized


def append_shadow_planning_row(
    row: dict[str, Any],
    *,
    output_path: Path | str = SHADOW_GENERATION_PLANNING_RESULTS_PATH,
) -> None:
    payload = validate_shadow_planning_storage_row(row)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, blob.encode("utf-8"))
    finally:
        os.close(fd)


def load_shadow_planning_rows(
    *,
    input_path: Path | str = SHADOW_GENERATION_PLANNING_RESULTS_PATH,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], int]:
    path = Path(input_path)
    if not path.exists():
        return [], 0

    rows: list[dict[str, Any]] = []
    malformed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
            rows.append(validate_shadow_planning_storage_row(decoded))
        except Exception:
            malformed += 1
            continue

    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed


def _build_audience_profile(channel_profile: ChannelProfile) -> AudienceProfile:
    return AudienceProfile(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        audience_id=f"aud_{channel_profile.channel_id}",
        primary_age_range="25-50",
        experience_level=channel_profile.experience_level,
        primary_motivation=f"Improve outcomes in {channel_profile.niche}",
        pain_points=["information overload", "inconsistent execution"],
        desired_outcomes=["clear decisions", "repeatable process"],
        language="tr",
    )


def build_planning_context(
    *,
    run_id: str,
    channel_id: str,
    content_type: _CONTENT_TYPE,
    topic: str,
    requested_objective: str,
    generation_timestamp: str,
) -> PlanningContext:
    resolver = get_default_channel_capability_resolver()
    capability = resolver.resolve(str(channel_id or "")).profile
    profiles = build_channel_profiles_from_registry()
    channel_profile = profiles.get(str(channel_id or ""))
    if channel_profile is None:
        channel_profile = ChannelProfile(
            schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
            channel_id=str(channel_id or "unknown"),
            name=str(channel_id or "Unknown Channel"),
            niche="general",
            audience_summary="general audience",
            experience_level="mixed",
            tone="educational",
            authority_level="medium",
            educational_depth="balanced",
            preferred_video_length_seconds=600,
            preferred_shorts_length_seconds=55,
            preferred_cta_style="educational",
            risk_tolerance="medium",
            monetization_suitability="medium",
            evergreen_ratio=0.6,
            trend_ratio=0.3,
            upload_frequency_per_week=7,
            playlist_strategy="clustered_series_by_topic",
            canonical_channel_id=str(channel_id or "unknown"),
        )
    audience_profile = _build_audience_profile(channel_profile)
    return PlanningContext(
        schema_version=SHADOW_GENERATION_PLANNING_SCHEMA_VERSION,
        run_id=str(run_id or ""),
        channel_id=str(channel_id or ""),
        content_type=content_type,
        topic=_bounded(topic, limit=220),
        requested_objective=str(requested_objective or "").strip(),
        generation_timestamp=_parse_iso("generation_timestamp", generation_timestamp),
        capability_profile={
            "standard_features": str(capability.standard_features.value),
            "intermediate_features": str(capability.intermediate_features.value),
            "advanced_features": str(capability.advanced_features.value),
            "source": str(capability.source),
        },
        channel_profile=channel_profile,
        audience_profile=audience_profile,
    )


def build_blueprint_from_context(context: PlanningContext) -> GenerationBlueprint:
    topic_kind = _topic_kind_from_text(context.topic)
    urgency = _urgency_from_topic_kind(topic_kind)
    retention_style = _retention_style_from_topic_kind(topic_kind)
    thumbnail_style = _thumbnail_style_from_topic_kind(topic_kind)
    narrative_template = _narrative_template_from_topic_kind(topic_kind)

    topic_intent = TopicIntent(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        topic_id=f"topic_{hashlib.sha1(context.topic.encode('utf-8')).hexdigest()[:10]}",
        topic_title=_bounded(context.topic, limit=140),
        topic_kind=topic_kind,  # type: ignore[arg-type]
        urgency=urgency,  # type: ignore[arg-type]
        expected_ctr_style="comparison" if topic_kind == "comparison" else "result_oriented",
        expected_retention_style=retention_style,  # type: ignore[arg-type]
        expected_thumbnail_style=thumbnail_style,  # type: ignore[arg-type]
        recommended_narrative_structure=narrative_template,  # type: ignore[arg-type]
    )

    content_goal = ContentGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        goal_id=f"goal_{context.run_id[:12]}",
        primary_outcome="Provide clear educational value",
        success_metric="avg_percentage_viewed",
        target_surface="shorts_feed" if context.content_type == "short" else "search",
        performance_horizon="mid_term",
    )

    hook_type = "warning" if topic_kind in {"warning", "breaking_news"} else "question"

    narrative_goal = NarrativeGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        narrative_template=narrative_template,  # type: ignore[arg-type]
        structure_notes="deterministic planning-only narrative scaffold",
        psychological_strategy="reduce uncertainty through structured explanation",
        expected_payoff_window_seconds=160 if context.content_type == "short" else 220,
    )

    hook_goal = HookGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        hook_type=hook_type,  # type: ignore[arg-type]
        psychological_intent="capture attention without altering runtime prompt",
        ideal_audience=context.channel_profile.experience_level,
        estimated_retention_objective="increase first 30 second retention",
    )

    refresh = 30 if retention_style == "fast_paced" else 45
    retention_goal = RetentionGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        opening_plan="establish value in first beats",
        first_30_seconds_plan="state outcome and framing",
        curiosity_refresh_interval_seconds=refresh,
        payoff_timing_seconds=35 if context.content_type == "short" else 210,
        cta_timing_seconds=45 if context.content_type == "short" else 420,
        ending_plan="summarize and bridge to next topic",
    )

    thumbnail_goal = ThumbnailGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        emotional_emphasis="medium",
        facial_emphasis="low",
        object_emphasis="high",
        contrast_level="high",
        information_density="balanced",
        text_length_target=4,
        curiosity_level="medium",
        urgency_level="high" if urgency == "high" else "medium",
        trust_signal_level="high",
        authority_signal_level="high" if context.channel_profile.authority_level == "high" else "medium",
    )

    seo_goal = SEOGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        title_objective="clear value proposition",
        keyword_strategy=f"keyword strategy for {context.channel_profile.niche}",
        search_intent="informational + practical intent",
        browse_intent="adjacent educational recommendations",
        suggested_traffic_objective="connect to related series",
        playlist_relevance_plan=context.channel_profile.playlist_strategy,
        tag_relevance_plan="high intent, low noise",
        hashtag_strategy="concise and topic-consistent",
    )

    shorts_goal = ShortsGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        clip_objective="deliver concise high-clarity takeaway",
        hook_type=hook_type,  # type: ignore[arg-type]
        context_length_seconds=12 if context.content_type == "short" else 20,
        payoff_timing_seconds=28,
        ending_style="cta_bridge",
        looping_suitability="medium",
        continuation_suitability="high",
    )

    discovery_goal = DiscoveryGoal(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        primary_surface="shorts_feed" if context.content_type == "short" else "search",
        secondary_surfaces=["browse", "suggested"],
        playlist_strategy=context.channel_profile.playlist_strategy,
        cards_strategy="bridge_to_related_topic",
        end_screen_strategy="next_logical_step",
    )

    performance = PerformanceExpectation(
        schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        expected_ctr=0.08,
        expected_average_view_duration_seconds=35.0 if context.content_type == "short" else 240.0,
        expected_average_percentage_viewed=0.68 if context.content_type == "short" else 0.42,
        expected_shorts_completion_rate=0.72,
        target_kpi="avg_percentage_viewed",
    )

    blueprint_id = "bp_" + hashlib.sha256(
        "|".join([
            context.run_id,
            context.channel_id,
            context.content_type,
            context.topic,
            context.requested_objective,
        ]).encode("utf-8")
    ).hexdigest()[:24]

    blueprint = build_generation_blueprint(
        channel_profile=context.channel_profile,
        audience_profile=context.audience_profile,
        topic_intent=topic_intent,
        content_goal=content_goal,
        narrative_goal=narrative_goal,
        hook_goal=hook_goal,
        retention_goal=retention_goal,
        thumbnail_goal=thumbnail_goal,
        seo_goal=seo_goal,
        shorts_goal=shorts_goal,
        discovery_goal=discovery_goal,
        performance_expectation=performance,
        blueprint_id=blueprint_id,
        created_at=context.generation_timestamp,
    )
    assert_blueprint_planning_consistency(blueprint)
    return blueprint


def build_shadow_generation_planning_artifact(
    *,
    run_id: str,
    channel_id: str,
    content_type: _CONTENT_TYPE,
    topic: str,
    requested_objective: str,
    generation_timestamp: str,
    storage_path: Path | str = SHADOW_GENERATION_PLANNING_RESULTS_PATH,
) -> dict[str, Any]:
    context = build_planning_context(
        run_id=run_id,
        channel_id=channel_id,
        content_type=content_type,
        topic=topic,
        requested_objective=requested_objective,
        generation_timestamp=generation_timestamp,
    )
    blueprint = build_blueprint_from_context(context)
    blueprint_payload = blueprint.to_dict()
    blueprint_hash = _json_hash(blueprint_payload)

    row = ShadowPlanningStorageRow(
        schema_version=SHADOW_GENERATION_PLANNING_SCHEMA_VERSION,
        run_id=context.run_id,
        blueprint_id=blueprint.blueprint_id,
        blueprint_hash=blueprint_hash,
        channel_id=context.channel_id,
        content_type=context.content_type,
        topic_excerpt=_bounded(context.topic, limit=120),
        requested_objective=context.requested_objective,
        planning_schema_version=CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        blueprint_schema_version=GENERATION_BLUEPRINT_SCHEMA_VERSION,
        blueprint_valid=True,
        advisory_only=True,
        pipeline_output_changed=False,
        created_at=_now_iso(),
    )
    append_shadow_planning_row(row.to_dict(), output_path=storage_path)

    return {
        "enabled": True,
        "mode": "advisory",
        "schema_version": SHADOW_GENERATION_PLANNING_SCHEMA_VERSION,
        "planning_schema_version": CONTENT_INTELLIGENCE_SCHEMA_VERSION,
        "blueprint_schema_version": GENERATION_BLUEPRINT_SCHEMA_VERSION,
        "run_id": context.run_id,
        "blueprint_id": blueprint.blueprint_id,
        "blueprint_hash": blueprint_hash,
        "channel_id": context.channel_id,
        "content_type": context.content_type,
        "topic_excerpt": _bounded(context.topic, limit=120),
        "requested_objective": context.requested_objective,
        "validation": {"valid": True, "error": None},
        "pipeline_output_changed": False,
        "context": context.to_dict(),
        "blueprint": blueprint_payload,
        "results_path": str(storage_path),
    }
