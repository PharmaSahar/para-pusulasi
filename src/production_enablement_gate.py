from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ReadinessChecklist:
    checklist_id: str
    readiness_items: tuple[str, ...]
    required_dependencies: tuple[str, ...] = ()
    required_contracts: tuple[str, ...] = ()
    configuration: Mapping[str, Any] = None

    def __post_init__(self) -> None:
        checklist_id = str(self.checklist_id or "").strip()
        if not checklist_id:
            raise ValueError("checklist_id is required")

        readiness_items = _normalize_nonempty_values(self.readiness_items, field_name="readiness_items")
        required_dependencies = _normalize_optional_values(self.required_dependencies)
        required_contracts = _normalize_optional_values(self.required_contracts)

        object.__setattr__(self, "checklist_id", checklist_id)
        object.__setattr__(self, "readiness_items", readiness_items)
        object.__setattr__(self, "required_dependencies", required_dependencies)
        object.__setattr__(self, "required_contracts", required_contracts)
        object.__setattr__(self, "configuration", dict(self.configuration or {}))


@dataclass(frozen=True, slots=True)
class DryRunApproval:
    approved: bool
    reason: str
    dry_run_only: bool = True

    def __post_init__(self) -> None:
        reason = str(self.reason or "").strip()
        if not reason:
            raise ValueError("reason is required")
        if bool(self.approved) and not bool(self.dry_run_only):
            raise ValueError("approval must remain dry_run_only")
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    checklist_id: str
    status: str
    score: int
    passed_items: tuple[str, ...]
    failed_items: tuple[str, ...]
    missing_dependencies: tuple[str, ...]
    contract_failures: tuple[str, ...]
    invalid_configuration: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    approval: DryRunApproval

    def __post_init__(self) -> None:
        checklist_id = str(self.checklist_id or "").strip()
        if not checklist_id:
            raise ValueError("checklist_id is required")

        status = str(self.status or "").strip().lower()
        if status not in {"ready", "partial", "blocked"}:
            raise ValueError("status is invalid")

        score = int(self.score)
        if score < 0 or score > 100:
            raise ValueError("score must be between 0 and 100")

        passed_items = _normalize_optional_values(self.passed_items)
        failed_items = _normalize_optional_values(self.failed_items)
        missing_dependencies = _normalize_optional_values(self.missing_dependencies)
        contract_failures = _normalize_optional_values(self.contract_failures)
        invalid_configuration = _normalize_optional_values(self.invalid_configuration)
        blocked_reasons = _normalize_optional_values(self.blocked_reasons)

        overlap = set(passed_items).intersection(set(failed_items))
        if overlap:
            raise ValueError("items cannot be both passed and failed")

        has_blockers = bool(missing_dependencies or contract_failures or invalid_configuration or failed_items)

        if status == "ready":
            if has_blockers:
                raise ValueError("ready report cannot contain blockers")
            if score != 100:
                raise ValueError("ready report must have score 100")
            if not self.approval.approved:
                raise ValueError("ready report requires approved dry-run")

        if status == "blocked" and self.approval.approved:
            raise ValueError("blocked report cannot be approved")

        if status != "ready" and not has_blockers:
            raise ValueError("non-ready report must contain at least one blocker")

        object.__setattr__(self, "checklist_id", checklist_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "passed_items", passed_items)
        object.__setattr__(self, "failed_items", failed_items)
        object.__setattr__(self, "missing_dependencies", missing_dependencies)
        object.__setattr__(self, "contract_failures", contract_failures)
        object.__setattr__(self, "invalid_configuration", invalid_configuration)
        object.__setattr__(self, "blocked_reasons", blocked_reasons)


