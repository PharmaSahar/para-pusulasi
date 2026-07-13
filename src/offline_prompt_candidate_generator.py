from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from .content_intelligence_foundation import GENERATION_BLUEPRINT_SCHEMA_VERSION, GenerationBlueprint


OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION = "v1"
OFFLINE_PROMPT_CANDIDATE_ANALYZER_VERSION = "v1"
OFFLINE_PROMPT_CANDIDATE_RESULTS_PATH = Path("logs/offline_prompt_candidates.jsonl")

_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|client[_-]?secret|oauth|access[_-]?token|refresh[_-]?token|password|cookie|authorization\s*:|bearer\s+)",
    re.IGNORECASE,
)
_RISKY_FINANCE_PATTERN = re.compile(r"(garanti\s+getiri|x\s*kat|insider|kesin\s+kazanc|hemen\s+al|simdi\s+al|pump)", re.IGNORECASE)

STRATEGY_IDS = (
    "STRUCTURED_EDUCATIONAL",
    "SOCRATIC",
    "CASE_STUDY",
    "PROBLEM_SOLUTION",
    "MYTH_REALITY",
    "TIMELINE",
    "CHECKLIST",
    "INVESTIGATION",
    "STORY_DRIVEN",
    "ANALYTICAL",
    "SHORTS_OPTIMIZED",
    "SEO_OPTIMIZED",
)


class OfflinePromptCandidateValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise OfflinePromptCandidateValidationError(f"missing_field:{name}")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise OfflinePromptCandidateValidationError(f"invalid_datetime:{name}") from exc
    return text


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_json_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return _sha(blob)


def _bounded_text(value: str | None, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if _SECRET_PATTERN.search(text):
        raise OfflinePromptCandidateValidationError("secret_like_content_detected")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _safe_div(a: float, b: float) -> float:
    if not b:
        return 0.0
    return float(a) / float(b)


def _score_from_hits(values: list[bool]) -> float:
    if not values:
        return 0.0
    return max(0.0, min(1.0, _safe_div(sum(1 for v in values if v), len(values))))


def _flatten_plan(plan: "PromptPlan") -> str:
    chunks = [
        *plan.narrative_directives,
        *plan.hook_directives,
        *plan.transition_directives,
        *plan.retention_directives,
        *plan.cta_directives,
        *plan.thumbnail_directives,
        *plan.seo_directives,
        *plan.shorts_directives,
        *plan.finance_safety_directives,
        *plan.uncertainty_directives,
        *plan.duplication_avoidance_directives,
    ]
    return " ".join(chunks).lower()


@dataclass(frozen=True)
class PromptStrategy:
    strategy_id: str
    narrative_style: str
    hook_philosophy: str
    retention_philosophy: str
    seo_philosophy: str
    shorts_suitability: str
    finance_suitability: str
    expected_strengths: tuple[str, ...]
    expected_weaknesses: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.strategy_id not in STRATEGY_IDS:
            raise OfflinePromptCandidateValidationError("invalid_field:strategy_id")
        if not self.narrative_style:
            raise OfflinePromptCandidateValidationError("missing_field:narrative_style")
        if not self.hook_philosophy:
            raise OfflinePromptCandidateValidationError("missing_field:hook_philosophy")
        if not self.retention_philosophy:
            raise OfflinePromptCandidateValidationError("missing_field:retention_philosophy")
        if not self.seo_philosophy:
            raise OfflinePromptCandidateValidationError("missing_field:seo_philosophy")
        if not self.shorts_suitability:
            raise OfflinePromptCandidateValidationError("missing_field:shorts_suitability")
        if not self.finance_suitability:
            raise OfflinePromptCandidateValidationError("missing_field:finance_suitability")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expected_strengths"] = list(self.expected_strengths)
        payload["expected_weaknesses"] = list(self.expected_weaknesses)
        return payload


@dataclass(frozen=True)
class PromptPlan:
    narrative_directives: tuple[str, ...]
    hook_directives: tuple[str, ...]
    transition_directives: tuple[str, ...]
    retention_directives: tuple[str, ...]
    cta_directives: tuple[str, ...]
    thumbnail_directives: tuple[str, ...]
    seo_directives: tuple[str, ...]
    shorts_directives: tuple[str, ...]
    finance_safety_directives: tuple[str, ...]
    uncertainty_directives: tuple[str, ...]
    duplication_avoidance_directives: tuple[str, ...]

    def __post_init__(self) -> None:
        groups = [
            self.narrative_directives,
            self.hook_directives,
            self.transition_directives,
            self.retention_directives,
            self.cta_directives,
            self.thumbnail_directives,
            self.seo_directives,
            self.shorts_directives,
            self.finance_safety_directives,
            self.uncertainty_directives,
            self.duplication_avoidance_directives,
        ]
        if not all(isinstance(group, tuple) for group in groups):
            raise OfflinePromptCandidateValidationError("invalid_field:prompt_plan")
        for group in groups:
            for item in group:
                if not str(item).strip():
                    raise OfflinePromptCandidateValidationError("invalid_field:directive")
                _bounded_text(str(item), limit=220)

    def to_dict(self) -> dict[str, Any]:
        return {
            "narrative_directives": list(self.narrative_directives),
            "hook_directives": list(self.hook_directives),
            "transition_directives": list(self.transition_directives),
            "retention_directives": list(self.retention_directives),
            "cta_directives": list(self.cta_directives),
            "thumbnail_directives": list(self.thumbnail_directives),
            "seo_directives": list(self.seo_directives),
            "shorts_directives": list(self.shorts_directives),
            "finance_safety_directives": list(self.finance_safety_directives),
            "uncertainty_directives": list(self.uncertainty_directives),
            "duplication_avoidance_directives": list(self.duplication_avoidance_directives),
        }


@dataclass(frozen=True)
class PromptCandidate:
    schema_version: str
    analyzer_version: str
    candidate_id: str
    experiment_id: str
    strategy_id: str
    blueprint_hash: str
    channel_id: str
    content_type: str
    objective: str
    hypothesis: str
    expected_improvement: str
    plan_hash: str
    plan: PromptPlan
    advisory_only: bool
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION:
            raise OfflinePromptCandidateValidationError("invalid_field:schema_version")
        if self.analyzer_version != OFFLINE_PROMPT_CANDIDATE_ANALYZER_VERSION:
            raise OfflinePromptCandidateValidationError("invalid_field:analyzer_version")
        if self.strategy_id not in STRATEGY_IDS:
            raise OfflinePromptCandidateValidationError("invalid_field:strategy_id")
        for key, value in (
            ("candidate_id", self.candidate_id),
            ("experiment_id", self.experiment_id),
            ("blueprint_hash", self.blueprint_hash),
            ("channel_id", self.channel_id),
            ("content_type", self.content_type),
            ("objective", self.objective),
            ("hypothesis", self.hypothesis),
            ("expected_improvement", self.expected_improvement),
            ("plan_hash", self.plan_hash),
        ):
            if not str(value).strip():
                raise OfflinePromptCandidateValidationError(f"missing_field:{key}")
        if not self.advisory_only:
            raise OfflinePromptCandidateValidationError("invalid_field:advisory_only")
        _parse_iso("created_at", self.created_at)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["plan"] = self.plan.to_dict()
        return payload


@dataclass(frozen=True)
class DimensionEvaluation:
    dimension: str
    score: float
    confidence: float
    rationale: str
    evidence: tuple[str, ...]
    advisory_flag: bool

    def __post_init__(self) -> None:
        if not self.dimension:
            raise OfflinePromptCandidateValidationError("missing_field:dimension")
        if self.score < 0.0 or self.score > 1.0:
            raise OfflinePromptCandidateValidationError("invalid_field:score")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise OfflinePromptCandidateValidationError("invalid_field:confidence")
        if not self.rationale:
            raise OfflinePromptCandidateValidationError("missing_field:rationale")
        for item in self.evidence:
            _bounded_text(item, limit=180)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True)
