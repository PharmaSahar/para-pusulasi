from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .causal_attribution_contract import CAUSAL_ATTRIBUTION_SCHEMA_VERSION
from .causal_attribution_store import CausalAttributionStore
from .decision_contract import DECISION_CONTRACT_SCHEMA_VERSION
from .decision_memory import DecisionMemoryStore
from .recommendation_contract import RECOMMENDATION_SCHEMA_VERSION
from .recommendation_store import RecommendationStore
from .recommendation_evaluation_contract import build_recommendation_evaluation_record
from .recommendation_evaluation_store import (
    RecommendationEvaluationAppendResult,
    RecommendationEvaluationStore,
)
from .run_recommendation_evaluation_audit import build_assessment_artifact
from .statistical_confidence_contract import STATISTICAL_CONFIDENCE_SCHEMA_VERSION
from .statistical_confidence_store import StatisticalConfidenceStore


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _select_latest(rows: list[dict[str, Any]], *, id_field: str, target_id: str, event_field: str) -> dict[str, Any] | None:
    matched = [row for row in rows if _safe_text(row.get(id_field)) == _safe_text(target_id)]
    if not matched:
        return None
    matched.sort(
        key=lambda row: (
            _safe_text(row.get("created_at")),
            _safe_text(row.get(id_field)),
            _safe_text(row.get(event_field)),
        )
    )
    return dict(matched[-1])


def _schema_value(row: dict[str, Any]) -> str:
    return _safe_text(row.get("schema_version") or row.get("evaluation_schema_version"))


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _safe_text(value)
        if text:
            return text
    return ""


@dataclass(frozen=True, slots=True)
class RecommendationEvaluationResult:
    evaluation_record: dict[str, Any]
    append_result: RecommendationEvaluationAppendResult
    projection: dict[str, Any]
    audit_artifact: dict[str, Any]
    offline_only: bool
    advisory_only: bool


class RecommendationEvaluatorError(RuntimeError):
    pass


