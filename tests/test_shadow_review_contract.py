from __future__ import annotations

from src.shadow_review_contract import build_human_review_item


def test_build_human_review_item_contract() -> None:
    item = build_human_review_item(
        channel_id="ch",
        run_id="run",
        content_type="mixed",
        finding_code="guaranteed_return_wording_detection",
        severity="HIGH",
        confidence="HIGH",
        affected_artifact="script",
        bounded_excerpt="Bu yöntem garanti getiri sağlar",
        explanation="Guarantee language detected",
        suggested_review_action="remove_guarantee_language",
        evidence_hashes={"script_hash": "abc"},
        created_at="2026-07-13T12:00:00+00:00",
    ).to_dict()

    expected = {
        "channel_id",
        "run_id",
        "content_type",
        "finding_code",
        "severity",
        "confidence",
        "affected_artifact",
        "bounded_excerpt",
        "explanation",
        "suggested_review_action",
        "evidence_hashes",
        "created_at",
    }
    assert expected.issubset(set(item.keys()))