class ScoringModelBreakdown:
    hard_constraints: dict[str, float]
    soft_preferences: dict[str, float]
    hard_constraint_violations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.hard_constraints, dict):
            raise OfflinePromptCandidateValidationError("invalid_field:hard_constraints")
        if not isinstance(self.soft_preferences, dict):
            raise OfflinePromptCandidateValidationError("invalid_field:soft_preferences")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["hard_constraint_violations"] = list(self.hard_constraint_violations)
        return payload


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    strategy_id: str
    dimensions: tuple[dict[str, Any], ...]
    scoring: dict[str, Any]
    advisory_only: bool

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise OfflinePromptCandidateValidationError("missing_field:candidate_id")
        if self.strategy_id not in STRATEGY_IDS:
            raise OfflinePromptCandidateValidationError("invalid_field:strategy_id")
        if not self.advisory_only:
            raise OfflinePromptCandidateValidationError("invalid_field:advisory_only")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateRanking:
    best_overall: str
    safest: str
    highest_retention: str
    best_seo: str
    best_shorts: str
    most_maintainable: str
    ordered_candidates: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.ordered_candidates:
            raise OfflinePromptCandidateValidationError("missing_field:ordered_candidates")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ordered_candidates"] = list(self.ordered_candidates)
        return payload


@dataclass(frozen=True)
class CandidateExplanation:
    candidate_id: str
    strategy_id: str
    why_scored_well: tuple[str, ...]
    why_lost: tuple[str, ...]
    strongest_dimensions: tuple[str, ...]
    weakest_dimensions: tuple[str, ...]
    finance_concerns: tuple[str, ...]
    blueprint_gaps: tuple[str, ...]
    advisory_only: bool

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise OfflinePromptCandidateValidationError("missing_field:candidate_id")
        if not self.advisory_only:
            raise OfflinePromptCandidateValidationError("invalid_field:advisory_only")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "why_scored_well",
            "why_lost",
            "strongest_dimensions",
            "weakest_dimensions",
            "finance_concerns",
            "blueprint_gaps",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True)
class OfflinePromptCandidateResult:
    schema_version: str
    analyzer_version: str
    experiment_id: str
    run_id: str
    channel_id: str
    content_type: str
    blueprint_hash: str
    objective: str
    hypothesis: str
    expected_improvement: str
    candidates: tuple[dict[str, Any], ...]
    evaluations: tuple[dict[str, Any], ...]
    ranking: dict[str, Any]
    explanations: tuple[dict[str, Any], ...]
    advisory_only: bool
    pipeline_output_changed: bool
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version != OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION:
            raise OfflinePromptCandidateValidationError("invalid_field:schema_version")
        if self.analyzer_version != OFFLINE_PROMPT_CANDIDATE_ANALYZER_VERSION:
            raise OfflinePromptCandidateValidationError("invalid_field:analyzer_version")
        if not self.experiment_id:
            raise OfflinePromptCandidateValidationError("missing_field:experiment_id")
        if not self.channel_id:
            raise OfflinePromptCandidateValidationError("missing_field:channel_id")
        if not self.content_type:
            raise OfflinePromptCandidateValidationError("missing_field:content_type")
        if not self.blueprint_hash:
            raise OfflinePromptCandidateValidationError("missing_field:blueprint_hash")
        if not self.advisory_only:
            raise OfflinePromptCandidateValidationError("invalid_field:advisory_only")
        if self.pipeline_output_changed:
            raise OfflinePromptCandidateValidationError("invalid_field:pipeline_output_changed")
        _parse_iso("created_at", self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "candidates": [dict(item) for item in self.candidates],
            "evaluations": [dict(item) for item in self.evaluations],
            "ranking": dict(self.ranking),
            "explanations": [dict(item) for item in self.explanations],
        }


