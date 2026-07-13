from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.shadow_review_queue import (
    REVIEW_QUEUE_SCHEMA_VERSION,
    ReviewQueueValidationError,
    make_review_queue_item,
)


def _base_row() -> dict:
    return {
        "schema_version": "v2",
        "evaluation_id": "eval_1",
        "run_id": "run_1",
        "content_id": "content_1",
        "channel_id": "channel_1",
        "content_type": "mixed",
        "checkpoint": "generation",
        "created_at": "2026-07-13T12:00:00+00:00",
    }


def _base_finding() -> dict:
    return {
        "code": "guaranteed_return_wording_detection",
        "category": "financial_claim_risk",
        "severity": "HIGH",
        "confidence": "HIGH",
        "validator_version": "shadow_quality_taxonomy_v1",
        "affected_artifact": "script",
        "evidence_excerpt": "Bu yontemle kesin getiri var.",
        "evidence_hash": "abc123",
        "message": "Guarantee wording detected",
        "remediation_class": "remove_guarantee_language",
        "blocking_eligible_future": True,
    }


def test_queue_item_defaults_and_schema() -> None:
    item = make_review_queue_item(
        row=_base_row(),
        finding=_base_finding(),
        queue_priority="P1_HIGH",
        queue_reason="finance_guaranteed_return_claim",
        queue_created_at="2026-07-13T12:10:00+00:00",
    )
    as_dict = item.to_dict()

    assert as_dict["schema_version"] == REVIEW_QUEUE_SCHEMA_VERSION
    assert as_dict["status"] == "OPEN"
    assert as_dict["disposition"] == "UNDECIDED"
    assert as_dict["advisory_only"] is True
    assert as_dict["review_item_id"].startswith("rq_")


def test_queue_item_id_deterministic_for_same_source() -> None:
    row = _base_row()
    finding = _base_finding()
    item1 = make_review_queue_item(
        row=row,
        finding=finding,
        queue_priority="P1_HIGH",
        queue_reason="finance_guaranteed_return_claim",
        queue_created_at="2026-07-13T12:10:00+00:00",
    )
    item2 = make_review_queue_item(
        row=row,
        finding=finding,
        queue_priority="P0_CRITICAL",
        queue_reason="another_reason",
        queue_created_at="2026-07-13T12:20:00+00:00",
    )
    assert item1.review_item_id == item2.review_item_id


def test_queue_item_changes_for_material_evidence_change() -> None:
    row = _base_row()
    finding = _base_finding()
    item1 = make_review_queue_item(
        row=row,
        finding=finding,
        queue_priority="P1_HIGH",
        queue_reason="finance_guaranteed_return_claim",
        queue_created_at="2026-07-13T12:10:00+00:00",
    )
    finding_changed = dict(finding)
    finding_changed["evidence_hash"] = "changed_hash"
    item2 = make_review_queue_item(
        row=row,
        finding=finding_changed,
        queue_priority="P1_HIGH",
        queue_reason="finance_guaranteed_return_claim",
        queue_created_at="2026-07-13T12:10:00+00:00",
    )
    assert item1.review_item_id != item2.review_item_id


def test_queue_item_excerpt_is_bounded() -> None:
    finding = _base_finding()
    finding["evidence_excerpt"] = "x" * 500
    item = make_review_queue_item(
        row=_base_row(),
        finding=finding,
        queue_priority="P2_MEDIUM",
        queue_reason="advisory",
        queue_created_at="2026-07-13T12:10:00+00:00",
    )
    assert len(item.bounded_evidence_excerpt) <= 223


def test_queue_item_rejects_secret_like_excerpt() -> None:
    finding = _base_finding()
    finding["evidence_excerpt"] = "access_token=secret_value"
    with pytest.raises(ReviewQueueValidationError):
        make_review_queue_item(
            row=_base_row(),
            finding=finding,
            queue_priority="P2_MEDIUM",
            queue_reason="advisory",
            queue_created_at="2026-07-13T12:10:00+00:00",
        )


def test_queue_item_is_immutable() -> None:
    item = make_review_queue_item(
        row=_base_row(),
        finding=_base_finding(),
        queue_priority="P1_HIGH",
        queue_reason="finance_guaranteed_return_claim",
        queue_created_at="2026-07-13T12:10:00+00:00",
    )
    with pytest.raises(FrozenInstanceError):
        item.status = "RESOLVED"  # type: ignore[misc]
