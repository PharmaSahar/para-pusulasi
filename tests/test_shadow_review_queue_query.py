from __future__ import annotations

from src.shadow_review_queue import query_review_items, summarize_review_items


def _items() -> list[dict]:
    return [
        {
            "review_item_id": "rq_1",
            "status": "OPEN",
            "disposition": "UNDECIDED",
            "queue_priority": "P1_HIGH",
            "severity": "HIGH",
            "confidence": "HIGH",
            "category": "financial_claim_risk",
            "finding_code": "guaranteed_return_wording_detection",
            "canonical_channel_id": "ch_a",
            "content_type": "mixed",
            "checkpoint": "generation",
            "queue_created_at": "2026-07-13T10:00:00+00:00",
        },
        {
            "review_item_id": "rq_2",
            "status": "IN_REVIEW",
            "disposition": "NEEDS_SOURCE_VERIFICATION",
            "queue_priority": "P2_MEDIUM",
            "severity": "MEDIUM",
            "confidence": "MEDIUM",
            "category": "shorts_structure",
            "finding_code": "shorts_missing_context",
            "canonical_channel_id": "ch_b",
            "content_type": "short",
            "checkpoint": "shorts",
            "queue_created_at": "2026-07-13T09:00:00+00:00",
        },
        {
            "review_item_id": "rq_3",
            "status": "RESOLVED",
            "disposition": "FALSE_POSITIVE",
            "queue_priority": "P3_LOW",
            "severity": "LOW",
            "confidence": "LOW",
            "category": "duplication",
            "finding_code": "duplicate_script_detection",
            "canonical_channel_id": "ch_a",
            "content_type": "mixed",
            "checkpoint": "generation",
            "queue_created_at": "2026-07-13T08:00:00+00:00",
        },
    ]


def test_query_filters_and_unresolved_only() -> None:
    items = _items()

    unresolved = query_review_items(items=items, unresolved_only=True)
    assert {item["review_item_id"] for item in unresolved} == {"rq_1", "rq_2"}

    finance = query_review_items(items=items, specific_security_financial_only=True)
    assert [item["review_item_id"] for item in finance] == ["rq_1"]

    shorts = query_review_items(items=items, shorts_only=True)
    assert [item["review_item_id"] for item in shorts] == ["rq_2"]

    duplicates = query_review_items(items=items, duplicates_only=True)
    assert [item["review_item_id"] for item in duplicates] == ["rq_3"]


def test_query_sorting_priority_then_severity_then_confidence_then_age() -> None:
    items = _items()
    ordered = query_review_items(items=items)
    assert [item["review_item_id"] for item in ordered] == ["rq_1", "rq_2", "rq_3"]


def test_summary_metrics_shape() -> None:
    summary = summarize_review_items(items=_items(), malformed_row_count=2)
    assert summary["open_item_count"] == 2
    assert summary["counts_by_priority"]["P1_HIGH"] == 1
    assert summary["counts_by_category"]["financial_claim_risk"] == 1
    assert summary["counts_by_channel"]["ch_a"] == 2
    assert summary["counts_by_finding_code"]["guaranteed_return_wording_detection"] == 1
    assert summary["high_risk_financial_item_count"] == 1
    assert summary["shorts_review_count"] == 1
    assert summary["duplication_review_count"] == 0
    assert summary["false_positive_disposition_count"] == 1
    assert summary["malformed_row_count"] == 2
