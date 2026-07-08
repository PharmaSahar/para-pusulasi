"""Schema validation for finance fact bundles."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .fact_bundle import (
    FactBundle,
    FactRecord,
    FactSourceStatus,
    FactTemporalScope,
    FactValidationStatus,
    FactVolatility,
)


class FactBundleValidationError(ValueError):
    """Raised when a fact bundle or fact record fails validation."""

    def __init__(self, issues: list[str], *, bundle_id: str | None = None):
        self.issues = issues
        self.bundle_id = bundle_id
        message = "; ".join(issues)
        if bundle_id:
            message = f"bundle_id={bundle_id}: {message}"
        super().__init__(message)


_ALLOWED_SOURCE_STATUSES = {"healthy", "degraded", "unavailable", "unknown"}


def _coerce_enum(enum_cls, value):
    if isinstance(value, enum_cls):
        return value
    return enum_cls(str(value).strip().lower())


def _ensure_aware(dt: datetime, field_name: str, issues: list[str]) -> None:
    if not isinstance(dt, datetime):
        issues.append(f"{field_name} must be a datetime")
        return
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        issues.append(f"{field_name} must be timezone-aware")


def _validate_fact_record(fact: FactRecord, issues: list[str], index: int) -> None:
    prefix = f"facts[{index}]"
    if not isinstance(fact.key, str) or not fact.key.strip():
        issues.append(f"{prefix}.key must be a non-empty string")
    if fact.value is None:
        issues.append(f"{prefix}.value must not be None")
    if not isinstance(fact.unit, str) or not fact.unit.strip():
        issues.append(f"{prefix}.unit must be a non-empty string")
    if not isinstance(fact.source, str) or not fact.source.strip():
        issues.append(f"{prefix}.source must be a non-empty string")
    _ensure_aware(fact.collected_at, f"{prefix}.collected_at", issues)
    if not isinstance(fact.confidence, (int, float)) or not 0.0 <= float(fact.confidence) <= 1.0:
        issues.append(f"{prefix}.confidence must be between 0.0 and 1.0")
    try:
        _coerce_enum(FactVolatility, fact.volatility)
    except ValueError:
        issues.append(f"{prefix}.volatility must be one of: low, medium, high")
    try:
        _coerce_enum(FactTemporalScope, fact.historical_current)
    except ValueError:
        issues.append(f"{prefix}.historical_current must be one of: historical, current")
    if not isinstance(fact.ttl, int) or fact.ttl <= 0:
        issues.append(f"{prefix}.ttl must be a positive integer")


def validate_fact_bundle(bundle: FactBundle) -> FactBundle:
    """Validate a fact bundle and return a validated copy.

    Raises FactBundleValidationError when the bundle or any fact is invalid.
    """
    issues: list[str] = []

    if not isinstance(bundle, FactBundle):
        raise FactBundleValidationError(["bundle must be a FactBundle instance"])

    if not isinstance(bundle.schema_version, int) or bundle.schema_version < 1:
        issues.append("schema_version must be an integer >= 1")
    if not isinstance(bundle.bundle_id, str) or not bundle.bundle_id.strip():
        issues.append("bundle_id must be a non-empty string")

    _ensure_aware(bundle.created_at, "created_at", issues)
    _ensure_aware(bundle.expires_at, "expires_at", issues)
    if isinstance(bundle.created_at, datetime) and isinstance(bundle.expires_at, datetime):
        if bundle.expires_at <= bundle.created_at:
            issues.append("expires_at must be later than created_at")

    if not isinstance(bundle.source_status, FactSourceStatus):
        issues.append("source_status must be a FactSourceStatus instance")
    else:
        if not isinstance(bundle.source_status.overall, str) or not bundle.source_status.overall.strip():
            issues.append("source_status.overall must be a non-empty string")
        elif bundle.source_status.overall.lower() not in _ALLOWED_SOURCE_STATUSES:
            issues.append("source_status.overall must be one of: healthy, degraded, unavailable, unknown")

        if bundle.source_status.primary_provider is not None and not bundle.source_status.primary_provider.strip():
            issues.append("source_status.primary_provider must be a non-empty string when provided")

        if not isinstance(bundle.source_status.fallback_providers, tuple):
            issues.append("source_status.fallback_providers must be a tuple of provider names")

    if not isinstance(bundle.facts, tuple):
        issues.append("facts must be stored as a tuple")
    elif not bundle.facts:
        issues.append("facts must contain at least one fact")
    else:
        for index, fact in enumerate(bundle.facts):
            if not isinstance(fact, FactRecord):
                issues.append(f"facts[{index}] must be a FactRecord instance")
                continue
            _validate_fact_record(fact, issues, index)

    try:
        _coerce_enum(FactValidationStatus, bundle.validation_status)
    except ValueError:
        issues.append("validation_status must be one of: unvalidated, validated, degraded, failed")

    if issues:
        raise FactBundleValidationError(issues, bundle_id=bundle.bundle_id if isinstance(bundle.bundle_id, str) else None)

    return replace(bundle, validation_status=FactValidationStatus.VALIDATED)


__all__ = ["FactBundleValidationError", "validate_fact_bundle"]