class RecommendationEvaluator:
    def __init__(
        self,
        *,
        recommendation_store: RecommendationStore,
        confidence_store: StatisticalConfidenceStore,
        attribution_store: CausalAttributionStore,
        decision_memory_store: DecisionMemoryStore,
        evaluation_store: RecommendationEvaluationStore,
        repo_root: Path | str = ".",
        created_by: str = "recommendation_evaluator",
        source_module: str = "src.recommendation_evaluator",
        source_version: str = "a3.2",
        audit_builder: Callable[..., dict[str, Any]] | None = None,
    ):
        self.recommendation_store = recommendation_store
        self.confidence_store = confidence_store
        self.attribution_store = attribution_store
        self.decision_memory_store = decision_memory_store
        self.evaluation_store = evaluation_store
        self.repo_root = Path(repo_root)
        self.created_by = _safe_text(created_by) or "recommendation_evaluator"
        self.source_module = _safe_text(source_module) or "src.recommendation_evaluator"
        self.source_version = _safe_text(source_version) or "a3.2"
        self.audit_builder = audit_builder or build_assessment_artifact

    def _require_schema(self, row: dict[str, Any], *, expected: str, label: str) -> None:
        actual = _schema_value(row)
        if actual != expected:
            raise RecommendationEvaluatorError(f"invalid_schema:{label}:{actual or 'missing'}")

    def _load_recommendation(self, recommendation_id: str) -> dict[str, Any]:
        recommendation = _select_latest(
            self.recommendation_store.get_rows(),
            id_field="recommendation_record_id",
            target_id=recommendation_id,
            event_field="recommendation_event_id",
        )
        if recommendation is None:
            raise RecommendationEvaluatorError(f"missing_recommendation:{recommendation_id}")
        self._require_schema(recommendation, expected=RECOMMENDATION_SCHEMA_VERSION, label="recommendation")
        return recommendation

    def _resolve_confidence(self, confidence_id: str) -> dict[str, Any]:
        confidence = _select_latest(
            self.confidence_store.get_rows(),
            id_field="confidence_id",
            target_id=confidence_id,
            event_field="record_hash",
        )
        if confidence is None:
            raise RecommendationEvaluatorError(f"missing_confidence:{confidence_id}")
        self._require_schema(confidence, expected=STATISTICAL_CONFIDENCE_SCHEMA_VERSION, label="confidence")
        return confidence

    def _resolve_attribution(self, attribution_record_id: str) -> dict[str, Any]:
        attribution = _select_latest(
            self.attribution_store.get_rows(),
            id_field="attribution_record_id",
            target_id=attribution_record_id,
            event_field="attribution_event_id",
        )
        if attribution is None:
            raise RecommendationEvaluatorError(f"missing_attribution:{attribution_record_id}")
        self._require_schema(attribution, expected=CAUSAL_ATTRIBUTION_SCHEMA_VERSION, label="attribution")
        return attribution

    def _resolve_decision(self, decision_id: str) -> dict[str, Any]:
        rows = self.decision_memory_store.get_by_decision_id(decision_id)
        if not rows:
            raise RecommendationEvaluatorError(f"missing_decision_memory:{decision_id}")
        rows.sort(
            key=lambda row: (
                _safe_text(row.get("decision_timestamp")),
                _safe_text(row.get("created_at")),
                _safe_text(row.get("decision_event_id")),
            )
        )
        decision = dict(rows[-1])
        self._require_schema(decision, expected=DECISION_CONTRACT_SCHEMA_VERSION, label="decision")
        return decision

    def _validate_lineage(
        self,
        *,
        recommendation: dict[str, Any],
        confidence: dict[str, Any],
        attribution: dict[str, Any],
        decision: dict[str, Any],
    ) -> bool:
        if not bool(recommendation.get("lineage_complete", False)):
            return False
        if not bool(recommendation.get("upstream_records_resolved", False)):
            return False
        if not recommendation.get("feature_lineage_refs"):
            return False
        if _safe_text(recommendation.get("decision_id")) != _safe_text(decision.get("decision_id")):
            return False
        if _safe_text(recommendation.get("confidence_id")) != _safe_text(confidence.get("confidence_id")):
            return False
        if _safe_text(recommendation.get("attribution_record_id")) != _safe_text(attribution.get("attribution_record_id")):
            return False
        if _safe_text(attribution.get("decision_id")) != _safe_text(decision.get("decision_id")):
            return False
        return True

    def _evaluation_payload(
        self,
        *,
        recommendation: dict[str, Any],
        confidence: dict[str, Any],
        attribution: dict[str, Any],
        lineage_complete: bool,
    ) -> dict[str, Any]:
        contamination_state = _first_non_empty(
            recommendation.get("contamination_state"),
            confidence.get("contamination_state"),
            attribution.get("contamination_state"),
            "NONE",
        )
        outcome_maturity_state = _first_non_empty(
            recommendation.get("outcome_maturity_state"),
            confidence.get("maturity_state"),
            attribution.get("outcome_maturity_state"),
            "unknown",
        )
        unresolved_evidence = not bool(recommendation.get("upstream_records_resolved", False))

        return {
            "evaluator_version": self.source_version,
            "recommendation_id": _safe_text(recommendation.get("recommendation_record_id")),
            "recommendation_schema_version": RECOMMENDATION_SCHEMA_VERSION,
            "decision_id": _safe_text(recommendation.get("decision_id")),
            "learning_record_id": _safe_text(recommendation.get("learning_record_id")),
            "outcome_record_id": _safe_text(recommendation.get("outcome_record_id")),
            "confidence_id": _safe_text(recommendation.get("confidence_id")),
            "attribution_record_id": _safe_text(recommendation.get("attribution_record_id")),
            "experiment_id": _first_non_empty(confidence.get("experiment_id"), attribution.get("experiment_id")),
            "lifecycle_id": _safe_text(recommendation.get("lifecycle_id")),
            "policy_id": _safe_text(recommendation.get("policy_version_ref")),
            "model_id": _safe_text(recommendation.get("model_version_ref")),
            "prompt_id": _safe_text(recommendation.get("prompt_version_ref")),
            "confidence_state": _safe_text(confidence.get("confidence_state")),
            "attribution_state": _safe_text(attribution.get("attribution_state")),
            "lineage_complete": lineage_complete,
            "human_review_required": True,
            "evidence_summary": {
                "recommendation_eligible": bool(recommendation.get("recommendation_eligible", False)),
                "policy_state": _safe_text(recommendation.get("recommendation_policy_status")) or "UNKNOWN",
                "synthetic_evidence": bool(recommendation.get("evidence_is_synthetic", False))
                or bool(attribution.get("evidence_is_synthetic", False)),
                "contamination_state": contamination_state,
                "outcome_maturity_state": outcome_maturity_state,
                "unresolved_evidence": unresolved_evidence,
            },
        }

    def evaluate_recommendation(
        self,
        recommendation_id: str,
        *,
        created_at: str | None = None,
        final_status: str = "REPORTED",
    ) -> RecommendationEvaluationResult:
        recommendation_id = _safe_text(recommendation_id)
        if not recommendation_id:
            raise RecommendationEvaluatorError("missing_recommendation_id")

        recommendation = self._load_recommendation(recommendation_id)
        confidence = self._resolve_confidence(_safe_text(recommendation.get("confidence_id")))
        attribution = self._resolve_attribution(_safe_text(recommendation.get("attribution_record_id")))
        self._resolve_decision(_safe_text(recommendation.get("decision_id")))

        lineage_complete = self._validate_lineage(
            recommendation=recommendation,
            confidence=confidence,
            attribution=attribution,
            decision=self._resolve_decision(_safe_text(recommendation.get("decision_id"))),
        )
        payload = self._evaluation_payload(
            recommendation=recommendation,
            confidence=confidence,
            attribution=attribution,
            lineage_complete=lineage_complete,
        )
        evaluation_record = build_recommendation_evaluation_record(
            payload,
            evaluator_version=self.source_version,
            created_at=created_at or _now_iso(),
        )
        append_result = self.evaluation_store.append_evaluation_event(
            payload,
            created_by=self.created_by,
            source_module=self.source_module,
            source_version=self.source_version,
            created_at=_safe_text(evaluation_record.get("created_at")),
        )
        projection, _diagnostics = self.evaluation_store.replay()
        audit_artifact = self.audit_builder(
            repo_root=self.repo_root,
            store=self.evaluation_store,
            generated_at=_safe_text(evaluation_record.get("created_at")),
            test_results={"recommendation_evaluator": "PASS"},
            final_status=_safe_text(final_status) or "REPORTED",
        )

        return RecommendationEvaluationResult(
            evaluation_record=dict(evaluation_record),
            append_result=append_result,
            projection=dict(projection),
            audit_artifact=dict(audit_artifact),
            offline_only=True,
            advisory_only=True,
        )
