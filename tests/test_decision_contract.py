from __future__ import annotations

import json

import pytest

from src.decision_contract import (
    DecisionExplanation,
    DecisionState,
    EvidenceClass,
    ExplanationBasis,
    build_decision_record,
    compute_decision_event_id,
    compute_decision_id,
    compute_record_hash,
    validate_decision_record_row,
)
from src.evidence_reference import build_evidence_reference
from tests.decision_memory_fixtures import build_decision_payload


def test_valid_decision_record_creation_is_deterministic() -> None:
    payload = build_decision_payload()
    first = build_decision_record(
        payload,
        created_by="tester",
        source_module="tests.test_decision_contract",
        source_version="1.0",
        created_at="2026-07-13T12:00:00+00:00",
        decision_timestamp="2026-07-13T12:00:00+00:00",
    )
    second = build_decision_record(
        payload,
        created_by="tester",
        source_module="tests.test_decision_contract",
        source_version="1.0",
        created_at="2026-07-13T12:00:00+00:00",
        decision_timestamp="2026-07-13T12:00:00+00:00",
    )

    assert first == second
    assert first["decision_id"] == compute_decision_id(first)
    assert first["decision_event_id"] == compute_decision_event_id(first)
    assert first["record_hash"] == compute_record_hash(first)
    assert list(json.loads(json.dumps(first, sort_keys=True)).keys()) == sorted(first.keys())
    assert first["decision_explanation"]["evidence_basis"] == ExplanationBasis.OBSERVATIONAL_EVIDENCE.value
    assert first["decision_explanation"]["evidence_class"] == EvidenceClass.OBSERVATIONAL.value


def test_missing_required_field_rejection() -> None:
    payload = build_decision_payload()
    payload.pop("content_id")

    with pytest.raises(ValueError, match="missing_field:content_id"):
        build_decision_record(
            payload,
            created_by="tester",
            source_module="tests.test_decision_contract",
            source_version="1.0",
        )


def test_explicit_unavailable_evidence_is_preserved() -> None:
    ref = build_evidence_reference(
        evidence_type="analytics_feedback",
        evidence_id=None,
        source_path=None,
        availability_state="unavailable",
    )
    payload = build_decision_payload(supporting_evidence_refs=[ref.to_dict()])
    record = build_decision_record(
        payload,
        created_by="tester",
        source_module="tests.test_decision_contract",
        source_version="1.0",
    )

    refs = record["supporting_evidence_refs"]
    assert refs[0]["availability_state"] == "unavailable"
    assert refs[0]["source_path"] is None
    assert refs[0]["evidence_id"] is None


def test_nested_reference_preservation() -> None:
    blueprint_ref = build_evidence_reference(
        evidence_type="planning_blueprint_lineage",
        evidence_id="bp_nested",
        source_path="logs/planning_blueprint_lineage.jsonl",
        availability_state="available",
    )
    payload = build_decision_payload(planning_blueprint_ref=blueprint_ref.to_dict())
    record = build_decision_record(
        payload,
        created_by="tester",
        source_module="tests.test_decision_contract",
        source_version="1.0",
    )

    assert record["planning_blueprint_ref"]["evidence_type"] == "planning_blueprint_lineage"
    assert record["planning_blueprint_ref"]["source_path"] == "logs/planning_blueprint_lineage.jsonl"


def test_nested_decision_explanation_validation() -> None:
    explanation = DecisionExplanation(
        summary="Why this choice was made.",
        selected_candidate_reason="Best observed demand.",
        rejected_candidate_reasons=("Less focused",),
        supporting_evidence_refs=tuple(),
        expected_kpi_impact={"ctr": 0.01},
        confidence=0.8,
        uncertainty_reasons=("Market volatility",),
        fallback_reason=None,
        risk_factors=("Trend fatigue",),
        human_review_requirement=False,
        evidence_basis=ExplanationBasis.OBSERVATIONAL_EVIDENCE,
        evidence_class=EvidenceClass.OBSERVATIONAL,
        decision_basis=ExplanationBasis.OBSERVATIONAL_EVIDENCE,
    )
    payload = build_decision_payload(decision_explanation=explanation)
    record = build_decision_record(
        payload,
        created_by="tester",
        source_module="tests.test_decision_contract",
        source_version="1.0",
    )

    assert record["decision_explanation"]["summary"] == "Why this choice was made."
    assert record["decision_explanation"]["evidence_class"] == EvidenceClass.OBSERVATIONAL.value


def test_invalid_evidence_type_and_hash_are_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported_field:evidence_type"):
        build_evidence_reference(evidence_type="not_supported", evidence_id="bad", source_path="x", availability_state="available")

    with pytest.raises(ValueError, match="invalid_field:content_hash"):
        build_evidence_reference(
            evidence_type="analytics_evidence_join",
            evidence_id="aej_bad",
            source_path="logs/analytics.jsonl",
            content_hash="not-a-hash",
            availability_state="available",
        )


def test_unsupported_schema_version_fails_explicitly() -> None:
    record = build_decision_record(
        build_decision_payload(schema_version="v999"),
        created_by="tester",
        source_module="tests.test_decision_contract",
        source_version="1.0",
    )
    record["schema_version"] = "v999"

    with pytest.raises(ValueError, match="invalid_field:schema_version"):
        validate_decision_record_row(record)