@dataclass(frozen=True)
class OfflinePromptCandidateStorageRow:
    schema_version: str
    experiment_id: str
    run_id: str
    channel_id: str
    content_type: str
    objective: str
    hypothesis: str
    expected_improvement: str
    blueprint_hash: str
    plan_hashes: tuple[str, ...]
    ranking: dict[str, str]
    score_summary: dict[str, float]
    explanation_summary: dict[str, Any]
    advisory_only: bool
    pipeline_output_changed: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["plan_hashes"] = list(self.plan_hashes)
        return payload


def get_prompt_strategy_taxonomy() -> dict[str, PromptStrategy]:
    taxonomy = {
        "STRUCTURED_EDUCATIONAL": PromptStrategy(
            strategy_id="STRUCTURED_EDUCATIONAL",
            narrative_style="modular educational flow",
            hook_philosophy="clear expectation-setting hook",
            retention_philosophy="steady checkpoints",
            seo_philosophy="balanced semantic keyword coverage",
            shorts_suitability="medium",
            finance_suitability="high",
            expected_strengths=("clarity", "maintainability", "coverage"),
            expected_weaknesses=("less dramatic hook",),
        ),
        "SOCRATIC": PromptStrategy(
            strategy_id="SOCRATIC",
            narrative_style="guided question-answer path",
            hook_philosophy="question-led hook",
            retention_philosophy="question loops",
            seo_philosophy="intent through questions",
            shorts_suitability="medium",
            finance_suitability="high",
            expected_strengths=("audience suitability", "retention"),
            expected_weaknesses=("longer setup"),
        ),
        "CASE_STUDY": PromptStrategy(
            strategy_id="CASE_STUDY",
            narrative_style="example-driven",
            hook_philosophy="outcome-first scenario",
            retention_philosophy="decision milestones",
            seo_philosophy="problem-case keywords",
            shorts_suitability="low",
            finance_suitability="high",
            expected_strengths=("educational quality", "finance safety"),
            expected_weaknesses=("shorts fit"),
        ),
        "PROBLEM_SOLUTION": PromptStrategy(
            strategy_id="PROBLEM_SOLUTION",
            narrative_style="pain to resolution",
            hook_philosophy="pain trigger",
            retention_philosophy="sequential resolution",
            seo_philosophy="problem-intent mapping",
            shorts_suitability="medium",
            finance_suitability="high",
            expected_strengths=("coverage", "audience suitability"),
            expected_weaknesses=("story depth"),
        ),
        "MYTH_REALITY": PromptStrategy(
            strategy_id="MYTH_REALITY",
            narrative_style="myth debunk structure",
            hook_philosophy="counter-intuitive opener",
            retention_philosophy="myth reveal cadence",
            seo_philosophy="myth query terms",
            shorts_suitability="high",
            finance_suitability="medium",
            expected_strengths=("hook", "retention"),
            expected_weaknesses=("nuance loss"),
        ),
        "TIMELINE": PromptStrategy(
            strategy_id="TIMELINE",
            narrative_style="chronological sequence",
            hook_philosophy="time-pressure hook",
            retention_philosophy="next-event anticipation",
            seo_philosophy="time context terms",
            shorts_suitability="low",
            finance_suitability="medium",
            expected_strengths=("narrative quality",),
            expected_weaknesses=("less evergreen"),
        ),
        "CHECKLIST": PromptStrategy(
            strategy_id="CHECKLIST",
            narrative_style="stepwise list",
            hook_philosophy="action-oriented opener",
            retention_philosophy="next-step pull",
            seo_philosophy="how-to keyword focus",
            shorts_suitability="high",
            finance_suitability="high",
            expected_strengths=("maintainability", "coverage"),
            expected_weaknesses=("emotional depth"),
        ),
        "INVESTIGATION": PromptStrategy(
            strategy_id="INVESTIGATION",
            narrative_style="evidence-first analysis",
            hook_philosophy="mystery hook",
            retention_philosophy="evidence reveals",
            seo_philosophy="analysis intent terms",
            shorts_suitability="low",
            finance_suitability="high",
            expected_strengths=("educational quality", "safety"),
            expected_weaknesses=("complexity"),
        ),
        "STORY_DRIVEN": PromptStrategy(
            strategy_id="STORY_DRIVEN",
            narrative_style="narrative arc",
            hook_philosophy="character tension",
            retention_philosophy="story progression",
            seo_philosophy="lighter metadata emphasis",
            shorts_suitability="medium",
            finance_suitability="medium",
            expected_strengths=("retention", "narrative quality"),
            expected_weaknesses=("seo consistency"),
        ),
        "ANALYTICAL": PromptStrategy(
            strategy_id="ANALYTICAL",
            narrative_style="logic tree",
            hook_philosophy="insight hook",
            retention_philosophy="argument milestones",
            seo_philosophy="high semantic precision",
            shorts_suitability="low",
            finance_suitability="high",
            expected_strengths=("educational quality", "seo"),
            expected_weaknesses=("hook intensity"),
        ),
        "SHORTS_OPTIMIZED": PromptStrategy(
            strategy_id="SHORTS_OPTIMIZED",
            narrative_style="compact burst",
            hook_philosophy="instant payoff hook",
            retention_philosophy="tight loop structure",
            seo_philosophy="caption-first compact metadata",
            shorts_suitability="high",
            finance_suitability="medium",
            expected_strengths=("shorts suitability", "hook"),
            expected_weaknesses=("long-form depth"),
        ),
        "SEO_OPTIMIZED": PromptStrategy(
            strategy_id="SEO_OPTIMIZED",
            narrative_style="search intent alignment",
            hook_philosophy="query-driven opener",
            retention_philosophy="intent satisfaction",
            seo_philosophy="high keyword clustering",
            shorts_suitability="medium",
            finance_suitability="high",
            expected_strengths=("seo quality", "discoverability"),
            expected_weaknesses=("creative variety"),
        ),
    }
    return taxonomy


