from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.fact_bundle import (
    FactBundle,
    FactRecord,
    FactSourceStatus,
    FactTemporalScope,
    FactValidationStatus,
    FactVolatility,
    create_fact_bundle,
)
from src.fact_bundle_validator import FactBundleValidationError, validate_fact_bundle
from src.fact_bundle_validator import DuplicateFactValidationError


def _fact(**overrides) -> FactRecord:
    base = {
        "key": "usd_try",
        "value": 46.84,
        "unit": "TRY",
        "source": "TCMB",
        "collected_at": datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
        "confidence": 0.95,
        "volatility": FactVolatility.HIGH,
        "historical_current": FactTemporalScope.CURRENT,
        "ttl": 300,
    }
    base.update(overrides)
    return FactRecord(**base)


def _bundle(**overrides) -> FactBundle:
    created_at = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    source_status = FactSourceStatus(overall="healthy", primary_provider="tcmb", checked_at=created_at)
    base = create_fact_bundle([_fact()], source_status, ttl_seconds=300, created_at=created_at)
    return replace(base, **overrides)


def test_validate_fact_bundle_returns_validated_copy():
    bundle = _bundle()

    validated = validate_fact_bundle(bundle)

    assert validated.bundle_id == bundle.bundle_id
    assert validated.validation_status == FactValidationStatus.VALIDATED
    assert validated.facts == bundle.facts


def test_validate_fact_bundle_rejects_bad_fact_confidence():
    bundle = _bundle(facts=(_fact(confidence=1.2),))

    with pytest.raises(FactBundleValidationError) as err:
        validate_fact_bundle(bundle)

    assert "confidence" in str(err.value)


def test_validate_fact_bundle_rejects_empty_fact_list():
    bundle = _bundle(facts=())

    with pytest.raises(FactBundleValidationError) as err:
        validate_fact_bundle(bundle)

    assert "facts must contain at least one fact" in str(err.value)


def test_validate_fact_bundle_rejects_duplicate_facts():
    bundle = _bundle(facts=(_fact(), _fact()))

    with pytest.raises(DuplicateFactValidationError) as err:
        validate_fact_bundle(bundle)

    assert "duplicate canonical fact" in str(err.value)


def test_validate_fact_bundle_rejects_duplicate_canonical_keys():
    bundle = _bundle(
        facts=(
            _fact(key="USD/TRY"),
            _fact(key="usd/try", value=47.1),
        )
    )

    with pytest.raises(DuplicateFactValidationError) as err:
        validate_fact_bundle(bundle)

    assert "duplicate canonical fact" in str(err.value)


def test_validate_fact_bundle_rejects_invalid_expiry_window():
    created_at = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    source_status = FactSourceStatus(overall="healthy", primary_provider="tcmb", checked_at=created_at)
    bundle = create_fact_bundle([_fact()], source_status, ttl_seconds=300, created_at=created_at)
    bundle = replace(bundle, expires_at=created_at)

    with pytest.raises(FactBundleValidationError) as err:
        validate_fact_bundle(bundle)

    assert "expires_at must be later than created_at" in str(err.value)


def test_validate_fact_bundle_rejects_timezone_naive_checked_at():
    created_at = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    source_status = FactSourceStatus(overall="healthy", primary_provider="tcmb", checked_at=created_at.replace(tzinfo=None))
    bundle = create_fact_bundle([_fact()], source_status, ttl_seconds=300, created_at=created_at)

    with pytest.raises(FactBundleValidationError) as err:
        validate_fact_bundle(bundle)

    assert "source_status.checked_at must be timezone-aware" in str(err.value)


def test_validate_fact_bundle_rejects_invalid_schema_version():
    bundle = _bundle(schema_version=0)

    with pytest.raises(FactBundleValidationError) as err:
        validate_fact_bundle(bundle)

    assert "schema_version must be an integer >= 1" in str(err.value)


def test_validate_fact_bundle_rejects_invalid_bundle_id():
    bundle = _bundle(bundle_id="")

    with pytest.raises(FactBundleValidationError) as err:
        validate_fact_bundle(bundle)

    assert "bundle_id must be a non-empty string" in str(err.value)


def test_validate_fact_bundle_rejects_invalid_source_status_value():
    bundle = _bundle(source_status=FactSourceStatus(overall="broken", primary_provider="tcmb"))

    with pytest.raises(FactBundleValidationError) as err:
        validate_fact_bundle(bundle)

    assert "source_status.overall must be one of" in str(err.value)


def test_fact_record_rejects_unknown_temporal_scope():
    with pytest.raises(ValueError):
        _fact(historical_current="future")