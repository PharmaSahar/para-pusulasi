from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Literal

from .content_intelligence_foundation import GENERATION_BLUEPRINT_SCHEMA_VERSION, GenerationBlueprint
from .shadow_blueprint_prompt_alignment import SafePromptRepresentation
from .shadow_prompt_experiment_registry import get_prompt_variant, get_prompt_variant_registry


SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION = "v1"
SHADOW_PROMPT_EXPERIMENT_ANALYZER_VERSION = "v1"
SHADOW_PROMPT_EXPERIMENT_RESULTS_PATH = Path("logs/shadow_prompt_experiments.jsonl")

_COMPARISON_STATE = Literal["BETTER", "SAME", "WORSE", "UNSUPPORTED", "UNKNOWN"]
_RECOMMENDATION = Literal[
    "KEEP_CURRENT",
    "EXPERIMENT_FURTHER",
    "PROMISING",
    "NEEDS_MORE_DATA",
    "REJECT",
    "UNSUPPORTED",
]

_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|client[_-]?secret|oauth|access[_-]?token|refresh[_-]?token|password|cookie|authorization\s*:|bearer\s+)",
    re.IGNORECASE,
)
_RISKY_PATTERN = re.compile(r"(garanti\s+getiri|x\s*kat|insider|hemen\s+al|simdi\s+al|simdi\s+sat|pump)", re.IGNORECASE)


class PromptExperimentValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PromptExperimentValidationError(f"missing_field:{name}")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise PromptExperimentValidationError(f"invalid_datetime:{name}") from exc
    return text


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_json_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return _sha(blob)


