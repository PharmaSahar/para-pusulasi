from __future__ import annotations

import pytest

from src.unresolved_analytics_recovery import (
    FinalDisposition,
    PHASE4C_SCHEMA_VERSION,
    RecoverabilityState,
    TaxonomyCategory,
    _build_classification,
    build_future_prevention_status,
)


@pytest.mark.parametrize("category", list(TaxonomyCategory))
def test_each_taxonomy_category_can_be_emitted(category: TaxonomyCategory) -> None:
    row = {
        "schema_version": PHASE4C_SCHEMA_VERSION,
        "unresolved_record_id": "uar_x",
        "canonical_analytics_record_id": "car_x",
    }
    result = _build_classification(
        row=row,
        category=category,
        secondary=[TaxonomyCategory.UNKNOWN.value],
        recoverability=RecoverabilityState.UNKNOWN,
        final_set=FinalDisposition.STILL_UNRESOLVED,
        evidence=[{"reason": "test"}],
        required_missing_proof="proof",
        recovery=None,
    )
    assert result["primary_category"] == category.value
    assert result["recoverability"] == RecoverabilityState.UNKNOWN.value
    assert result["required_missing_proof"] == "proof"
    assert result["pipeline_output_changed"] is False


@pytest.mark.parametrize("category", list(TaxonomyCategory))
def test_future_prevention_status_defined_for_each_category(category: TaxonomyCategory) -> None:
    assert isinstance(build_future_prevention_status(category), str)