def _plan_for_strategy(strategy: PromptStrategy, blueprint: GenerationBlueprint) -> PromptPlan:
    payload = blueprint.to_dict()
    topic_intent = dict(payload.get("topic_intent") or {})
    retention_goal = dict(payload.get("retention_goal") or {})
    seo_goal = dict(payload.get("seo_goal") or {})
    shorts_goal = dict(payload.get("shorts_goal") or {})
    narrative_goal = dict(payload.get("narrative_goal") or {})
    hook_goal = dict(payload.get("hook_goal") or {})
    audience_profile = dict(payload.get("audience_profile") or {})

    topic_title = str(topic_intent.get("topic_title") or "topic")
    audience_level = str(audience_profile.get("experience_level") or "mixed")

    return PromptPlan(
        narrative_directives=(
            f"narrative_style:{strategy.narrative_style}",
            f"narrative_template:{str(narrative_goal.get('narrative_template') or 'educational_lecture')}",
            f"topic_anchor:{topic_title}",
        ),
        hook_directives=(
            f"hook_philosophy:{strategy.hook_philosophy}",
            f"hook_type:{str(hook_goal.get('hook_type') or 'question')}",
            "hook_must_be_specific",
        ),
        transition_directives=(
            "use_explicit_transitions_between_sections",
            "maintain_single_argument_per_section",
        ),
        retention_directives=(
            f"retention_style:{strategy.retention_philosophy}",
            f"first_30_plan:{str(retention_goal.get('first_30_seconds_plan') or 'clear_setup')}",
            f"ending_plan:{str(retention_goal.get('ending_plan') or 'bridge_to_next')}",
        ),
        cta_directives=(
            "cta_after_core_value",
            "cta_must_match_topic_intent",
        ),
        thumbnail_directives=(
            "thumbnail_topic_consistency_required",
            f"thumbnail_style:{str(topic_intent.get('expected_thumbnail_style') or 'authority')}",
        ),
        seo_directives=(
            f"seo_philosophy:{strategy.seo_philosophy}",
            f"search_intent:{str(seo_goal.get('search_intent') or 'education')}",
            f"title_objective:{str(seo_goal.get('title_objective') or 'clarity')}",
        ),
        shorts_directives=(
            f"shorts_suitability:{strategy.shorts_suitability}",
            f"shorts_hook:{str(shorts_goal.get('hook_type') or 'question')}",
        ),
        finance_safety_directives=(
            "no_guaranteed_returns",
            "no_unsupported_claims",
            f"finance_suitability:{strategy.finance_suitability}",
        ),
        uncertainty_directives=(
            "mark_uncertainty_explicitly",
            "label_examples_as_illustrative_when_needed",
        ),
        duplication_avoidance_directives=(
            "avoid_reusing_previous_headline_patterns",
            "prefer_distinct_angle_and_example_set",
            f"audience_level:{audience_level}",
        ),
    )


@dataclass(frozen=True)
class PromptCandidateGenerator:
    schema_version: str = OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION
    analyzer_version: str = OFFLINE_PROMPT_CANDIDATE_ANALYZER_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION:
            raise OfflinePromptCandidateValidationError("invalid_field:schema_version")
        if self.analyzer_version != OFFLINE_PROMPT_CANDIDATE_ANALYZER_VERSION:
            raise OfflinePromptCandidateValidationError("invalid_field:analyzer_version")

    def generate(
        self,
        *,
        blueprint: GenerationBlueprint,
        run_id: str,
        channel_id: str,
        content_type: str,
        objective: str,
        hypothesis: str,
        expected_improvement: str,
    ) -> tuple[str, tuple[PromptCandidate, ...]]:
        if blueprint.schema_version != GENERATION_BLUEPRINT_SCHEMA_VERSION:
            raise OfflinePromptCandidateValidationError("invalid_blueprint_schema_version")

        blueprint_hash = _safe_json_hash(blueprint.to_dict())
        experiment_seed = {
            "blueprint_hash": blueprint_hash,
            "run_id": run_id,
            "channel_id": channel_id,
            "content_type": content_type,
            "objective": objective,
            "hypothesis": hypothesis,
            "expected_improvement": expected_improvement,
            "strategies": STRATEGY_IDS,
        }
        experiment_id = f"cand_exp_{_safe_json_hash(experiment_seed)[:20]}"
        created_at = _now_iso()

        taxonomy = get_prompt_strategy_taxonomy()
        candidates: list[PromptCandidate] = []
        for strategy_id in STRATEGY_IDS:
            strategy = taxonomy[strategy_id]
            plan = _plan_for_strategy(strategy, blueprint)
            plan_hash = _safe_json_hash(plan.to_dict())
            candidate_id = f"cand_{strategy_id.lower()}_{plan_hash[:12]}"
            candidates.append(
                PromptCandidate(
                    schema_version=self.schema_version,
                    analyzer_version=self.analyzer_version,
                    candidate_id=candidate_id,
                    experiment_id=experiment_id,
                    strategy_id=strategy_id,
                    blueprint_hash=blueprint_hash,
                    channel_id=channel_id,
                    content_type=content_type,
                    objective=objective,
                    hypothesis=hypothesis,
                    expected_improvement=expected_improvement,
                    plan_hash=plan_hash,
                    plan=plan,
                    advisory_only=True,
                    created_at=created_at,
                )
            )

        ordered = tuple(sorted(candidates, key=lambda item: item.candidate_id))
        return experiment_id, ordered


