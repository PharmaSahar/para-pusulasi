"""Core models for validated finance fact bundles.

This module defines the bundle and fact schema plus abstract provider
interfaces. It intentionally contains no live provider implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Sequence
import uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_fact_bundle_id() -> str:
    return uuid.uuid4().hex


def _coerce_enum(enum_cls, value):
    if isinstance(value, enum_cls):
        return value
    return enum_cls(str(value).strip().lower())


class FactVolatility(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FactTemporalScope(str, Enum):
    HISTORICAL = "historical"
    CURRENT = "current"


class FactValidationStatus(str, Enum):
    UNVALIDATED = "unvalidated"
    VALIDATED = "validated"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FactRecord:
    key: str
    value: Any
    unit: str
    source: str
    collected_at: datetime
    confidence: float
    volatility: FactVolatility | str
    historical_current: FactTemporalScope | str
    ttl: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "volatility", _coerce_enum(FactVolatility, self.volatility))
        object.__setattr__(self, "historical_current", _coerce_enum(FactTemporalScope, self.historical_current))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "collected_at": self.collected_at.isoformat(),
            "confidence": self.confidence,
            "volatility": self.volatility.value,
            "historical_current": self.historical_current.value,
            "ttl": self.ttl,
        }


@dataclass(frozen=True, slots=True)
class FactSourceStatus:
    overall: str
    primary_provider: str | None = None
    fallback_providers: tuple[str, ...] = ()
    checked_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "primary_provider": self.primary_provider,
            "fallback_providers": list(self.fallback_providers),
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


@dataclass(frozen=True, slots=True)
class FactBundle:
    schema_version: int
    bundle_id: str
    created_at: datetime
    expires_at: datetime
    source_status: FactSourceStatus
    facts: tuple[FactRecord, ...] = field(default_factory=tuple)
    validation_status: FactValidationStatus = FactValidationStatus.UNVALIDATED

    @classmethod
    def create(
        cls,
        facts: Sequence[FactRecord],
        source_status: FactSourceStatus,
        *,
        ttl_seconds: int,
        schema_version: int = 1,
        created_at: datetime | None = None,
        bundle_id: str | None = None,
        validation_status: FactValidationStatus | str = FactValidationStatus.UNVALIDATED,
    ) -> "FactBundle":
        created_at = created_at or utcnow()
        expires_at = created_at + timedelta(seconds=ttl_seconds)
        return cls(
            schema_version=schema_version,
            bundle_id=bundle_id or generate_fact_bundle_id(),
            created_at=created_at,
            expires_at=expires_at,
            source_status=source_status,
            facts=tuple(facts),
            validation_status=_coerce_enum(FactValidationStatus, validation_status),
        )

    def with_validation_status(self, validation_status: FactValidationStatus | str) -> "FactBundle":
        return replace(self, validation_status=_coerce_enum(FactValidationStatus, validation_status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "source_status": self.source_status.to_dict(),
            "facts": [fact.to_dict() for fact in self.facts],
            "validation_status": self.validation_status.value,
        }


class FactBundleProvider(ABC):
    """Abstract provider interface for bundle construction."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def fetch_fact(self, key: str) -> FactRecord:
        raise NotImplementedError

    def fetch_facts(self, keys: Sequence[str]) -> tuple[FactRecord, ...]:
        return tuple(self.fetch_fact(key) for key in keys)


def create_fact_bundle(
    facts: Sequence[FactRecord],
    source_status: FactSourceStatus,
    *,
    ttl_seconds: int,
    schema_version: int = 1,
    created_at: datetime | None = None,
    bundle_id: str | None = None,
    validation_status: FactValidationStatus | str = FactValidationStatus.UNVALIDATED,
) -> FactBundle:
    return FactBundle.create(
        facts,
        source_status,
        ttl_seconds=ttl_seconds,
        schema_version=schema_version,
        created_at=created_at,
        bundle_id=bundle_id,
        validation_status=validation_status,
    )


__all__ = [
    "FactBundle",
    "FactBundleProvider",
    "FactRecord",
    "FactSourceStatus",
    "FactTemporalScope",
    "FactValidationStatus",
    "FactVolatility",
    "create_fact_bundle",
    "generate_fact_bundle_id",
]