class ReadinessEvaluator:
    """Deterministic evaluator for production readiness in dry-run mode only."""

    _FORBIDDEN_TRUE_KEYS = (
        "automatic_execution_enabled",
        "scheduler_enabled",
        "deployment_enabled",
        "restart_services",
        "systemd_enabled",
        "cron_enabled",
        "uploads_enabled",
        "migration_enabled",
        "production_mutation_enabled",
    )

    def evaluate(
        self,
        *,
        checklist: ReadinessChecklist,
        readiness_results: Mapping[str, bool],
        dependency_results: Mapping[str, bool] | None = None,
        contract_results: Mapping[str, bool] | None = None,
    ) -> ReadinessReport:
        readiness_map = {str(key).strip(): bool(value) for key, value in dict(readiness_results).items() if str(key).strip()}
        dependency_map = {str(key).strip(): bool(value) for key, value in dict(dependency_results or {}).items() if str(key).strip()}
        contract_map = {str(key).strip(): bool(value) for key, value in dict(contract_results or {}).items() if str(key).strip()}

        passed_items = tuple(item for item in checklist.readiness_items if readiness_map.get(item, False))
        failed_items = tuple(item for item in checklist.readiness_items if not readiness_map.get(item, False))

        missing_dependencies = tuple(
            dependency
            for dependency in checklist.required_dependencies
            if not dependency_map.get(dependency, False)
        )

        contract_failures = tuple(
            contract
            for contract in checklist.required_contracts
            if not contract_map.get(contract, False)
        )

        invalid_configuration = tuple(
            key
            for key in sorted(checklist.configuration.keys())
            if key in self._FORBIDDEN_TRUE_KEYS and bool(checklist.configuration.get(key))
        )

        blocked_reasons = self._build_blocked_reasons(
            failed_items=failed_items,
            missing_dependencies=missing_dependencies,
            contract_failures=contract_failures,
            invalid_configuration=invalid_configuration,
        )

        total_items = len(checklist.readiness_items)
        score = 0 if total_items == 0 else int((len(passed_items) * 100) // total_items)

        status = self._resolve_status(
            score=score,
            blocked_reasons=blocked_reasons,
            total_items=total_items,
        )

        approval = DryRunApproval(
            approved=(status == "ready"),
            reason="ready for production enablement gate" if status == "ready" else "blocked by readiness gate",
            dry_run_only=True,
        )

        return ReadinessReport(
            checklist_id=checklist.checklist_id,
            status=status,
            score=score,
            passed_items=passed_items,
            failed_items=failed_items,
            missing_dependencies=missing_dependencies,
            contract_failures=contract_failures,
            invalid_configuration=invalid_configuration,
            blocked_reasons=blocked_reasons,
            approval=approval,
        )

    def _resolve_status(self, *, score: int, blocked_reasons: tuple[str, ...], total_items: int) -> str:
        if blocked_reasons:
            return "partial" if score > 0 and total_items > 0 else "blocked"
        return "ready"

    def _build_blocked_reasons(
        self,
        *,
        failed_items: tuple[str, ...],
        missing_dependencies: tuple[str, ...],
        contract_failures: tuple[str, ...],
        invalid_configuration: tuple[str, ...],
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if missing_dependencies:
            reasons.append("missing_dependencies")
        if invalid_configuration:
            reasons.append("invalid_configuration")
        if contract_failures:
            reasons.append("contract_validation_failed")
        if failed_items:
            reasons.append("failed_readiness_items")
        return tuple(reasons)


class ProductionEnablementGate:
    """Evaluates production readiness without performing any runtime mutations."""

    def __init__(self, *, evaluator: ReadinessEvaluator | None = None) -> None:
        self._evaluator = evaluator or ReadinessEvaluator()

    def evaluate(
        self,
        *,
        checklist: ReadinessChecklist,
        readiness_results: Mapping[str, bool],
        dependency_results: Mapping[str, bool] | None = None,
        contract_results: Mapping[str, bool] | None = None,
    ) -> ReadinessReport:
        return self._evaluator.evaluate(
            checklist=checklist,
            readiness_results=readiness_results,
            dependency_results=dependency_results,
            contract_results=contract_results,
        )


def _normalize_nonempty_values(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    normalized = _normalize_optional_values(values)
    if not normalized:
        raise ValueError(f"{field_name} must contain at least one value")
    return normalized


def _normalize_optional_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({str(item).strip() for item in tuple(values) if str(item).strip()}))


__all__ = [
    "DryRunApproval",
    "ProductionEnablementGate",
    "ReadinessChecklist",
    "ReadinessEvaluator",
    "ReadinessReport",
]