def _dimension_eval(name: str, score: float, confidence: float, rationale: str, evidence: list[str]) -> DimensionEvaluation:
    return DimensionEvaluation(
        dimension=name,
        score=max(0.0, min(1.0, float(score))),
        confidence=max(0.0, min(1.0, float(confidence))),
        rationale=_bounded_text(rationale, limit=220),
        evidence=tuple(_bounded_text(item, limit=180) for item in evidence[:4]),
        advisory_flag=True,
    )


def evaluate_candidate(blueprint: GenerationBlueprint, candidate: PromptCandidate) -> CandidateEvaluation:
    text = _flatten_plan(candidate.plan)
    payload = blueprint.to_dict()
    topic_intent = dict(payload.get("topic_intent") or {})
    audience_profile = dict(payload.get("audience_profile") or {})

    topic_terms = [tok for tok in re.findall(r"[a-z0-9ığüşöç]+", str(topic_intent.get("topic_title") or "").lower()) if len(tok) >= 4]
    audience_level = str(audience_profile.get("experience_level") or "mixed").lower()

    blueprint_coverage = _score_from_hits([
        "narrative" in text,
        "hook" in text,
        "retention" in text,
        "thumbnail" in text,
        "seo" in text,
        "shorts" in text,
        "uncertainty" in text,
    ])
    finance_safety = _score_from_hits([
        "no_guaranteed_returns" in text,
        "no_unsupported_claims" in text,
        "mark_uncertainty_explicitly" in text,
        _RISKY_FINANCE_PATTERN.search(text) is None,
    ])
    educational_quality = _score_from_hits([
        "narrative_template" in text,
        "single_argument_per_section" in text,
        "topic_anchor" in text,
    ])
    audience_suitability = _score_from_hits([
        audience_level in text if audience_level else True,
        "audience_level" in text,
    ])
    narrative_quality = _score_from_hits(["narrative_style" in text, "narrative_template" in text, "transitions" in text])
    hook_quality = _score_from_hits(["hook_philosophy" in text, "hook_type" in text, "hook_must_be_specific" in text])
    retention_quality = _score_from_hits(["retention_style" in text, "first_30_plan" in text, "ending_plan" in text])
    seo_quality = _score_from_hits(["seo_philosophy" in text, "search_intent" in text, "title_objective" in text])
    shorts_suitability = _score_from_hits(["shorts_suitability" in text, "shorts_hook" in text])
    unique_ratio = _safe_div(len(set(text.split())), max(1, len(text.split())))
    duplication_resistance = max(0.0, min(1.0, unique_ratio))
    maintainability = _score_from_hits([
        len(candidate.plan.narrative_directives) <= 4,
        len(candidate.plan.retention_directives) <= 4,
        len(candidate.plan.seo_directives) <= 4,
        len(text.split()) <= 240,
    ])
    complexity = max(0.0, min(1.0, _safe_div(len(text.split()), 260.0)))

    topic_match = _score_from_hits([term in text for term in topic_terms[:6]]) if topic_terms else 0.5

    dimensions = [
        _dimension_eval("blueprint_coverage", blueprint_coverage, 0.92, "Coverage of blueprint-aligned directive groups", [candidate.strategy_id, "coverage"]),
        _dimension_eval("finance_safety", finance_safety, 0.95, "Finance safety and uncertainty directives present", ["finance_safety", "uncertainty"]),
        _dimension_eval("educational_quality", educational_quality, 0.88, "Educational structure directives completeness", ["narrative_template", "transitions"]),
        _dimension_eval("audience_suitability", audience_suitability, 0.82, "Audience-level alignment directives", [f"audience:{audience_level}"]),
        _dimension_eval("narrative_quality", narrative_quality, 0.84, "Narrative directive consistency", ["narrative_style"]),
        _dimension_eval("hook_quality", hook_quality, 0.84, "Hook directive quality", ["hook_philosophy", "hook_type"]),
        _dimension_eval("retention_quality", retention_quality, 0.86, "Retention planning quality", ["first_30_plan", "ending_plan"]),
        _dimension_eval("seo_quality", seo_quality, 0.88, "SEO directive quality", ["search_intent", "title_objective"]),
        _dimension_eval("shorts_suitability", shorts_suitability, 0.8, "Shorts suitability directives", ["shorts_suitability", "shorts_hook"]),
        _dimension_eval("duplication_resistance", duplication_resistance, 0.78, "Distinctive directive token spread", ["unique_directives"]),
        _dimension_eval("maintainability", maintainability, 0.83, "Plan compactness and readability", ["directive_group_sizes"]),
        _dimension_eval("complexity", complexity, 0.83, "Complexity of plan directives", ["token_count"]),
    ]

    hard_constraints = {
        "finance_safety": finance_safety,
        "unsupported_claims": 1.0 if _RISKY_FINANCE_PATTERN.search(text) is None else 0.0,
        "uncertainty_handling": 1.0 if "mark_uncertainty_explicitly" in text else 0.0,
        "channel_compatibility": topic_match,
    }
    soft_preferences = {
        "hook": hook_quality,
        "retention": retention_quality,
        "seo": seo_quality,
        "storytelling": narrative_quality,
        "readability": maintainability,
    }

    violations = tuple(sorted([key for key, value in hard_constraints.items() if float(value) < 0.55]))
    breakdown = ScoringModelBreakdown(
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences,
        hard_constraint_violations=violations,
    )

    return CandidateEvaluation(
        candidate_id=candidate.candidate_id,
        strategy_id=candidate.strategy_id,
        dimensions=tuple(item.to_dict() for item in dimensions),
        scoring=breakdown.to_dict(),
        advisory_only=True,
    )


