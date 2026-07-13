from __future__ import annotations

from src.shadow_review_queue import build_related_finding_bundles


def test_finance_bundle_and_equivalent_no_double_count() -> None:
    items = [
        {
            "review_item_id": "rq_1",
            "run_id": "run_1",
            "content_id": "content_1",
            "canonical_channel_id": "ch",
            "checkpoint": "generation",
            "category": "financial_claim_risk",
            "affected_artifact": "script",
            "finding_code": "guaranteed_return_wording_detection",
            "severity": "HIGH",
            "confidence": "HIGH",
            "bounded_evidence_excerpt": "kesin getiri",
        },
        {
            "review_item_id": "rq_2",
            "run_id": "run_1",
            "content_id": "content_1",
            "canonical_channel_id": "ch",
            "checkpoint": "generation",
            "category": "financial_claim_risk",
            "affected_artifact": "script",
            "finding_code": "unsupported_financial_claim_detection",
            "severity": "HIGH",
            "confidence": "HIGH",
            "bounded_evidence_excerpt": "garanti",
        },
    ]

    bundles = build_related_finding_bundles(items=items)
    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle["finding_count"] == 2
    assert bundle["grouped_finding_count"] == 1
    assert set(bundle["finding_codes"]) == {
        "guaranteed_return_wording_detection",
        "unsupported_financial_claim_detection",
    }


def test_shorts_and_duplication_bundle_examples() -> None:
    items = [
        {
            "review_item_id": "rq_3",
            "run_id": "run_2",
            "content_id": "content_2",
            "canonical_channel_id": "ch",
            "checkpoint": "shorts",
            "category": "shorts_structure",
            "affected_artifact": "shorts",
            "finding_code": "shorts_abrupt_beginning",
            "severity": "MEDIUM",
            "confidence": "MEDIUM",
            "bounded_evidence_excerpt": "ve sonra",
        },
        {
            "review_item_id": "rq_4",
            "run_id": "run_2",
            "content_id": "content_2",
            "canonical_channel_id": "ch",
            "checkpoint": "shorts",
            "category": "shorts_structure",
            "affected_artifact": "shorts",
            "finding_code": "shorts_missing_context",
            "severity": "MEDIUM",
            "confidence": "MEDIUM",
            "bounded_evidence_excerpt": "bu konu",
        },
        {
            "review_item_id": "rq_5",
            "run_id": "run_2",
            "content_id": "content_2",
            "canonical_channel_id": "ch",
            "checkpoint": "generation",
            "category": "duplication",
            "affected_artifact": "script",
            "finding_code": "duplicate_script_detection",
            "severity": "MEDIUM",
            "confidence": "HIGH",
            "bounded_evidence_excerpt": "aynı acilis",
        },
        {
            "review_item_id": "rq_6",
            "run_id": "run_2",
            "content_id": "content_2",
            "canonical_channel_id": "ch",
            "checkpoint": "generation",
            "category": "repetition",
            "affected_artifact": "script",
            "finding_code": "repetitive_opening_detection",
            "severity": "MEDIUM",
            "confidence": "HIGH",
            "bounded_evidence_excerpt": "aynı acilis",
        },
    ]

    bundles = build_related_finding_bundles(items=items)
    assert len(bundles) == 1
    assert bundles[0]["category"] == "shorts_structure"
    assert bundles[0]["review_item_ids"] == ["rq_3", "rq_4"]
