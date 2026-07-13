from __future__ import annotations

import pytest

from src.historical_lineage_recovery import (
    RecoveryConfidence,
    RecoveryLinkType,
    validate_recovery_record,
)


def test_recovery_confidence_is_proven_only() -> None:
    assert RecoveryConfidence.PROVEN.value == "PROVEN"


def test_link_types_available() -> None:
    assert RecoveryLinkType.OWNERSHIP_TO_PLANNING.value == "OWNERSHIP_TO_PLANNING"


def test_validate_recovery_record_invariants() -> None:
    row = {
        "schema_version": "v1",
        "recovery_id": "hr_1",
        "source_record": {"record_type": "a"},
        "target_record": {"record_type": "b"},
        "recovery_method": "content_id_exact_match",
        "confidence": "PROVEN",
        "proof": {"matched_content_id": "c1"},
        "link_type": "CONTENT_TO_OWNERSHIP",
        "created_at": "2026-07-14T00:00:00+00:00",
        "advisory_only": True,
        "pipeline_output_changed": False,
    }
    validated = validate_recovery_record(row)
    assert validated["pipeline_output_changed"] is False

    bad = dict(row)
    bad["confidence"] = "LIKELY"
    with pytest.raises(Exception):
        validate_recovery_record(bad)