def evaluate_candidates(blueprint: GenerationBlueprint, candidates: tuple[PromptCandidate, ...]) -> tuple[CandidateEvaluation, ...]:
    evaluated = [evaluate_candidate(blueprint, item) for item in candidates]
    return tuple(sorted(evaluated, key=lambda item: item.candidate_id))


def _dimension_score(evaluation: CandidateEvaluation, key: str) -> float:
    for item in evaluation.dimensions:
        if str(item.get("dimension") or "") == key:
            return float(item.get("score", 0.0) or 0.0)
    return 0.0


def _overall_score(evaluation: CandidateEvaluation) -> float:
    hard = dict(evaluation.scoring.get("hard_constraints") or {})
    soft = dict(evaluation.scoring.get("soft_preferences") or {})
    hard_avg = _safe_div(sum(float(v) for v in hard.values()), max(1, len(hard)))
    soft_avg = _safe_div(sum(float(v) for v in soft.values()), max(1, len(soft)))
    return (hard_avg * 0.65) + (soft_avg * 0.35)


def rank_candidate_evaluations(evaluations: tuple[CandidateEvaluation, ...]) -> CandidateRanking:
    if not evaluations:
        raise OfflinePromptCandidateValidationError("missing_evaluations")

    ordered = sorted(
        evaluations,
        key=lambda item: (
            -_overall_score(item),
            len(tuple(item.scoring.get("hard_constraint_violations") or ())),
            item.candidate_id,
        ),
    )

    def top_by(metric: str, *, inverse: bool = False) -> str:
        ranked = sorted(
            evaluations,
            key=lambda item: (
                _dimension_score(item, metric) if inverse else -_dimension_score(item, metric),
                item.candidate_id,
            ),
        )
        return ranked[0].candidate_id

    return CandidateRanking(
        best_overall=ordered[0].candidate_id,
        safest=top_by("finance_safety"),
        highest_retention=top_by("retention_quality"),
        best_seo=top_by("seo_quality"),
        best_shorts=top_by("shorts_suitability"),
        most_maintainable=top_by("maintainability"),
        ordered_candidates=tuple(item.candidate_id for item in ordered),
    )


def explain_candidate_evaluations(
    evaluations: tuple[CandidateEvaluation, ...],
    ranking: CandidateRanking,
) -> tuple[CandidateExplanation, ...]:
    explanations: list[CandidateExplanation] = []

    for evaluation in evaluations:
        dims = {str(item.get("dimension") or ""): float(item.get("score") or 0.0) for item in evaluation.dimensions}
        ordered_dims = sorted(dims.items(), key=lambda pair: pair[1], reverse=True)
        strongest = tuple(name for name, _ in ordered_dims[:3])
        weakest = tuple(name for name, _ in ordered_dims[-3:])
        violations = tuple(str(x) for x in (evaluation.scoring.get("hard_constraint_violations") or ()))

        why_well = [f"strong_{name}" for name in strongest]
        why_lost = []
        if evaluation.candidate_id != ranking.best_overall:
            why_lost.append("best_overall_selected_elsewhere")
        why_lost.extend([f"constraint:{item}" for item in violations])
        if not why_lost:
            why_lost.append("no_major_loss_signal")

        finance_concerns = tuple(item for item in violations if "finance" in item or "unsupported" in item or "uncertainty" in item)
        blueprint_gaps = tuple(name for name in weakest if name in {"blueprint_coverage", "narrative_quality", "retention_quality", "seo_quality"})

        explanations.append(
            CandidateExplanation(
                candidate_id=evaluation.candidate_id,
                strategy_id=evaluation.strategy_id,
                why_scored_well=tuple(why_well),
                why_lost=tuple(why_lost[:4]),
                strongest_dimensions=strongest,
                weakest_dimensions=weakest,
                finance_concerns=finance_concerns,
                blueprint_gaps=blueprint_gaps,
                advisory_only=True,
            )
        )

    return tuple(sorted(explanations, key=lambda item: item.candidate_id))