def _bounded_text(value: str | None, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if _SECRET_PATTERN.search(text):
        raise PromptExperimentValidationError("secret_like_content_detected")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _token_estimate(text: str) -> int:
    if not text:
        return 0
    return max(1, int(round(len(text) / 4)))


def _safe_div(a: float, b: float) -> float:
    if not b:
        return 0.0
    return float(a) / float(b)


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> float:
    text_n = _normalize_text(text)
    if not keywords:
        return 0.0
    hit = sum(1 for k in keywords if k in text_n)
    return max(0.0, min(1.0, _safe_div(hit, len(keywords))))


def _blueprint_topic_text(blueprint: GenerationBlueprint) -> str:
    payload = blueprint.to_dict()
    topic_intent = dict(payload.get("topic_intent") or {})
    return str(topic_intent.get("topic_title") or "")


def _variant_prompt_text(base_excerpt: str, variant_id: str) -> str:
    base = str(base_excerpt or "").strip()
    variant_key = str(variant_id or "").strip().upper()
    if variant_key in {"CURRENT_PRODUCTION", "CONTROL", "FUTURE"}:
        return base
    if variant_key == "CANDIDATE_A":
        return (
            f"{base} | safety: uncertainty language, no guaranteed returns, source transparency "
            "| structure: hook, narrative blocks, retention checkpoints"
        )
    if variant_key == "CANDIDATE_B":
        return (
            f"{base} | retention: first-30s hook, mid-video curiosity loop, ending teaser "
            "| seo: search intent terms, title objective, thumbnail-topic consistency"
        )
    return base


def _compute_dimension_metrics(blueprint: GenerationBlueprint, prompt_text: str) -> dict[str, float]:
    text = _normalize_text(prompt_text)
    topic_text = _normalize_text(_blueprint_topic_text(blueprint))
    prompt_tokens = re.findall(r"[a-z0-9ığüşöç]+", text)
    unique_ratio = _safe_div(len(set(prompt_tokens)), len(prompt_tokens))
    risky_hits = len(_RISKY_PATTERN.findall(text))

    metrics = {
        "blueprint_coverage": _keyword_hits(text, ("hook", "retention", "narrative", "thumbnail", "seo", "shorts")),
        "finance_safety": max(0.0, min(1.0, 1.0 - (0.2 * risky_hits) + _keyword_hits(text, ("risk", "uncertainty", "safe", "dogrulan")))),
        "hook_quality": _keyword_hits(text, ("hook", "first 30", "ilk 30", "opening")),
        "narrative_completeness": _keyword_hits(text, ("narrative", "structure", "story", "bolum")),
        "retention_planning": _keyword_hits(text, ("retention", "curiosity", "teaser", "cta")),
        "seo_planning": _keyword_hits(text, ("seo", "keyword", "search intent", "title objective")),
        "shorts_planning": _keyword_hits(text, ("short", "shorts", "clip", "loop")),
        "thumbnail_alignment": _keyword_hits(text, ("thumbnail", "visual", "contrast", "topic")),
        "duplication_risk": max(0.0, min(1.0, 1.0 - unique_ratio)),
        "prompt_complexity": max(0.0, min(1.0, _safe_div(len(prompt_tokens), 800.0))),
        "estimated_token_size": float(_token_estimate(prompt_text)),
        "unsupported_features": 1.0 if "auto_publish" in text or "runtime_replace" in text else 0.0,
        "clarity": max(0.0, min(1.0, unique_ratio + 0.2)),
        "safety": max(0.0, min(1.0, 1.0 - (0.25 * risky_hits))),
        "repetition": max(0.0, min(1.0, 1.0 - unique_ratio)),
        "alignment": _keyword_hits(f"{text} {topic_text}", tuple(sorted(set(topic_text.split()))[:8])) if topic_text else 0.0,
        "maintainability": max(0.0, min(1.0, 1.0 - abs(_token_estimate(prompt_text) - 180) / 280.0)),
        "coverage": _keyword_hits(text, ("hook", "retention", "thumbnail", "seo", "narrative", "safety")),
        "conflicts": max(0.0, min(1.0, 0.2 * risky_hits)),
    }
    return metrics


def _compare_value(candidate: float, baseline: float, *, inverse: bool = False) -> _COMPARISON_STATE:
    if inverse:
        candidate = -candidate
        baseline = -baseline
    delta = candidate - baseline
    if delta > 0.02:
        return "BETTER"
    if delta < -0.02:
        return "WORSE"
    return "SAME"


def _build_comparison_states(candidate_metrics: dict[str, float], baseline_metrics: dict[str, float]) -> dict[str, _COMPARISON_STATE]:
    return {
        "blueprint_coverage": _compare_value(candidate_metrics["blueprint_coverage"], baseline_metrics["blueprint_coverage"]),
        "finance_safety": _compare_value(candidate_metrics["finance_safety"], baseline_metrics["finance_safety"]),
        "hook_quality": _compare_value(candidate_metrics["hook_quality"], baseline_metrics["hook_quality"]),
        "narrative_completeness": _compare_value(candidate_metrics["narrative_completeness"], baseline_metrics["narrative_completeness"]),
        "retention_planning": _compare_value(candidate_metrics["retention_planning"], baseline_metrics["retention_planning"]),
        "seo_planning": _compare_value(candidate_metrics["seo_planning"], baseline_metrics["seo_planning"]),
        "shorts_planning": _compare_value(candidate_metrics["shorts_planning"], baseline_metrics["shorts_planning"]),
        "thumbnail_alignment": _compare_value(candidate_metrics["thumbnail_alignment"], baseline_metrics["thumbnail_alignment"]),
        "duplication_risk": _compare_value(candidate_metrics["duplication_risk"], baseline_metrics["duplication_risk"], inverse=True),
        "prompt_complexity": _compare_value(candidate_metrics["prompt_complexity"], baseline_metrics["prompt_complexity"], inverse=True),
        "estimated_token_size": _compare_value(abs(candidate_metrics["estimated_token_size"] - 180.0), abs(baseline_metrics["estimated_token_size"] - 180.0), inverse=True),
        "unsupported_features": "UNSUPPORTED" if candidate_metrics["unsupported_features"] > 0 else "SAME",
    }


def _recommendation_from_metrics(candidate: dict[str, float], baseline: dict[str, float]) -> tuple[_RECOMMENDATION, str]:
    if candidate.get("unsupported_features", 0.0) > 0.0:
        return "UNSUPPORTED", "unsupported_feature_detected"

    if candidate.get("safety", 0.0) < 0.55 or candidate.get("conflicts", 1.0) > 0.35:
        return "REJECT", "safety_or_conflict_regression"

    composite = (
        candidate.get("coverage", 0.0) * 0.25
        + candidate.get("alignment", 0.0) * 0.20
        + candidate.get("clarity", 0.0) * 0.15
        + candidate.get("safety", 0.0) * 0.20
        + (1.0 - candidate.get("repetition", 0.0)) * 0.10
        + candidate.get("maintainability", 0.0) * 0.10
    )
    base_composite = (
        baseline.get("coverage", 0.0) * 0.25
        + baseline.get("alignment", 0.0) * 0.20
        + baseline.get("clarity", 0.0) * 0.15
        + baseline.get("safety", 0.0) * 0.20
        + (1.0 - baseline.get("repetition", 0.0)) * 0.10
        + baseline.get("maintainability", 0.0) * 0.10
    )

    delta = composite - base_composite
    if delta >= 0.08 and candidate.get("safety", 0.0) >= baseline.get("safety", 0.0):
        return "PROMISING", "composite_improvement_detected"
    if delta >= 0.03:
        return "EXPERIMENT_FURTHER", "moderate_improvement_detected"
    if abs(delta) < 0.03:
        return "KEEP_CURRENT", "no_material_delta"
    return "NEEDS_MORE_DATA", "inconclusive_delta"


@dataclass(frozen=True)
class PromptExperiment:
    schema_version: str
    experiment_id: str
    blueprint_hash: str
    objective: str
    hypothesis: str
    expected_improvement: str
    analyzer_version: str
    advisory_only: bool
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version != SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION:
            raise PromptExperimentValidationError("invalid_field:schema_version")
        if self.analyzer_version != SHADOW_PROMPT_EXPERIMENT_ANALYZER_VERSION:
            raise PromptExperimentValidationError("invalid_field:analyzer_version")
        if not self.experiment_id:
            raise PromptExperimentValidationError("missing_field:experiment_id")
        if not self.blueprint_hash:
            raise PromptExperimentValidationError("missing_field:blueprint_hash")
        if not self.objective:
            raise PromptExperimentValidationError("missing_field:objective")
        if not self.hypothesis:
            raise PromptExperimentValidationError("missing_field:hypothesis")
        if not self.expected_improvement:
            raise PromptExperimentValidationError("missing_field:expected_improvement")
        if not self.advisory_only:
            raise PromptExperimentValidationError("invalid_field:advisory_only")
        _parse_iso("created_at", self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptVariant:
    variant_id: str
    template_id: str
    prompt_version: str
    prompt_hash: str
    analyzer_version: str
    channel_id: str
    content_type: str
    objective: str
    hypothesis: str
    expected_improvement: str
    advisory_only: bool
    created_at: str

    def __post_init__(self) -> None:
        if not self.variant_id:
            raise PromptExperimentValidationError("missing_field:variant_id")
        if not self.template_id:
            raise PromptExperimentValidationError("missing_field:template_id")
        if not self.prompt_hash:
            raise PromptExperimentValidationError("missing_field:prompt_hash")
        if not self.prompt_version:
            raise PromptExperimentValidationError("missing_field:prompt_version")
        if self.analyzer_version != SHADOW_PROMPT_EXPERIMENT_ANALYZER_VERSION:
            raise PromptExperimentValidationError("invalid_field:analyzer_version")
        if not self.channel_id:
            raise PromptExperimentValidationError("missing_field:channel_id")
        if not self.content_type:
            raise PromptExperimentValidationError("missing_field:content_type")
        if not self.objective:
            raise PromptExperimentValidationError("missing_field:objective")
        if not self.hypothesis:
            raise PromptExperimentValidationError("missing_field:hypothesis")
        if not self.expected_improvement:
            raise PromptExperimentValidationError("missing_field:expected_improvement")
        if not self.advisory_only:
            raise PromptExperimentValidationError("invalid_field:advisory_only")
        _parse_iso("created_at", self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptCandidate:
    variant_id: str
    candidate_id: str
    prompt_hash: str
    template_id: str
    prompt_version: str
    channel_id: str
    content_type: str
    objective: str
    hypothesis: str
    expected_improvement: str
    advisory_only: bool
    created_at: str

    def __post_init__(self) -> None:
        if not self.variant_id or not self.candidate_id:
            raise PromptExperimentValidationError("missing_field:candidate_id")
        if not self.prompt_hash:
            raise PromptExperimentValidationError("missing_field:prompt_hash")
        if not self.template_id:
            raise PromptExperimentValidationError("missing_field:template_id")
        if not self.prompt_version:
            raise PromptExperimentValidationError("missing_field:prompt_version")
        if not self.channel_id:
            raise PromptExperimentValidationError("missing_field:channel_id")
        if not self.content_type:
            raise PromptExperimentValidationError("missing_field:content_type")
        if not self.objective:
            raise PromptExperimentValidationError("missing_field:objective")
        if not self.hypothesis:
            raise PromptExperimentValidationError("missing_field:hypothesis")
        if not self.expected_improvement:
            raise PromptExperimentValidationError("missing_field:expected_improvement")
        if not self.advisory_only:
            raise PromptExperimentValidationError("invalid_field:advisory_only")
        _parse_iso("created_at", self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptComparison:
    variant_id: str
    compared_to_variant_id: str
    comparison_states: dict[str, _COMPARISON_STATE]
    summary_score_delta: float

    def __post_init__(self) -> None:
        if not self.variant_id or not self.compared_to_variant_id:
            raise PromptExperimentValidationError("missing_field:comparison_variant")
        if not isinstance(self.comparison_states, dict):
            raise PromptExperimentValidationError("invalid_field:comparison_states")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptEvaluation:
    variant_id: str
    evaluation_metrics: dict[str, float]
    advisory_only: bool

    def __post_init__(self) -> None:
        if not self.variant_id:
            raise PromptExperimentValidationError("missing_field:variant_id")
        if not isinstance(self.evaluation_metrics, dict):
            raise PromptExperimentValidationError("invalid_field:evaluation_metrics")
        if not self.advisory_only:
            raise PromptExperimentValidationError("invalid_field:advisory_only")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptRecommendation:
    variant_id: str
    recommendation: _RECOMMENDATION
    reason: str
    advisory_only: bool

    def __post_init__(self) -> None:
        if not self.variant_id:
            raise PromptExperimentValidationError("missing_field:variant_id")
        if not self.reason:
            raise PromptExperimentValidationError("missing_field:reason")
        if self.recommendation not in {
            "KEEP_CURRENT",
            "EXPERIMENT_FURTHER",
            "PROMISING",
            "NEEDS_MORE_DATA",
            "REJECT",
            "UNSUPPORTED",
        }:
            raise PromptExperimentValidationError("invalid_field:recommendation")
        if not self.advisory_only:
            raise PromptExperimentValidationError("invalid_field:advisory_only")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptDecision:
    decision: str
    selected_variant_id: str
    rationale: str
    advisory_only: bool
    pipeline_output_changed: bool

    def __post_init__(self) -> None:
        if self.decision != "NO_RUNTIME_CHANGE":
            raise PromptExperimentValidationError("invalid_field:decision")
        if not self.selected_variant_id:
            raise PromptExperimentValidationError("missing_field:selected_variant_id")
        if not self.rationale:
            raise PromptExperimentValidationError("missing_field:rationale")
        if not self.advisory_only:
            raise PromptExperimentValidationError("invalid_field:advisory_only")
        if self.pipeline_output_changed:
            raise PromptExperimentValidationError("invalid_field:pipeline_output_changed")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PromptExperimentResult:
    schema_version: str
    experiment_id: str
    blueprint_hash: str
    prompt_hash: str
    template_id: str
    prompt_version: str
    analyzer_version: str
    run_id: str
    channel_id: str
    content_type: str
    objective: str
    hypothesis: str
    expected_improvement: str
    variants_evaluated: tuple[dict[str, Any], ...]
    comparisons: tuple[dict[str, Any], ...]
    recommendations: tuple[dict[str, Any], ...]
    decision: dict[str, Any]
    evaluation_metrics: dict[str, Any]
    advisory_only: bool
    pipeline_output_changed: bool
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version != SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION:
            raise PromptExperimentValidationError("invalid_field:schema_version")
        if self.analyzer_version != SHADOW_PROMPT_EXPERIMENT_ANALYZER_VERSION:
            raise PromptExperimentValidationError("invalid_field:analyzer_version")
        if not self.experiment_id:
            raise PromptExperimentValidationError("missing_field:experiment_id")
        if not self.blueprint_hash:
            raise PromptExperimentValidationError("missing_field:blueprint_hash")
        if not self.prompt_hash:
            raise PromptExperimentValidationError("missing_field:prompt_hash")
        if not self.template_id:
            raise PromptExperimentValidationError("missing_field:template_id")
        if not self.prompt_version:
            raise PromptExperimentValidationError("missing_field:prompt_version")
        if not self.channel_id:
            raise PromptExperimentValidationError("missing_field:channel_id")
        if not self.content_type:
            raise PromptExperimentValidationError("missing_field:content_type")
        if not self.objective:
            raise PromptExperimentValidationError("missing_field:objective")
        if not self.hypothesis:
            raise PromptExperimentValidationError("missing_field:hypothesis")
        if not self.expected_improvement:
            raise PromptExperimentValidationError("missing_field:expected_improvement")
        if not self.advisory_only:
            raise PromptExperimentValidationError("invalid_field:advisory_only")
        if self.pipeline_output_changed:
            raise PromptExperimentValidationError("invalid_field:pipeline_output_changed")
        _parse_iso("created_at", self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "variants_evaluated": [dict(item) for item in self.variants_evaluated],
            "comparisons": [dict(item) for item in self.comparisons],
            "recommendations": [dict(item) for item in self.recommendations],
            "decision": dict(self.decision),
            "evaluation_metrics": dict(self.evaluation_metrics),
        }


@dataclass(frozen=True)
class PromptExperimentStorageRow:
    schema_version: str
    experiment_id: str
    run_id: str
    channel_id: str
    content_type: str
    objective: str
    hypothesis: str
    expected_improvement: str
    blueprint_hash: str
    prompt_hash: str
    template_id: str
    prompt_version: str
    analyzer_version: str
    variants: tuple[str, ...]
    recommendation: str
    selected_variant_id: str
    recommendation_reason: str
    aggregate_metrics: dict[str, float]
    advisory_only: bool
    pipeline_output_changed: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["variants"] = list(self.variants)
        return payload


def validate_prompt_experiment_storage_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise PromptExperimentValidationError("invalid_payload")

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
        "prompt_hash",
        "template_id",
        "prompt_version",
        "analyzer_version",
        "variants",
        "recommendation",
        "selected_variant_id",
        "recommendation_reason",
        "aggregate_metrics",
        "advisory_only",
        "pipeline_output_changed",
        "created_at",
    ]
    for key in required:
        if key not in row:
            raise PromptExperimentValidationError(f"missing_field:{key}")

    if str(row.get("schema_version") or "") != SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION:
        raise PromptExperimentValidationError("invalid_field:schema_version")
    if str(row.get("analyzer_version") or "") != SHADOW_PROMPT_EXPERIMENT_ANALYZER_VERSION:
        raise PromptExperimentValidationError("invalid_field:analyzer_version")
    _parse_iso("created_at", str(row.get("created_at") or ""))

    normalized = dict(row)
    normalized["variants"] = [str(v) for v in (row.get("variants") or []) if str(v).strip()]
    reason_text = str(row.get("recommendation_reason") or "")
    if _SECRET_PATTERN.search(reason_text):
        raise PromptExperimentValidationError("secret_like_content_detected")
    normalized["recommendation_reason"] = _bounded_text(reason_text, limit=220)
    normalized["advisory_only"] = bool(row.get("advisory_only"))
    normalized["pipeline_output_changed"] = bool(row.get("pipeline_output_changed"))

    if not normalized["advisory_only"]:
        raise PromptExperimentValidationError("invalid_field:advisory_only")
    if normalized["pipeline_output_changed"]:
        raise PromptExperimentValidationError("invalid_field:pipeline_output_changed")

    return normalized


def append_prompt_experiment_row(
    row: dict[str, Any],
    *,
    output_path: Path | str = SHADOW_PROMPT_EXPERIMENT_RESULTS_PATH,
) -> None:
    payload = validate_prompt_experiment_storage_row(row)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, blob.encode("utf-8"))
    finally:
        os.close(fd)


def load_prompt_experiment_rows(
    *,
    input_path: Path | str = SHADOW_PROMPT_EXPERIMENT_RESULTS_PATH,
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
                row = validate_prompt_experiment_storage_row(raw)
            except Exception:
                malformed += 1
                continue
            rows.append(row)

    if limit > 0:
        rows = rows[-limit:]
    return rows, malformed


def replay_prompt_experiments(
    *,
    input_path: Path | str = SHADOW_PROMPT_EXPERIMENT_RESULTS_PATH,
    limit: int = 200,
) -> dict[str, Any]:
    rows, malformed = load_prompt_experiment_rows(input_path=input_path, limit=limit)
    by_variant: dict[str, int] = {}
    by_recommendation: dict[str, int] = {}

    for row in rows:
        for variant in list(row.get("variants") or []):
            by_variant[variant] = int(by_variant.get(variant, 0)) + 1
        rec = str(row.get("recommendation") or "")
        by_recommendation[rec] = int(by_recommendation.get(rec, 0)) + 1

    return {
        "schema_version": SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION,
        "rows": len(rows),
        "malformed_rows": malformed,
        "by_variant": dict(sorted(by_variant.items())),
        "by_recommendation": dict(sorted(by_recommendation.items())),
    }


def build_prompt_experiment_storage_row(result: PromptExperimentResult) -> PromptExperimentStorageRow:
    recommendations = [dict(item) for item in result.recommendations]
    selected = next((r for r in recommendations if r.get("variant_id") != "CURRENT_PRODUCTION"), recommendations[0] if recommendations else {})
    aggregate = {
        "coverage": float(result.evaluation_metrics.get("coverage", 0.0) or 0.0),
        "conflicts": float(result.evaluation_metrics.get("conflicts", 0.0) or 0.0),
        "clarity": float(result.evaluation_metrics.get("clarity", 0.0) or 0.0),
        "safety": float(result.evaluation_metrics.get("safety", 0.0) or 0.0),
        "repetition": float(result.evaluation_metrics.get("repetition", 0.0) or 0.0),
        "alignment": float(result.evaluation_metrics.get("alignment", 0.0) or 0.0),
        "maintainability": float(result.evaluation_metrics.get("maintainability", 0.0) or 0.0),
    }

    return PromptExperimentStorageRow(
        schema_version=SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION,
        experiment_id=result.experiment_id,
        run_id=result.run_id,
        channel_id=result.channel_id,
        content_type=result.content_type,
        objective=result.objective,
        hypothesis=result.hypothesis,
        expected_improvement=result.expected_improvement,
        blueprint_hash=result.blueprint_hash,
        prompt_hash=result.prompt_hash,
        template_id=result.template_id,
        prompt_version=result.prompt_version,
        analyzer_version=result.analyzer_version,
        variants=tuple(str(item.get("variant_id") or "") for item in result.variants_evaluated),
        recommendation=str(selected.get("recommendation") or "KEEP_CURRENT"),
        selected_variant_id=str(selected.get("variant_id") or "CURRENT_PRODUCTION"),
        recommendation_reason=str(selected.get("reason") or "no_material_delta"),
        aggregate_metrics=aggregate,
        advisory_only=True,
        pipeline_output_changed=False,
        created_at=result.created_at,
    )


def _supports_variant(variant_id: str, *, channel_id: str, content_type: str) -> bool:
    entry = get_prompt_variant(variant_id)
    channels = set(entry.supported_channels)
    content_types = set(entry.supported_content_types)
    channel_ok = "*" in channels or channel_id in channels
    content_ok = content_type in content_types
    return channel_ok and content_ok


def run_prompt_experiment(
    *,
    blueprint: GenerationBlueprint,
    prompt_representation: SafePromptRepresentation,
    run_id: str,
    channel_id: str,
    content_type: str,
    objective: str = "improve_prompt_alignment",
    hypothesis: str = "candidate_variants_can_improve_quality_without_runtime_changes",
    expected_improvement: str = "better_coverage_and_safety_with_equal_or_lower_conflicts",
    variant_ids: list[str] | None = None,
) -> PromptExperimentResult:
    if blueprint.schema_version != GENERATION_BLUEPRINT_SCHEMA_VERSION:
        raise PromptExperimentValidationError("invalid_blueprint_schema_version")

    variants_to_run = [str(v).strip().upper() for v in (variant_ids or list(get_prompt_variant_registry().keys())) if str(v).strip()]
    if not variants_to_run:
        raise PromptExperimentValidationError("missing_variants")

    base_prompt = _bounded_text(prompt_representation.bounded_excerpt, limit=260)
    blueprint_hash = _safe_json_hash(blueprint.to_dict())
    seed = {
        "blueprint_hash": blueprint_hash,
        "prompt_hash": prompt_representation.prompt_hash,
        "variants": variants_to_run,
        "objective": objective,
        "hypothesis": hypothesis,
        "expected_improvement": expected_improvement,
    }
    experiment_id = f"exp_{_safe_json_hash(seed)[:20]}"
    created_at = _now_iso()

    experiment = PromptExperiment(
        schema_version=SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION,
        experiment_id=experiment_id,
        blueprint_hash=blueprint_hash,
        objective=str(objective or "improve_prompt_alignment"),
        hypothesis=str(hypothesis or "candidate_variants_can_improve_quality_without_runtime_changes"),
        expected_improvement=str(expected_improvement or "better_coverage_and_safety_with_equal_or_lower_conflicts"),
        analyzer_version=SHADOW_PROMPT_EXPERIMENT_ANALYZER_VERSION,
        advisory_only=True,
        created_at=created_at,
    )

    evaluations: list[PromptEvaluation] = []
    variants: list[PromptVariant] = []
    candidates: list[PromptCandidate] = []

    baseline_metrics: dict[str, float] | None = None
    for variant_id in variants_to_run:
        prompt_text = _variant_prompt_text(base_prompt, variant_id)
        prompt_hash = _sha(prompt_text)

        variant = PromptVariant(
            variant_id=variant_id,
            template_id=prompt_representation.template_id,
            prompt_version=prompt_representation.prompt_version,
            prompt_hash=prompt_hash,
            analyzer_version=SHADOW_PROMPT_EXPERIMENT_ANALYZER_VERSION,
            channel_id=channel_id,
            content_type=content_type,
            objective=experiment.objective,
            hypothesis=experiment.hypothesis,
            expected_improvement=experiment.expected_improvement,
            advisory_only=True,
            created_at=created_at,
        )
        variants.append(variant)

        candidate = PromptCandidate(
            variant_id=variant_id,
            candidate_id=f"cand_{variant_id.lower()}_{prompt_hash[:12]}",
            prompt_hash=prompt_hash,
            template_id=prompt_representation.template_id,
            prompt_version=prompt_representation.prompt_version,
            channel_id=channel_id,
            content_type=content_type,
            objective=experiment.objective,
            hypothesis=experiment.hypothesis,
            expected_improvement=experiment.expected_improvement,
            advisory_only=True,
            created_at=created_at,
        )
        candidates.append(candidate)

        metrics = _compute_dimension_metrics(blueprint, prompt_text)
        if not _supports_variant(variant_id, channel_id=channel_id, content_type=content_type):
            metrics["unsupported_features"] = 1.0
        evaluation = PromptEvaluation(variant_id=variant_id, evaluation_metrics=metrics, advisory_only=True)
        evaluations.append(evaluation)

        if variant_id == "CURRENT_PRODUCTION":
            baseline_metrics = metrics

    if baseline_metrics is None:
        baseline_eval = evaluations[0]
        baseline_metrics = dict(baseline_eval.evaluation_metrics)

    comparisons: list[PromptComparison] = []
    recommendations: list[PromptRecommendation] = []

    for evaluation in evaluations:
        states = _build_comparison_states(evaluation.evaluation_metrics, baseline_metrics)
        delta = float(evaluation.evaluation_metrics.get("coverage", 0.0) - baseline_metrics.get("coverage", 0.0))
        comparisons.append(
            PromptComparison(
                variant_id=evaluation.variant_id,
                compared_to_variant_id="CURRENT_PRODUCTION",
                comparison_states=states,
                summary_score_delta=delta,
            )
        )

        recommendation, reason = _recommendation_from_metrics(evaluation.evaluation_metrics, baseline_metrics)
        recommendations.append(
            PromptRecommendation(
                variant_id=evaluation.variant_id,
                recommendation=recommendation,
                reason=reason,
                advisory_only=True,
            )
        )

    ranked = sorted(
        recommendations,
        key=lambda item: (
            {"PROMISING": 5, "EXPERIMENT_FURTHER": 4, "KEEP_CURRENT": 3, "NEEDS_MORE_DATA": 2, "REJECT": 1, "UNSUPPORTED": 0}.get(item.recommendation, 0),
            item.variant_id != "CURRENT_PRODUCTION",
        ),
        reverse=True,
    )
    selected = ranked[0] if ranked else PromptRecommendation("CURRENT_PRODUCTION", "KEEP_CURRENT", "no_data", True)

    decision = PromptDecision(
        decision="NO_RUNTIME_CHANGE",
        selected_variant_id="CURRENT_PRODUCTION",
        rationale=f"advisory_only:{selected.variant_id}:{selected.recommendation}",
        advisory_only=True,
        pipeline_output_changed=False,
    )

    aggregate = {
        "coverage": float(sum(ev.evaluation_metrics.get("coverage", 0.0) for ev in evaluations) / max(1, len(evaluations))),
        "conflicts": float(sum(ev.evaluation_metrics.get("conflicts", 0.0) for ev in evaluations) / max(1, len(evaluations))),
        "clarity": float(sum(ev.evaluation_metrics.get("clarity", 0.0) for ev in evaluations) / max(1, len(evaluations))),
        "safety": float(sum(ev.evaluation_metrics.get("safety", 0.0) for ev in evaluations) / max(1, len(evaluations))),
        "repetition": float(sum(ev.evaluation_metrics.get("repetition", 0.0) for ev in evaluations) / max(1, len(evaluations))),
        "alignment": float(sum(ev.evaluation_metrics.get("alignment", 0.0) for ev in evaluations) / max(1, len(evaluations))),
        "maintainability": float(sum(ev.evaluation_metrics.get("maintainability", 0.0) for ev in evaluations) / max(1, len(evaluations))),
    }

    return PromptExperimentResult(
        schema_version=SHADOW_PROMPT_EXPERIMENT_SCHEMA_VERSION,
        experiment_id=experiment.experiment_id,
        blueprint_hash=experiment.blueprint_hash,
        prompt_hash=prompt_representation.prompt_hash,
        template_id=prompt_representation.template_id,
        prompt_version=prompt_representation.prompt_version,
        analyzer_version=SHADOW_PROMPT_EXPERIMENT_ANALYZER_VERSION,
        run_id=str(run_id or ""),
        channel_id=str(channel_id or ""),
        content_type=str(content_type or "mixed"),
        objective=experiment.objective,
        hypothesis=experiment.hypothesis,
        expected_improvement=experiment.expected_improvement,
        variants_evaluated=tuple(v.to_dict() for v in variants),
        comparisons=tuple(c.to_dict() for c in comparisons),
        recommendations=tuple(r.to_dict() for r in recommendations),
        decision=decision.to_dict(),
        evaluation_metrics=aggregate,
        advisory_only=True,
        pipeline_output_changed=False,
        created_at=created_at,
    )


def run_prompt_experiment_and_store(
    *,
    blueprint: GenerationBlueprint,
    prompt_representation: SafePromptRepresentation,
    run_id: str,
    channel_id: str,
    content_type: str,
    objective: str = "improve_prompt_alignment",
    hypothesis: str = "candidate_variants_can_improve_quality_without_runtime_changes",
    expected_improvement: str = "better_coverage_and_safety_with_equal_or_lower_conflicts",
    variant_ids: list[str] | None = None,
    storage_path: Path | str = SHADOW_PROMPT_EXPERIMENT_RESULTS_PATH,
) -> dict[str, Any]:
    result = run_prompt_experiment(
        blueprint=blueprint,
        prompt_representation=prompt_representation,
        run_id=run_id,
        channel_id=channel_id,
        content_type=content_type,
        objective=objective,
        hypothesis=hypothesis,
        expected_improvement=expected_improvement,
        variant_ids=variant_ids,
    )
    row = build_prompt_experiment_storage_row(result)
    append_prompt_experiment_row(row.to_dict(), output_path=storage_path)

    payload = result.to_dict()
    payload["results_path"] = str(storage_path)
    return payload


def benchmark_prompt_experiment(
    *,
    blueprint: GenerationBlueprint,
    prompt_representation: SafePromptRepresentation,
    runs: int = 25,
) -> dict[str, Any]:
    if runs <= 0:
        raise PromptExperimentValidationError("invalid_field:runs")

    start = datetime.now(timezone.utc)
    for _ in range(runs):
        run_prompt_experiment(
            blueprint=blueprint,
            prompt_representation=prompt_representation,
            run_id="bench",
            channel_id=blueprint.channel_profile.channel_id,
            content_type="mixed",
        )
    end = datetime.now(timezone.utc)
    elapsed_ms = (end - start).total_seconds() * 1000.0
    one_ms = elapsed_ms / float(runs)

    return {
        "one_experiment_ms": round(one_ms, 3),
        "fifty_experiment_ms": round(one_ms * 50.0, 3),
        "variant_count": len(get_prompt_variant_registry()),
        "complexity_note": "O(variant_count * metrics_dimensions)",
        "suitability_for_201_channels": "suitable_with advisory-only offline shadow evaluation",
    }
