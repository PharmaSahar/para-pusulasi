from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol


class RecommendationEvaluatorProtocol(Protocol):
    def evaluate_recommendation(
        self,
        recommendation_id: str,
        *,
        created_at: str | None = None,
        final_status: str = "REPORTED",
    ) -> Any:
        ...


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen = {str(key): _deep_freeze(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
        return MappingProxyType(frozen)
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    raise TypeError("unsupported_mapping_value")


def _to_serializable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_serializable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, tuple):
        return [_to_serializable(item) for item in value]
    if isinstance(value, list):
        return [_to_serializable(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class BridgeEvaluationResult:
    recommendation_record_id: str
    evaluation_record: Mapping[str, Any]
    append_result: Mapping[str, Any]
    projection: Mapping[str, Any]
    audit_artifact: Mapping[str, Any]
    offline_only: bool
    advisory_only: bool


@dataclass(frozen=True, slots=True)
class BridgeBatchResult:
    results: tuple[BridgeEvaluationResult, ...]
    batch_fingerprint: str
    offline_only: bool
    advisory_only: bool


class RecommendationGovernanceBridgeError(RuntimeError):
    pass


class RecommendationGovernanceBridge:
    def __init__(self, *, evaluator: RecommendationEvaluatorProtocol):
        self._evaluator = evaluator

    @staticmethod
    def _recommendation_record_id(record: Mapping[str, Any]) -> str:
        recommendation_record_id = _safe_text(
            record.get("recommendation_record_id")
            or record.get("recommendation_id")
        )
        if not recommendation_record_id:
            raise RecommendationGovernanceBridgeError("missing_recommendation_record_id")
        return recommendation_record_id

    @staticmethod
    def _fingerprint(results: tuple[BridgeEvaluationResult, ...]) -> str:
        payload = [
            {
                "recommendation_record_id": item.recommendation_record_id,
                "evaluation_record": _to_serializable(item.evaluation_record),
                "append_result": _to_serializable(item.append_result),
                "projection": _to_serializable(item.projection),
                "audit_artifact": _to_serializable(item.audit_artifact),
                "offline_only": item.offline_only,
                "advisory_only": item.advisory_only,
            }
            for item in results
        ]
        digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:24]
        return f"rgbf_{digest}"

    def evaluate_records(
        self,
        recommendation_records: Iterable[Mapping[str, Any]],
        *,
        created_at: str | None = None,
        final_status: str = "REPORTED",
    ) -> BridgeBatchResult:
        records = [dict(record) for record in recommendation_records]
        ordered = sorted(records, key=self._recommendation_record_id)

        results: list[BridgeEvaluationResult] = []
        for record in ordered:
            recommendation_record_id = self._recommendation_record_id(record)
            evaluation = self._evaluator.evaluate_recommendation(
                recommendation_record_id,
                created_at=created_at,
                final_status=final_status,
            )

            result = BridgeEvaluationResult(
                recommendation_record_id=recommendation_record_id,
                evaluation_record=_deep_freeze(_as_mapping(evaluation.evaluation_record)),
                append_result=_deep_freeze(_as_mapping(evaluation.append_result)),
                projection=_deep_freeze(_as_mapping(evaluation.projection)),
                audit_artifact=_deep_freeze(_as_mapping(evaluation.audit_artifact)),
                offline_only=bool(getattr(evaluation, "offline_only", False)),
                advisory_only=bool(getattr(evaluation, "advisory_only", False)),
            )
            results.append(result)

        frozen_results = tuple(results)
        return BridgeBatchResult(
            results=frozen_results,
            batch_fingerprint=self._fingerprint(frozen_results),
            offline_only=all(item.offline_only for item in frozen_results),
            advisory_only=all(item.advisory_only for item in frozen_results),
        )