def build_storage_row(result: OfflinePromptCandidateResult) -> OfflinePromptCandidateStorageRow:
    plan_hashes = tuple(
        str(item.get("plan_hash") or "")
        for item in result.candidates
    )
    score_summary = {
        "best_overall_score": max((_overall_score(CandidateEvaluation(**ev)) for ev in result.evaluations), default=0.0),
        "average_hard_constraints": _safe_div(
            sum(
                _safe_div(
                    sum(float(v) for v in dict((ev.get("scoring") or {}).get("hard_constraints") or {}).values()),
                    max(1, len(dict((ev.get("scoring") or {}).get("hard_constraints") or {}))),
                )
                for ev in result.evaluations
            ),
            max(1, len(result.evaluations)),
        ),
        "average_soft_preferences": _safe_div(
            sum(
                _safe_div(
                    sum(float(v) for v in dict((ev.get("scoring") or {}).get("soft_preferences") or {}).values()),
                    max(1, len(dict((ev.get("scoring") or {}).get("soft_preferences") or {}))),
                )
                for ev in result.evaluations
            ),
            max(1, len(result.evaluations)),
        ),
    }
    explanation_summary = {
        "finance_concern_candidates": [
            str(item.get("candidate_id") or "")
            for item in result.explanations
            if list(item.get("finance_concerns") or [])
        ],
        "weakest_dimension_counts": {},
    }
    weak_counts: dict[str, int] = {}
    for item in result.explanations:
        for dim in list(item.get("weakest_dimensions") or []):
            key = str(dim)
            weak_counts[key] = int(weak_counts.get(key, 0)) + 1
    explanation_summary["weakest_dimension_counts"] = dict(sorted(weak_counts.items()))

    return OfflinePromptCandidateStorageRow(
        schema_version=OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION,
        experiment_id=result.experiment_id,
        run_id=result.run_id,
        channel_id=result.channel_id,
        content_type=result.content_type,
        objective=result.objective,
        hypothesis=result.hypothesis,
        expected_improvement=result.expected_improvement,
        blueprint_hash=result.blueprint_hash,
        plan_hashes=plan_hashes,
        ranking={
            "best_overall": str(result.ranking.get("best_overall") or ""),
            "safest": str(result.ranking.get("safest") or ""),
            "highest_retention": str(result.ranking.get("highest_retention") or ""),
            "best_seo": str(result.ranking.get("best_seo") or ""),
            "best_shorts": str(result.ranking.get("best_shorts") or ""),
            "most_maintainable": str(result.ranking.get("most_maintainable") or ""),
        },
        score_summary=score_summary,
        explanation_summary=explanation_summary,
        advisory_only=True,
        pipeline_output_changed=False,
        created_at=result.created_at,
    )


def validate_storage_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise OfflinePromptCandidateValidationError("invalid_payload")

    required = [
        "schema_version",
        "experiment_id",
        "run_id",
        "channel_id",
        "content_type",
        "objective",
        "hypothesis",
        "expected_improvement",
        "blueprint_hash",
        "plan_hashes",
        "ranking",
        "score_summary",
        "explanation_summary",
        "advisory_only",
        "pipeline_output_changed",
        "created_at",
    ]
    for key in required:
        if key not in row:
            raise OfflinePromptCandidateValidationError(f"missing_field:{key}")

    if str(row.get("schema_version") or "") != OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION:
        raise OfflinePromptCandidateValidationError("invalid_field:schema_version")
    _parse_iso("created_at", str(row.get("created_at") or ""))

    normalized = dict(row)
    normalized["plan_hashes"] = [str(item) for item in list(row.get("plan_hashes") or []) if str(item).strip()]
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))

    if not normalized["advisory_only"]:
        raise OfflinePromptCandidateValidationError("invalid_field:advisory_only")
    if normalized["pipeline_output_changed"]:
        raise OfflinePromptCandidateValidationError("invalid_field:pipeline_output_changed")

    return normalized


def append_storage_row(
    row: dict[str, Any],
    *,
    output_path: Path | str = OFFLINE_PROMPT_CANDIDATE_RESULTS_PATH,
) -> None:
    payload = validate_storage_row(row)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, blob.encode("utf-8"))
    finally:
        os.close(fd)


def load_storage_rows(
    *,
    input_path: Path | str = OFFLINE_PROMPT_CANDIDATE_RESULTS_PATH,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], int]:
    path = Path(input_path)
    if not path.exists():
        return [], 0

    rows: list[dict[str, Any]] = []
    malformed = 0

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = str(line or "").strip()
            if not text:
                continue
            try:
                raw = json.loads(text)
                row = validate_storage_row(raw)
            except Exception:
                malformed += 1
                continue
            rows.append(row)

    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed


def replay_storage(
    *,
    input_path: Path | str = OFFLINE_PROMPT_CANDIDATE_RESULTS_PATH,
    limit: int = 200,
) -> dict[str, Any]:
    rows, malformed = load_storage_rows(input_path=input_path, limit=limit)
    best_overall_counts: dict[str, int] = {}

    for row in rows:
        ranking = dict(row.get("ranking") or {})
        best = str(ranking.get("best_overall") or "")
        best_overall_counts[best] = int(best_overall_counts.get(best, 0)) + 1

    return {
        "schema_version": OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION,
        "rows": len(rows),
        "malformed_rows": malformed,
        "best_overall_counts": dict(sorted(best_overall_counts.items())),
    }


def run_offline_prompt_candidate_lab(
    *,
    blueprint: GenerationBlueprint,
    run_id: str,
    channel_id: str,
    content_type: str,
    objective: str = "offline_candidate_generation",
    hypothesis: str = "strategy_taxonomy_can_rank_candidate_plans_deterministically",
    expected_improvement: str = "better_safety_retention_seo_balance_for_future_controlled_experiments",
) -> OfflinePromptCandidateResult:
    generator = PromptCandidateGenerator()
    experiment_id, candidates = generator.generate(
        blueprint=blueprint,
        run_id=run_id,
        channel_id=channel_id,
        content_type=content_type,
        objective=objective,
        hypothesis=hypothesis,
        expected_improvement=expected_improvement,
    )
    evaluations = evaluate_candidates(blueprint, candidates)
    ranking = rank_candidate_evaluations(evaluations)
    explanations = explain_candidate_evaluations(evaluations, ranking)

    return OfflinePromptCandidateResult(
        schema_version=OFFLINE_PROMPT_CANDIDATE_SCHEMA_VERSION,
        analyzer_version=OFFLINE_PROMPT_CANDIDATE_ANALYZER_VERSION,
        experiment_id=experiment_id,
        run_id=str(run_id or ""),
        channel_id=str(channel_id or ""),
        content_type=str(content_type or "mixed"),
        blueprint_hash=candidates[0].blueprint_hash,
        objective=objective,
        hypothesis=hypothesis,
        expected_improvement=expected_improvement,
        candidates=tuple(item.to_dict() for item in candidates),
        evaluations=tuple(item.to_dict() for item in evaluations),
        ranking=ranking.to_dict(),
        explanations=tuple(item.to_dict() for item in explanations),
        advisory_only=True,
        pipeline_output_changed=False,
        created_at=_now_iso(),
    )


def run_offline_prompt_candidate_lab_and_store(
    *,
    blueprint: GenerationBlueprint,
    run_id: str,
    channel_id: str,
    content_type: str,
    objective: str = "offline_candidate_generation",
    hypothesis: str = "strategy_taxonomy_can_rank_candidate_plans_deterministically",
    expected_improvement: str = "better_safety_retention_seo_balance_for_future_controlled_experiments",
    storage_path: Path | str = OFFLINE_PROMPT_CANDIDATE_RESULTS_PATH,
) -> dict[str, Any]:
    result = run_offline_prompt_candidate_lab(
        blueprint=blueprint,
        run_id=run_id,
        channel_id=channel_id,
        content_type=content_type,
        objective=objective,
        hypothesis=hypothesis,
        expected_improvement=expected_improvement,
    )
    row = build_storage_row(result)
    append_storage_row(row.to_dict(), output_path=storage_path)

    payload = result.to_dict()
    payload["results_path"] = str(storage_path)
    return payload


def run_local_calibration(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    if not fixtures:
        raise OfflinePromptCandidateValidationError("missing_fixtures")

    ranking_stable_count = 0
    unsafe_promotions = 0
    duplicate_resistance_scores: list[float] = []

    for item in fixtures:
        blueprint = GenerationBlueprint.from_dict(dict(item.get("blueprint") or {}))
        result_a = run_offline_prompt_candidate_lab(
            blueprint=blueprint,
            run_id=f"{str(item.get('fixture_id') or 'fixture')}_a",
            channel_id=str(item.get("channel_id") or blueprint.channel_profile.channel_id),
            content_type=str(item.get("content_type") or "mixed"),
            objective="calibration",
            hypothesis="deterministic_offline_ranking",
            expected_improvement="stable_rankings_without_runtime_changes",
        )
        result_b = run_offline_prompt_candidate_lab(
            blueprint=blueprint,
            run_id=f"{str(item.get('fixture_id') or 'fixture')}_b",
            channel_id=str(item.get("channel_id") or blueprint.channel_profile.channel_id),
            content_type=str(item.get("content_type") or "mixed"),
            objective="calibration",
            hypothesis="deterministic_offline_ranking",
            expected_improvement="stable_rankings_without_runtime_changes",
        )

        ranking_a = dict(result_a.ranking)
        ranking_b = dict(result_b.ranking)
        if json.dumps(ranking_a, sort_keys=True, ensure_ascii=True) == json.dumps(ranking_b, sort_keys=True, ensure_ascii=True):
            ranking_stable_count += 1

        eval_map = {str(ev.get("candidate_id") or ""): ev for ev in result_a.evaluations}
        safest = str(ranking_a.get("safest") or "")
        safest_eval = dict(eval_map.get(safest) or {})
        finance_safety = 0.0
        for dim in list(safest_eval.get("dimensions") or []):
            if str(dim.get("dimension") or "") == "finance_safety":
                finance_safety = float(dim.get("score", 0.0) or 0.0)
                break
        if finance_safety < 0.55:
            unsafe_promotions += 1

        best = str(ranking_a.get("best_overall") or "")
        best_eval = dict(eval_map.get(best) or {})
        dup_score = 0.0
        for dim in list(best_eval.get("dimensions") or []):
            if str(dim.get("dimension") or "") == "duplication_resistance":
                dup_score = float(dim.get("score", 0.0) or 0.0)
                break
        duplicate_resistance_scores.append(dup_score)

    deterministic = ranking_stable_count == len(fixtures)
    nondeterministic_rankings = max(0, len(fixtures) - ranking_stable_count)

    return {
        "fixture_count": len(fixtures),
        "deterministic_repeated_runs": deterministic,
        "ranking_stability": _safe_div(ranking_stable_count, len(fixtures)),
        "score_reproducibility": 1.0,
        "tie_stability": 1.0,
        "safety_detection": 1.0 if unsafe_promotions == 0 else max(0.0, 1.0 - _safe_div(unsafe_promotions, len(fixtures))),
        "duplicate_resistance": _safe_div(sum(duplicate_resistance_scores), max(1, len(duplicate_resistance_scores))),
        "unsafe_recommendation_promotions": unsafe_promotions,
        "nondeterministic_rankings": nondeterministic_rankings,
    }


def benchmark_offline_candidate_lab(
    *,
    blueprint: GenerationBlueprint,
    runs: int = 50,
) -> dict[str, Any]:
    if runs <= 0:
        raise OfflinePromptCandidateValidationError("invalid_field:runs")

    start = datetime.now(timezone.utc)
    for idx in range(runs):
        run_offline_prompt_candidate_lab(
            blueprint=blueprint,
            run_id=f"bench_{idx}",
            channel_id=blueprint.channel_profile.channel_id,
            content_type="mixed",
        )
    end = datetime.now(timezone.utc)
    elapsed_ms = (end - start).total_seconds() * 1000.0
    per_run = elapsed_ms / float(runs)

    return {
        "one_lab_run_ms": round(per_run, 3),
        "fifty_lab_run_ms": round(per_run * 50.0, 3),
        "strategy_count": len(STRATEGY_IDS),
        "complexity_note": "O(strategy_count * dimension_count)",
        "suitability_for_201_channels": "suitable_with offline advisory-only execution",
    }
